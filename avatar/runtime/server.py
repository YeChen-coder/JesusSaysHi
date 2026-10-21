"""PCM bridge from the JesusSaysHi voice loop to the FeatherTalk avatar, plus verse cards."""
import asyncio
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from realtime_session import RealtimeLoopSession
from idle_transition import IdleTransition
from streaming_resampler import StreamingResampler24To16
from frame_delivery import deliver_frames
from frame_encoding import encode_frame, frame_metadata
from engine_runtime import engine, lock

MODE = os.getenv("FEATHERTALK_MODE", "fast").strip().lower()
NATIVE = engine.assets.renderer == 'native_face'
TEETH = 'model' if NATIVE else os.getenv("FEATHERTALK_TEETH_MODE", engine.assets.settings['teeth_mode']).strip().lower()
BUFFER_MS = int(os.getenv("FEATHERTALK_BUFFER_MS", "100"))
if MODE not in {"fast", "balanced", "quality"}:
    raise ValueError("FEATHERTALK_MODE must be fast, balanced or quality")
if TEETH not in {"model", "new"} or (TEETH == "new" and engine.teeth is None):
    raise ValueError("FEATHERTALK_TEETH_MODE must be model or available new teeth")
if not 40 <= BUFFER_MS <= 1000:
    raise ValueError("FEATHERTALK_BUFFER_MS must be between 40 and 1000")
BUFFER_BYTES = 24000 * BUFFER_MS // 1000 * 2
SETTLE_MS = engine.assets.settings['settle_ms'] if NATIVE else int(os.getenv("FEATHERTALK_SETTLE_MS", str(engine.assets.settings['settle_ms'])))
if (NATIVE and SETTLE_MS != 0) or (not NATIVE and not 80 <= SETTLE_MS <= 1000):
    raise ValueError("Native QinChe uses direct idle handoff; gentleman settling must be 80..1000 ms")
SETTLE_FRAMES = 0 if NATIVE else max(2, round(SETTLE_MS / 40))

app = FastAPI()
viewers = {}
publisher = None
publisher_source = None
publisher_finished = asyncio.Event()
publisher_finished.set()
publisher_switch_lock = asyncio.Lock()
superseded_publishers = set()
active = False
latest = None
requested_frame = None
sync_event = asyncio.Event()
frames_rendered = 0
teeth_restored_frames = 0
settle_frames_rendered = 0
last_error = ""
release = engine.assets.metadata
CHARACTERS = list(json.loads((Path(__file__).with_name("characters.json")).read_text(encoding="utf-8"))["characters"])
# The verses currently on screen, so a viewer that connects late shows them too.
current_verses = None
timeline_anchor = 0
timeline_anchor_at = time.monotonic()


@app.get("/")
def home():
    return FileResponse("/lab/index.html", headers={"Cache-Control": "no-store"})


@app.get("/avatar/video")
def video():
    return FileResponse(engine.idle_video_path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})


@app.get("/poster")
def poster():
    return FileResponse(engine.idle_poster_path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"ok": True, "model": "FeatherTalk loop", "publisher": publisher is not None,
            "viewers": len(viewers), "speech_active": active, "mode": MODE,
            "buffer_ms": BUFFER_MS, "teeth_mode": TEETH,
            "source": publisher_source, "takeover_policy": "latest_connection",
            "character": engine.assets.name, "characters": CHARACTERS,
            "compositor": 'NativeFaceMatch' if NATIVE else 'GentlemanDetailBalance',
            "rendering_profile": engine.assets.renderer,
            "frame_transport": 'mouth_png' if NATIVE else 'full_jpeg', "viewer_protocol": 2,
            "native_background_layer": 'continuous_video' if NATIVE else 'full_frame',
            "idle_color_space": engine.manifest.get('color_space'),
            "selected_epoch": release.get('selected_epoch'), "idle_name": release.get('idle_name'),
            "unique_base_frames": len(engine.unique_frames) if NATIVE else engine.count,
            "width": engine.manifest['width'], "height": engine.manifest['height'],
            "checkpoint": str(engine.assets.checkpoint), "base_frames": engine.count,
            "release": release["release"], "checkpoint_sha256": release["checkpoint_sha256"],
            "idle_video_sha256": release["idle_video_sha256"],
            "base_assets": str(engine.assets.base), "teeth_assets": None if NATIVE else str(engine.assets.teeth),
            "detail_assets": None if NATIVE else str(engine.assets.detail),
            "loop_mode": engine.manifest.get("loop_mode"),
            "duration_seconds": engine.count / 25,
            "frames_rendered": frames_rendered, "teeth_restored_frames": teeth_restored_frames,
            "settle_ms": SETTLE_FRAMES * 40, "settle_frames_rendered": settle_frames_rendered,
            "detail_profile": engine.detail_profile, "detail_last_ms": engine.detail_last_ms,
            "frame_delivery": "incremental", "history_seconds": 4,
            "lookahead_frames": {"fast": 0, "balanced": 10, "quality": 25}[MODE],
            "model_load_seconds": engine.load_seconds,
            "stream_warmup_seconds": engine.stream_shape_warmup_seconds,
            "native_match_last_ms": getattr(engine, 'native_match_last_ms', 0.),
            "idle_handoff": 'direct_native' if NATIVE else 'matched_residual',
            "frame_fade_ms": 0 if NATIVE else 80,
            "resampler_lookahead_ms": 32 / 24,
            "sample_rate": 24000, "inference_sample_rate": 16000,
            "error": last_error}


async def send(ws, messages):
    async with viewers[ws]:
        for item in messages:
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_text(json.dumps(item))


async def broadcast(*messages):
    for ws in tuple(viewers):
        try:
            await asyncio.wait_for(send(ws, messages), timeout=.2)
        except (OSError, RuntimeError, asyncio.TimeoutError, KeyError, WebSocketDisconnect):
            viewers.pop(ws, None)
            try:
                await ws.close()
            except (OSError, RuntimeError):
                pass


def verse_message(control):
    """Keep only well-formed verse cards: at most 3, each a short reference and its text."""
    if control.get("type") == "verse_clear":
        return {"type": "verse_clear"}
    cards = control.get("verses")
    if not isinstance(cards, list):
        return None
    clean = [{"ref": card["ref"][:40], "text": card["text"][:600]} for card in cards[:3]
             if isinstance(card, dict) and isinstance(card.get("ref"), str) and isinstance(card.get("text"), str)]
    return {"type": "verse", "verses": clean} if clean else None


def infer_frames(session, raw, final=False):
    global frames_rendered, teeth_restored_frames
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    restored_before = session.teeth_restored_frames
    for index, image in session.push(pcm, final):
        encoded = encode_frame(engine,index,image,NATIVE)
        frames_rendered += 1
        teeth_restored_frames += session.teeth_restored_frames - restored_before
        restored_before = session.teeth_restored_frames
        yield index, encoded


def infer_settle(transition):
    global settle_frames_rendered
    index, image = transition.next_frame()
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError("FeatherTalk transition JPEG encoding failed")
    settle_frames_rendered += 1
    return index, jpeg.tobytes()


@app.websocket("/publish")
async def publish(ws: WebSocket):
    global publisher, publisher_source, publisher_finished, active, latest, requested_frame, last_error
    global current_verses
    await ws.accept()
    source = ws.query_params.get("source", "legacy")
    if source not in {"jesus", "legacy", "test"}:
        await ws.close(code=1008, reason="Unknown source")
        return
    # Serialize handoffs. The old handler must finish its tail and release
    # the engine before a newer publisher can become the owner.
    async with publisher_switch_lock:
        if publisher is not None:
            previous_finished = publisher_finished
            superseded_publishers.add(publisher)
            try:
                await publisher.close(code=4001, reason="Replaced by newer source")
            except (RuntimeError, WebSocketDisconnect):
                pass
            try:
                await asyncio.wait_for(previous_finished.wait(), timeout=5)
            except asyncio.TimeoutError:
                await ws.close(code=1013, reason="Previous source still shutting down")
                return
        publisher = ws
        publisher_source = source
        finished = asyncio.Event()
        publisher_finished = finished
        await broadcast({"type": "source", "source": source})
    session = None
    owned = False
    pending = bytearray()
    resampler = StreamingResampler24To16()
    last_audio = 0.
    settling = None
    settle_next_at = 0.

    async def release(control="idle"):
        nonlocal session, owned, last_audio, settling
        global active, latest, timeline_anchor, timeline_anchor_at
        if active:
            timeline_anchor=engine.cursor
            timeline_anchor_at=time.monotonic()
        session = None
        settling = None
        pending.clear()
        resampler.reset()
        last_audio = 0.
        active = False
        latest = None
        if owned:
            lock.release()
            owned = False
        await broadcast({"type": control})

    async def begin_settle(interrupted=False):
        nonlocal session, settling, settle_next_at
        source = settling if settling is not None else session
        pending.clear()
        resampler.reset()
        if source is None or source.last_image is None:
            await release("reset")
            return
        if SETTLE_FRAMES == 0:
            await release("reset" if interrupted else "idle")
            return
        settling = IdleTransition(engine, source.last_index, source.last_image, SETTLE_FRAMES)
        session = None
        settle_next_at = time.monotonic()
        await broadcast({"type": "settling", "drop_pending": interrupted})

    async def step_settle():
        nonlocal settle_next_at
        global latest
        started = time.monotonic()
        index, image = await asyncio.to_thread(infer_settle, settling)
        latest = (index, image)
        await broadcast({"type": "frame", "index": index, "phase": "settling",
                         "step": settling.step, "steps": settling.frames}, image)
        settle_next_at = started + .04
        if settling.step >= settling.frames:
            await release()

    async def render(raw, final=False):
        async def send_frame(frame):
            global latest
            index, image = frame
            latest = (index, image)
            await broadcast(frame_metadata(engine,index,NATIVE), image)
        await deliver_frames(infer_frames(session, raw, final), send_frame)

    try:
        await broadcast({"type": "reset"})
        while True:
            try:
                timeout = max(.001, settle_next_at - time.monotonic()) if settling is not None else .1
                event = await asyncio.wait_for(ws.receive(), timeout=timeout)
            except asyncio.TimeoutError:
                event = None
            if event and event["type"] == "websocket.disconnect":
                break
            if event and event.get("text"):
                control = json.loads(event["text"])
                if control.get("type") == "reset":
                    if active:
                        await begin_settle(interrupted=True)
                    else:
                        await release("reset")
                elif control.get("type") in {"verse", "verse_clear"}:
                    message = verse_message(control)
                    if message is not None:
                        current_verses = message if message["type"] == "verse" else None
                        await broadcast(message)
            if event and event.get("bytes"):
                packet = event["bytes"]
                if len(packet) <= 8 or (len(packet) - 8) % 2 or len(packet) > 96008:
                    raise ValueError("Expected timestamp + mono 24 kHz PCM16 packet (maximum 2 seconds)")
                if session is None:
                    if owned:
                        # Resume from the moving tail, without seeking back to
                        # the paused video's old frame or hiding the face.
                        settling = None
                        requested_frame = engine.cursor
                        await broadcast({"type": "resume"})
                    else:
                        if not lock.acquire(blocking=False):
                            raise RuntimeError("FeatherTalk lab preview is busy; stop its sample playback first")
                        owned = True
                        active = True
                        latest = None
                        requested_frame = ((timeline_anchor+int((time.monotonic()-timeline_anchor_at)*25))%engine.count) if NATIVE else None
                        sync_event.clear()
                        await broadcast({"type": "start"})
                        if viewers:
                            try:
                                await asyncio.wait_for(sync_event.wait(), timeout=.1)
                            except asyncio.TimeoutError:
                                pass
                    start_frame = requested_frame if requested_frame is not None else (engine.cursor if NATIVE else 0)
                    session = await asyncio.to_thread(
                        RealtimeLoopSession, engine, MODE, start_frame, TEETH)
                    last_error = ""
                pending.extend(packet[8:])
                last_audio = time.monotonic()
            # EN: Flush a short final packet on timeout; continuous packets use the chosen buffer.
            # 中文：连续音频按设定缓冲推理；超时时排空不足一包的尾音。
            if session is not None and pending and (len(pending) >= BUFFER_BYTES or event is None):
                converted = resampler.push_pcm(bytes(pending))
                pending.clear()
                await render(converted)
            if session is not None and event is None and time.monotonic() - last_audio > .24:
                await render(resampler.finish(), final=True)
                await begin_settle()
            if settling is not None and time.monotonic() >= settle_next_at:
                await step_settle()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        if ws not in superseded_publishers:
            last_error = f"{type(exc).__name__}: {exc}"
            print("FeatherTalk Realtime bridge failed:", last_error, flush=True)
            await broadcast({"type": "error", "message": last_error})
            await ws.close(code=1011)
    finally:
        # Session shutdown closes the audio publisher; finish the visible tail
        # as well, so an ordinary end-conversation does not abruptly cut to idle.
        try:
            if active:
                await begin_settle(interrupted=True)
                while settling is not None:
                    await asyncio.sleep(max(0., settle_next_at - time.monotonic()))
                    await step_settle()
        finally:
            try:
                if owned:
                    await release("reset")
            finally:
                if publisher is ws:
                    publisher = None
                    publisher_source = None
                    await broadcast({"type": "source", "source": None})
                    if current_verses is not None:  # the conversation is over
                        current_verses = None
                        await broadcast({"type": "verse_clear"})
                finished.set()
                superseded_publishers.discard(ws)


@app.websocket("/view")
async def view(ws: WebSocket):
    global requested_frame
    await ws.accept()
    if NATIVE and ws.query_params.get('protocol') != '2':
        await ws.close(code=1008,reason='Refresh viewer for mouth-only transport')
        return
    viewers[ws] = asyncio.Lock()
    try:
        await send(ws, [{"type": "source", "source": publisher_source}])
        if current_verses is not None:
            await send(ws, [current_verses])
        if active:
            await send(ws, [{"type": "start"}])
            if latest is not None:
                await send(ws, [frame_metadata(engine,latest[0],NATIVE), latest[1]])
        while True:
            event = await ws.receive()
            if event["type"] == "websocket.disconnect":
                break
            if event.get("text"):
                control = json.loads(event["text"])
                if control.get("type") == "sync" and isinstance(control.get("frame"), int) and not sync_event.is_set():
                    requested_frame = max(0, control["frame"]) % engine.count
                    sync_event.set()
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        viewers.pop(ws, None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info", ws_per_message_deflate=False)
