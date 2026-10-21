"""Scripture retrieval: dense embeddings, plus BM25 and a reciprocal-rank-fusion hybrid.

Dense is the default because it scored best in eval/results.md: BM25 is weak on how
people actually talk, and equal-weight fusion drags the dense ranking down with it.

The corpus is ~1,800 passages, so everything is brute force over numpy arrays in memory.
No vector database: a cosine over the whole matrix takes well under a millisecond.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np

from scripture import Passage

EmbedFn = Callable[[list[str]], np.ndarray]
MODES = ("bm25", "dense", "hybrid")

_STOPWORDS = frozenset("""
a about after all also am an and any are as at be because been but by can could did do
does for from had has have he her him his how i if in into is it its just me my no not
now of on or our out she so some than that the their them then there these they this to
up us was we were what when where which who whom why will with would you your yours yet
""".split())


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower().replace("’", "'"))
    return [_stem(w) for w in words if w not in _STOPWORDS and len(w) > 1]


def _stem(word: str) -> str:
    # Crude suffix stripping so "worries", "worried" and "worrying" share one term.
    # It only needs to be consistent between queries and passages, not linguistically right.
    if len(word) > 4 and word.endswith(("ies", "ied")):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = np.array([sum(d.values()) for d in self.docs], dtype=np.float32)
        self.avg_length = float(self.lengths.mean()) if len(self.docs) else 0.0
        frequency = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}

    def scores(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.docs), dtype=np.float32)
        norm = self.k1 * (1 - self.b + self.b * self.lengths / max(self.avg_length, 1e-9))
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([d.get(term, 0) for d in self.docs], dtype=np.float32)
            scores += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal rank fusion: only ranks matter, so BM25 and cosine scores need no calibration."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            fused[doc] = fused.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused, key=lambda doc: (-fused[doc], doc))


def distinct(passages: list[Passage], ranking: list[int], k: int) -> list[Passage]:
    """Take the top k passages, skipping any window that overlaps one already chosen,
    so three results are three different places rather than one scene three times."""
    chosen: list[Passage] = []
    seen: set = set()
    for doc in ranking:
        passage = passages[doc]
        if passage.keys() & seen:
            continue
        chosen.append(passage)
        seen |= passage.keys()
        if len(chosen) == k:
            break
    return chosen


class ScriptureIndex:
    def __init__(self, passages: list[Passage], embeddings: np.ndarray, embed: EmbedFn):
        if len(passages) != len(embeddings):
            raise ValueError("passages and embeddings are out of sync; rebuild the index")
        self.passages = passages
        self.embeddings = embeddings
        self.embed = embed
        self.bm25 = BM25([p.text for p in passages])

    @classmethod
    def load(cls, index_dir: Path, embed: EmbedFn) -> "ScriptureIndex":
        rows = json.loads((index_dir / "passages.json").read_text(encoding="utf-8"))
        embeddings = np.load(index_dir / "embeddings.npy")
        return cls([Passage.from_json(r) for r in rows], embeddings, embed)

    def rank(self, query: str, mode: str = "dense", depth: int = 50,
             query_vector: np.ndarray | None = None) -> list[int]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        lexical: list[int] = []
        dense: list[int] = []
        if mode in ("bm25", "hybrid"):
            lexical = [int(i) for i in np.argsort(-self.bm25.scores(query), kind="stable")[:depth]]
        if mode in ("dense", "hybrid"):
            vector = query_vector if query_vector is not None else self.embed([query])[0]
            dense = [int(i) for i in np.argsort(-(self.embeddings @ vector), kind="stable")[:depth]]
        if mode == "bm25":
            return lexical
        if mode == "dense":
            return dense
        return rrf([lexical, dense])

    def search(self, query: str, k: int = 3, mode: str = "dense",
               query_vector: np.ndarray | None = None, jesus_only: bool = False) -> list[Passage]:
        # jesus_only is accepted for interface parity with RagflowIndex and ignored:
        # plain verse windows carry no red-letter metadata.
        return distinct(self.passages, self.rank(query, mode, query_vector=query_vector), k)


def openai_embedder(client, model: str) -> EmbedFn:
    def embed(texts: list[str]) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), 256):
            response = client.embeddings.create(model=model, input=texts[start:start + 256])
            vectors.extend(item.embedding for item in response.data)
        matrix = np.asarray(vectors, dtype=np.float32)
        return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return embed


REWRITE_INSTRUCTIONS = (
    "Turn the user's message into a short search query for passages in the four Gospels. "
    "Name the underlying human need and the themes Jesus speaks to, in plain words a "
    "modern English Bible would use, plus a few concrete keywords. Do not cite or guess "
    "chapter and verse numbers. Reply with the query only, under 25 words."
)


def rewrite_query(client, text: str, model: str) -> str:
    """Close the gap between how people talk ("my boss gaslights me") and how scripture
    talks. In the voice app the realtime model writes the tool argument itself, so this
    rewrite costs no extra round trip there; offline it stands in for that step."""
    response = client.responses.create(model=model, instructions=REWRITE_INSTRUCTIONS, input=text)
    return response.output_text.strip()
