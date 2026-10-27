"""One Realtime conversation, by microphone and speaker or by typed text, with scripture search.

Ported from SpecterSaysHi's realtime_agent.py and cut down to what this character needs:
no camera, no memory, no reminders. What stays is what took longest to get right there:
local barge-in over echo-cancelled audio, and keeping what the model believes it said
equal to what the person actually heard. New here: the search_scripture tool, and a
faithfulness check on every reply (see faithfulness.py), logged to logs/faithfulness.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents import function_tool
from agents.realtime import (
    RealtimeAgent, RealtimeModelSendRawMessage, RealtimePlaybackTracker, RealtimeRunner,
)
from agents.realtime.model_inputs import RealtimeModelSendInterrupt

from avatar_link import AvatarLink, avatar_enabled, verse_cards
from config import ROOT
from echo import SpeakerReference
from faithfulness import check
from memory import overlaps, told
from research import make_research_tool
from persona import INSTRUCTIONS, INSTRUCTIONS_MEMORY, OPENING, SEARCH_DESCRIPTION, format_passages
from retrieval import ScriptureIndex
from safety import safety_instructions
from scripture import Passage

LOG = logging.getLogger("jesus")
SAMPLE_RATE = 24_000
FRAMES_PER_CHUNK = 2_400
_TRUE = {"1", "true", "yes", "on"}
# "I remember the night...", "I once sat with...": a particular memory being told.
_REMEMBERS = re.compile(r"\bI (?:remember|recall|once (?:sat|stood|walked|told|watched|saw|met|knew))\b[^.?!]*",
                        re.IGNORECASE)


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE


def tracing_enabled() -> bool:
    """Hosted SDK traces would upload conversations, so they are off unless asked for."""
    return _flag("JESUS_TRACE_ENABLED")


def transcript_logging_enabled() -> bool:
    """Local logs keep only lengths and references unless this is switched on."""
    return _flag("JESUS_LOG_TRANSCRIPTS")


def barge_in_mode() -> str:
    """local (default): while he speaks the mic is not uploaded, and a voice clearly
    louder than his echo stops him locally. server: Realtime VAD interrupts. off."""
    mode = os.getenv("JESUS_BARGE_IN_MODE", "local").strip().lower()
    return mode if mode in {"local", "server", "off"} else "local"


def echo_cancellation_enabled() -> bool:
    return _flag("JESUS_AEC_ENABLED", "true")


class LocalBargeIn:
    """Tell the person's voice from his own echo by loudness after echo cancelling.

    The first second of each playback only learns the echo level (the canceller is
    still converging); after that, 3 consecutive 100 ms chunks louder than
    max(min_rms, factor x baseline) count as an interruption.
    """

    def __init__(self, warmup_s: float | None = None, factor: float | None = None,
                 min_rms: float | None = None, chunks: int | None = None) -> None:
        self.warmup_s = warmup_s if warmup_s is not None else float(os.getenv("JESUS_BARGE_WARMUP_MS", "1000")) / 1000
        self.factor = factor if factor is not None else float(os.getenv("JESUS_BARGE_FACTOR", "3.0"))
        self.min_rms = min_rms if min_rms is not None else float(os.getenv("JESUS_BARGE_MIN_RMS", "500"))
        self.chunks = chunks if chunks is not None else int(os.getenv("JESUS_BARGE_CHUNKS", "3"))
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.started, self.baseline, self.loud, self.peak = now, 0.0, 0, 0.0

    def observe(self, rms: float, now: float) -> bool:
        self.peak = max(self.peak, rms)
        if now - self.started < self.warmup_s:
            self.baseline = max(self.baseline * 0.9 + rms * 0.1, rms * 0.5)
            return False
        if rms > max(self.min_rms, self.factor * self.baseline):
            self.loud += 1
        else:
            self.loud = 0
            self.baseline = self.baseline * 0.95 + rms * 0.05
        return self.loud >= self.chunks


def explicit_close_phrase(text: str) -> bool:
    return bool(len(text) <= 120 and re.fullmatch(
        r"(?:please\s+)?(?:can you\s+|could you\s+|would you\s+|i want (?:you )?to\s+)?"
        r"(?:end|close|stop)\s+(?:(?:this|the|our|current)\s+)?(?:conversation|session)"
        r"(?:\s+(?:now|please))?[.!?]?|stop listening[.!?]?",
        text.strip(), re.IGNORECASE,
    ))


def session_settings(text_mode: bool = False, create_response: bool = True) -> dict[str, Any]:
    """create_response=False: server VAD only detects turns, and the app starts each reply
    itself (the memory persona does, after recalling a verse)."""
    settings: dict[str, Any] = {
        # The full model, not mini: mini got the details of a remembered episode wrong in about 6 of 10
        # tellings, the full model in about 1 of 6 (README Phase 8). It costs about 3 times as much.
        "model_name": os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1"),
        "output_modalities": ["text"] if text_mode else ["audio"],
    }
    if text_mode:
        return settings
    # The microphone is the camera's, across the desk: far field, as in SpecterSaysHi.
    reduction = os.getenv("JESUS_SERVER_NOISE_REDUCTION", "far_field").strip().lower()
    if reduction not in {"far_field", "near_field", "off"}:
        raise ValueError("JESUS_SERVER_NOISE_REDUCTION must be far_field, near_field, or off")
    audio_format = {"type": "audio/pcm", "rate": SAMPLE_RATE}
    settings["audio"] = {
        "input": {
            "format": audio_format,
            # The language is fixed: left to guess, it once turned English into Korean.
            "transcription": {"model": os.getenv("OPENAI_INPUT_TRANSCRIPTION_MODEL", "gpt-transcribe"),
                              "language": os.getenv("JESUS_TRANSCRIPTION_LANGUAGE", "en")},
            "noise_reduction": None if reduction == "off" else {"type": reduction},
            "turn_detection": {
                "type": "server_vad",
                "threshold": float(os.getenv("JESUS_VAD_THRESHOLD", "0.65")),
                "prefix_padding_ms": int(os.getenv("JESUS_VAD_PREFIX_PADDING_MS", "300")),
                "silence_duration_ms": int(os.getenv("JESUS_VAD_SILENCE_DURATION_MS", "650")),
                "create_response": create_response,
                "interrupt_response": barge_in_mode() == "server",
            },
        },
        "output": {
            "format": audio_format,
            # ash: lower and calmer than cedar, which sounded too bright and eager for him.
            "voice": os.getenv("JESUS_VOICE", "ash"),
            "speed": float(os.getenv("JESUS_VOICE_SPEED", "0.85")),
        },
    }
    return settings


PROBLEMS = {
    "paraphrased": "paraphrased", "unsupported_citations": "unsupported citation",
    "misattributed_quotes": "misattributed", "uncited_quotes": "uncited",
}


def problems(report: dict) -> str:
    """The non-zero faithfulness problems of one reply or a whole session, as text."""
    return ", ".join(f"{report[key]} {label}" for key, label in PROBLEMS.items() if report.get(key))


def audio_device(sd: Any, name: str, direction: str) -> int | None:
    """Resolve a named audio device; an empty name uses the OS default."""
    if not name:
        return None
    channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
    for index, item in enumerate(sd.query_devices()):
        if name.casefold() in item["name"].casefold() and item[channel_key] > 0:
            return index
    raise RuntimeError(f"No {direction} audio device contains {name!r}")


class Conversation:
    """One session: opens with "Peace be with you.", closes on goodbye, idle, or age."""

    def __init__(self, index: ScriptureIndex, text_mode: bool = False,
                 say: list[str] | None = None, log_dir: Path | None = None,
                 out: Callable[[str], None] = print,
                 crisis_check: Callable[[str], str | None] | None = None,
                 recall: Any = None):
        self.index = index
        # Persona v3: a memory.EpisodeRecall; episodes of his life arrive as MEMORY notes, no search tool.
        self.recall = recall
        self.history: list[dict] = []  # [{"user", "replies", "memory"}], for recall and the checks
        self.crisis_items: set[str] = set()  # input items already answered by a safety reply
        self.turn_seq = 0  # user turns begun; a newer one cancels an older turn's phase B
        self.phase_state: dict | None = None  # the current two-phase turn (memory persona)
        self._session: Any = None
        self.used_refs: set[str] = set()
        self.crisis_check = crisis_check
        self.safety_replies = 0
        self.background: set[asyncio.Task] = set()
        self.text_mode = text_mode
        # Typed lines sent one per reply instead of reading the keyboard (text mode).
        self.script = list(say) if say is not None else None
        self.out = out
        self.log_dir = log_dir or ROOT / "logs"
        self.session_id = uuid.uuid4().hex[:8]
        self.stop = asyncio.Event()
        self.ready = asyncio.Event()
        self.reply_done = asyncio.Event()
        self.typed_lines: asyncio.Queue[str | None] = asyncio.Queue()
        # Realtime can generate audio faster than it plays, so the queue is unbounded:
        # a bounded one silently dropped chunks from long answers in Specter.
        self.audio_queue: asyncio.Queue[tuple[int, str, int, bytes]] = asyncio.Queue()
        self.playback_tracker = RealtimePlaybackTracker()
        self.speaker_reference = SpeakerReference()
        self.avatar = AvatarLink() if avatar_enabled() else None
        self.playback_generation = 0
        self.barge_mode = barge_in_mode()
        self.allow_barge_in = self.barge_mode == "server"
        self.use_aec = (not text_mode and self.barge_mode in {"server", "local"}
                        and echo_cancellation_enabled())
        self.local_barge = LocalBargeIn() if self.barge_mode == "local" else None
        self.barged_in = False
        self.last_committed_item: str | None = None
        self.response_input_item: str | None = None
        self.response_output_items: list[str] = []
        self.discarded_items: set[str] = set()
        self.checked_items: set[str] = set()
        self.playback_started_at: float | None = None
        self.started = self.last_activity = time.monotonic()
        self.response_active = False
        self.response_request_pending = False
        self.response_turns = 0
        self.turn_had_text = False
        self.turn_called_tool = False
        self.microphone_speaking = False
        self.speaker_busy = False
        self.tools_in_progress = 0
        self.completed_input_items: set[str] = set()
        self.pending_transcriptions = 0
        self.conversation_started = False
        self.voice_close_requested_at: float | None = None
        self.voice_close_goodbye_generated = False
        self.explicit_close_transcript_at: float | None = None
        self.searches = 0
        self.reports: list[dict] = []
        # Debugging timeline: one JSON line per event, text included when transcripts are on.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.timeline_path = self.log_dir / "sessions" / f"{stamp}_{self.session_id}.jsonl"
        # The microphone's current "not sent" window: why, since when, how loud it got.
        self.mic_window: dict[str, Any] | None = None
        # The opening line is John 20:19, so the check knows where it came from.
        # Only that verse: its whole window would let ordinary words ("Jesus said to her")
        # pass as quotes of John 20:15-18.
        window = next((p for p in index.passages
                       if p.book == "John" and p.chapter == 20 and 19 in p.verses), None)
        opening = window and Passage(window.id, "John", 20, (19,), (window.texts[window.verses.index(19)],))
        self.retrieved: dict[int, Passage] = {opening.id: opening} if opening else {}

    # Debugging timeline

    def _trace(self, event: str, **fields: Any) -> None:
        """Append one event to logs/sessions/<stamp>_<session>.jsonl. Text fields are kept
        only when JESUS_LOG_TRANSCRIPTS is on; timing and numbers always are."""
        if not transcript_logging_enabled():
            fields = {k: v for k, v in fields.items() if k not in {"text", "themes"}}
        entry = {"t": round(time.monotonic() - self.started, 3),
                 "at": datetime.now().isoformat(timespec="milliseconds"), "event": event, **fields}
        try:
            self.timeline_path.parent.mkdir(parents=True, exist_ok=True)
            with self.timeline_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            LOG.exception("Could not write the session timeline")

    def _mic_state(self, reason: str | None, rms: float) -> None:
        """Track why microphone audio is not being sent. When the reason changes, the
        finished window is logged with its length and its loudest chunk, so an attempt to
        interrupt that went nowhere shows up as a loud chunk in a muted window."""
        window = self.mic_window
        if window is not None and window["reason"] == reason:
            window["chunks"] += 1
            window["peak_rms"] = max(window["peak_rms"], rms)
            return
        if window is not None:
            self._trace("mic_not_sent", reason=window["reason"], ms=window["chunks"] * 100,
                        peak_rms=round(window["peak_rms"]))
        self.mic_window = None if reason is None else {"reason": reason, "chunks": 1, "peak_rms": rms}

    # Tools

    def make_search_tool(self):
        async def search_scripture(themes: str, jesus_words_only: bool = False) -> str:
            return await self.search(themes, jesus_words_only)

        search_scripture.__doc__ = SEARCH_DESCRIPTION
        return function_tool(search_scripture)

    async def search(self, themes: str, jesus_words_only: bool = False) -> str:
        """The search_scripture tool: retrieve, remember for the faithfulness check, format."""
        themes = themes.strip()[:500]
        if not themes:
            return "No themes were given. Ask the person one short question."
        started = time.monotonic()
        try:
            passages = await asyncio.to_thread(self.index.search, themes, 3, jesus_only=jesus_words_only)
        except Exception as exc:
            LOG.error("Scripture search failed (%s)", type(exc).__name__)
            self._trace("search_failed", themes=themes, error=type(exc).__name__)
            return ("Scripture search failed. Say briefly that you cannot find the words "
                    "right now. Do not quote from memory.")
        self.searches += 1
        for passage in passages:
            self.retrieved[passage.id] = passage
        self._trace("search", themes=themes, jesus_words_only=jesus_words_only,
                    ms=round((time.monotonic() - started) * 1000),
                    results=sorted({p.ref for p in passages}), abstained=not passages)
        if transcript_logging_enabled():
            LOG.info("Scripture search %r -> %s", themes, ", ".join(p.ref for p in passages))
        else:
            LOG.info("Scripture search (%d characters) -> %s", len(themes),
                     ", ".join(p.ref for p in passages))
        return format_passages(passages)

    def make_end_conversation_tool(self):
        @function_tool
        async def end_conversation() -> str:
            """Close the conversation when the person asks to stop or says goodbye."""
            if self.voice_close_requested_at is None:
                self.voice_close_requested_at = time.monotonic()
                LOG.info("Close requested by the person")
                self._trace("end_conversation_called")
            return "The conversation is closing. Say one short goodbye now."

        return end_conversation

    async def _research_gate(self, question: str) -> str | None:
        """Phase A may call research_web before the turn has been read (about 0.6 s in, the
        reading takes about 1.5 s). Wait for the kind; look up only information. For a
        ModuleNotFoundError, the search used to run and the fix came back step by step."""
        state = self.phase_state
        if state is None or "kind_ready" not in state:
            return None
        try:
            await asyncio.wait_for(state["kind_ready"].wait(), timeout=4)
        except asyncio.TimeoutError:
            return None
        kind = state.get("kind")
        if kind == "expert":
            return ("Not looked up: this needs a professional's judgment. Do not answer it or give steps. Say kindly "
                    "who would know (the doctor who has seen them, a lawyer, someone who works in that trade), "
                    "then turn to how they are.")
        if kind == "talk":
            return "Not looked up: this is not a question for information. Answer them as yourself."
        return None

    def build_agent(self) -> RealtimeAgent:
        if self.recall is not None:
            # research_web answers informational questions (weather, news, a fact) directly.
            return RealtimeAgent(name="Jesus", instructions=INSTRUCTIONS_MEMORY,
                                 tools=[make_research_tool(tracing_enabled(), self._research_gate),
                                        self.make_end_conversation_tool()])
        return RealtimeAgent(
            name="Jesus", instructions=INSTRUCTIONS,
            tools=[self.make_search_tool(), self.make_end_conversation_tool()],
        )

    # Faithfulness

    def _check_reply(self, item_id: str | None, text: str) -> dict | None:
        if not text.strip() or (item_id is not None and item_id in self.checked_items):
            return None
        if item_id is not None:
            self.checked_items.add(item_id)
        report = check(text, list(self.retrieved.values()))
        self.reports.append(report)
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": self.session_id, "mode": "text" if self.text_mode else "voice",
            "item": item_id, **report,
        }
        if not transcript_logging_enabled():
            # Copies: the report itself keeps its text for the avatar and the evals.
            record["sentences"] = [{k: v for k, v in s.items() if k != "text"} for s in report["sentences"]]
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with (self.log_dir / "faithfulness.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(record) + "\n")
        except OSError:
            LOG.exception("Could not write the faithfulness log")
        LOG.info("Faithfulness: %d words, grounded %.0f%%; %s", report["words"],
                 report["grounded_share"] * 100, problems(report) or "no problems")
        return report

    def summary(self) -> str:
        checked = [r for r in self.reports if r["words"]]
        if not checked:
            return "No replies were checked."
        # Weighted by words, so a short line before a quote does not halve the score.
        words = sum(r["words"] for r in checked)
        grounded = sum(r["grounded_words"] for r in checked) / words
        totals = {key: sum(r[key] for r in checked) for key in PROBLEMS}
        return (f"{len(checked)} replies, {self.searches} searches, {self.safety_replies} safety "
                f"replies, {grounded:.0%} of {words} spoken words verbatim scripture; "
                f"{problems(totals) or 'no problems'}")

    def _on_assistant_text(self, item_id: str | None, text: Any) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        if self.voice_close_requested_at is not None:
            self.voice_close_goodbye_generated = True
        if item_id in self.discarded_items:
            return
        self.turn_had_text = True
        report = self._check_reply(item_id, text)
        state = self.phase_state
        if state is not None and state["a_turn"] == self.response_turns:
            state["a_text"] = (state["a_text"] + " " + text.strip()).strip()
        if self.history:
            self.history[-1]["replies"].append(text.strip())
        if report and self.recall is not None:
            task = asyncio.get_running_loop().create_task(self._check_memory_use(text, self.history[-1] if self.history else {}))
            self.background.add(task)
            task.add_done_callback(self.background.discard)
        if report:
            self._trace("reply", item=item_id, text=text.strip(), words=report["words"],
                        grounded_share=report["grounded_share"], problems=problems(report) or None,
                        quoted=sorted({s["ref"] for s in report["sentences"] if s["kind"] != "own"}),
                        citations=report["citations"])
        if report and self.avatar:
            self.avatar.show_verses(verse_cards(report, list(self.retrieved.values())))
        if transcript_logging_enabled():
            LOG.info("Reply: %r", text)
        else:
            LOG.info("Reply produced (%d characters)", len(text))
        if self.text_mode:
            self.out(f"\nJesus: {text.strip()}")
            if report and report["words"] and self.recall is None:  # the quote persona's check
                quoted = sorted({s["ref"] for s in report["sentences"] if s["kind"] == "verbatim"})
                self.out(f"  [grounded {report['grounded_share']:.0%} · verbatim {', '.join(quoted) or '-'}"
                         f" · {problems(report) or 'no problems'}]")
            self.reply_done.set()

    # Turn state

    @staticmethod
    async def _send_raw(session: Any, kind: str, **fields: Any) -> None:
        """Events without a high-level SDK method (send_message would start a reply)."""
        await session.model.send_event(
            RealtimeModelSendRawMessage(message={"type": kind, "other_data": fields})
        )

    async def _request_opening(self, session: Any) -> None:
        if self.response_active or self.response_request_pending:
            return
        self.response_request_pending = True
        try:
            await self._send_raw(session, "response.create", response={
                "output_modalities": ["text"] if self.text_mode else ["audio"],
                "instructions": OPENING,
            })
        except Exception:
            self.response_request_pending = False
            raise

    async def _request_safety_reply(self, session: Any, kind: str) -> None:
        # Wait for a cancelled reply to finish: Realtime refuses a second active response.
        for _ in range(60):
            if not self.response_active:
                break
            await asyncio.sleep(0.05)
        self.response_request_pending = True
        try:
            await self._send_raw(session, "response.create", response={
                "output_modalities": ["text"] if self.text_mode else ["audio"],
                "instructions": safety_instructions(kind), "tool_choice": "none",
            })
        except Exception:
            self.response_request_pending = False
            LOG.exception("Could not request the safety reply")

    async def _check_crisis(self, session: Any, text: str, item_id: str | None = None) -> bool:
        """Replace the model's own answer to crisis language with a safety reply."""
        if self.crisis_check is None:
            return False
        started = time.monotonic()
        kind = await asyncio.to_thread(self.crisis_check, text)
        self._trace("crisis_check", item=item_id, result=kind, ms=round((time.monotonic() - started) * 1000))
        if not kind:
            return False
        self.safety_replies += 1
        if item_id is not None:
            self.crisis_items.add(item_id)
        LOG.warning("Crisis language (%s): replacing the reply with a safety reply", kind)
        if self.recall is not None:
            # Memory persona: phase A is one short receiving sentence with no scripture and
            # no advice, so it is let finish; cutting it after 0.7 s sounded like being
            # talked over. Phase B is skipped (crisis_items) and the safety reply follows.
            self._trace("crisis_reply_after_phase_a", item=item_id, kind=kind)
        elif item_id is not None and item_id == self.response_input_item and (
                self.response_active or self.speaker_busy):
            if self.response_active:
                try:
                    await self._send_raw(session, "response.cancel")
                except Exception:
                    LOG.exception("Could not cancel the reply")
            self._drop_playback("Dropped the reply to crisis language")
            self.playback_tracker.on_interrupted()
            await self._delete_items(session, self._forget_items(list(self.response_output_items)))
        await self._request_safety_reply(session, kind)
        return True

    # Two-phase reply (memory persona): speak at once, recall meanwhile, then continue.

    def _phase_instructions(self, phase: str, heard: str, said: str = "", memory_given: bool = False,
                            kind: str = "talk") -> str:
        """Per-response instructions replace the session's, so the persona is repeated. The
        transcript is included because the model's own hearing of a far-field microphone is
        worse than the transcription model's."""
        heard_line = ("# What they just said\nTranscribed: \"" + heard.replace('"', "'") + "\"\n"
                      "Trust these words over what you think you heard, including every \"not\" and \"don't\".\n\n")
        if phase == "A":
            rule = ("# Right now\nSay only ONE short sentence, at most about twelve words, that receives what they "
                    "said and how they feel, in your own voice. No advice, no question, no scripture, and do not "
                    "say what you are about to do (thinking, looking, searching, closing). Then stop; you will "
                    "go on in a moment. If it is a plain question for information (the weather, the news, a "
                    "price), say only a few natural words such as \"Let me see.\" instead.")
        elif phase == "single":
            rule = "# Right now\nAnswer them, following everything above."
        else:
            rule = ("# Right now\nYou have just said to them: \"" + said.replace('"', "'") + "\"\n"
                    "Go on from there as one flowing reply: do not repeat or rephrase that sentence, do not greet "
                    "them again, and do not open with a filler such as \"let me sit with you\". Say one or two more "
                    "short sentences that add something new, following everything above (including any MEMORY "
                    "note just given). If that sentence already answered a simple question, such as your name, "
                    "add only one short warm line. Never describe what you are about to say or do: no \"I'll share a "
                    "memory\", no \"then I'll stay with you\". If you tell a memory, simply begin it.")
        if phase == "B" and kind == "information":
            rule += ("\nThey asked for information. If you have not looked it up yet, call research_web now; then "
                     "tell them the answer plainly in a sentence or two, with nothing spiritual attached.")
        elif phase == "B" and kind == "expert":
            rule += ("\nThis needs a professional's judgment. Do not answer it, give steps or look it up: say kindly "
                     "who would know (the doctor who has seen them, a lawyer, someone who works in that trade), "
                     "then turn to how they are.")
        if phase in ("single", "B") and not memory_given:
            # Without a memory the model made one up ("I remember sitting with Peter at dusk,
            # and he'd get everyone smiling with some rough joke"); the general rule in the
            # persona did not hold, so the turn itself says so.
            rule += ("\nNo particular moment of your life comes to mind this time: do not tell one, and do not "
                     "begin \"I remember\". Speak as yourself.")
        return INSTRUCTIONS_MEMORY + "\n\n" + heard_line + rule

    async def _create_response(self, instructions: str | None = None) -> None:
        self.response_request_pending = True
        try:
            if instructions is None:
                await self._send_raw(self._session, "response.create")
            else:
                await self._send_raw(self._session, "response.create", response={"instructions": instructions})
        except Exception:
            self.response_request_pending = False
            LOG.exception("Could not start the reply")

    async def _answer_turn(self, item_id: str | None, text: str) -> None:
        """The words are known: start speaking now. The first turn gets one whole reply (no
        memory is offered then); later turns get phase A, one short sentence that receives
        them, while the memory is recalled for phase B."""
        first = len(self.history) <= 1
        self.turn_seq += 1
        state = {"seq": self.turn_seq, "item": item_id, "first": first, "phase": "single" if first else "A",
                 "a_done": asyncio.Event(), "a_text": "", "a_turn": None, "awaiting_start": True,
                 "t0": time.monotonic(), "done": False, "heard": text,
                 # The turn's kind (memory.read_turn), awaited by research_web's gate.
                 "kind": None, "kind_ready": asyncio.Event()}
        if first:
            state["kind_ready"].set()  # the first turn is not read; a lookup it asks for runs
        self.phase_state = state
        await self._create_response(self._phase_instructions("single" if first else "A", text))
        self._trace("phase_a_requested" if not first else "reply_requested", item=item_id, seq=state["seq"])
        await self._continue_turn(item_id, text)

    async def _continue_turn(self, item_id: str | None, text: str) -> None:
        """With the words known: recall (rewrite, RAGFlow, rank), wait for phase A to finish,
        then add the MEMORY note and start phase B. A newer turn, a crisis reply or the end
        of the session cancels phase B."""
        state = self.phase_state
        if state is None or state["done"] or (item_id is not None and state["item"] != item_id):
            return
        if state["first"]:
            state["done"] = True
            return
        try:
            # A RAGFlow read once took 16 s to time out, which in voice is 16 s of silence after
            # phase A. Past the limit he goes on without a memory (the thread finishes unseen).
            memo, episodes = await asyncio.wait_for(
                asyncio.to_thread(self.recall.recall, list(self.history), set(self.used_refs)),
                timeout=float(os.getenv("JESUS_MEMORY_TIMEOUT_SECONDS", "4")))
        except asyncio.TimeoutError:
            LOG.warning("Memory recall took too long; going on without a memory")
            memo, episodes = {"why_none": "recall took too long"}, []
        except Exception as exc:
            LOG.exception("Memory recall failed")
            memo, episodes = {"why_none": f"recall failed: {type(exc).__name__}"}, []
        memo["ready_ms"] = round((time.monotonic() - state["t0"]) * 1000)
        state["kind"] = memo.get("kind")
        state["kind_ready"].set()
        if self.history:
            self.history[-1]["memory"] = memo
            self.history[-1]["episodes"] = episodes  # with their text, for the check after the reply
        self._trace("memory", item=item_id, **memo)
        LOG.info("Memory ready at %d ms after the turn: %s", memo["ready_ms"],
                 "; ".join(f"{e['ref']} {e['title']}" for e in episodes) or memo.get("why_none"))
        try:
            await asyncio.wait_for(state["a_done"].wait(), timeout=20)
        except asyncio.TimeoutError:
            LOG.warning("Phase A never finished; skipping phase B")
        # Phase A sometimes calls research_web itself ("Let me check the forecast"). The SDK then
        # answers the tool output with a response of its own; a phase B started meanwhile ran
        # before the result and said "the lookup is still running", and the forecast it had
        # found was never spoken. That response is phase B now.
        reason = ("a newer turn started" if state["seq"] != self.turn_seq else
                  "phase A called a tool; its answer comes after the tool" if state.get("tool_called") else
                  "the crisis check answered this turn" if item_id is not None and item_id in self.crisis_items else
                  "the session is closing" if self.stop.is_set() or self.voice_close_requested_at is not None
                  else None)
        if reason:
            state["done"] = True
            self._trace("phase_b_skipped", item=item_id, reason=reason)
            return
        if episodes:
            await self._send_raw(self._session, "conversation.item.create", item={
                "type": "message", "role": "system",
                "content": [{"type": "input_text", "text": self.recall.note(episodes)}]})
        if self.text_mode:
            self.out("  [memory: " + ("; ".join(f"{e['ref']} · {e['title']} ({'there' if e['present'] else 'heard'})"
                                                for e in episodes) or memo.get("why_none", "none")) + "]")
        await self._create_response(self._phase_instructions("B", state["heard"], state["a_text"], bool(episodes),
                                                             memo.get("kind", "talk")))
        state["done"] = True
        now = round((time.monotonic() - state["t0"]) * 1000)
        self._trace("phase_b_requested", item=item_id, at_ms=now, memory_ready_ms=memo["ready_ms"],
                    a_done_ms=state.get("a_done_ms"), waited_for="memory" if memo["ready_ms"] >= (state.get("a_done_ms") or 0)
                    else "phase A")

    async def _check_memory_use(self, text: str, turn: dict) -> None:
        """Which offered episode did the reply tell, and did it recite scripture word for word
        from somewhere else? He retells episodes in his own words, so telling is detected by
        distinctive words shared with the episode (memory.told); the reply eval adds an LLM
        judge for that and for invented details. The second check runs against all four
        Gospels, so a verse the model recites from its own training shows up."""
        if not turn:
            return  # the opening "Peace be with you." is scripted, not a memory
        episodes = turn.get("episodes") or []
        result: dict[str, Any] = {"offered": [e["ref"] for e in episodes], "told": []}
        invented = _REMEMBERS.search(text) if not episodes else None
        if invented:
            # A particular memory with no episode behind it: the model's own invention.
            result["memory_without_source"] = invented.group(0)
            LOG.warning("Reply told a memory that was not offered: %r", invented.group(0))
        for e in episodes:
            shared = told(text, e["text"])
            if len(shared) >= 3:
                result["told"].append({"ref": e["ref"], "title": e["title"], "shared": shared[:8]})
                # Told now, so not offered again this session (nor another Gospel's account of it).
                self.used_refs.add(e["doc"])
                if self.avatar:
                    self.avatar.show_verses([{"ref": e["ref"], "text": e["title"]}])
        if os.getenv("JESUS_CHECK_ALL_SCRIPTURE", "true").strip().lower() in _TRUE:
            started = time.monotonic()
            everything = await asyncio.to_thread(check, text, list(self.index.passages))
            result["other_scripture"] = [
                {"kind": s["kind"], "ref": s["ref"], "text": s["text"]} for s in everything["sentences"]
                # Six or more words verbatim: a whole-Gospel "paraphrase" match fires on ordinary
                # sentences. A verse inside an offered episode is the episode, not "other".
                if s["kind"] == "verbatim" and s.get("matched_words", 0) >= 6
                and not any(overlaps(s["ref"] or "", e["ref"]) for e in episodes)]
            result["check_ms"] = round((time.monotonic() - started) * 1000)
        turn.setdefault("checks", []).append(result)
        self._trace("memory_check", **result)
        if result.get("other_scripture"):
            LOG.warning("Reply recited scripture that was not in an offered episode: %s",
                        ", ".join(f"{s['ref']} ({s['kind']})" for s in result["other_scripture"]))

    def _accept_user_transcript(self, item_id: str | None, transcript: str | None) -> None:
        if isinstance(item_id, str):
            if item_id in self.completed_input_items:
                return
            self.completed_input_items.add(item_id)
            self.pending_transcriptions = max(0, self.pending_transcriptions - 1)
        if not isinstance(transcript, str) or not transcript.strip():
            LOG.info("Ignored empty audio turn")
            self._trace("user_unrecognized", item=item_id)
            return
        transcript = transcript.strip()
        self.last_activity = time.monotonic()
        self._trace("user", item=item_id, text=transcript, chars=len(transcript))
        self.history.append({"user": transcript, "replies": []})
        if explicit_close_phrase(transcript):
            self.explicit_close_transcript_at = time.monotonic()
            LOG.info("Direct close phrase recognized")
        else:
            self.conversation_started = True
        if transcript_logging_enabled():
            LOG.info("User: %r", transcript)
        else:
            LOG.info("User speech accepted (%d characters)", len(transcript))

    def _finish_close_if_ready(self) -> None:
        if (
            self.voice_close_requested_at is not None and self.voice_close_goodbye_generated
            and not self.response_active and not self.response_request_pending
            and not self.speaker_busy and self.audio_queue.empty() and not self.tools_in_progress
        ):
            LOG.info("Closing after the goodbye")
            self.stop.set()

    async def _on_event(self, session: Any, event: Any) -> None:
        if event.type == "audio":
            if event.item_id in self.discarded_items:
                return  # a reply already dropped (unrecognized speech, a duplicated opening)
            if not self.speaker_busy:
                self.playback_started_at = time.monotonic()
                self._trace("playback_start", item=event.item_id)
            self.speaker_busy = True
            if event.item_id not in self.response_output_items:
                self.response_output_items.append(event.item_id)
            self.audio_queue.put_nowait((
                self.playback_generation, event.item_id, event.content_index, event.audio.data,
            ))
            return
        if event.type == "audio_interrupted":
            self._trace("sdk_audio_interrupted", speaker_busy=self.speaker_busy)
            self._drop_playback("Reply audio interrupted")
            return
        if event.type == "tool_start":
            self.tools_in_progress += 1
            self._trace("tool_start", tool=getattr(event.tool, "name", None), arguments=getattr(event, "arguments", None))
            return
        if event.type == "tool_end":
            self._trace("tool_end", tool=getattr(event.tool, "name", None))
            self.tools_in_progress = max(0, self.tools_in_progress - 1)
            # The SDK answers every tool output with a new response.
            self.response_request_pending = True
            self.last_activity = time.monotonic()
            return
        if event.type == "error":
            LOG.error("Realtime SDK error: %s", type(event.error).__name__)
            return
        if event.type != "raw_model_event":
            return
        raw = event.data
        if raw.type == "turn_started":
            self.barged_in = False
            self.response_input_item, self.last_committed_item = self.last_committed_item, None
            self.response_output_items = []
            self.response_turns += 1
            self.turn_had_text = False
            self.turn_called_tool = False
            self.response_active = True
            self.response_request_pending = False
            self.last_activity = time.monotonic()
            state = self.phase_state
            if state is not None and state["awaiting_start"]:
                state["awaiting_start"] = False
                state["a_turn"] = self.response_turns
            self._trace("response_start", turn=self.response_turns, answering=self.response_input_item)
        elif raw.type == "turn_ended":
            self._trace("response_end", turn=self.response_turns)
            state = self.phase_state
            if state is not None and state["a_turn"] == self.response_turns and not state["a_done"].is_set():
                state["a_done_ms"] = round((time.monotonic() - state["t0"]) * 1000)
                state["a_done"].set()
            self.response_active = False
            self.response_request_pending = False
            self.last_activity = time.monotonic()
            # A reply that ends without a word (seen when many sessions ran at once) used to
            # leave a typed session waiting for ever; the next line now goes on, and the
            # empty turn is in the trace.
            if (self.text_mode and not self.turn_had_text and not self.turn_called_tool
                    and not self.reply_done.is_set() and (state is None or state["done"])):
                self._trace("no_reply", turn=self.response_turns)
                LOG.warning("A reply ended without any text")
                self.reply_done.set()
            self._finish_close_if_ready()
        elif raw.type == "input_audio_transcription_completed":
            await self._on_user_transcript(session, raw.item_id, raw.transcript)
        elif raw.type == "raw_server_event":
            data = raw.data
            kind = data.get("type") if isinstance(data, dict) else None
            if kind == "conversation.item.input_audio_transcription.completed":
                await self._on_user_transcript(session, data.get("item_id"), data.get("transcript"))
            elif kind == "input_audio_buffer.committed":
                item_id = data.get("item_id")
                self.last_committed_item = item_id if isinstance(item_id, str) else None

            elif kind == "response.output_item.added":
                item = data.get("item")
                item_id = item.get("id") if isinstance(item, dict) else None
                if (self.response_turns == 1 and isinstance(item_id, str) and isinstance(item, dict)
                        and item.get("type") == "message" and self.response_output_items):
                    # The opening reply produced a second "Peace be with you."; drop it unheard.
                    self._forget_items([item_id])
                    self._trace("opening_duplicate_dropped", item=item_id)
                    try:
                        await self._send_raw(session, "response.cancel")
                    except Exception:
                        LOG.exception("Could not cancel the duplicated opening")
                    await self._delete_items(session, [item_id])
                    return
                if isinstance(item, dict) and item.get("type") == "function_call":
                    self.turn_called_tool = True  # its words come in the response after the tool
                    if self.phase_state is not None and not self.phase_state["done"]:
                        self.phase_state["tool_called"] = True
                if isinstance(item_id, str) and item_id not in self.response_output_items:
                    self.response_output_items.append(item_id)
            elif kind == "session.updated" and not self.ready.is_set():
                LOG.info("Realtime session configured")
                self.ready.set()
                await self._request_opening(session)
            elif kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
                self.last_activity = time.monotonic()
                self.microphone_speaking = kind.endswith("speech_started")
                self._trace("vad_" + kind.rsplit("_", 1)[-1], audio_ms=data.get(
                    "audio_start_ms" if self.microphone_speaking else "audio_end_ms"))
                if self.microphone_speaking and self.avatar:
                    self.avatar.clear_verses()
                if not self.microphone_speaking:
                    self.pending_transcriptions += 1
            elif kind == "response.output_audio_transcript.done":
                self._on_assistant_text(data.get("item_id"), data.get("transcript"))
                self._finish_close_if_ready()
            elif kind == "response.output_text.done":
                self._on_assistant_text(data.get("item_id"), data.get("text"))
                self._finish_close_if_ready()
            elif kind == "response.done":
                response = data.get("response") or {}
                if response.get("status") not in (None, "completed"):
                    # cancelled / incomplete / failed: say why, or a silent turn is a mystery.
                    details = response.get("status_details") or {}
                    LOG.warning("Reply %s: %s", response.get("status"), json.dumps(details)[:300])
                    self._trace("reply_not_completed", status=response.get("status"), details=details)
            elif kind == "error":
                error = data.get("error") or {}
                LOG.error("Realtime event error: %s %s", error.get("code"), error.get("message"))
                self._trace("server_error", code=error.get("code"), message=error.get("message"))

    async def _consume_events(self, session: Any) -> None:
        try:
            async for event in session:
                await self._on_event(session, event)
        except Exception:
            LOG.exception("Realtime event stream failed")
        finally:
            self.stop.set()

    def _drop_playback(self, reason: str) -> None:
        """Stop his speech now: discard queued audio and its echo reference."""
        queued = self.audio_queue.qsize()
        self.playback_generation += 1
        while not self.audio_queue.empty():
            self.audio_queue.get_nowait()
        self.speaker_reference.clear()
        if self.avatar:
            self.avatar.reset()
        self.playback_started_at = None
        self.speaker_busy = False
        self.last_activity = time.monotonic()
        LOG.info("%s (discarded_chunks=%d)", reason, queued)

    def _forget_items(self, item_ids: list[str]) -> list[str]:
        """Mark replies as never said, so they are neither checked nor kept in context."""
        self.discarded_items.update(item_ids)
        return item_ids

    async def _delete_items(self, session: Any, item_ids: list[str]) -> None:
        for item_id in item_ids:
            try:
                await self._send_raw(session, "conversation.item.delete", item_id=item_id)
            except Exception:
                LOG.exception("Could not delete conversation item")

    async def _local_interrupt(self, session: Any, recent: list[bytes]) -> None:
        """The person spoke over him: stop, truncate the reply where they stopped hearing
        it, remove the parts that never played, then pass their words on."""
        self.barged_in = True
        state = self.playback_tracker.get_state()
        heard_item, heard_ms = state["current_item_id"], state["elapsed_ms"]
        try:
            await session.model.send_event(RealtimeModelSendInterrupt(playback_only=not self.response_active))
        except Exception:
            LOG.exception("Could not interrupt the reply")
        self._drop_playback("Person interrupted; reply stopped")
        self._trace("local_interrupt", item=heard_item, heard_ms=heard_ms,
                    baseline=round(self.local_barge.baseline) if self.local_barge else None)
        if heard_item is not None and heard_ms is not None:
            later = []
            if heard_item in self.response_output_items:
                later = self.response_output_items[self.response_output_items.index(heard_item) + 1:]
            await self._delete_items(session, self._forget_items(later))
            LOG.info("Reply cut at %.1f s (%d unplayed part(s) removed)", heard_ms / 1000, len(later))
        for chunk in recent:
            await session.send_audio(chunk)

    async def _on_user_transcript(self, session: Any, item_id: Any, transcript: Any) -> None:
        """Server VAD starts answering at speech stop; if the transcript then comes back
        empty (nothing recognized), cancel that answer and remove both from context."""
        repeated = isinstance(item_id, str) and item_id in self.completed_input_items
        self._accept_user_transcript(item_id, transcript)
        if repeated or not isinstance(item_id, str):
            return
        if isinstance(transcript, str) and transcript.strip():
            # In a task: the moderation call and the wait for a cancelled reply to end
            # both need this event loop to keep consuming events.
            if self.recall is not None:
                # Phase A waits for the transcript (about 0.4 s): started on the audio alone,
                # the model heard "scene" as "sin" and "I don't feel happy" as happy, and
                # phase B carried the mistake on.
                answer = asyncio.create_task(self._answer_turn(item_id, transcript.strip()))
                self.background.add(answer)
                answer.add_done_callback(self.background.discard)
            task = asyncio.create_task(self._check_crisis(session, transcript, item_id))
            self.background.add(task)
            task.add_done_callback(self.background.discard)
            return
        if self.phase_state is not None and self.phase_state["item"] == item_id:
            self.phase_state["done"] = True  # nothing recognized: no phase B
        if item_id != self.response_input_item or not (self.response_active or self.speaker_busy):
            return
        self.barged_in = True
        if self.response_active:
            try:
                await self._send_raw(session, "response.cancel")
            except Exception:
                LOG.exception("Could not cancel the reply")
        self._drop_playback("Speech was not recognized; dropped the reply it started")
        self._trace("dropped_reply_to_unrecognized_speech", item=item_id)
        self.playback_tracker.on_interrupted()
        self.response_input_item = None
        await self._delete_items(session, [item_id, *self._forget_items(list(self.response_output_items))])

    # Input and output

    def _read_keyboard(self, loop: asyncio.AbstractEventLoop) -> None:
        # A daemon thread, so a pending input() never blocks shutdown.
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                line = None
            loop.call_soon_threadsafe(self.typed_lines.put_nowait, line)
            if line is None:
                return

    async def _typed_input(self, session: Any) -> None:
        await asyncio.wait_for(self.ready.wait(), timeout=20)
        if self.script is None:
            threading.Thread(target=self._read_keyboard, args=(asyncio.get_running_loop(),),
                             daemon=True).start()
        while not self.stop.is_set():
            await self.reply_done.wait()
            while (self.response_active or self.response_request_pending or self.tools_in_progress
                   or (self.phase_state is not None and not self.phase_state["done"])):
                await asyncio.sleep(0.1)
            if self.stop.is_set():
                return
            if self.script is not None:
                line = self.script.pop(0) if self.script else None
                if line is not None:
                    self.out(f"\nYou: {line}")
            else:
                print("\nYou: ", end="", flush=True)
                line = await self.typed_lines.get()
            if line is None or line.strip().lower() in {"quit", "exit"}:
                self.stop.set()
                return
            if not line.strip():
                continue
            self.reply_done.clear()
            if self.avatar:
                self.avatar.clear_verses()
            line = line.strip()
            self._accept_user_transcript(None, line)
            kind = await asyncio.to_thread(self.crisis_check, line) if self.crisis_check else None
            if self.recall is not None and not kind:
                await self._send_raw(session, "conversation.item.create", item={
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": line}]})
                await self._answer_turn(None, line)
                continue
            if kind:
                self.safety_replies += 1
                LOG.warning("Crisis language (%s): answering with a safety reply", kind)
                await self._send_raw(session, "conversation.item.create", item={
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": line}],
                })
                await self._request_safety_reply(session, kind)
            else:
                await session.send_message(line)

    async def _microphone(self, session: Any, device: int | None) -> None:
        """Blocking capture in a worker thread; echo-cancelled against the speaker
        reference, and held back while a tool runs or (local mode) while he speaks."""
        import numpy as np
        import sounddevice as sd

        await asyncio.wait_for(self.ready.wait(), timeout=20)
        recent: deque[bytes] = deque(maxlen=4)  # ~0.4 s, sent on after an interruption
        processor = None
        if self.use_aec:
            from pywebrtc_audio import AudioProcessor

            processor = AudioProcessor(
                sample_rate=SAMPLE_RATE, echo_cancellation=True, noise_suppression=True,
                auto_gain_control=False, stream_delay_ms=int(os.getenv("JESUS_AEC_DELAY_MS", "0")),
            )
            LOG.info("WebRTC acoustic echo cancellation enabled")
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                   device=device, blocksize=FRAMES_PER_CHUNK) as stream:
                while not self.stop.is_set():
                    chunk, _overflow = await asyncio.to_thread(stream.read, FRAMES_PER_CHUNK)
                    pcm = bytes(chunk)
                    if self.voice_close_requested_at is not None:
                        continue
                    if processor is not None:
                        reference = self.speaker_reference.take(len(pcm))
                        pcm = processor.process(np.frombuffer(pcm, dtype=np.int16),
                                                np.frombuffer(reference, dtype=np.int16)).tobytes()
                    speaking = (self.response_active or self.speaker_busy) and not self.barged_in
                    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(samples ** 2)))
                    if self.local_barge is not None:
                        if speaking and self.playback_started_at:
                            if self.local_barge.started != self.playback_started_at:
                                self.local_barge.reset(self.playback_started_at)
                                recent.clear()
                            recent.append(pcm)
                            warm = time.monotonic() - self.playback_started_at < self.local_barge.warmup_s
                            self._mic_state("his speech, echo warmup (cannot interrupt)" if warm
                                            else "his speech (listening for an interruption)", rms)
                            if self.local_barge.observe(rms, time.monotonic()):
                                LOG.info("Local interruption: voice %.0f over echo baseline %.0f",
                                         rms, self.local_barge.baseline)
                                await self._local_interrupt(session, list(recent))
                                recent.clear()
                            continue
                        recent.clear()
                    if self.allow_barge_in and speaking and self.playback_started_at:
                        warmup = float(os.getenv("JESUS_AEC_WARMUP_MS", "500")) / 1000
                        if time.monotonic() - self.playback_started_at < warmup:
                            self._mic_state("echo warmup (server barge-in)", rms)
                            continue  # let AEC learn the room echo before VAD can interrupt
                    if not self.tools_in_progress and (self.allow_barge_in or not speaking):
                        self._mic_state(None, rms)
                        await session.send_audio(pcm)
                    else:
                        self._mic_state("tool running (search)" if self.tools_in_progress
                                        else "reply being generated, not yet playing", rms)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Microphone unavailable")
            self.stop.set()

    async def _speaker(self, device: int | None) -> None:
        """Play reply audio in 100 ms pieces so the echo reference tracks the real
        playback clock, and report progress so an interruption truncates correctly."""
        import sounddevice as sd

        try:
            with sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                    device=device) as stream:
                active_generation = self.playback_generation
                while not self.stop.is_set():
                    if active_generation != self.playback_generation:
                        await asyncio.to_thread(stream.abort)
                        await asyncio.to_thread(stream.start)
                        active_generation = self.playback_generation
                    try:
                        generation, item_id, content_index, chunk = await asyncio.wait_for(
                            self.audio_queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        if not self.response_active and self.audio_queue.empty():
                            self._mark_playback_complete()
                        continue
                    if generation != self.playback_generation:
                        continue
                    for offset in range(0, len(chunk), FRAMES_PER_CHUNK * 2):
                        if generation != self.playback_generation:
                            break
                        piece = chunk[offset:offset + FRAMES_PER_CHUNK * 2]
                        if self.use_aec:
                            self.speaker_reference.push(piece)
                        await asyncio.to_thread(stream.write, piece)
                        if generation == self.playback_generation:
                            if self.avatar:
                                self.avatar.push(piece)
                            self.playback_tracker.on_play_bytes(item_id, content_index, piece)
                            self.last_activity = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Speaker unavailable")
            self.stop.set()

    def _mark_playback_complete(self) -> None:
        if not self.speaker_busy:
            return
        state = self.playback_tracker.get_state()
        if state["elapsed_ms"] is not None:
            LOG.info("Playback complete (%.0f ms)", state["elapsed_ms"])
        barge = self.local_barge
        if barge is not None and barge.peak:
            threshold = max(barge.min_rms, barge.factor * barge.baseline)
            LOG.info("Echo while speaking: baseline %.0f, loudest %.0f, interrupt above %.0f",
                     barge.baseline, barge.peak, threshold)
        self._trace("playback_complete", ms=state["elapsed_ms"],
                    echo_baseline=round(barge.baseline) if barge else None,
                    loudest=round(barge.peak) if barge else None,
                    interrupt_above=round(max(barge.min_rms, barge.factor * barge.baseline)) if barge else None)
        self.playback_tracker.on_interrupted()
        self.speaker_busy = False
        self.playback_started_at = None
        self._finish_close_if_ready()

    async def _watchdog(self) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(1)
            now = time.monotonic()
            if self.voice_close_requested_at is not None and now - self.voice_close_requested_at > 12:
                LOG.info("Closing after the goodbye timed out")
                self.stop.set()
                return
            if (self.explicit_close_transcript_at is not None and self.voice_close_requested_at is None
                    and now - self.explicit_close_transcript_at > 3):
                LOG.warning("end_conversation was not called; closing after the direct request")
                self.stop.set()
                return
            opening_only = not self.conversation_started and not self.text_mode
            idle = float(os.getenv("JESUS_OPENING_IDLE_SECONDS", "30") if opening_only
                         else os.getenv("JESUS_SESSION_IDLE_SECONDS", "300"))
            maximum = float(os.getenv("JESUS_SESSION_MAX_SECONDS", "2700"))
            if now - self.started > maximum:
                LOG.info("Closing after %.0f seconds maximum", maximum)
                self.stop.set()
            elif (self.ready.is_set() and not self.response_active and not self.speaker_busy
                  and not self.response_request_pending and not self.tools_in_progress
                  and not self.microphone_speaking and self.pending_transcriptions == 0
                  and now - self.last_activity > idle):
                LOG.info("Closing after %.0f seconds of inactivity", idle)
                self.stop.set()

    async def run(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is missing; set JESUS_EXISTING_ENV in config.local.env")
        input_device = output_device = None
        if not self.text_mode:
            import sounddevice as sd

            input_device = audio_device(sd, os.getenv("JESUS_MIC_NAME", ""), "input")
            output_device = audio_device(sd, os.getenv("JESUS_SPEAKER_NAME", ""), "output")
        runner = RealtimeRunner(self.build_agent(), config={
            "model_settings": session_settings(self.text_mode, create_response=self.recall is None),
            "tracing_disabled": not tracing_enabled(),
        })
        LOG.info("Opening %s conversation (session=%s)", "text" if self.text_mode else "voice",
                 self.session_id)
        settings = session_settings(self.text_mode, create_response=self.recall is None)
        audio = settings.get("audio", {})
        config = {
            "model": settings["model_name"], "voice": audio.get("output", {}).get("voice"),
            "speed": audio.get("output", {}).get("speed"),
            "transcription": audio.get("input", {}).get("transcription"),
            "noise_reduction": audio.get("input", {}).get("noise_reduction"),
            "turn_detection": audio.get("input", {}).get("turn_detection"),
            "barge_in_mode": self.barge_mode, "aec": self.use_aec,
            "local_barge": None if not self.local_barge else {
                "warmup_s": self.local_barge.warmup_s, "factor": self.local_barge.factor,
                "min_rms": self.local_barge.min_rms, "chunks": self.local_barge.chunks},
            "persona": "memory (v3, episodes)" if self.recall is not None else "quote (B)",
            "memory": None if self.recall is None else {
                "rewrite": self.recall.rewrite, "first_turn": self.recall.first_turn,
                "offer": self.recall.offer, "min_score": self.recall.min_score},
            "retriever": type(self.index).__name__, "avatar": self.avatar is not None,
            "crisis_check": self.crisis_check is not None,
            "mic": os.getenv("JESUS_MIC_NAME", "") or "default", "speaker": os.getenv("JESUS_SPEAKER_NAME", "") or "default",
        }
        LOG.info("Session settings: %s", json.dumps(config))
        LOG.info("Session timeline: %s", self.timeline_path)
        self._trace("session_start", session=self.session_id, mode="text" if self.text_mode else "voice", **config)
        session = await runner.run(model_config={"playback_tracker": self.playback_tracker})
        self._session = session
        try:
            await session.enter()
            tasks = [asyncio.create_task(self._consume_events(session), name="realtime-events"),
                     asyncio.create_task(self._watchdog(), name="watchdog")]
            if self.avatar:
                tasks.append(asyncio.create_task(self.avatar.run(), name="avatar-link"))
            if self.text_mode:
                tasks.append(asyncio.create_task(self._typed_input(session), name="typed-input"))
            else:
                tasks += [asyncio.create_task(self._microphone(session, input_device), name="microphone"),
                          asyncio.create_task(self._speaker(output_device), name="speaker")]
            try:
                await self.stop.wait()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            try:
                await asyncio.wait_for(session.close(), timeout=10)
            except asyncio.TimeoutError:
                LOG.error("Realtime session close timed out after 10 seconds")
            self._mic_state(None, 0.0)
            self._trace("session_end", summary=self.summary())
            LOG.info("Conversation ended: %s", self.summary())
