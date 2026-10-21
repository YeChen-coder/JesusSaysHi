"""Continuous 24 kHz to 16 kHz speech resampler with packet-independent phase."""

from __future__ import annotations

import numpy as np


class StreamingResampler24To16:
    radius = 32  # 1.33 ms lookahead at 24 kHz
    cutoff = 0.30  # cycles per 24-kHz input sample; Nyquist after conversion is 1/3

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.samples = np.empty(0, dtype=np.float64)
        self.base = 0
        self.received = 0
        self.output_index = 0
        self.finished = False
        offsets = np.arange(-self.radius, self.radius + 1)
        self.offsets = offsets
        self.kernels = []
        for phase in (0.0, 0.5):
            distance = offsets - phase
            window = np.where(np.abs(distance) <= self.radius,
                              0.5 + 0.5 * np.cos(np.pi * distance / self.radius), 0.0)
            kernel = 2 * self.cutoff * np.sinc(2 * self.cutoff * distance) * window
            self.kernels.append(kernel / kernel.sum())

    def push_pcm(self, pcm: bytes) -> bytes:
        if self.finished:
            raise RuntimeError("resampler has finished; call reset before new audio")
        if len(pcm) % 2:
            raise ValueError("PCM must contain complete 16-bit samples")
        if pcm:
            new = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
            self.samples = np.concatenate((self.samples, new))
            self.received += len(new)
        output = []
        while True:
            target_twice = self.output_index * 3
            center = target_twice // 2
            phase = target_twice & 1
            if center + self.radius >= self.received:
                break
            indices = center + self.offsets - self.base
            valid = (indices >= 0) & (indices < len(self.samples))
            taps = np.zeros(len(indices), dtype=np.float64)
            taps[valid] = self.samples[indices[valid]]
            output.append(float(np.dot(taps, self.kernels[phase])))
            self.output_index += 1
        keep_from = max(0, self.output_index * 3 // 2 - self.radius)
        drop = max(0, keep_from - self.base)
        self.samples = self.samples[drop:]
        self.base += drop
        if not output:
            return b""
        return np.rint(np.clip(output, -1.0, 32767 / 32768) * 32768).astype("<i2").tobytes()

    def finish(self) -> bytes:
        """Emit samples held back for the symmetric FIR filter, padding with silence."""
        tail = self.push_pcm(bytes(self.radius * 2))
        self.finished = True
        return tail
