"""search_scripture backed by RAGFlow: hybrid retrieval, reranking, metadata filter, abstention.

Online pipeline per query (the realtime model has already rewritten the person's words
into themes when it called the tool):
  hybrid recall (full-text + dense, weighted) -> rerank the top candidates -> drop
  everything if the best score is under the abstention threshold -> one result per
  section (parent chunk) -> split back into verses for quoting and the faithfulness check.
Every call appends a trace (scores per stage, latency) to logs/retrieval.jsonl.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

from config import RAW_BSB, ROOT
from ragflow_client import RagflowClient, RagflowError
from scripture import Passage, make_passages, read_verses

LOG = logging.getLogger("jesus")
_VERSE = re.compile(r"^(Matthew|Mark|Luke|John) (\d+):(\d+) (.+)$")
_HEADER = re.compile(r"^.+? · (.+)$")


def chunk_passages(content: str) -> list[Passage]:
    """Turn a returned section back into passages, one per chapter it spans."""
    title, groups = "", {}
    for line in content.splitlines():
        line = line.strip()
        verse = _VERSE.match(line)
        if verse:
            book, chapter = verse[1], int(verse[2])
            groups.setdefault((book, chapter), []).append((int(verse[3]), verse[4]))
        elif not title and (header := _HEADER.match(line)):
            title = header[1]
    passages = []
    for (book, chapter), rows in groups.items():
        rows.sort()
        key = f"{book} {chapter}:{rows[0][0]}"
        passages.append(Passage(zlib.crc32(key.encode()), book, chapter,
                                tuple(v for v, _ in rows), tuple(t for _, t in rows), title))
    return passages


class RagflowIndex:
    def __init__(self, client: RagflowClient, dataset_ids: list[str], *, rerank_id: str | None = None,
                 keyword_weight: float = 0.3, candidates: int = 30, min_score: float | None = None,
                 llm_keywords: bool = False, trace_path: Path | None = None):
        self.client = client
        self.dataset_ids = dataset_ids
        self.rerank_id = rerank_id
        self.keyword_weight = keyword_weight
        self.candidates = candidates
        self.min_score = min_score
        self.llm_keywords = llm_keywords
        self.trace_path = trace_path
        # Local verse windows, only so the opening line can be found without a query.
        self.passages = make_passages(read_verses(RAW_BSB))
        self.last: dict | None = None

    @classmethod
    def from_env(cls, client: RagflowClient | None = None) -> "RagflowIndex":
        client = client or RagflowClient()
        name = os.getenv("JESUS_RAGFLOW_DATASET", "BSB Gospels")
        dataset = client.find_dataset(name)
        if dataset is None:
            raise RuntimeError(f"RAGFlow dataset {name!r} not found; run ingest_ragflow.py first")
        threshold = os.getenv("JESUS_RAGFLOW_MIN_SCORE", "").strip()
        return cls(client, [dataset["id"]], rerank_id=os.getenv("JESUS_RAGFLOW_RERANK") or None,
                   keyword_weight=float(os.getenv("JESUS_RAGFLOW_KEYWORD_WEIGHT", "0.3")),
                   min_score=float(threshold) if threshold else None,
                   trace_path=ROOT / "logs" / "retrieval.jsonl")

    def retrieve(self, query: str, k: int = 3, jesus_only: bool = False, **overrides) -> list[dict]:
        """Up to k chunks, one per section, best first; [] when the best is below min_score."""
        min_score = overrides.pop("min_score", self.min_score)
        params = {
            "page": 1, "page_size": max(k * 3, 10), "similarity_threshold": 0.0,
            "keywords_similarity_weight": self.keyword_weight,
            "rerank_candidates_count": self.candidates, "keyword": self.llm_keywords,
            "highlight": False, "include_knowledge_compilation": False,
        }
        if self.rerank_id:
            params["rerank_id"] = self.rerank_id
        if jesus_only:
            params["metadata_condition"] = {"logic": "and", "conditions": [
                {"name": "jesus_speaks", "comparison_operator": "=", "value": "yes"}]}
        params.update(overrides)
        started = time.perf_counter()
        fallback = None
        try:
            data = self.client.retrieve(query, self.dataset_ids, **params)
        except RagflowError as exc:
            # A reranker outage or rate limit must not end a spoken turn: answer from
            # the hybrid ranking alone and record that it happened.
            if "rerank_id" not in params or "rerank" not in str(exc).lower():
                raise
            fallback = str(exc)[:200]
            LOG.warning("Rerank failed, using hybrid ranking only: %s", fallback)
            params.pop("rerank_id")
            data = self.client.retrieve(query, self.dataset_ids, **params)
        elapsed = (time.perf_counter() - started) * 1000
        chunks, seen = [], set()
        for chunk in data.get("chunks", []):
            if chunk["document_id"] not in seen:
                seen.add(chunk["document_id"])
                chunks.append(chunk)
        abstained = bool(min_score is not None and (not chunks or chunks[0]["similarity"] < min_score))
        kept = [] if abstained else chunks[:k]
        self.last = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ms": round(elapsed),
            "rerank": params.get("rerank_id"), "keyword_weight": params["keywords_similarity_weight"],
            "jesus_only": jesus_only, "abstained": abstained, "rerank_fallback": fallback,
            "candidates": [{"doc": c.get("document_keyword"), "score": round(c["similarity"], 4),
                            "term": round(c.get("term_similarity", 0), 4),
                            "vector": round(c.get("vector_similarity", 0), 4)} for c in chunks[:10]],
        }
        if self.trace_path is not None:
            try:
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self.trace_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(self.last) + "\n")
            except OSError:
                LOG.exception("Could not write the retrieval trace")
        return kept

    def search(self, query: str, k: int = 3, jesus_only: bool = False) -> list[Passage]:
        return [p for chunk in self.retrieve(query, k, jesus_only) for p in chunk_passages(chunk["content"])]
