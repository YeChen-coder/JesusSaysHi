"""Scripture as memory (persona v2): before each reply, recall a few sayings of his own.

Instead of giving the voice model a search tool, the system "remembers" for it, from the
second user turn on, using only what the person just said (so a change of subject is
followed at once):

1. RAGFlow retrieves sections for the sentence (hybrid + rerank; below the reranked
   threshold it abstains and nothing is remembered). In parallel, the sentence is embedded.
2. Inside those sections, the red-letter sayings (Jesus' own words, exact pieces of the
   BSB verse; built by build_memory_index.py) are ranked by similarity to the sentence.
   Only sayings kept by curate_memory.py (said as they are to someone who came to be
   comforted) are candidates; a word list also drops judgment and warning, and anything
   already said is left out.
3. Up to three go into a system note starting with MEMORY. The voice model picks at most
   one, or none, while writing its reply, and must say it word for word.

One LLM call sits on this path, the query rewrite (about 1 s; JESUS_MEMORY_REWRITE=false
turns it off). The selector call that used to follow it is gone: whether a saying suits a
hurting person is judged offline (curate_memory.py), and which one fits is ranked locally.
The selector is kept as JESUS_MEMORY_SELECTOR=llm for comparison. Every step, its timing and its reason
for remembering nothing are returned for the debugging timeline.

Status: opt-in with JESUS_PERSONA=memory while the persona is being tuned.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from config import ROOT, embed_model, rewrite_model
from retrieval import rewrite_query
from scripture import Passage

LOG = logging.getLogger("jesus")
MEMORY_DIR = ROOT / "data" / "memory"

# Words of judgment and warning are true to the Gospels but wrong for someone who came to
# be comforted ("...will be subject to the fire of hell" was once offered for a fight with
# a mother). A word list is crude; it only has to keep these out of the candidates.
_HARSH = re.compile(
    r"\b(?:hell|fire|woe|judg(?:e|ed|ment)|condemn(?:ed|ation)?|perish|destroy\w*|curs\w*|wicked|"
    r"hypocrit\w*|vipers?|unquenchable|gnashing|outer darkness|adulterous|Sanhedrin|"
    r"millstone|cut it off|gouge|executioner|torment\w*|Beelzebul|Satan)\b",
    re.IGNORECASE)
_NOT_HARSH = re.compile(r"\b(?:neither do I condemn|not condemn|not to condemn|did not come to judge)\b",
                        re.IGNORECASE)

SELECTOR = """You help Jesus remember one of his own words for the person he is talking with.
From the sayings below, choose AT MOST ONE that Jesus could naturally say to this person right now.
It must comfort, reassure, or gently speak to what they are going through.
Match the person's place in their own story: if they hurt someone and ask whether they will be forgiven, do
not choose words telling them to forgive others. If nothing truly fits, return null: that is often right.
Reply with JSON only: {"ref": "Book C:V" or null, "reason": "one short sentence"}"""


def memory_note(sayings: list[str]) -> str:
    # The persona must not reveal that a memory was handed to it ("a line came to mind").
    listed = " / ".join(f'"{s}"' for s in sayings)
    return (f"MEMORY: things you once said that may fit this moment: {listed}. Use at most one, and only if "
            "it truly fits what they just said; often none does. If you use one, say it word for word, plainly "
            "to this person or as something you once said to someone. Do not describe it as a memory, a line "
            "or a quote.")


# The persona may say "you are not condemned here" but must not absolve on God's behalf.
_ABSOLUTION = re.compile(r"\b(?:sins? (?:are|is) forgiven|forgive(?:s|n)? (?:your|his|her) sins)\b", re.IGNORECASE)


def harsh(words: str) -> bool:
    """Not to be offered: judgment and warning, or a pronouncement that sins are forgiven."""
    return (bool(_HARSH.search(words)) and not _NOT_HARSH.search(words)) or bool(_ABSOLUTION.search(words))


class MemoryRecall:
    def __init__(self, index, client, *, rewrite: bool | None = None, first_turn: int | None = None):
        self.index = index
        self.client = client
        if rewrite is None:
            # On by default: +8 points hit@3 in the RAGFlow ablation, for about 1 s per turn.
            rewrite = os.getenv("JESUS_MEMORY_REWRITE", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.rewrite = rewrite
        # 0-based user turn from which memories are offered; the first turn only listens.
        self.first_turn = int(os.getenv("JESUS_MEMORY_FIRST_TURN", "1")) if first_turn is None else first_turn
        self.selector = os.getenv("JESUS_MEMORY_SELECTOR", "local").strip().lower()
        self.model = os.getenv("JESUS_MEMORY_SELECTOR_MODEL", rewrite_model())
        self.offer = int(os.getenv("JESUS_MEMORY_OFFER", "3"))
        # RAGFlow's reranked threshold already decides whether the sections are relevant at
        # all; this floor only drops sayings that share nothing with the moment.
        self.min_similarity = float(os.getenv("JESUS_MEMORY_MIN_SIMILARITY", "0.15"))
        self.units = json.loads((MEMORY_DIR / "units.json").read_text(encoding="utf-8"))
        self.vectors = np.load(MEMORY_DIR / "embeddings.npy")
        # curate_memory.py's one-off judgment: only sayings that can be said, as they are,
        # to someone who came to be comforted (278 of 2,109). Without the file, all are used.
        curation = MEMORY_DIR / "curation.json"
        self.kept: set[int] | None = None
        if curation.is_file() and os.getenv("JESUS_MEMORY_CURATED", "true").strip().lower() in {"1", "true", "yes", "on"}:
            keep = {(c["ref"], c["words"]) for c in json.loads(curation.read_text(encoding="utf-8"))["items"] if c["keep"]}
            self.kept = {i for i, u in enumerate(self.units) if (u["ref"], u["words"]) in keep}
        self.by_verse: dict[tuple[str, int, int], list[int]] = {}
        for i, unit in enumerate(self.units):
            self.by_verse.setdefault((unit["book"], unit["chapter"], unit["verse"]), []).append(i)
        self.pool = ThreadPoolExecutor(3)

    def query_for(self, history: list[dict]) -> str:
        """The sentence just said. A very short one ("Not so good.") borrows the one before
        it for context; nothing older, so a change of subject is followed at once."""
        current = history[-1]["user"]
        if len(current.split()) < 6 and len(history) > 1:
            return history[-2]["user"] + " " + current
        return current

    def recall(self, history: list[dict], used_refs: set[str]) -> tuple[dict, list[Passage]]:
        """history: [{"user": str, "replies": [str]}], the current user turn last.
        Returns (trace fields, passages offered: one per saying, holding only its words)."""
        turn = len(history) - 1
        memo: dict = {"turn": turn}
        if turn < self.first_turn:
            memo["why_none"] = "first turn: listen first"
            return memo, []
        started = time.perf_counter()
        said = self.query_for(history)
        memo["said"] = said
        # The person's own words pick the saying (the reply answers what they said), so they
        # are embedded at once, alongside the rewrite; the rewrite only drives the search.
        vector_future = self.pool.submit(self._embed, said)
        query = said
        if self.rewrite:
            try:
                query = rewrite_query(self.client, said, rewrite_model())
            except Exception as exc:
                LOG.warning("Query rewrite failed (%s); searching with the words as said", type(exc).__name__)
                memo["rewrite_failed"] = type(exc).__name__
            memo["rewrite_ms"] = round((time.perf_counter() - started) * 1000)
        memo["query"] = query
        # The rewrite reads like scripture ("sorrow, comfort, rest"); the words as said are
        # short and plain ("I don't feel happy"), so similarity to them alone stayed under
        # 0.25 even for John 16:22. Both count; the second embedding runs alongside RAGFlow.
        query_future = self.pool.submit(self._embed, query) if query != said else vector_future
        t0 = time.perf_counter()
        sections = self._retrieve(query)
        memo["retrieve_ms"] = round((time.perf_counter() - t0) * 1000)
        vector = (vector_future.result() + query_future.result()) / 2
        memo["sections"] = [{"title": s["title"], "score": s["score"]} for s in sections]
        if not sections:
            memo["why_none"] = "retrieval abstained (best reranked score below threshold) or found nothing"
            return memo, []

        used_words = [u[6:].lower() for u in used_refs if u.startswith("words:")]
        candidates, skipped = [], {"not curated": 0, "harsh": 0, "used": 0}
        for section in sections:
            for passage in section["passages"]:
                for verse in passage.verses:
                    for i in self.by_verse.get((passage.book, passage.chapter, verse), []):
                        unit = self.units[i]
                        words = unit["words"].lower()
                        if self.kept is not None and i not in self.kept:
                            skipped["not curated"] += 1
                        elif unit["ref"] in used_refs or any(w in words or words in w for w in used_words):
                            skipped["used"] += 1
                        elif harsh(unit["words"]):
                            skipped["harsh"] += 1
                        else:
                            candidates.append(i)
        memo["candidates"], memo["skipped"] = len(candidates), skipped
        if not candidates:
            memo["why_none"] = "no curated saying in the retrieved sections (or all used / harsh)"
            return memo, []
        scores = self.vectors[candidates] @ vector
        ranked = [(candidates[j], float(scores[j])) for j in np.argsort(-scores)]
        memo["ranked"] = [{"ref": self.units[i]["ref"], "similarity": round(s, 3), "words": self.units[i]["words"]}
                          for i, s in ranked[:6]]
        picked = [i for i, s in ranked if s >= self.min_similarity][:self.offer]
        if self.selector == "llm" and picked:
            picked = self._select(history, picked, memo)
        memo["total_ms"] = round((time.perf_counter() - started) * 1000)
        if not picked:
            memo.setdefault("why_none", f"no saying above similarity {self.min_similarity}")
            return memo, []
        memo["offered"] = [{"ref": self.units[i]["ref"], "words": self.units[i]["words"]} for i in picked]
        return memo, [Passage(hash((self.units[i]["ref"], self.units[i]["words"])) & 0x7FFFFFFF,
                              self.units[i]["book"], self.units[i]["chapter"], (self.units[i]["verse"],),
                              (self.units[i]["words"],)) for i in picked]

    def _embed(self, text: str) -> np.ndarray:
        vector = np.asarray(self.client.embeddings.create(model=embed_model(), input=[text]).data[0].embedding,
                            dtype=np.float32)
        return vector / np.linalg.norm(vector)

    def _retrieve(self, query: str) -> list[dict]:
        """Sections as [{"title", "score", "passages"}], best first, for either index type."""
        if hasattr(self.index, "retrieve"):  # RAGFlow
            from ragflow_retrieval import chunk_passages

            return [{"title": c.get("document_keyword"), "score": round(c["similarity"], 3),
                     "passages": chunk_passages(c["content"])} for c in self.index.retrieve(query, 3)]
        return [{"title": p.ref, "score": None, "passages": [p]} for p in self.index.search(query, 3)]

    def _select(self, history: list[dict], picked: list[int], memo: dict) -> list[int]:
        """Optional (JESUS_MEMORY_SELECTOR=llm): a model narrows the offer to one, about +1 s."""
        conversation = "\n".join(f"Person: {h['user']}" for h in history)
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.model, instructions=SELECTOR,
            input=f"Conversation so far:\n{conversation}\n\nSayings:\n"
                  + "\n".join(f"{self.units[i]['ref']}: {self.units[i]['words']}" for i in picked))
        memo["select_ms"] = round((time.perf_counter() - started) * 1000)
        try:
            choice = json.loads(response.output_text.strip().strip("`").removeprefix("json").strip())
        except json.JSONDecodeError:
            memo["why_none"] = "selector output was not JSON"
            return []
        memo["selector"] = choice
        if not choice.get("ref"):
            memo["why_none"] = f"selector chose none: {choice.get('reason')}"
        return [i for i in picked if self.units[i]["ref"] == choice.get("ref")][:1]
