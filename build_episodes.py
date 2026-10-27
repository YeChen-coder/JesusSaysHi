"""Label each BSB section by whether Jesus was there, for episodic memory (memory.py).

Each of the 487 sections in data/sections/ is one episode: an event, a conversation or a
story. When one is recalled, he tells it the way a person tells their own past. The one
thing he cannot tell from the text in the moment is whether he was there: he can say "I
remember the night Peter..." of his own life, but of his birth, or of John the Baptist's
death, he should say "I heard..." or "my mother told me...". Whether an episode is a
story he told or something that happened is plain from the text, so it is not labelled.

How the label is decided, in order:
1. He speaks in the section (red letters in the BSB USFM): he was there. A story or a
   prophecy he tells is his own words, even when its characters are other people.
2. Otherwise a small model is asked three times and the majority wins. Asking once was
   not stable: a second pass flipped some answers ("The Baptism of Jesus" became "not
   there"), and the model also judged parables by their characters.
3. REVIEWED: answers checked by hand where the votes split or were wrong.
The label writes nothing he will say. Re-running reuses the votes already taken.

    python build_episodes.py     # writes data/episodes/episodes.json
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from config import RAW_BSB, ROOT, load_settings, rewrite_model
from pericopes import read_sections

SECTIONS = ROOT / "data" / "sections"
USFM_DIR = RAW_BSB.parent / "usfm" / "bsb_usfm"
OUT = ROOT / "data" / "episodes" / "episodes.json"
VOTES = 3

# Checked by hand: True = he was there. He stood in the high priest's house while Peter
# denied him ("the Lord turned and looked at Peter", Luke 22:61) and before Pilate while
# the crowd chose Barabbas, without a word in these sections; he was a baby at the temple
# and when the Magi came. At the empty tomb (Luke 24) and with the guards (Matthew 27:62)
# his red letters are others quoting him while he is not there.
REVIEWED = {
    "Luke 24.01 The Resurrection.txt": False,
    "Matthew 27.62 The Guards at the Tomb.txt": False,
    "Mark 14.66 Peter Denies Jesus.txt": True,
    "Matthew 26.69 Peter Denies Jesus.txt": True,
    "John 18.15 Peters First Denial.txt": True,
    "John 18.25 Peters Second and Third Denials.txt": True,
    "Mark 15.06 The Crowd Chooses Barabbas.txt": True,
    "Matthew 27.15 The Crowd Chooses Barabbas.txt": True,
    "Luke 02.21 Jesus Presented at the Temple.txt": False,
    "Luke 02.36 The Prophecy of Anna.txt": False,
    "Matthew 02.01 The Pilgrimage of the Magi.txt": False,
}

INSTRUCTIONS = """Below is one section of the Gospels. Was Jesus himself there for what happens in it, old enough
to remember it?
- yes: he is present and takes part: he travels, eats, heals, argues, teaches, tells a story, prays, is
  baptized, tempted, arrested, tried, crucified, or appears after rising. If he first hears news and then
  goes, acts or speaks in the same section, yes. As a boy of twelve in the temple, yes.
- no: he takes no part at all in this section, or is a baby: his birth and infancy, genealogies, the
  prologue about the Word, and things done by John the Baptist, Herod, Judas, the priests, the guards or
  the disciples while he is elsewhere (or while he lies in the tomb).
Reply with JSON only: {"present": "yes" | "no", "gist": "what happens, at most 15 plain words"}"""


def read_section(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    ref, _, title = lines[0].partition(" · ")
    return {"ref": ref.strip(), "title": title.strip(), "text": "\n".join(lines[1:])}


def vote(client: OpenAI, section: dict) -> tuple[str, str]:
    response = client.responses.create(model=rewrite_model(), instructions=INSTRUCTIONS,
                                       input=f"{section['ref']} · {section['title']}\n{section['text']}")
    data = json.loads(response.output_text.strip().strip("`").removeprefix("json").strip())
    if data.get("present") not in ("yes", "no"):
        raise ValueError(f"{section['ref']}: unexpected answer {data.get('present')!r}")
    return data["present"], str(data.get("gist", ""))


def votes_for(client: OpenAI, path: Path) -> dict:
    votes = [vote(client, read_section(path)) for _ in range(VOTES)]
    tally = Counter(answer for answer, _ in votes)
    answer = tally.most_common(1)[0][0]
    return {"llm_present": answer == "yes", "agreement": f"{tally[answer]}/{VOTES}",
            "gist": next(g for a, g in votes if a == answer)}


def main() -> None:
    load_settings()
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    for entry in old.values():  # files written before the red-letter rule kept the vote as "present"
        entry.setdefault("llm_present", entry.get("present"))
    sections = {s.filename(): s for s in read_sections(USFM_DIR)}
    shares = {name: s.jesus_share for name, s in sections.items()}
    paths = sorted(SECTIONS.glob("*.txt"))
    missing = [p.name for p in paths if p.name not in shares]
    if missing:
        raise SystemExit(f"{len(missing)} section files are not in the USFM sections, e.g. {missing[0]}")
    todo = [p for p in paths if "llm_present" not in old.get(p.name, {})]
    print(f"{len(paths) - len(todo)} with votes, {len(todo)} to ask")
    client = OpenAI(timeout=60, max_retries=2)

    def one(path: Path):
        try:
            return path.name, votes_for(client, path), None
        except Exception as exc:  # one failure must not lose the rest; re-run picks it up
            return path.name, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(8) as pool:
        for name, result, error in pool.map(one, todo):
            if error:
                print(f"  failed {name}: {error}")
            else:
                old.setdefault(name, {}).update(result)

    episodes = {}
    for path in paths:
        if path.name not in old:
            continue
        section, entry = read_section(path), old[path.name]
        share = shares[path.name]
        if path.name in REVIEWED:
            present, source = REVIEWED[path.name], "reviewed"
        elif share > 0:
            present, source = True, "he speaks"
        else:
            present, source = entry["llm_present"], f"model {entry['agreement']}"
        episodes[path.name] = {"ref": section["ref"], "title": section["title"], "present": present,
                               "source": source, "jesus_share": share, "llm_present": entry["llm_present"],
                               "agreement": entry["agreement"], "gist": entry["gist"],
                               # Other Gospels' accounts of the same event, so recall offers one, not two.
                               "parallels": [p.replace("–", "-") for p in sections[path.name].parallels]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(episodes, ensure_ascii=False, indent=1), encoding="utf-8")
    sources = Counter(e["source"].split()[0] for e in episodes.values())
    print(f"Wrote {OUT}: {len(episodes)} episodes, {sum(not e['present'] for e in episodes.values())} where he was "
          f"not there; decided by {dict(sources)}")
    for name, e in episodes.items():
        if e["source"] == "he speaks" and not e["llm_present"]:
            print(f"  red letters overruled the model: {e['ref']} · {e['title']}")


if __name__ == "__main__":
    main()
