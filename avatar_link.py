"""Send played reply audio and verse cards to the FeatherTalk avatar (avatar/runtime/server.py).

Audio is copied as it reaches the speaker, so the lips follow what is heard rather than
what the model has generated ahead. Verse cards carry the retrieved text, not the
spoken one: if the voice paraphrased a verse, the screen still shows it as written.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import struct
import time

from scripture import Passage

LOG = logging.getLogger("jesus")
MAX_CARD_VERSES = 4
_REF = re.compile(r"^(.+) (\d+):(\d+)(?:-(\d+))?$")


def avatar_enabled() -> bool:
    return os.getenv("JESUS_AVATAR_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def verse_cards(report: dict, passages: list[Passage]) -> list[dict]:
    """The verses a reply quoted (verbatim or paraphrased), in the order spoken, with
    neighbouring verses of one chapter merged into a single card."""
    texts = {(p.book, p.chapter, v): t for p in passages for v, t in zip(p.verses, p.texts)}
    keys: list[tuple[str, int, int]] = []
    for sentence in report["sentences"]:
        match = _REF.match(sentence["ref"] or "") if sentence["kind"] != "own" else None
        if not match:
            continue
        book, chapter, first = match[1], int(match[2]), int(match[3])
        for verse in range(first, int(match[4] or first) + 1):
            key = (book, chapter, verse)
            if key in texts and key not in keys:
                keys.append(key)
    cards: list[dict] = []
    for book, chapter, verse in keys[:MAX_CARD_VERSES]:
        last = cards[-1] if cards else None
        if last and last["key"][:2] == (book, chapter) and last["key"][3] == verse - 1:
            last["key"] = (book, chapter, last["key"][2], verse)
            last["text"] += " " + texts[(book, chapter, verse)]
        else:
            cards.append({"key": (book, chapter, verse, verse), "text": texts[(book, chapter, verse)]})
    return [{"ref": f"{b} {c}:{v1}" + (f"-{v2}" if v2 != v1 else ""), "text": card["text"]}
            for card in cards for b, c, v1, v2 in [card["key"]]]


class AvatarLink:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("JESUS_AVATAR_URL", "ws://127.0.0.1:19388/publish?source=jesus")
        self.queue: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=32)

    def _put(self, item: bytes | str) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            LOG.warning("Avatar link queue full; dropping a message")

    def reset(self) -> None:
        """Drop queued audio, keep queued verse cards, then tell the avatar to stop."""
        kept = []
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if isinstance(item, str) and item != '{"type":"reset"}':
                kept.append(item)
        for item in kept:
            self._put(item)
        self._put('{"type":"reset"}')

    def push(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            return
        if self.queue.full():
            self.reset()  # the avatar fell behind; restart its stream rather than lag
        self._put(struct.pack("<d", time.time() * 1000) + pcm)

    def show_verses(self, cards: list[dict]) -> None:
        if cards:
            self._put(json.dumps({"type": "verse", "verses": cards}))

    def clear_verses(self) -> None:
        self._put('{"type":"verse_clear"}')

    async def run(self) -> None:
        import websockets

        while True:
            try:
                async with websockets.connect(self.url, open_timeout=2, max_size=None) as ws:
                    LOG.info("Avatar link connected")
                    await ws.send('{"type":"reset"}')
                    while True:
                        await ws.send(await self.queue.get())
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.exceptions.WebSocketException) as exc:
                LOG.warning("Avatar link disconnected: %s", exc)
                self.reset()
                await asyncio.sleep(2)
