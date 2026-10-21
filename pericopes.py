"""Structure-aware ingestion: cut the Gospels at the BSB's own section headings.

The USFM edition carries what plain text loses: section headings (\\s1), the parallel
accounts listed under them (\\r), and red-letter spans for the words of Jesus (\\wj).
Each section becomes one document for RAGFlow: a header, then one line per verse. With
parent-child chunking the verse lines are the children that get matched, and the whole
section is the parent that is handed to the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripture import GOSPELS

USFM_FILES = {"Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN"}

_FOOTNOTE = re.compile(r"\\f .*?\\f\*|\\x .*?\\x\*", re.S)
_REF_LINK = re.compile(r"\\ref ([^|\\]*)\|[^\\]*\\ref\*")
# An opening marker owns the space after it ("\wj text"); a closing one does not
# ("text\wj* he said"), or the words on either side would run together.
_MARKER = re.compile(r"\\[a-z]+[0-9]*\*|\\[a-z]+[0-9]* ?")


@dataclass
class VerseText:
    chapter: int
    verse: int
    text: str
    jesus_words: int = 0  # words inside red-letter spans
    words: int = 0


@dataclass
class Section:
    book: str
    title: str
    parallels: list[str] = field(default_factory=list)
    verses: list[VerseText] = field(default_factory=list)

    @property
    def ref(self) -> str:
        first, last = self.verses[0], self.verses[-1]
        if first.chapter == last.chapter:
            span = f"{first.verse}" + (f"-{last.verse}" if last.verse != first.verse else "")
            return f"{self.book} {first.chapter}:{span}"
        return f"{self.book} {first.chapter}:{first.verse}-{last.chapter}:{last.verse}"

    @property
    def jesus_share(self) -> float:
        words = sum(v.words for v in self.verses)
        return round(sum(v.jesus_words for v in self.verses) / words, 2) if words else 0.0

    def document(self) -> str:
        """A header, then one line per verse, each led by its full reference. Parallels
        live in the metadata only: as a line of their own, a bare "Hosea 11:1-7" got
        LLM keywords and questions about Hosea that the section does not contain."""
        lines = [f"{self.ref} \u00b7 {self.title}"]
        lines += [f"{self.book} {v.chapter}:{v.verse} {v.text}" for v in self.verses]
        return "\n".join(lines) + "\n"

    def filename(self) -> str:
        first = self.verses[0]
        safe = re.sub(r"[^A-Za-z0-9 ,'-]+", "", self.title).strip()
        return f"{self.book} {first.chapter:02d}.{first.verse:02d} {safe}.txt"

    def metadata(self) -> dict:
        first, last = self.verses[0], self.verses[-1]
        return {
            "book": self.book, "title": self.title, "reference": self.ref,
            "chapter_start": first.chapter, "verse_start": first.verse,
            "chapter_end": last.chapter, "verse_end": last.verse,
            "parallels": "; ".join(self.parallels),
            "jesus_speaks": "yes" if self.jesus_share > 0 else "no",
            "jesus_share": self.jesus_share,
        }


def _clean(raw: str, red: bool = False) -> tuple[str, int, int, bool]:
    """Plain verse text, how many of its words are red-letter, and whether a red-letter
    span is still open at the end (spans often run across several verses)."""
    raw = _FOOTNOTE.sub("", raw)
    jesus = 0
    for piece in re.split(r"(\\wj\*|\\wj )", raw):
        if piece == "\\wj ":
            red = True
        elif piece == "\\wj*":
            red = False
        elif red:
            jesus += len(_MARKER.sub("", piece).split())
    text = _MARKER.sub("", raw)
    text = re.sub(r"\[[‘’“”'\"]+\]", "", text)  # editorial closing-quote marks
    text = re.sub(r"\s+", " ", text).strip()
    # Joining poetry lines puts a space where the printed text has none.
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+(\)|\.\.\.)", r"\1", text)
    text = re.sub(r"([‘“])\s+", r"\1", text)  # opening quotes only
    text = re.sub(r"’\s+”", "’”", text)  # thin space between nested quotes
    text = re.sub(r"\s*—\s*", "—", text)
    return text, min(jesus, len(text.split())), len(text.split()), red


def read_sections(usfm_dir: Path, books: tuple[str, ...] = GOSPELS,
                  canonical: dict | None = None) -> list[Section]:
    """Sections with their verses. Pass `canonical` ({(book, chapter, verse): text}, from
    bsb.txt) to take the verse wording from there: structure comes from the USFM, text
    from the same edition the rest of the project quotes and checks against."""
    sections: list[Section] = []
    for book in books:
        source = (usfm_dir / f"{USFM_FILES[book]}.usfm").read_text(encoding="utf-8-sig")
        source = _FOOTNOTE.sub("", source)
        chapter = 0
        current: Section | None = None
        verse: tuple[int, int] | None = None
        buffer: list[str] = []
        red = [False]  # red-letter span open across verses

        def flush() -> None:
            if verse is None or current is None:
                return
            text, jesus, words, red[0] = _clean(" ".join(buffer), red[0])
            if text and canonical is not None:
                text = canonical.get((book, verse[0], verse[1]), text)
            if text:  # the BSB keeps empty placeholders for verses missing from early manuscripts
                current.verses.append(VerseText(verse[0], verse[1], text, jesus, words))

        for line in source.splitlines():
            if line.startswith("\\c "):
                flush()
                verse, buffer = None, []
                chapter = int(line.split()[1])
            elif line.startswith("\\s1 "):
                flush()
                verse, buffer = None, []
                current = Section(book, line[4:].strip())
                sections.append(current)
            elif line.startswith("\\r ") and current is not None and not current.verses:
                current.parallels = [m.strip() for m in _REF_LINK.findall(line)]
            elif "\\v " in line:
                head, *parts = re.split(r"\\v (\d+) ", line)
                buffer.append(head)
                for number, text in zip(parts[0::2], parts[1::2]):
                    flush()
                    verse, buffer = (chapter, int(number)), [text]
            elif verse is not None and not line.startswith(("\\id", "\\h", "\\toc", "\\mt", "\\usfm", "\\r ")):
                buffer.append(line)
        flush()
    return [s for s in sections if s.verses]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
