"""Turn integrity (ported from SpecterSaysHi), the crisis takeover, search and the reply log."""

import asyncio
import json
from types import SimpleNamespace

from agents.realtime.model_inputs import RealtimeModelSendInterrupt

from scripture import Passage
from voice import Conversation

REST = Passage(0, "Matthew", 11, (28,), (
    "Come to Me, all you who are weary and burdened, and I will give you rest.",))
PEACE = Passage(1, "John", 20, (19,), ("“Peace be with you!” He said to them.",))


class FakeIndex:
    passages = [REST, PEACE]

    def __init__(self):
        self.queries = []

    def search(self, themes, k=3, jesus_only=False):
        self.queries.append(themes)
        self.jesus_only = jesus_only
        return [REST]


class RecordingModel:
    def __init__(self):
        self.events = []

    async def send_event(self, event):
        self.events.append(getattr(event, "message", event))


class RecordingSession:
    def __init__(self):
        self.model = RecordingModel()
        self.sent_audio = []

    async def send_audio(self, chunk):
        self.sent_audio.append(chunk)


def raw_event(kind, **fields):
    return SimpleNamespace(type="raw_model_event",
                           data=SimpleNamespace(type="raw_server_event", data={"type": kind, **fields}))


def turn(kind):
    return SimpleNamespace(type="raw_model_event", data=SimpleNamespace(type=kind))


def audio(item_id, ms):
    return SimpleNamespace(type="audio", item_id=item_id, content_index=0,
                           audio=SimpleNamespace(data=b"\0" * (48 * ms)))


def sent(session, kind):
    return [e for e in session.model.events if isinstance(e, dict) and e.get("type") == kind]


def conversation(tmp_path, **kwargs):
    return Conversation(FakeIndex(), log_dir=tmp_path, out=lambda _text: None, **kwargs)


async def answer_started(c, session, item="in1"):
    await c._on_event(session, raw_event("input_audio_buffer.committed", item_id=item))
    await c._on_event(session, turn("turn_started"))
    await c._on_event(session, audio("out1", 500))


def test_reply_to_unrecognized_speech_is_cancelled_and_forgotten(tmp_path):
    async def scenario():
        c, session = conversation(tmp_path), RecordingSession()
        await answer_started(c, session)
        await c._on_event(session, raw_event(
            "conversation.item.input_audio_transcription.completed", item_id="in1", transcript="  "))
        await c._on_event(session, raw_event(
            "response.output_audio_transcript.done", item_id="out1", transcript="A guess at nothing."))
        return c, session

    c, session = asyncio.run(scenario())
    assert len(sent(session, "response.cancel")) == 1
    assert [e["other_data"]["item_id"] for e in sent(session, "conversation.item.delete")] == ["in1", "out1"]
    assert c.audio_queue.empty()
    assert c.reports == []  # a reply nobody heard is never checked


def test_recognized_speech_keeps_its_reply(tmp_path):
    async def scenario():
        c, session = conversation(tmp_path), RecordingSession()
        await answer_started(c, session)
        await c._on_event(session, raw_event(
            "conversation.item.input_audio_transcription.completed", item_id="in1", transcript="Hi there"))
        await asyncio.gather(*c.background)
        return session

    session = asyncio.run(scenario())
    assert not sent(session, "response.cancel")
    assert not sent(session, "conversation.item.delete")


def test_interruption_truncates_and_drops_unplayed_parts(tmp_path):
    async def scenario():
        c, session = conversation(tmp_path), RecordingSession()
        await answer_started(c, session)
        await c._on_event(session, audio("out2", 5_000))
        await c._on_event(session, turn("turn_ended"))
        c.playback_tracker.on_play_bytes("out1", 0, b"\0" * (48 * 300))
        await c._local_interrupt(session, [b"voice"])
        return session

    session = asyncio.run(scenario())
    interrupts = [e for e in session.model.events if isinstance(e, RealtimeModelSendInterrupt)]
    assert len(interrupts) == 1 and interrupts[0].playback_only
    assert [e["other_data"]["item_id"] for e in sent(session, "conversation.item.delete")] == ["out2"]
    assert session.sent_audio == [b"voice"]


def crisis_scenario(tmp_path, still_generating):
    async def scenario():
        c = conversation(tmp_path, crisis_check=lambda text: "self_harm" if "alive" in text else None)
        session = RecordingSession()
        await answer_started(c, session)
        if not still_generating:
            await c._on_event(session, turn("turn_ended"))  # generated, still playing
        await c._on_event(session, raw_event(
            "conversation.item.input_audio_transcription.completed", item_id="in1",
            transcript="I don't want to be alive anymore"))
        if still_generating:
            for _ in range(200):  # the check runs in a thread; wait for it to cancel
                if sent(session, "response.cancel"):
                    break
                await asyncio.sleep(0.01)
            await c._on_event(session, turn("turn_ended"))  # the cancelled reply ends
        await asyncio.gather(*c.background)
        return c, session

    return asyncio.run(scenario())


def test_crisis_language_cancels_a_reply_still_being_generated(tmp_path):
    c, session = crisis_scenario(tmp_path, still_generating=True)
    assert len(sent(session, "response.cancel")) == 1
    assert [e["other_data"]["item_id"] for e in sent(session, "conversation.item.delete")] == ["out1"]
    [create] = sent(session, "response.create")
    response = create["other_data"]["response"]
    assert response["tool_choice"] == "none" and "988" in response["instructions"]
    assert c.safety_replies == 1 and c.audio_queue.empty()


def test_crisis_language_stops_a_finished_reply_that_is_still_playing(tmp_path):
    c, session = crisis_scenario(tmp_path, still_generating=False)
    assert not sent(session, "response.cancel")  # nothing left to cancel
    assert [e["other_data"]["item_id"] for e in sent(session, "conversation.item.delete")] == ["out1"]
    assert len(sent(session, "response.create")) == 1
    assert c.audio_queue.empty() and not c.speaker_busy


def test_search_remembers_passages_and_formats_one_verse_per_line(tmp_path):
    c = conversation(tmp_path)
    result = asyncio.run(c.search("  weariness, rest  "))
    assert c.index.queries == ["weariness, rest"]
    assert REST.id in c.retrieved and c.searches == 1
    assert result.splitlines()[1] == f"Matthew 11:28: {REST.texts[0]}"
    assert "No themes" in asyncio.run(c.search("   "))
    asyncio.run(c.search("forgiveness", jesus_words_only=True))
    assert c.index.jesus_only is True


def test_each_reply_is_checked_once_and_logged_without_text(tmp_path, monkeypatch):
    monkeypatch.delenv("JESUS_LOG_TRANSCRIPTS", raising=False)
    c = conversation(tmp_path)
    c.retrieved[REST.id] = REST
    spoken = "Come to Me, all you who are weary and burdened, and I will give you rest. Matthew 11:28."
    c._on_assistant_text("out1", spoken)
    c._on_assistant_text("out1", spoken)  # the same item reported twice
    [line] = (tmp_path / "faithfulness.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["grounded_share"] == 1.0 and record["citations"][0]["supported"]
    assert all("text" not in s for s in record["sentences"])
    assert "100% of 16 spoken words verbatim scripture; no problems" in c.summary()


def test_opening_line_counts_as_scripture(tmp_path):
    c = conversation(tmp_path)
    report = c._check_reply("open", "Peace be with you.")
    assert report["sentences"][0]["kind"] == "verbatim"
