"""Build the memory index: every red-letter saying (the words of Jesus) in the Gospels,
cut per verse, checked to be an exact piece of the bsb.txt verse, and embedded.

Memory (memory.py) ranks these against what the person just said, inside the sections
RAGFlow returned, so picking a saying needs no LLM call on the spoken turn.
Writes data/memory/units.json and data/memory/embeddings.npy.
"""

from __future__ import annotations

import json
import re

import numpy as np
from openai import OpenAI

from config import RAW_BSB, ROOT, embed_model, load_settings
from pericopes import USFM_FILES, _FOOTNOTE, _MARKER
from retrieval import openai_embedder
from scripture import GOSPELS, read_verses

USFM_DIR = ROOT / "data" / "raw" / "usfm" / "bsb_usfm"
OUT = ROOT / "data" / "memory"
_QUOTES = "“”‘’\"' "


def _plain(text: str) -> str:
    text = _MARKER.sub("", text)
    text = re.sub(r"\[[‘’“”'\"]+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def red_spans() -> dict[tuple[str, int, int], list[str]]:
    """{(book, chapter, verse): [red-letter pieces in order]}; spans may run across verses."""
    spans: dict[tuple[str, int, int], list[str]] = {}
    for book in GOSPELS:
        source = _FOOTNOTE.sub("", (USFM_DIR / f"{USFM_FILES[book]}.usfm").read_text(encoding="utf-8-sig"))
        chapter, verse, red = 0, None, False
        current: list[str] = []

        def flush():
            if verse is not None:
                pieces = [p for p in (_plain(x) for x in current) if p]
                if pieces:
                    spans[(book, chapter, verse)] = pieces

        for line in source.splitlines():
            if line.startswith("\\c "):
                flush(); verse, current = None, []
                chapter = int(line.split()[1])
                continue
            if line.startswith(("\\id", "\\h", "\\toc", "\\mt", "\\usfm", "\\r ", "\\s")):
                continue
            parts = re.split(r"\\v (\d+) ", line)
            for i, part in enumerate(parts):
                if i % 2 == 1:  # a verse number
                    flush(); verse, current = int(part), []
                    if red:
                        current.append("")
                    continue
                for piece in re.split(r"(\\wj\*|\\wj )", part):
                    if piece == "\\wj ":
                        red = True
                        current.append("")
                    elif piece == "\\wj*":
                        red = False
                    elif red and current:
                        current[-1] += " " + piece
        flush()
    return spans


def main() -> None:
    load_settings()
    canonical = {v.key: v.text for v in read_verses(RAW_BSB)}
    units, dropped = [], 0
    for (book, chapter, verse), pieces in red_spans().items():
        text = canonical.get((book, chapter, verse))
        if not text:
            continue
        for piece in pieces:
            words = piece.strip(_QUOTES + ",;:")
            # Keep the closing period/question mark when the verse has it right after.
            if not words or len(words.split()) < 3:
                continue
            if words not in text:
                dropped += 1
                continue
            end = text.index(words) + len(words)
            if end < len(text) and text[end] in ".?!":
                words += text[end]
            units.append({"ref": f"{book} {chapter}:{verse}", "book": book, "chapter": chapter,
                          "verse": verse, "words": words, "verse_text": text})
    print(f"{len(units)} sayings from {len({u['ref'] for u in units})} verses ({dropped} pieces not exact, dropped)")
    vectors = openai_embedder(OpenAI(), embed_model())([u["words"] for u in units])
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "embeddings.npy", vectors)
    (OUT / "units.json").write_text(json.dumps(units, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
