"""Short PCM reference buffer for WebRTC acoustic echo cancellation (from SpecterSaysHi)."""

from __future__ import annotations


class SpeakerReference:
    """Pair each microphone block with the nearest speaker block.

    Speaker and microphone both use 24 kHz mono PCM16. WebRTC AEC needs near-end (mic)
    and far-end (speaker) blocks of equal length; silence pads the gaps. Both producers
    run as tasks on one event loop, so push/take need no lock.
    """

    def __init__(self, max_bytes: int = 48_000):
        if max_bytes <= 0 or max_bytes % 2:
            raise ValueError("max_bytes must be a positive number of PCM16 bytes")
        self.max_bytes = max_bytes
        self._pending = bytearray()

    def push(self, pcm: bytes) -> None:
        """Append only audio that is about to reach the actual speaker, so audio the
        model generated ahead of playback does not pollute the reference."""
        if len(pcm) % 2:
            raise ValueError("PCM16 audio must contain whole samples")
        self._pending.extend(pcm)
        overflow = len(self._pending) - self.max_bytes
        if overflow > 0:
            del self._pending[:overflow]

    def take(self, count: int) -> bytes:
        """Return a same-length reference for a microphone block, padded with silence."""
        if count < 0 or count % 2:
            raise ValueError("count must be a nonnegative number of PCM16 bytes")
        available = min(count, len(self._pending))
        result = bytes(self._pending[:available])
        del self._pending[:available]
        return result + bytes(count - available)

    def clear(self) -> None:
        """Drop an interrupted reply's unplayed reference audio."""
        self._pending.clear()
