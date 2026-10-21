"""Curate the memory pool once, offline: keep only sayings that can be said, as they are,
to someone who came to be comforted.

Ranking sayings by similarity at run time is fast but blind to tone: it offered "No one
is good except God alone" to "I'll never be good enough" and "Do you still not
understand?" to "Maybe I'm not smart enough". The judgment an LLM selector made on every
turn (about 1 s) is made here, once per saying, so the spoken turn stays LLM-free.
Writes data/memory/curation.json; memory.py uses only the kept sayings when it exists.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from config import ROOT, load_settings, rewrite_model

MEMORY_DIR = ROOT / "data" / "memory"
BATCH = 40

INSTRUCTIONS = """You are curating sayings of Jesus (from the Gospels) that a gentle, fatherly Jesus could say,
exactly as written, to someone who came to him to be comforted: sad, ashamed, lonely, afraid, grieving,
discouraged, or feeling unworthy.

KEEP a saying only if ALL are true:
1. It is a complete sentence that makes sense alone, without the story around it.
2. Its tone is comfort, welcome, reassurance, mercy, forgiveness, peace, hope, rest, love, or gentle
   encouragement, and it would land kindly if said to a hurting person today.

DROP it if it is any of: a rebuke or a rebuking question; a warning, judgment or threat; a prediction of
persecution, suffering or betrayal; a specific command (sell, go, follow me, forgive your brother, pray
this way); a rule or teaching about other people; a line of narration inside a parable or story; words
tied to one scene ("Lazarus, come out"); a fragment or a list; anything about money, law or the temple.

Return JSON only: {"items": [{"i": <number>, "keep": true|false, "theme": "<2-4 words>"}]} with one entry
per saying, in order."""


def judge(client, model, batch: list[tuple[int, dict]]) -> list[dict]:
    listing = "\n".join(f"{i}. {u['words']}" for i, u in batch)
    for attempt in range(3):
        response = client.responses.create(model=model, instructions=INSTRUCTIONS, input=listing)
        try:
            items = json.loads(response.output_text.strip().strip("`").removeprefix("json").strip())["items"]
            if {item["i"] for item in items} == {i for i, _ in batch}:
                return items
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    raise RuntimeError(f"Could not judge batch starting at {batch[0][0]}")


def main() -> None:
    load_settings()
    units = json.loads((MEMORY_DIR / "units.json").read_text(encoding="utf-8"))
    client, model = OpenAI(timeout=60, max_retries=2), rewrite_model()
    batches = [list(enumerate(units))[start:start + BATCH] for start in range(0, len(units), BATCH)]
    with ThreadPoolExecutor(6) as pool:
        results = [item for items in pool.map(lambda b: judge(client, model, b), batches) for item in items]
    by_index = {item["i"]: item for item in results}
    curated = [{"ref": u["ref"], "words": u["words"], "keep": bool(by_index[i]["keep"]),
                "theme": by_index[i].get("theme", "")} for i, u in enumerate(units)]
    (MEMORY_DIR / "curation.json").write_text(json.dumps({"model": model, "items": curated}, ensure_ascii=False,
                                                         indent=0), encoding="utf-8")
    kept = [c for c in curated if c["keep"]]
    print(f"kept {len(kept)} of {len(curated)} sayings ({model})")


if __name__ == "__main__":
    main()
