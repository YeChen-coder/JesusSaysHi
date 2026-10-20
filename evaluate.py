"""Score retrieval strategies against eval/questions.jsonl and write eval/results.md.

A question counts as answered at rank r when the r-th distinct passage overlaps any of
its expected ranges. The voice tool will hand the model 3 passages, so hit@3 is the
headline number.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import date
from pathlib import Path

from openai import OpenAI

from config import INDEX_DIR, RAW_BSB, ROOT, embed_model, load_settings, rewrite_model
from retrieval import ScriptureIndex, openai_embedder, rewrite_query
from scripture import Passage, range_keys, read_verses

QUESTIONS = ROOT / "eval" / "questions.jsonl"
RESULTS = ROOT / "eval" / "results.md"
KS = (1, 3, 5)
DEPTH = 10
STRATEGIES = (  # (label, mode, rewrite)
    ("bm25", "bm25", False),
    ("dense", "dense", False),
    ("hybrid", "hybrid", False),
    ("bm25 + rewrite", "bm25", True),
    ("dense + rewrite", "dense", True),
    ("hybrid + rewrite", "hybrid", True),
)


def load_questions(path: Path, verses) -> list[dict]:
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for q in questions:
        q["keys"] = set().union(*(range_keys(spec, verses) for spec in q["expected"]))
    return questions


def first_hit(passages: list[Passage], expected: set) -> int | None:
    for rank, passage in enumerate(passages, start=1):
        if passage.keys() & expected:
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict:
    n = len(ranks)
    row = {f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
    row["mrr"] = sum(1 / r for r in ranks if r is not None) / n
    return row


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def timed(fn, *args):
    started = time.perf_counter()
    value = fn(*args)
    return value, (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-rewrite", action="store_true", help="skip the LLM rewrite strategies")
    args = parser.parse_args()

    load_settings()
    client = OpenAI()
    embed = openai_embedder(client, embed_model())
    index = ScriptureIndex.load(INDEX_DIR, embed)
    questions = load_questions(QUESTIONS, read_verses(RAW_BSB))
    strategies = [s for s in STRATEGIES if not (args.no_rewrite and s[2])]

    latency = {"embed": [], "rewrite": [], "bm25": []}
    records = []
    for q in questions:
        record = {"id": q["id"], "type": q["type"], "question": q["question"],
                  "expected": q["expected"], "ranks": {}, "top": {}}
        vector, ms = timed(embed, [q["question"]])
        latency["embed"].append(ms)
        queries = {False: (q["question"], vector[0])}
        if any(s[2] for s in strategies):
            rewritten, ms = timed(rewrite_query, client, q["question"], rewrite_model())
            latency["rewrite"].append(ms)
            queries[True] = (rewritten, embed([rewritten])[0])
            record["rewrite"] = rewritten
        _, ms = timed(index.rank, q["question"], "bm25")
        latency["bm25"].append(ms)

        for label, mode, rewrite in strategies:
            text, vec = queries[rewrite]
            passages = index.search(text, DEPTH, mode, query_vector=vec)
            record["ranks"][label] = first_hit(passages, q["keys"])
            record["top"][label] = [p.ref for p in passages[:3]]
        records.append(record)
        print(f"{q['id']:>3} " + "  ".join(f"{label}={record['ranks'][label]}" for label, *_ in strategies))

    RESULTS.write_text(render(records, strategies, latency), encoding="utf-8")
    (ROOT / "eval" / "results.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"\nWrote {RESULTS}")


def render(records: list[dict], strategies, latency: dict) -> str:
    lines = [
        "# Retrieval eval", "",
        f"{date.today().isoformat()} · {len(records)} questions · embeddings `{embed_model()}` · "
        f"rewrite `{rewrite_model()}` · index `{INDEX_DIR.relative_to(ROOT).as_posix()}`", "",
    ]
    for subset in ("all", "direct", "situational"):
        chosen = [r for r in records if subset == "all" or r["type"] == subset]
        if not chosen:
            continue
        lines += [f"## {subset} ({len(chosen)})", "",
                  "| strategy | hit@1 | hit@3 | hit@5 | MRR@10 |", "|---|---|---|---|---|"]
        for label, *_ in strategies:
            row = summarize([r["ranks"][label] for r in chosen])
            lines.append(f"| {label} | " + " | ".join(f"{row[f'hit@{k}']:.0%}" for k in KS)
                         + f" | {row['mrr']:.2f} |")
        lines.append("")

    lines += ["## Latency (ms)", "", "| step | p50 | p90 |", "|---|---|---|"]
    for step, values in latency.items():
        if values:
            lines.append(f"| {step} | {statistics.median(values):.0f} | {percentile(values, 90):.0f} |")
    lines.append("")

    for label in ("hybrid", "hybrid + rewrite"):
        if label not in {s[0] for s in strategies}:
            continue
        misses = [r for r in records if r["ranks"][label] is None or r["ranks"][label] > 3]
        lines += [f"## Outside top 3 for {label} ({len(misses)})", ""]
        for r in misses:
            lines.append(f"- **{r['id']}** ({r['type']}) {r['question']}")
            lines.append(f"  expected {', '.join(r['expected'])}; got {', '.join(r['top'][label])}")
            if label.endswith("rewrite"):
                lines.append(f"  rewrite: {r['rewrite']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
