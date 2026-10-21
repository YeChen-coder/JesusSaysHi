"""Ablation of the RAGFlow pipeline on eval/questions.jsonl; writes eval/ragflow_results.md.

Each configuration changes one stage: dense only, hybrid at two full-text weights, then
hybrid + reranker. Every configuration runs on the raw question and on the theme rewrite
stored by evaluate.py (the stand-in for what the realtime model passes to the tool), so
the comparison with phase 1 uses identical queries. A hit is the first returned section
that overlaps an expected range. The abstention check compares best scores on the real
questions with those on eval/offtopic.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import date

from config import RAW_BSB, ROOT, load_settings
from evaluate import KS, load_questions, percentile, summarize
from ragflow_retrieval import RagflowIndex, chunk_passages
from scripture import read_verses

RESULTS = ROOT / "eval" / "ragflow_results.md"
OFFTOPIC = ROOT / "eval" / "offtopic.jsonl"
DEPTH = 5


def configurations(rerank_id: str | None) -> list[tuple[str, dict]]:
    configs = [
        ("dense", {"keywords_similarity_weight": 0.0}),
        ("hybrid (full-text 0.3)", {"keywords_similarity_weight": 0.3}),
        ("hybrid (full-text 0.7, RAGFlow default)", {"keywords_similarity_weight": 0.7}),
    ]
    if rerank_id:
        configs.append((f"hybrid 0.3 + rerank ({rerank_id.split('@')[0]})",
                        {"keywords_similarity_weight": 0.3, "rerank_id": rerank_id}))
    return configs


def first_hit(chunks: list[dict], expected: set) -> int | None:
    for rank, chunk in enumerate(chunks, start=1):
        if any(p.keys() & expected for p in chunk_passages(chunk["content"])):
            return rank
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rerank", help="RAGFlow rerank model id (default: JESUS_RAGFLOW_RERANK)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_settings()

    index = RagflowIndex.from_env()
    index.trace_path = None  # evaluation traffic stays out of the production trace
    index.rerank_id = None  # each configuration names its own reranker, or none
    rerank = args.rerank or os.getenv("JESUS_RAGFLOW_RERANK")
    questions = load_questions(ROOT / "eval" / "questions.jsonl", read_verses(RAW_BSB))
    rewrites = {r["id"]: r["rewrite"] for r in json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))}
    offtopic = [json.loads(line) for line in OFFTOPIC.read_text(encoding="utf-8").splitlines() if line.strip()]

    rows, scores = [], {}
    for label, params in configurations(rerank):
        for rewrite in (False, True):
            name = label + (" + rewrite" if rewrite else "")
            ranks, latencies, best = [], [], []
            for q in questions:
                query = rewrites[q["id"]] if rewrite else q["question"]
                chunks = index.retrieve(query, DEPTH, **params)
                if index.last.get("rerank_fallback"):  # never score a fallback as a rerank row
                    raise RuntimeError(f"rerank failed during {name}: {index.last['rerank_fallback']}")
                latencies.append(index.last["ms"])
                ranks.append(first_hit(chunks, q["keys"]))
                best.append(chunks[0]["similarity"] if chunks else 0.0)
            off = [(index.retrieve(o["question"], 1, **params) or [{"similarity": 0.0}])[0]["similarity"]
                   for o in offtopic]
            by_type = {t: summarize([r for r, q in zip(ranks, questions) if q["type"] == t])
                       for t in ("direct", "situational")}
            rows.append((name, summarize(ranks), by_type, statistics.median(latencies), percentile(latencies, 90)))
            scores[name] = (best, off)
            print(f"{name:<55} hit@3 {rows[-1][1]['hit@3']:.0%}  p50 {rows[-1][3]:.0f} ms")

    lines = ["# RAGFlow retrieval eval", "",
             f"{date.today().isoformat()} · {len(questions)} questions · one result per BSB section · "
             "hit = first section overlapping an expected range", "",
             "| configuration | hit@1 | hit@3 | hit@5 | MRR | situational hit@3 | p50 ms | p90 ms |",
             "|---|---|---|---|---|---|---|---|"]
    for name, row, by_type, p50, p90 in rows:
        lines.append(f"| {name} | " + " | ".join(f"{row[f'hit@{k}']:.0%}" for k in KS)
                     + f" | {row['mrr']:.2f} | {by_type['situational']['hit@3']:.0%} | {p50:.0f} | {p90:.0f} |")
    lines += ["", "## Abstention: best score, real questions vs off-topic", "",
              "| configuration | real: min / p10 / median | off-topic: max / median | separable |",
              "|---|---|---|---|"]
    for name, (best, off) in scores.items():
        ordered = sorted(best)
        lines.append(f"| {name} | {ordered[0]:.3f} / {percentile(best, 10):.3f} / {statistics.median(best):.3f} | "
                     f"{max(off):.3f} / {statistics.median(off):.3f} | {'yes' if max(off) < ordered[0] else 'no'} |")
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()
