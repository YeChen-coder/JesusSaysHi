"""BSB parsing, passage windows and eval range expansion."""

import pytest

from scripture import make_passages, range_keys, read_verses

SAMPLE = (
    "﻿The Holy Bible, Berean Standard Bible\t\r\n"
    "Verse\tBerean Standard Bible\r\n"
    "Malachi 4:6\tAnd he will turn the hearts of the fathers.\r\n"
    + "".join(f"Matthew 1:{v}\tMatthew one {v}.\r\n" for v in range(1, 8))
    + "Matthew 2:1\tMatthew two 1.\r\n"
    "Matthew 2:2\t\r\n"
    "Matthew 2:3\tMatthew two 3.\r\n"
    "John 7:52\tSeventy-two.\r\n"
    "John 7:53\tThen each went to his own home.\r\n"
    "John 8:1\tBut Jesus went to the Mount of Olives.\r\n"
)


@pytest.fixture
def verses(tmp_path):
    path = tmp_path / "bsb.txt"
    path.write_bytes(SAMPLE.encode("utf-8"))
    return read_verses(path)


def test_reads_only_gospels_and_skips_empty_placeholder_verses(verses):
    refs = [v.key for v in verses]
    assert ("Malachi", 4, 6) not in refs
    assert ("Matthew", 2, 2) not in refs
    assert refs[0] == ("Matthew", 1, 1)
    assert len(verses) == 7 + 2 + 3


def test_windows_stay_inside_a_chapter_and_cover_its_last_verse(verses):
    passages = make_passages(verses, size=5, stride=2)
    matthew1 = [p for p in passages if p.book == "Matthew" and p.chapter == 1]
    assert [p.verses for p in matthew1] == [(1, 2, 3, 4, 5), (3, 4, 5, 6, 7)]
    short = [p for p in passages if p.book == "Matthew" and p.chapter == 2]
    assert [p.verses for p in short] == [(1, 3)]
    assert short[0].ref == "Matthew 2:1-3"
    assert short[0].numbered() == "[1] Matthew two 1. [3] Matthew two 3."
    assert [p.id for p in passages] == list(range(len(passages)))


def test_range_crosses_chapters_and_rejects_unknown_verses(verses):
    assert range_keys("John 7:53-8:1", verses) == {("John", 7, 53), ("John", 8, 1)}
    assert range_keys("Matthew 1:6", verses) == {("Matthew", 1, 6)}
    with pytest.raises(ValueError):
        range_keys("Matthew 1:9", verses)
    with pytest.raises(ValueError):
        range_keys("Matthew 1:5-2", verses)
