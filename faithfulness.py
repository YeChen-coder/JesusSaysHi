"""Check what the voice actually said against the verses it retrieved.

Retrieval metrics say whether the right passage was found; this says whether the model
then used it honestly. Ground truth here is exact text, so plain string matching is
enough, with no LLM judge:

- each spoken sentence is aligned with the retrieved passage it overlaps most and
  labelled verbatim (not one word changed inside the quoted stretch), paraphrased
  (similar, but changed) or own words;
- each spoken reference ("Matthew 11:28") must point at a verse that was retrieved;
- each quote must come from a verse cited in its own paragraph (otherwise it is
  misattributed), and a quote in a paragraph that cites nothing is counted as uncited.

It runs after the reply is spoken, so it measures and logs; it cannot stop a bad reply.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from scripture import GOSPELS, Passage

PARAPHRASE = 0.6
MIN_QUOTE_WORDS = 4  # fewer shared words than this is coincidence ("I am", "to you")

_BOOKS = "|".join(GOSPELS)
_REFERENCE = re.compile(
    rf"\b({_BOOKS})\s+(?:chapter\s+)?(\d+)(?:\s*:\s*|,?\s+verses?\s+)(\d+)"
    r"(?:\s*(?:-|–|to|through)\s*(\d+))?",
    re.IGNORECASE,
)
# An ellipsis marks an honest omission, so the pieces on either side are checked apart.
_SENTENCE_END = re.compile(r"[.!?;:“”\"…]+")


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower().replace("’", "'"))


def cited_references(text: str) -> list[tuple[str, int, int, int]]:
    refs = []
    for match in _REFERENCE.finditer(text):
        book = next(b for b in GOSPELS if b.lower() == match[1].lower())
        first = int(match[3])
        refs.append((book, int(match[2]), first, int(match[4]) if match[4] else first))
    return refs


def align(spoken: list[str], source: list[str]) -> tuple[float, int, int, int, int]:
    """Return (similarity, changed words, matched words, source start, source end).

    Words before the quoted stretch are allowed as a bridge ("My child, ..."). Words
    right after it are compared with the words that follow in the source, otherwise
    "...I will give you peace" for "...I will give you rest" would pass as a partial
    quote followed by one word of the speaker's own.
    """
    blocks = [b for b in SequenceMatcher(None, spoken, source, autojunk=False).get_matching_blocks()
              if b.size >= 2]
    matched = sum(b.size for b in blocks)
    if matched < MIN_QUOTE_WORDS:
        return 0.0, len(spoken), matched, 0, 0
    first, last = blocks[0], blocks[-1]
    spoken_end, source_end = last.a + last.size, last.b + last.size
    tail = min(len(spoken) - spoken_end, len(source) - source_end)
    spoken_span = spoken_end - first.a + tail
    source_span = source_end - first.b + tail
    changed = max(spoken_span, source_span) - matched
    return 2 * matched / (spoken_span + source_span), changed, matched, first.b, source_end


def _source(passage: Passage, only: set[int] | None = None) -> tuple[Passage, list[str], list[int]]:
    tokens, verse_of = [], []
    for verse, text in zip(passage.verses, passage.texts):
        if only is None or verse in only:
            verse_words = words(text)
            tokens += verse_words
            verse_of += [verse] * len(verse_words)
    return passage, tokens, verse_of


def check(spoken: str, passages: list[Passage]) -> dict:
    retrieved = {(p.book, p.chapter, v) for p in passages for v in p.verses}

    # Each passage as one word list, remembering which verse every word came from,
    # so a quote that runs across two verses is checked as one stretch.
    sources = [_source(passage) for passage in passages]

    sentences, citations = [], []
    total = grounded = uncited = misattributed = 0
    # A reference covers the quotes of its own paragraph: splicing Matthew 18:16 onto
    # "Luke 17:3-4" passes every check on its own but still names the wrong source.
    for paragraph in re.split(r"\n\s*\n", spoken):
        cited = set()
        for book, chapter, first, last in cited_references(paragraph):
            keys = {(book, chapter, v) for v in range(first, last + 1)}
            cited |= keys
            citations.append({"ref": f"{book} {chapter}:{first}" + (f"-{last}" if last != first else ""),
                              "supported": bool(keys & retrieved)})
        for raw in _SENTENCE_END.split(_REFERENCE.sub(" ", paragraph)):
            tokens = words(raw)
            if not tokens:
                continue
            total += len(tokens)
            candidates = []
            # The cited verses on their own as well: "Jesus said to her" occurs at John 4:7
            # and 4:13, and a quote cited as 4:13 must be able to align there.
            cited_sources = [_source(p, {v for v in p.verses if (p.book, p.chapter, v) in cited})
                             for p in passages if any((p.book, p.chapter, v) in cited for v in p.verses)]
            for passage, source, verse_of in sources + cited_sources:
                similarity, changed, matched, start, end = align(tokens, source)
                if similarity > 0:
                    v1, v2 = verse_of[start], verse_of[end - 1]
                    ref = f"{passage.book} {passage.chapter}:{v1}" + (f"-{v2}" if v2 != v1 else "")
                    keys = {(passage.book, passage.chapter, v) for v in set(verse_of[start:end])}
                    candidates.append((similarity, changed, matched, ref, keys))
            best = max(candidates, key=lambda c: c[0], default=(0.0, len(tokens), 0, None, set()))
            # Parallel accounts word a saying almost identically ("Give to Caesar..." is in
            # Matthew, Mark and Luke). If the cited verse fits the sentence as well as the
            # best match does, the sentence is that quote, not a misattributed one.
            if cited and best[3] and not best[4] & cited:
                fitting = [c for c in candidates if c[4] & cited and (
                    c[1] == 0 if best[1] == 0 else c[0] >= best[0] - 0.05)]
                if fitting:
                    best = max(fitting, key=lambda c: c[0])
            similarity, changed, matched, ref, keys = best
            if ref and changed == 0:
                kind = "verbatim"
                grounded += matched
            elif ref and similarity >= PARAPHRASE:
                kind = "paraphrased"
            else:
                kind, ref = "own", None
            sentence = {"kind": kind, "ref": ref, "similarity": round(similarity, 2),
                        "changed_words": changed if ref else None, "matched_words": matched if ref else 0,
                        "text": raw.strip()}
            if kind != "own" and not cited:
                uncited += 1
                sentence["uncited"] = True
            elif kind != "own" and not keys & cited:
                misattributed += 1
                sentence["misattributed"] = True
            sentences.append(sentence)

    return {
        "words": total,
        "grounded_words": grounded,
        "grounded_share": round(grounded / total, 2) if total else 0.0,
        "retrieved": [p.ref for p in passages],
        "sentences": sentences,
        "citations": citations,
        "paraphrased": sum(1 for s in sentences if s["kind"] == "paraphrased"),
        "unsupported_citations": sum(1 for c in citations if not c["supported"]),
        "uncited_quotes": uncited,
        "misattributed_quotes": misattributed,
    }
