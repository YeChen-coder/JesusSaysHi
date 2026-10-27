"""How true to the text is he when he tells a memory? Claim by claim, with a strong judge.

Reads replies already produced (eval/episodes_samples.json by default). For every reply on a
turn where episodes were offered, a strong model lists each concrete claim the reply makes
about his past and labels it. A first version had one "added" label for everything not in
the offered text; reading its output, most of those were not errors: the night and the
cold at Gethsemane, "I loved Peter", or Peter weeping when he had only been given the
prediction of the denial. So the labels now separate what a person remembering would
naturally say from what is wrong:

  supported   in the episode he was given
  elsewhere   not in it, but true elsewhere in the four Gospels (his life, which he knows)
  feeling     what he felt, or the plain setting (night, cold, quiet), consistent with the text
  wrong       contradicts the text: wrong person or gender, order, number or speaker, a story
              he told presented as something he saw, two episodes blended into one
  invented    an event, person, object or saying that is in none of the four Gospels

"wrong" and "invented" are the errors; the rest is retelling.

Writes eval/fidelity_results.md and .json.

    python evaluate_fidelity.py [samples.json]
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from openai import OpenAI

from config import ROOT, load_settings
from memory import EPISODES, overlaps, read_episode

OUT = ROOT / "eval" / "fidelity_results"
LABELS = ("supported", "elsewhere", "feeling", "wrong", "invented")
ERRORS = ("wrong", "invented")

JUDGE = """You check a voice companion who speaks as Jesus and sometimes retells a moment of his own life from the
Gospels. You get what the person said, his reply, the episode texts he was given (OFFERED, one or two), and other
Gospels' accounts of the same events (PARALLEL). You know the four Gospels well yourself.

List every concrete claim his reply makes about the past: people, places, actions, objects, numbers, what someone
said, what someone felt. Do not list comfort or advice spoken to the person now, or his general images ("like a
lamp in a window"). Label each claim:
- supported: stated in, or plainly implied by, the OFFERED episode it belongs to
- elsewhere: not in that episode, but true according to another passage of the four Gospels (including PARALLEL)
- feeling: what Jesus himself felt, or the plain setting of the scene (night, cold, a quiet place), consistent with
  the text and not contradicted by it
- wrong: contradicts the Gospels: wrong person or gender, wrong order, number or speaker; a parable he told
  presented as something that happened to him or that he saw; details of two different episodes blended into one;
  thoughts or words given to another person that the text does not give them
- invented: an event, person, object or saying that is in none of the four Gospels
Reply with JSON only:
{"told": "<title of the offered episode he retold, or null if he retold none>",
 "claims": [{"claim": "<short paraphrase>", "label": "<label>", "evidence": "<a few words of the text, or empty>"}]}"""


def parallels_text(doc: str, episodes: dict) -> str:
    """Other sections telling the same event, by the parallel references of this one."""
    refs = episodes[doc].get("parallels", [])
    found = [name for name, e in episodes.items() if name != doc and any(overlaps(r, e["ref"]) for r in refs)]
    return "\n\n".join(f"[{episodes[n]['ref']} · {episodes[n]['title']}]\n{read_episode(n)}" for n in found[:3])


def judge(client: OpenAI, turn: dict, episodes: dict) -> dict:
    offered = "\n\n".join(f"[{o['ref']} · {o['title']}]\n{turn['texts'].get(o['doc'], '')}" for o in turn["offered"])
    parallel = "\n\n".join(p for p in (parallels_text(o["doc"], episodes) for o in turn["offered"]) if p) or "(none)"
    reply = " ".join(turn["replies"])
    response = client.responses.create(
        model=os.getenv("JESUS_FIDELITY_MODEL", "gpt-6-sol"), instructions=JUDGE,
        input=f"Person said: {turn['user']}\n\nHis reply: {reply}\n\nOFFERED:\n{offered}\n\nPARALLEL:\n{parallel}")
    raw = response.output_text.strip().strip("`").removeprefix("json").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"told": None, "claims": [], "error": "judge output was not JSON"}


def main() -> None:
    load_settings()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "episodes_samples.json"
    samples = json.loads(source.read_text(encoding="utf-8"))
    episodes = json.loads(EPISODES.read_text(encoding="utf-8"))
    client = OpenAI(timeout=120, max_retries=2)
    jobs = [(setting, conv, i, t) for setting, convs in samples.items() for conv, turns in convs.items()
            for i, t in enumerate(turns) if t.get("offered") and t.get("replies")]
    with ThreadPoolExecutor(6) as pool:
        verdicts = list(pool.map(lambda job: judge(client, job[3], episodes), jobs))
    rows = []
    for (setting, conv, i, t), v in zip(jobs, verdicts):
        rows.append({"setting": setting, "conversation": conv, "turn": i, "user": t["user"],
                     "reply": " ".join(t["replies"]), "offered": [o["title"] for o in t["offered"]], **v})

    lines = ["# How true to the text is he when he tells a memory?", "",
             f"{date.today().isoformat()} · replies from `{source.name}` · claims listed and labelled by "
             f"`{os.getenv('JESUS_FIDELITY_MODEL', 'gpt-6-sol')}` against the offered episodes and their parallel "
             "accounts", "",
             "| setting | memories told | with no error | claims | " + " | ".join(LABELS) + " |",
             "|---|---|---|---|" + "---|" * len(LABELS)]
    for setting in samples:
        told = [r for r in rows if r["setting"] == setting and r.get("told")]
        claims = [c for r in told for c in r.get("claims", [])]
        counts = Counter(c.get("label") for c in claims)
        clean = sum(not any(c.get("label") in ERRORS for c in r.get("claims", [])) for r in told)
        lines.append(f"| {setting} | {len(told)} | {clean}/{len(told)} | {len(claims)} | "
                     + " | ".join(str(counts[label]) for label in LABELS) + " |")
    lines += ["", "## Every error (wrong or invented)", ""]
    for r in rows:
        bad = [c for c in r.get("claims", []) if c.get("label") in ERRORS]
        if not r.get("told") or not bad:
            continue
        lines.append(f"- **{r['setting']} · {r['conversation']} · turn {r['turn']}** (told: {r['told']}; offered: "
                     f"{'; '.join(r['offered'])})")
        for c in bad:
            lines.append(f"  - `{c.get('label')}` {c.get('claim')}" + (f" — text: “{c['evidence']}”" if c.get("evidence") else ""))
    OUT.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"Wrote {OUT.with_suffix('.md')}")


if __name__ == "__main__":
    main()
