"""Verse cards, the avatar message queue, and where the voice loop feeds the avatar."""

import asyncio
import json
import struct

from avatar_link import AvatarLink, verse_cards
from faithfulness import check
from scripture import Passage
from test_voice import REST, RecordingSession, audio, conversation, raw_event

MATTHEW_11 = Passage(5, "Matthew", 11, (28, 29, 30), (
    "Come to Me, all you who are weary and burdened, and I will give you rest.",
    "Take My yoke upon you and learn from Me, for I am gentle and humble in heart, "
    "and you will find rest for your souls.",
    "For My yoke is easy and My burden is light.",
))
LUKE_17 = Passage(6, "Luke", 17, (3,), (
    "Watch yourselves. If your brother sins, rebuke him; and if he repents, forgive him.",))


def test_cards_show_the_retrieved_text_and_merge_neighbouring_verses():
    spoken = ("Come to Me, all you who are weary and burdened, and I will give you peace. "
              "Take My yoke upon you and learn from Me. Matthew 11:28-29.\n\n"
              "If your brother sins, rebuke him. Luke 17:3.")
    cards = verse_cards(check(spoken, [MATTHEW_11, LUKE_17]), [MATTHEW_11, LUKE_17])
    assert [c["ref"] for c in cards] == ["Matthew 11:28-29", "Luke 17:3"]
    # The voice said "peace"; the card shows the verse as written.
    assert cards[0]["text"].startswith("Come to Me") and "give you rest." in cards[0]["text"]


def test_own_words_make_no_card():
    assert verse_cards(check("My child, I hear you.", [MATTHEW_11]), [MATTHEW_11]) == []


def test_queue_frames_audio_and_resets_when_the_avatar_falls_behind():
    async def scenario():
        link = AvatarLink("ws://unused")
        link.push(b"\1\0" * 10)
        link.push(b"\1")  # half a sample is ignored
        first = link.queue.get_nowait()
        for _ in range(40):
            link.push(b"\0\0")
        return first, [link.queue.get_nowait() for _ in range(link.queue.qsize())]

    first, rest = asyncio.run(scenario())
    assert len(first) == 8 + 20 and struct.unpack("<d", first[:8])[0] > 0
    assert '{"type":"reset"}' in rest and len(rest) <= 32


def test_voice_loop_feeds_cards_and_clears_them_when_the_person_speaks(tmp_path, monkeypatch):
    monkeypatch.setenv("JESUS_AVATAR_ENABLED", "true")

    async def scenario():
        c, session = conversation(tmp_path), RecordingSession()
        c.retrieved[REST.id] = REST
        c._on_assistant_text("out1", "Come to Me, all you who are weary and burdened. Matthew 11:28.")
        await c._on_event(session, raw_event("input_audio_buffer.speech_started"))
        await c._on_event(session, audio("out2", 100))
        c._drop_playback("test")
        return [c.avatar.queue.get_nowait() for _ in range(c.avatar.queue.qsize())]

    messages = asyncio.run(scenario())
    verse = json.loads(messages[0])
    assert verse == {"type": "verse", "verses": [{"ref": "Matthew 11:28", "text": REST.texts[0]}]}
    assert json.loads(messages[1]) == {"type": "verse_clear"}
    assert messages[-1] == '{"type":"reset"}'  # dropped playback resets the lips
