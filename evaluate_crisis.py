"""Score the crisis check: recall by kind of crisis, and false alarms on hard negatives.

The negatives are the phrases a naive filter trips on: figures of speech ("this commute is
killing me"), grief, and questions about scripture that mention death. A false alarm here
replaces a real answer with a helpline message, so both columns matter.

Two sets: crisis.jsonl was used to tune the phrase patterns; crisis_holdout.jsonl was
written before that tuning and never used for it, so it is the honest number.

    python evaluate_crisis.py     # writes eval/crisis_results.md (moderation calls are free)
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from openai import OpenAI

from config import ROOT, load_settings
from safety import CrisisCheck, classifier_check, phrase_check

SETS = {"tuning set": ROOT / "eval" / "crisis.jsonl", "held-out set": ROOT / "eval" / "crisis_holdout.jsonl"}
RESULTS = ROOT / "eval" / "crisis_results.md"
GROUPS = ("self_harm_active", "self_harm_passive", "abuse", "emergency")


def evaluate(name: str, cases: list[dict], layers: dict) -> list[str]:
    with ThreadPoolExecutor(8) as pool:
        flags = {layer: dict(zip([c["id"] for c in cases], pool.map(lambda c: bool(check(c["text"])), cases)))
                 for layer, check in layers.items()}
    groups = defaultdict(list)
    for case in cases:
        groups[case["group"]].append(case)
    order = [g for g in GROUPS if g in groups]
    positives = [c for c in cases if c["crisis"]]
    negatives = [c for c in cases if not c["crisis"]]
    lines = [f"## {name} ({len(positives)} crisis, {len(negatives)} hard negatives)", "",
             "| layer | " + " | ".join(f"{g} ({len(groups[g])})" for g in order)
             + " | all crisis | false alarms |", "|---|" + "---|" * (len(order) + 2)]
    for layer, flagged in flags.items():
        lines.append(f"| {layer} | " + " | ".join(f"{sum(flagged[c['id']] for c in groups[g])}/{len(groups[g])}"
                                                  for g in order)
                     + f" | **{sum(flagged[c['id']] for c in positives)}/{len(positives)}**"
                     + f" | {sum(flagged[c['id']] for c in negatives)}/{len(negatives)} |")
    production = flags[list(flags)[-1]]
    missed = [c for c in positives if not production[c["id"]]]
    alarms = [c for c in negatives if production[c["id"]]]
    lines += ["", "Missed in production:", ""] + ([f"- {c['id']} ({c['group']}): {c['text']}" for c in missed]
                                                  or ["- none"])
    lines += ["", "False alarms in production:", ""] + ([f"- {c['id']}: {c['text']}" for c in alarms] or ["- none"])
    return lines + [""]


def main() -> None:
    load_settings()
    client = OpenAI(timeout=15, max_retries=1)
    layers = {
        "phrases": phrase_check,
        "moderation": CrisisCheck(client, phrases=False, classifier=False),
        "classifier": lambda text: classifier_check(client, text),
        "before: phrases + moderation": CrisisCheck(client, classifier=False),
        "now: phrases + classifier (production)": CrisisCheck(client),
    }
    lines = ["# Crisis check eval", "", f"{date.today().isoformat()} · each layer alone, then combined as the "
             "check runs them; any layer flagging is enough, and moderation now only steps in when the "
             "classifier call fails. The phrase patterns were changed after seeing the tuning set, never the "
             "held-out set. The classifier is a model and not deterministic: a rerun can move a borderline "
             "case.", ""]
    for name, path in SETS.items():
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        lines += evaluate(name, cases, layers)
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
