"""End-to-end reply eval: each eval question in its own typed Realtime session, scored on
what Jesus actually said.

The retrieval evals (evaluate.py, evaluate_ragflow.py) ask whether the right section was
found. This asks the rest: did the model search, quote what came back word for word,
cite it correctly, and pick a verse that answers the question? Off-topic questions should
get no quote at all. Writes eval/replies_results.md and eval/replies_results.json.

    python evaluate_replies.py            # 55 questions + 10 off-topic, 3 runs, 4 sessions at a time
    python evaluate_replies.py --limit 5  # a quick smoke run
    python evaluate_replies.py --ids q12,q21 --no-write   # look at a few replies
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import date

from openai import OpenAI

from config import RAW_BSB, ROOT, load_settings
from safety import CrisisCheck
from scripture import range_keys, read_verses

QUESTIONS = ROOT / "eval" / "questions.jsonl"
OFFTOPIC = ROOT / "eval" / "offtopic.jsonl"
RESULTS = ROOT / "eval" / "replies_results"
PROBLEMS = ("paraphrased", "unsupported_citations", "misattributed_quotes", "uncited_quotes")


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def ask(index, crisis_check, question: str, verses, timeout: float = 120) -> dict:
    """One fresh typed session: the opening, one question, its reply. Returns what was said."""
    from voice import Conversation

    conversation = Conversation(index, text_mode=True, say=[question], log_dir=ROOT / "logs" / "eval_replies",
                                out=lambda _text: None, crisis_check=crisis_check)
    spoken: list[str] = []
    check_reply = conversation._check_reply

    def keep_text(item_id, text):  # the raw reply, references included
        spoken.append(text.strip())
        return check_reply(item_id, text)

    conversation._check_reply = keep_text
    started = time.monotonic()
    try:
        await asyncio.wait_for(conversation.run(), timeout=timeout)
        error = None
    except Exception as exc:  # one failed session must not stop the eval
        error = type(exc).__name__
    replies = conversation.reports[1:]  # the first report is the opening "Peace be with you."
    opening_ids = {p.id for p in index.passages if p.book == "John" and p.chapter == 20}
    retrieved = [p for pid, p in conversation.retrieved.items() if pid not in opening_ids]
    quoted, sentences = [], []
    for report in replies:
        for sentence in report["sentences"]:
            if sentence["ref"] == "John 20:19":  # "Peace be with you" again: a greeting, not an answer
                continue
            sentences.append({k: sentence.get(k) for k in ("kind", "ref", "text", "misattributed", "uncited")})
            if sentence["kind"] != "own" and sentence["ref"] and sentence["ref"] not in quoted:
                quoted.append(sentence["ref"])
    return {
        "error": error, "seconds": round(time.monotonic() - started, 1),
        "searches": conversation.searches, "safety_replies": conversation.safety_replies,
        "retrieved": sorted({p.ref for p in retrieved}),
        "retrieved_keys": sorted({k for p in retrieved for k in p.keys()}),
        "quoted": quoted,
        "verbatim": sum(1 for s in sentences if s["kind"] == "verbatim"),
        "words": sum(r["words"] for r in replies),
        "grounded_words": sum(r["grounded_words"] for r in replies),
        **{key: sum(r[key] for r in replies) for key in PROBLEMS},
        "reply": "\n\n".join(spoken[1:]),
    }


def quoted_keys(record: dict, verses) -> set:
    keys = set()
    for ref in record["quoted"]:
        try:
            keys |= range_keys(ref, verses)
        except ValueError:
            pass
    return keys


def score(records: list[dict], verses) -> dict:
    n = len(records)
    words = sum(r["words"] for r in records) or 1

    def share(test):
        return sum(1 for r in records if test(r)) / n

    clean = lambda r: r["verbatim"] > 0 and not (r["paraphrased"] or r["unsupported_citations"] or r["misattributed_quotes"])
    row = {
        "n": n,
        "searched": share(lambda r: r["searches"] > 0),
        "retrieved_relevant": share(lambda r: bool(set(map(tuple, r["retrieved_keys"])) & r["keys"])),
        "quoted": share(lambda r: r["verbatim"] > 0),
        "quote_relevant": share(lambda r: bool(quoted_keys(r, verses) & r["keys"])),
        "clean": share(clean),
        "grounded_share": sum(r["grounded_words"] for r in records) / words,
    }
    for key in PROBLEMS:
        row[key] = share(lambda r, key=key: r[key] > 0)
    return row


def spread(values: list[float]) -> str:
    """Mean of the runs, with their range when there is more than one."""
    mean = sum(values) / len(values)
    if len(values) == 1 or min(values) == max(values):
        return f"{mean:.0%}"
    return f"{mean:.0%} ({min(values):.0%}–{max(values):.0%})"


def render(runs: list[dict]) -> str:
    """runs: one {"scope", "records", "offtopic", "safety"} per run of the whole set."""
    last = runs[-1]
    lines = [
        "# End-to-end reply eval", "",
        f"{date.today().isoformat()} · retriever `{os.getenv('JESUS_RETRIEVER', 'ragflow')}` · model "
        f"`{os.getenv('OPENAI_REALTIME_MODEL', 'gpt-realtime-2.1-mini')}` · one typed session per question · "
        f"{len(runs)} run(s); cells show the mean and, across runs, the range", "",
        "Every reply is scored on its text by [faithfulness.py](../faithfulness.py), against the verses "
        "retrieved in that session. *Relevant* means the verse overlaps the question's expected ranges in "
        "[questions.jsonl](questions.jsonl). The realtime model writes its own search query here, so these "
        "retrieval numbers are lower than the offline ones, which use stored rewrites.", "",
        "| questions | searched | retrieved a relevant section | quoted verbatim | quoted a relevant verse "
        "| clean reply | words verbatim scripture |",
        "|---|---|---|---|---|---|---|",
    ]
    columns = ("searched", "retrieved_relevant", "quoted", "quote_relevant", "clean", "grounded_share")
    for name, row in last["scope"].items():
        cells = [spread([run["scope"][name][key] for run in runs]) for key in columns]
        lines.append(f"| {name} ({row['n']}) | " + " | ".join(cells) + " |")
    lines += ["", "*Clean* = at least one verbatim quote and no paraphrased quote, unsupported citation or "
              "misattributed quote. *Misattributed* is strict: a wrong book, a verse off by one, and a quote "
              "that runs on past the one verse it cites all count.", "", "Share of replies with each problem:", "",
              "| questions | paraphrased | unsupported citation | misattributed | uncited |", "|---|---|---|---|---|"]
    for name in last["scope"]:
        cells = [spread([run["scope"][name][key] for run in runs]) for key in PROBLEMS]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    total = len(last["offtopic"])
    quiet = [sum(1 for r in run["offtopic"] if r["verbatim"] == 0 and not r["paraphrased"]) for run in runs]
    searched = [sum(1 for r in run["offtopic"] if r["searches"]) for run in runs]
    lines += ["", f"## Off-topic ({total})", "",
              "- no scripture quoted, per run: **" + ", ".join(f"{q}/{total}" for q in quiet) + "**",
              "- searched anyway, per run: " + ", ".join(str(n) for n in searched), ""]
    for i, run in enumerate(runs, start=1):
        for r in run["offtopic"]:
            if r["verbatim"] or r["paraphrased"]:
                lines.append(f"- run {i}, **{r['id']}** {r['question']}: quoted {', '.join(r['quoted'])}")
    safety = sorted({(r["id"], r["question"]) for run in runs for r in run["safety"]})
    if safety:
        lines += ["", "Answered by the crisis check instead, in at least one run (not scored above): "
                  + ", ".join(f"**{i}** {q}" for i, q in safety)]
    errors = [r for run in runs for r in run["records"] + run["offtopic"] if r["error"]]
    if errors:
        lines += ["", "Sessions that failed: " + ", ".join(f"{r['id']} ({r['error']})" for r in errors)]
    lines += ["", "## Replies that were not clean (last run)", ""]
    for r in last["records"]:
        if r["verbatim"] > 0 and not (r["paraphrased"] or r["unsupported_citations"] or r["misattributed_quotes"]):
            continue
        problems = [key for key in PROBLEMS[:3] if r[key]] or (["no verbatim quote"] if not r["verbatim"] else [])
        lines.append(f"- **{r['id']}** ({r['type']}) {r['question']} — {', '.join(problems)}; "
                     f"quoted {', '.join(r['quoted']) or 'nothing'}")
        lines.append(f"  > {' '.join(r['reply'].split())[:300]}")
    return "\n".join(lines) + "\n"


async def run(limit: int | None, parallel: int, ids: set[str] | None = None, write: bool = True,
              repeats: int = 1) -> None:
    from jesus import open_index

    load_settings()
    os.environ["JESUS_AVATAR_ENABLED"] = "false"  # no avatar page involved
    client = OpenAI(timeout=10, max_retries=1)
    index = open_index(client)
    crisis = CrisisCheck(client)
    verses = read_verses(RAW_BSB)
    questions = [q for q in load(QUESTIONS) if not ids or q["id"] in ids][:limit]
    offtopic = [q for q in load(OFFTOPIC) if not ids or q["id"] in ids][:limit]
    gate = asyncio.Semaphore(parallel)

    async def one(item):
        async with gate:
            record = {**item, **await ask(index, crisis, item["question"], verses)}
            print(f"{item['id']:>4} searched={record['searches']} quoted={','.join(record['quoted']) or '-'} "
                  f"{record['seconds']}s{' ERROR ' + record['error'] if record['error'] else ''}", flush=True)
            return record

    runs = []
    for repeat in range(repeats):
        print(f"run {repeat + 1}/{repeats}", flush=True)
        records = await asyncio.gather(*(one(q) for q in questions))
        for record in records:
            record["keys"] = set().union(*(range_keys(spec, verses) for spec in record["expected"]))
        off = await asyncio.gather(*(one(q) for q in offtopic))
        if not write:
            for r in records + off:
                print(f"\n{r['id']} {r['question']}\n  retrieved {', '.join(r['retrieved'])}\n  {r['reply']}")
            continue
        # A crisis-check reply is the safety path working, not a retrieval reply: scored apart.
        safety = [r for r in records if r["safety_replies"]]
        records = [r for r in records if not r["safety_replies"]]
        scope = {"all": score(records, verses)}
        for kind in ("direct", "situational"):
            subset = [r for r in records if r["type"] == kind]
            if subset:
                scope[kind] = score(subset, verses)
        runs.append({"scope": scope, "records": records, "offtopic": off, "safety": safety})
    if not write:
        return
    RESULTS.with_suffix(".md").write_text(render(runs), encoding="utf-8")
    dump = [[{k: v for k, v in r.items() if k not in ("keys", "retrieved_keys")}
             for r in run["records"] + run["safety"] + run["offtopic"]] for run in runs]
    RESULTS.with_suffix(".json").write_text(json.dumps(dump, indent=1), encoding="utf-8")
    print(f"\nWrote {RESULTS.with_suffix('.md')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N questions of each set")
    parser.add_argument("--parallel", type=int, default=4, help="sessions at a time")
    parser.add_argument("--ids", help="comma-separated question ids to run")
    parser.add_argument("--no-write", action="store_true", help="print the replies instead of writing results")
    parser.add_argument("--runs", type=int, default=3, help="repeat the whole set; the model is not deterministic")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ids = set(args.ids.split(",")) if args.ids else None
    asyncio.run(run(args.limit, args.parallel, ids, not args.no_write, args.runs))


if __name__ == "__main__":
    main()
