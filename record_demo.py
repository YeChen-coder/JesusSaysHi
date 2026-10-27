"""Record a scripted demo of the live avatar with OBS (ported from SpecterSaysHi).

The "user" is a TTS voice that is played aloud and fed into the session in place of the
microphone, so server VAD, transcription, retrieval, the faithfulness check and the
verse cards all run the normal code. OBS records the avatar page and the speaker.
No real microphone is opened.

One-time OBS setup: create a profile and a scene collection both named JesusDemo, with
the profile at 720x1088 and 25 fps (OBS 31.1 crashed when this was set over WebSocket),
and enable the WebSocket server. Then start OBS with
    obs64.exe --profile JesusDemo --collection JesusDemo
and run
    python record_demo.py [out_dir]          # or --voices-only to prepare the TTS lines
Next to the recording it writes <recording>.timeline.json (for captions) with the
faithfulness report of every reply.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import ROOT, load_settings
from jesus import open_index
from retrieval import ScriptureIndex
from safety import CrisisCheck
from voice import SAMPLE_RATE, Conversation

LOG = logging.getLogger("jesus")
OBS_CONFIG = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
DEMO = "JesusDemo"
AVATAR_PAGE = "http://127.0.0.1:19388/?clean=1"

USER_VOICE = "coral"
USER_STYLE = "A tired young woman at the end of a long week, speaking quietly and honestly. Natural pace."
# One line per turn; each is spoken after his reply has finished.
SCRIPT = [
    "Hi. It's been a really long week.",
    "I'm exhausted. Everything feels so heavy right now.",
    # One sentence: a pause between two sentences can end the turn early (server VAD, 650 ms).
    "My brother keeps hurting me and then apologizing, and I don't know how many times I'm supposed to forgive him.",
    "Are you really Jesus?",
    "Okay. Thank you. Goodbye.",
]


def user_voice(text: str, cache: Path) -> bytes:
    """24 kHz mono PCM16 of one line, cached by text, voice and style."""
    key = hashlib.sha256("\n".join((text, USER_VOICE, USER_STYLE)).encode()).hexdigest()[:12]
    path = cache / f"{key}.pcm"
    if not path.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        response = OpenAI(timeout=60).audio.speech.create(
            model="gpt-4o-mini-tts", voice=USER_VOICE, input=text,
            instructions=USER_STYLE, response_format="pcm",
        )
        path.write_bytes(response.content)
    pcm = path.read_bytes()
    return pcm[:len(pcm) // 2 * 2]


class VirtualMic:
    """Stands in for sounddevice.RawInputStream: real-time 100 ms reads, silence when idle."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.next_read: float | None = None

    def __enter__(self) -> "VirtualMic":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def feed(self, pcm: bytes) -> None:
        with self.lock:
            self.buffer.extend(pcm)

    def read(self, frames: int) -> tuple[bytes, bool]:
        now = time.monotonic()
        self.next_read = max(self.next_read or now, now - 0.2) + frames / SAMPLE_RATE
        time.sleep(max(0.0, self.next_read - now))
        size = frames * 2
        with self.lock:
            chunk = bytes(self.buffer[:size])
            del self.buffer[:size]
        return chunk + bytes(size - len(chunk)), False


class Obs:
    """Minimal obs-websocket v5 client: requests by id, events on a queue."""

    def __init__(self) -> None:
        self.pending: dict[str, asyncio.Future] = {}
        self.events: asyncio.Queue[dict] = asyncio.Queue()

    async def connect(self) -> None:
        from websockets.asyncio.client import connect

        config = json.loads(OBS_CONFIG.read_text(encoding="utf-8"))
        self.ws = await connect(f"ws://127.0.0.1:{config.get('server_port', 4455)}", max_size=None)
        hello = json.loads(await self.ws.recv())["d"]
        identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 1 << 6}  # Outputs
        auth = hello.get("authentication")
        if auth:
            secret = base64.b64encode(hashlib.sha256(
                (config["server_password"] + auth["salt"]).encode()).digest()).decode()
            identify["authentication"] = base64.b64encode(hashlib.sha256(
                (secret + auth["challenge"]).encode()).digest()).decode()
        await self.ws.send(json.dumps({"op": 1, "d": identify}))
        message = json.loads(await self.ws.recv())
        if message["op"] != 2:
            raise RuntimeError(f"OBS did not accept the connection: {message}")
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for raw in self.ws:
            message = json.loads(raw)
            if message["op"] == 7:
                future = self.pending.pop(message["d"]["requestId"], None)
                if future and not future.done():
                    future.set_result(message["d"])
            elif message["op"] == 5:
                self.events.put_nowait(message["d"])

    async def call(self, kind: str, check: bool = True, **data: Any) -> dict:
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        await self.ws.send(json.dumps({"op": 6, "d": {
            "requestType": kind, "requestId": request_id, "requestData": data,
        }}))
        reply = await asyncio.wait_for(future, timeout=30)
        status = reply["requestStatus"]
        if check and not status["result"]:
            raise RuntimeError(f"OBS {kind} failed: {status.get('code')} {status.get('comment')}")
        return reply.get("responseData") or {}

    async def wait_record_state(self, state: str) -> dict:
        while True:
            event = await self.events.get()
            if event.get("eventType") == "RecordStateChanged" and event["eventData"]["outputState"] == state:
                return event["eventData"]


async def prepare_obs(obs: Obs, out_dir: Path) -> None:
    """Add the avatar page and speaker audio to OBS's separate demo scene collection."""
    profile = (await obs.call("GetProfileList"))["currentProfileName"]
    collection = (await obs.call("GetSceneCollectionList"))["currentSceneCollectionName"]
    video = await obs.call("GetVideoSettings")
    expected = {"baseWidth": 720, "baseHeight": 1088, "outputWidth": 720, "outputHeight": 1088,
                "fpsNumerator": 25, "fpsDenominator": 1}
    if profile != DEMO or collection != DEMO or video != expected:
        raise RuntimeError(f"Start OBS with the {DEMO} profile and collection (now {profile}/{collection}, {video})")
    await obs.call("SetRecordDirectory", recordDirectory=str(out_dir))
    scene = (await obs.call("GetCurrentProgramScene"))["currentProgramSceneName"]
    names = {item["inputName"]: item["inputKind"] for item in (await obs.call("GetInputList"))["inputs"]}
    # The room microphone must not be in the demo; only what the speaker plays.
    for name, kind in names.items():
        if kind == "wasapi_input_capture":
            await obs.call("SetInputMute", inputName=name, inputMuted=True)
    if "wasapi_output_capture" not in names.values():
        await obs.call("CreateInput", sceneName=scene, inputName="Speaker", inputKind="wasapi_output_capture",
                       inputSettings={"device_id": "default"})
    if "Avatar" not in names:
        await obs.call("CreateInput", sceneName=scene, inputName="Avatar", inputKind="browser_source", inputSettings={
            "url": AVATAR_PAGE, "width": 720, "height": 1088, "fps_custom": True, "fps": 25,
            "css": "body{margin:0;overflow:hidden;background:#000}",
            "reroute_audio": False, "shutdown": False,
        })
    else:
        await obs.call("PressInputPropertiesButton", inputName="Avatar", propertyName="refreshnocache")


class DemoConversation(Conversation):
    """The normal voice session; a spoken script replaces the room microphone."""

    def __init__(self, index: ScriptureIndex, voices: dict[str, bytes], t0: float, **kwargs: Any):
        super().__init__(index, **kwargs)
        self.voices = voices
        self.t0 = t0
        self.mic = VirtualMic()
        self.use_aec = False  # the virtual microphone carries no speaker echo
        self.timeline: list[dict[str, Any]] = []

    def _mark(self, **entry: Any) -> dict[str, Any]:
        entry["t"] = round(time.monotonic() - self.t0, 3)
        self.timeline.append(entry)
        return entry

    async def _on_event(self, session: Any, event: Any) -> None:
        if event.type == "audio" and not self.speaker_busy:
            self._mark(role="assistant", event="start")
        await super()._on_event(session, event)

    def _check_reply(self, item_id: str | None, text: str) -> dict | None:
        report = super()._check_reply(item_id, text)
        if report is not None:
            self._mark(role="assistant", event="text", text=text.strip(), faithfulness={
                key: report[key] for key in ("grounded_share", "paraphrased", "unsupported_citations",
                                             "misattributed_quotes", "uncited_quotes")})
        return report

    def _mark_playback_complete(self) -> None:
        if self.speaker_busy:
            self._mark(role="assistant", event="end")
        super()._mark_playback_complete()

    def _idle(self) -> bool:
        # A two-phase reply (memory persona) is quiet between phase A and phase B while the
        # memory is recalled; it is finished only once phase B was requested or skipped.
        pending_phase_b = self.phase_state is not None and not self.phase_state["done"]
        return not (self.response_active or self.response_request_pending or self.speaker_busy
                    or not self.audio_queue.empty() or self.tools_in_progress or pending_phase_b)

    async def _wait_reply_done(self, turns_before: int) -> None:
        while self.response_turns <= turns_before and not self.stop.is_set():
            await asyncio.sleep(0.05)
        quiet_since = None
        while not self.stop.is_set():
            if self._idle():
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since > 0.6:
                    return
            else:
                quiet_since = None
            await asyncio.sleep(0.05)

    async def _say(self, text: str) -> None:
        """Play one line aloud (for the recording) and feed the same PCM to the session."""
        import numpy as np
        import sounddevice as sd

        pcm = self.voices[text]
        self.conversation_started = True
        self.last_activity = time.monotonic()
        self._mark(role="user", event="start", text=text)
        sd.play(np.frombuffer(pcm, dtype=np.int16), SAMPLE_RATE)
        self.mic.feed(pcm)
        await asyncio.sleep(len(pcm) / 2 / SAMPLE_RATE)
        self._mark(role="user", event="end", text=text)

    async def _drive(self) -> None:
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=20)
            await self._wait_reply_done(0)  # the opening "Peace be with you."
            for line in SCRIPT:
                if self.stop.is_set():
                    return
                turns = self.response_turns
                await asyncio.sleep(1.0)
                await self._say(line)
                await self._wait_reply_done(turns)
            await asyncio.sleep(1.5)
            self.stop.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Demo script failed")
            self.stop.set()

    async def _microphone(self, session: Any, device: int | None) -> None:
        """Run the normal microphone path (VAD upload, local barge-in) on the virtual mic."""
        import sounddevice as sd

        original = sd.RawInputStream
        sd.RawInputStream = lambda **_: self.mic
        driver = asyncio.create_task(self._drive(), name="demo-script")
        try:
            await super()._microphone(session, device)
        finally:
            sd.RawInputStream = original
            driver.cancel()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2", "openai", "agents", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    load_settings()
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    out_dir = Path(args[0]).resolve() if args else ROOT / "logs" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    voices = {line: await asyncio.to_thread(user_voice, line, out_dir / "voice") for line in SCRIPT}
    LOG.info("User voice ready: %s", ", ".join(f"{len(pcm) / 48000:.1f}s" for pcm in voices.values()))
    if "--voices-only" in sys.argv:
        return

    os.environ["JESUS_AVATAR_ENABLED"] = "true"
    client = OpenAI(timeout=10, max_retries=1)
    index = open_index(client)
    obs = Obs()
    await obs.connect()
    await prepare_obs(obs, out_dir)
    LOG.info("Waiting for the avatar page to load in OBS")
    await asyncio.sleep(8)
    await obs.call("StartRecord")
    await asyncio.wait_for(obs.wait_record_state("OBS_WEBSOCKET_OUTPUT_STARTED"), timeout=20)
    LOG.info("OBS recording started")
    t0 = time.monotonic()
    # Same persona as jesus.py: episodic memory unless JESUS_PERSONA=quote.
    recall = None
    if os.getenv("JESUS_PERSONA", "memory").strip().lower() == "memory":
        from memory import EpisodeRecall

        recall = EpisodeRecall(index, OpenAI(timeout=20, max_retries=1))
    crisis = None  # JESUS_CRISIS_CHECK as in jesus.py (on by default)
    if os.getenv("JESUS_CRISIS_CHECK", "true").strip().lower() in {"1", "true", "yes", "on"}:
        crisis = CrisisCheck(client)
    conversation = DemoConversation(index, voices, t0, log_dir=out_dir, crisis_check=crisis, recall=recall)
    try:
        await asyncio.sleep(2.0)
        try:
            await conversation.run()
        finally:
            end = round(time.monotonic() - t0, 3)
        await asyncio.sleep(2.0)
    finally:
        await obs.call("StopRecord")
        stopped = await asyncio.wait_for(obs.wait_record_state("OBS_WEBSOCKET_OUTPUT_STOPPED"), timeout=30)
    recording = Path(stopped["outputPath"])
    timeline = {"recording": str(recording), "session_end": end, "summary": conversation.summary(),
                "events": conversation.timeline}
    recording.with_suffix(".timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    LOG.info("Recorded %s (%s)", recording, conversation.summary())


if __name__ == "__main__":
    asyncio.run(main())
