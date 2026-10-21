"""Parse the Berean Standard Bible text and cut the Gospels into overlapping passages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GOSPELS = ("Matthew", "Mark", "Luke", "John")

_LINE = re.compile(r"^(?P<book>(?:\d )?[A-Za-z ]+?) (?P<chapter>\d+):(?P<verse>\d+)\t(?P<text>.*)$")
_RANGE = re.compile(
    r"^(?P<book>(?:\d )?[A-Za-z ]+?) (?P<c1>\d+):(?P<v1>\d+)(?:-(?:(?P<c2>\d+):)?(?P<v2>\d+))?$"
)

VerseKey = tuple[str, int, int]


@dataclass(frozen=True)
class Verse:
    book: str
    chapter: int
    verse: int
    text: str

    @property
    def key(self) -> VerseKey:
        return (self.book, self.chapter, self.verse)


@dataclass(frozen=True)
class Passage:
    id: int
    book: str
    chapter: int
    verses: tuple[int, ...]
    texts: tuple[str, ...]
    title: str = ""  # the BSB section heading, when the passage came from a section

    @property
    def ref(self) -> str:
        first, last = self.verses[0], self.verses[-1]
        return f"{self.book} {self.chapter}:{first}" + (f"-{last}" if last != first else "")

    @property
    def text(self) -> str:
        return " ".join(self.texts)

    def numbered(self) -> str:
        # The voice model cites single verses, so it needs the verse numbers inline.
        return " ".join(f"[{v}] {t}" for v, t in zip(self.verses, self.texts))

    def keys(self) -> set[VerseKey]:
        return {(self.book, self.chapter, v) for v in self.verses}

    def to_json(self) -> dict:
        return {"id": self.id, "book": self.book, "chapter": self.chapter,
                "verses": list(self.verses), "texts": list(self.texts)}

    @classmethod
    def from_json(cls, row: dict) -> "Passage":
        return cls(row["id"], row["book"], row["chapter"], tuple(row["verses"]), tuple(row["texts"]))


def read_verses(path: Path, books: tuple[str, ...] = GOSPELS) -> list[Verse]:
    """Return verses in canonical order, skipping the header and the empty verses the
    BSB keeps as placeholders for passages missing from the oldest manuscripts."""
    verses = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _LINE.match(line)
        if not match or match["book"] not in books:
            continue
        text = match["text"].strip()
        if text:
            verses.append(Verse(match["book"], int(match["chapter"]), int(match["verse"]), text))
    return verses


def make_passages(verses: list[Verse], size: int = 5, stride: int = 2) -> list[Passage]:
    """Slide a window of `size` verses over each chapter. Windows never cross a chapter,
    and the last window is pinned to the chapter end so no verse is left out."""
    chapters: dict[tuple[str, int], list[Verse]] = {}
    for verse in verses:
        chapters.setdefault((verse.book, verse.chapter), []).append(verse)

    passages: list[Passage] = []
    for (book, chapter), rows in chapters.items():
        starts = list(range(0, max(len(rows) - size, 0) + 1, stride))
        if starts[-1] + size < len(rows):
            starts.append(len(rows) - size)
        for start in starts:
            window = rows[start:start + size]
            passages.append(Passage(
                len(passages), book, chapter,
                tuple(v.verse for v in window), tuple(v.text for v in window),
            ))
    return passages


def range_keys(spec: str, verses: list[Verse]) -> set[VerseKey]:
    """Expand "John 7:53-8:11", "Mark 12:28-34" or "John 3:16" into verse keys.
    Both ends must exist in the corpus, so a typo in the eval set fails loudly."""
    match = _RANGE.match(spec.strip())
    if not match:
        raise ValueError(f"Cannot parse scripture range: {spec!r}")
    book, c1, v1 = match["book"], int(match["c1"]), int(match["v1"])
    c2 = int(match["c2"]) if match["c2"] else c1
    v2 = int(match["v2"]) if match["v2"] else v1
    index = {verse.key: i for i, verse in enumerate(verses)}
    try:
        first, last = index[(book, c1, v1)], index[(book, c2, v2)]
    except KeyError as missing:
        raise ValueError(f"{spec!r} names a verse not in the corpus: {missing}") from None
    if last < first:
        raise ValueError(f"{spec!r} ends before it starts")
    return {verse.key for verse in verses[first:last + 1]}
