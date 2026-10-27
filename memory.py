"""Episodic memory: before a reply, recall a moment of his life from the Gospels.

The unit of memory is an episode, one BSB section (an event, a conversation or a story he
told; 487 of them, the parent chunks in RAGFlow). He remembers what happened, who was
there and what he did, not a line cut out of it: "I am the resurrection" means little
without Martha at the tomb and Lazarus four days dead.

From the second user turn on, using what the person just said:
1. Read it: is it a question for information, for an expert, or conversation? Only
   conversation is remembered; for it, the same call writes the search query: what they
   are going through and the kinds of moments in Jesus' life it resembles.
2. RAGFlow retrieves sections (hybrid search, Voyage rerank). Below the reranked
   threshold nothing is recalled: the moment does not touch his life closely enough.
3. Up to two episodes not yet told in this session go to the voice model in a MEMORY
   note, the whole section each, marked by whether he was there (build_episodes.py).
4. The voice model may tell one, briefly and in plain modern words, true to what
   happened; often it tells none. Tone is its judgment, in context: a hard word he said
   to the Pharisees in that story is not said to the hurting person in front of him.

The rewrite is the one LLM call on this path (about 1 s, covered by phase A of the reply).
Every step, its timing and its reason for recalling nothing go into the session trace.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from config import ROOT, rewrite_model
from retrieval import tokenize

LOG = logging.getLogger("jesus")
SECTIONS = ROOT / "data" / "sections"
EPISODES = ROOT / "data" / "episodes" / "episodes.json"
_VERSE_PREFIX = re.compile(r"^(?:Matthew|Mark|Luke|John) \d+:\d+ ")
_SPAN = re.compile(r"^((?:\d )?[A-Za-z ]+?) (\d+):(\d+)(?:-(?:(\d+):)?(\d+))?")

# The one LLM call on the path reads the turn twice over: what kind of question it is, and,
# for a conversation, what to search for. The kind used to be a prompt rule for the voice
# model ("look information up; leave expert questions to experts"); the mini model fixed a
# ModuleNotFoundError step by step anyway, and the rewrite turned "the news today" into a
# leper's prayer. A label decided here is acted on in code.
# Two lessons about the query itself from the first trial: told to look for moments of his
# life, it lifted "the weather in Chicago" to "Jesus calms the storm", over the threshold;
# and "my best friend died" found other mourning but not Lazarus, so it may name moments.
READ = """Read what the person just said to a companion who speaks as Jesus. Reply with JSON only:
{"kind": "information" | "expert" | "talk", "query": "..."}
- information: they want a current or plain fact: the weather, the news, a price, opening hours, a date.
- expert: they want an answer that needs a professional's judgment: fixing code or a device, a medical question
  (is this risky, what does this symptom mean, which dose), a legal or tax question, whether to buy or sell.
- talk: anything else: their feelings, their life and relationships, faith, Jesus' own life, and questions of how
  to live, learn or love ("how do I make peace with my brother").
For talk, the query is a short search query for moments in the four Gospels: name what they are going through and
how they feel, and the kinds of moments in Jesus' life that resemble it (what he lived through, people he met and
what happened to them, stories he told). If particular moments come to mind, name them plainly (for example:
Lazarus' death, Peter's denial). Plain words a modern English Bible would use, under 30 words, no chapter or verse
numbers. For information and expert, the query is ""."""
KINDS = ("information", "expert", "talk")


def read_turn(client, said: str) -> tuple[str, str]:
    """(kind, query). Output that is not the JSON asked for is taken as a plain query.

    Its own deadline: in a demo one read took over 4 s (usually 1-1.8 s), so the whole recall
    timed out and the turn that most needed a memory (a friend's death) got none. Past the
    deadline the caller searches with the words as said."""
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=float(os.getenv("JESUS_MEMORY_READ_TIMEOUT_SECONDS", "2.5")),
                                     max_retries=0)
    response = client.responses.create(model=rewrite_model(), instructions=READ, input=said)
    raw = response.output_text.strip()
    try:
        data = json.loads(raw.strip("`").removeprefix("json").strip())
    except json.JSONDecodeError:
        return "talk", raw
    kind = data.get("kind") if data.get("kind") in KINDS else "talk"
    return kind, str(data.get("query") or "").strip() or said


# The one episode never recalled: Judas' suicide. In the first trial it came first for
# "I'm too ashamed to go home." Everything else about tone is the voice model's call in
# context; a death by suicide offered to someone in shame is not a call to leave to it.
NEVER_RECALLED = frozenset({"Matthew 27.03 Judas Hangs Himself.txt"})

# Words every episode shares, which say nothing about whether a reply told this one.
_GENERIC = frozenset(tokenize(
    "jesus god lord father son man men woman people said say says tell told come came go went know one "
    "day time will like heart love child friend way life thing things also"))


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def read_episode(filename: str) -> str:
    """The section's verses as running text, without references (he does not cite them)."""
    lines = (SECTIONS / filename).read_text(encoding="utf-8").splitlines()[1:]
    return " ".join(_VERSE_PREFIX.sub("", line) for line in lines if line.strip())


def verse_span(ref: str):
    """("Luke", (22, 54), (22, 62)) for "Luke 22:54-62"; None if it is not a reference."""
    match = _SPAN.match(ref)
    if not match:
        return None
    c1, v1 = int(match[2]), int(match[3])
    c2 = int(match[4]) if match[4] else c1
    v2 = int(match[5]) if match[5] else v1
    return match[1], (c1, v1), (c2, v2)


def overlaps(a: str, b: str) -> bool:
    """Do two references share a verse ("Luke 22:61" and "Luke 22:54-62")?"""
    x, y = verse_span(a), verse_span(b)
    return bool(x and y and x[0] == y[0] and x[1] <= y[2] and y[1] <= x[2])


def parallel(a: dict, b: dict) -> bool:
    """Two accounts of one event (Peter's denial in Matthew, Mark, Luke and John): either
    lists the other among its parallels, with overlapping verses."""
    return any(overlaps(ref, y["ref"]) for x, y in ((a, b), (b, a)) for ref in x.get("parallels", []))


# Parables whose BSB titles do not say so. A parable told as something he saw ("I heard a man
# planning his barns" for the rich fool) was the most visible error in the fidelity eval.
_PARABLES = frozenset({
    "Luke 16.19 The Rich Man and Lazarus.txt", "Luke 18.09 The Pharisee and the Tax Collector.txt",
    "Mark 04.26 The Seed Growing Secretly.txt", "Matthew 18.21 The Unforgiving Servant.txt",
})


def is_parable(doc: str, title: str) -> bool:
    return "parable" in title.lower() or doc in _PARABLES


def close_fit() -> float:
    """The reranked score from which an episode is told, not just offered (README Phase 8:
    on the full model, 0 of 10 tellings at 0.40 and up had an error, 4 of 12 below)."""
    return float(os.getenv("JESUS_MEMORY_CLOSE", "0.40"))


def fits_closely(episodes: list[dict]) -> bool:
    return bool(episodes) and (episodes[0].get("score") or 0) >= close_fit()


def memory_note(episodes: list[dict]) -> str:
    """The MEMORY note for phase B. It must not show that a memory was handed over.

    A note that only allowed a memory ("at most one, or none; often none fits") was read as
    "don't": in the v3 demo he told none of three, giving advice in images instead. So a
    close fit is now asked for, and a loose one allowed only if told exactly as it was."""
    parts = []
    for e in episodes:
        if is_parable(e.get("doc", ""), e["title"]):
            how = ("A story you told, not something that happened to you: if you tell it, say that you once told "
                   "it; its people are characters in your story, not people you met.")
        elif e["present"]:
            how = "You were there."
        else:
            how = "You were not there: you heard of it, or were told it (of your birth, by your mother)."
        parts.append(f"[{e['title']}] {how}\n{e['text']}")
    if fits_closely(episodes):
        ask = ("MEMORY: moments from your life. The first speaks closely to what they just said: tell it now, in "
               "this reply, unless telling it would hurt them. ")
    else:
        ask = ("MEMORY: moments from your life that only touch on what they just said. Tell one only if it truly "
               "fits and you can tell it exactly as it happened; never bend it to fit them. Otherwise tell none. ")
    return (ask + "Tell at most one, briefly, in one or two sentences of plain modern words, the "
            "way a man remembers his own past: what happened, who was there, what you did or said, or, if it is a "
            "story you told, that you once told it. Say the names and places it has (Lazarus, Martha, Bethany, "
            "Peter): names are what make it your memory and not a vague story. Keep the order of what happened. You may "
            "say what you felt; do not say what others thought or felt unless it is there. Add nothing it does not "
            "have, and do "
            "not turn it into a judgment of this person. Do not mention chapter, verse, the Gospels, a memory or a "
            "note, and never say what you are about to do (\"I'll share a memory\", \"I'll keep this short\"): "
            "just speak.\n\n" + "\n\n".join(parts))


def told(reply: str, episode_text: str) -> list[str]:
    """Distinctive words the reply shares with an episode. He retells in his own words, so
    word-for-word matching cannot see it; three or more shared distinctive words (Peter,
    rooster, courtyard) is the cheap live signal. The reply eval uses an LLM judge."""
    shared = set(tokenize(reply)) & set(tokenize(episode_text))
    return sorted(w for w in shared - _GENERIC if len(w) > 3)


class EpisodeRecall:
    def __init__(self, index, client, *, rewrite: bool | None = None, first_turn: int | None = None,
                 offer: int | None = None, min_score: float | None | str = "index",
                 episodes: dict[str, dict] | None = None):
        if not hasattr(index, "retrieve"):
            raise RuntimeError("Episodic memory needs RAGFlow sections; set JESUS_RETRIEVER=ragflow")
        self.index = index
        self.client = client
        # On by default: +8 points hit@3 in the RAGFlow ablation, for about 1 s per turn.
        self.rewrite = _flag("JESUS_MEMORY_REWRITE", "true") if rewrite is None else rewrite
        # 0-based user turn from which memories are offered; the first turn only listens.
        self.first_turn = int(os.getenv("JESUS_MEMORY_FIRST_TURN", "1")) if first_turn is None else first_turn
        self.offer = int(os.getenv("JESUS_MEMORY_OFFER", "2")) if offer is None else offer
        # How closely a moment must touch his life to be recalled: the reranked score of the
        # best section. "index" keeps RAGFlow's own abstention threshold (0.30); a number
        # overrides it; None recalls something on every turn.
        if min_score == "index":
            env = os.getenv("JESUS_MEMORY_MIN_SCORE", "").strip().lower()
            min_score = "index" if not env else None if env == "none" else float(env)
        self.min_score = min_score
        # {section filename: label from build_episodes.py}; an entry may carry its own "text".
        self.episodes: dict[str, dict] = (json.loads(EPISODES.read_text(encoding="utf-8"))
                                          if episodes is None else episodes)

    def query_for(self, history: list[dict]) -> str:
        """The sentence just said. A very short one ("Not so good.") borrows the one before
        it for context; nothing older, so a change of subject is followed at once."""
        current = history[-1]["user"]
        if len(current.split()) < 6 and len(history) > 1:
            return history[-2]["user"] + " " + current
        return current

    def recall(self, history: list[dict], told_before: set[str]) -> tuple[dict, list[dict]]:
        """history: [{"user": str, ...}], the current user turn last; told_before: section
        filenames already told this session. Returns (trace fields, episodes offered)."""
        turn = len(history) - 1
        memo: dict = {"turn": turn}
        if turn < self.first_turn:
            memo["why_none"] = "first turn: listen first"
            return memo, []
        started = time.perf_counter()
        said = self.query_for(history)
        memo["said"] = said
        kind, query = "talk", said
        if self.rewrite:
            try:
                kind, query = read_turn(self.client, said)
            except Exception as exc:
                LOG.warning("Query rewrite failed (%s); searching with the words as said", type(exc).__name__)
                memo["rewrite_failed"] = type(exc).__name__
            memo["rewrite_ms"] = round((time.perf_counter() - started) * 1000)
        memo["kind"] = kind
        if kind != "talk":
            # Looked up, or left to someone who knows that work: nothing to remember here.
            memo["why_none"] = ("a question for information: looked up, not remembered" if kind == "information"
                                else "a question for an expert: not his to answer")
            return memo, []
        memo["query"] = query
        t0 = time.perf_counter()
        overrides = {} if self.min_score == "index" else {"min_score": self.min_score}
        # Extra candidates, since parallels and episodes already told are passed over.
        chunks = self.index.retrieve(query, self.offer + len(told_before) + 3, **overrides)
        memo["retrieve_ms"] = round((time.perf_counter() - t0) * 1000)
        memo["sections"] = [{"doc": c.get("document_keyword"), "score": round(c["similarity"], 3)} for c in chunks]
        memo["min_score"] = getattr(self.index, "min_score", None) if self.min_score == "index" else self.min_score
        if not chunks:
            memo["why_none"] = "retrieval abstained (best reranked score below threshold) or found nothing"
            return memo, []
        offered = []
        told = [self.episodes[d] for d in told_before if d in self.episodes]
        for chunk in chunks:
            doc = chunk.get("document_keyword")
            if doc in told_before or doc not in self.episodes or doc in NEVER_RECALLED:
                continue
            e = self.episodes[doc]
            # One account per event: not another Gospel's telling of one offered or told already.
            if any(parallel(e, other) for other in told + [self.episodes[o["doc"]] for o in offered]):
                memo.setdefault("skipped_parallels", []).append(e["ref"])
                continue
            offered.append({"doc": doc, "ref": e["ref"], "title": e["title"], "present": e["present"],
                            "score": round(chunk["similarity"], 3), "text": e.get("text") or read_episode(doc)})
            if len(offered) == self.offer:
                break
        memo["total_ms"] = round((time.perf_counter() - started) * 1000)
        if not offered:
            memo["why_none"] = "every retrieved episode was already told in this session"
            return memo, []
        memo["offered"] = [{k: e[k] for k in ("doc", "ref", "title", "present", "score")} for e in offered]
        return memo, offered

    def note(self, episodes: list[dict]) -> str:
        return memory_note(episodes)
