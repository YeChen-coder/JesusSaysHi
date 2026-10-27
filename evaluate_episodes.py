"""How often should he remember? Run the same short conversations at three recall settings
and lay the replies side by side for a person to judge, with an LLM judge's notes beside them.

Settings: every turn (no threshold), RAGFlow's threshold (0.30, the default) and a stricter
0.40. Each conversation opens with a greeting, since the first turn only listens. For every
turn the judge is shown what was offered and what he said, and answers: did he tell one of
the offered moments, is it true to the text (anything invented?), and did it fit to tell it
here? Writes eval/episodes_samples.md and .json.

    python evaluate_episodes.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import date

from openai import OpenAI

from config import ROOT, load_settings, rewrite_model

OUT = ROOT / "eval" / "episodes_samples"
SETTINGS = {"every turn": None, "threshold 0.30": "index", "threshold 0.40": 0.40}
CONVERSATIONS = [
    ("grief", ["Hi.", "My best friend died last week and I can't stop crying.",
               "We grew up together. I keep thinking I should have visited him more."]),
    ("betrayal", ["Hey. Can I tell you something?", "I lied to my closest friend when it really mattered.",
                  "He won't answer my messages. I don't think he'll ever forgive me."]),
    ("family", ["Hi there.", "My family thinks I'm wasting my life making art.",
                "My dad said I'll end up with nothing. Maybe he's right."]),
    ("exhausted", ["Hello.", "I'm exhausted. Work, kids, everything. I have nothing left.",
                   "I can't even remember the last time I rested."]),
    ("anger", ["Hi.", "I'm so angry at my brother I could scream.",
               "He took money from our mom and lied about it. Why should I forgive that?"]),
    ("shame", ["Hey.", "I blew all the money my parents gave me and I'm too ashamed to go home.",
               "What if they don't want me back?"]),
    ("lonely", ["Hi.", "I moved to a new city and I don't know anyone.",
                "Most nights I just eat alone and go to sleep."]),
    ("fear", ["Hello.", "I have a big surgery next week and I'm scared.",
              "What if something goes wrong?"]),
    ("small talk", ["Hi!", "What did you like to eat, back then?", "Did you ever just have a good laugh with friends?"]),
    ("off-topic", ["Hi.", "What's the weather going to be like in Chicago tomorrow?",
                   "Okay. Do you know a good way to learn Python?"]),
]

JUDGE = """You review a reply from a voice companion who speaks as Jesus and may recall moments of his life
from the Gospels. You are given what the person said, the moments offered to him (full text), and his reply.
Answer with JSON only:
{"told": "<title of the offered moment he told, or null>",
 "true_to_text": true | false | null,      // null if he told none; false if he added names, events or
                                           // outcomes that are not in that moment's text
 "invented": "<what he added, or empty>",
 "fit": "good" | "forced" | "wrong" | null, // null if he told none: did telling it help this person now?
 "missed": true | false,                   // he told none, but one offered moment would have helped
 "note": "<one short sentence>"}"""


async def converse(index, lines: list[str], min_score) -> list[dict]:
    from memory import EpisodeRecall
    from voice import Conversation

    recall = EpisodeRecall(index, OpenAI(timeout=20, max_retries=1), min_score=min_score)
    c = Conversation(index, text_mode=True, say=list(lines), log_dir=ROOT / "logs" / "eval_episodes",
                     out=lambda _text: None, recall=recall)
    try:
        await asyncio.wait_for(c.run(), timeout=240)
    except Exception as exc:  # one failed session must not stop the comparison
        logging.warning("Session failed: %s", type(exc).__name__)
    turns = []
    for turn in c.history:
        memo = turn.get("memory") or {}
        turns.append({"user": turn["user"], "replies": turn["replies"],
                      "offered": memo.get("offered") or [], "why_none": memo.get("why_none"),
                      "best": (memo.get("sections") or [{}])[0].get("score"),
                      "texts": {e["doc"]: e["text"] for e in turn.get("episodes") or []},
                      "told_heuristic": [t["ref"] for check in turn.get("checks", []) for t in check["told"]],
                      "invented": [c["memory_without_source"] for c in turn.get("checks", [])
                                   if c.get("memory_without_source")]})
    return turns


def judge(client: OpenAI, turn: dict) -> dict | None:
    if not turn["offered"]:
        return None
    offered = "\n\n".join(f"[{o['title']}] ({'he was there' if o['present'] else 'he was not there'})\n"
                          f"{turn['texts'].get(o['doc'], '')}" for o in turn["offered"])
    response = client.responses.create(
        model=os.getenv("JESUS_JUDGE_MODEL", rewrite_model()), instructions=JUDGE,
        input=f"Person said: {turn['user']}\n\nOffered moments:\n{offered}\n\nHis reply: {' '.join(turn['replies'])}")
    raw = response.output_text.strip().strip("`").removeprefix("json").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"note": "judge output was not JSON"}


def render(results: dict, conversations: list, settings: list | None = None) -> str:
    settings = settings or list(SETTINGS)
    lines = ["# How often should he remember? Samples", "",
             f"{date.today().isoformat()} · the same {len(conversations)} conversations at three recall settings · "
             "`memory` = the moments offered to him (best reranked score) · `judge` = an LLM's notes, a hint, not the "
             "verdict", ""]
    lines += ["## Summary", "", "*invented* is counted in code: \"I remember...\" said on a turn when no moment was "
              "offered. The other columns are the judge's.", "",
              "| setting | turns with a memory offered | told one | true to the text | fit good | forced or wrong | "
              "missed | invented with nothing offered |", "|---|---|---|---|---|---|---|---|"]
    for setting in settings:
        turns = [t for conv in results[setting].values() for t in conv[1:]]
        judged = [t["judge"] for t in turns if t.get("judge")]
        told = [j for j in judged if j.get("told")]
        lines.append(f"| {setting} | {sum(bool(t['offered']) for t in turns)}/{len(turns)} | {len(told)} | "
                     f"{sum(j.get('true_to_text') is True for j in told)}/{len(told)} | "
                     f"{sum(j.get('fit') == 'good' for j in told)} | "
                     f"{sum(j.get('fit') in ('forced', 'wrong') for j in told)} | "
                     f"{sum(bool(j.get('missed')) for j in judged)} | "
                     f"{sum(bool(t.get('invented')) for t in turns)} |")
    for name, conv_lines in conversations:
        lines += ["", f"## {name}", ""]
        for i, said in enumerate(conv_lines):
            if i == 0:
                continue  # the greeting
            lines += [f"**Person:** {said}", ""]
            for setting in settings:
                turns = results[setting][name]
                if i >= len(turns):
                    lines += [f"- *{setting}*: (session ended early)", ""]
                    continue
                t = turns[i]
                memo = ("; ".join(f"{o['title']} ({'there' if o['present'] else 'heard'}, {o['score']})"
                                  for o in t["offered"]) or f"none ({t['why_none']}, best {t['best']})")
                reply = " ".join(" ".join(t["replies"]).split())
                lines += [f"- *{setting}* · memory: {memo}", f"  > {reply}"]
                if t.get("invented"):
                    lines.append(f"  ⚠ invented a memory with nothing offered: \"{t['invented'][0]}\"")
                j = t.get("judge")
                if j:
                    bits = [f"told: {j.get('told') or '—'}"]
                    if j.get("told"):
                        bits.append(f"true to text: {j.get('true_to_text')}" + (f" ({j['invented']})" if j.get("invented") else ""))
                        bits.append(f"fit: {j.get('fit')}")
                    elif j.get("missed"):
                        bits.append("missed a fitting one")
                    lines.append(f"  judge: {' · '.join(bits)} — {j.get('note', '')}")
                lines.append("")
    return "\n".join(lines) + "\n"


async def main_async(only: list[str] | None, parallel: int, settings: list[str] | None = None,
                     out=None) -> None:
    from jesus import open_index

    load_settings()
    os.environ["JESUS_AVATAR_ENABLED"] = "false"
    index = open_index(OpenAI(timeout=10, max_retries=1))
    client = OpenAI(timeout=60, max_retries=1)
    # Two at a time: four sessions hit the realtime model's 200k tokens-per-minute limit.
    gate = asyncio.Semaphore(parallel)
    chosen = [c for c in CONVERSATIONS if not only or c[0] in only]

    async def one(setting, name, lines):
        async with gate:
            turns = await converse(index, lines, SETTINGS[setting])
            for turn in turns:
                turn["judge"] = await asyncio.to_thread(judge, client, turn)
            print(f"{setting:15} {name:11} " + " | ".join(
                (t["offered"][0]["title"] if t["offered"] else "-") for t in turns[1:]), flush=True)
            return setting, name, turns

    chosen_settings = [s for s in SETTINGS if not settings or s in settings]
    done = await asyncio.gather(*(one(s, n, l) for s in chosen_settings for n, l in chosen))
    results = {s: {} for s in chosen_settings}
    for setting, name, turns in done:
        results[setting][name] = turns
    target = out or OUT
    target.with_suffix(".md").write_text(render(results, chosen, chosen_settings), encoding="utf-8")
    target.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {target.with_suffix('.md')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated conversation names")
    parser.add_argument("--parallel", type=int, default=2, help="sessions at a time")
    parser.add_argument("--settings", help=f"comma-separated, from: {', '.join(SETTINGS)}")
    parser.add_argument("--out", help="output path without extension (default eval/episodes_samples)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from pathlib import Path

    asyncio.run(main_async(args.only.split(",") if args.only else None, args.parallel,
                           args.settings.split(",") if args.settings else None,
                           Path(args.out) if args.out else None))


if __name__ == "__main__":
    main()
