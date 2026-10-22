"""Bounded PCM history for long replies, using the existing LoopEngine."""
import numpy as np


class RealtimeLoopSession:
    def __init__(self, engine, mode, start_frame, teeth):
        from stream_core import MODES
        from face_utils import gather_audio_window

        if mode not in MODES or teeth not in {"model", "new"}:
            raise ValueError("Invalid FeatherTalk mode or teeth mode")
        if teeth == "new" and engine.teeth is None:
            raise ValueError("New teeth assets are unavailable")
        self.engine = engine
        self.lookahead = MODES[mode]["lookahead"]
        self.mask_after = MODES[mode].get("mask_after")
        self.gather = gather_audio_window
        self.pcm = np.empty(0, dtype=np.float32)
        self.base_frame = self.next_frame = self.received_samples = 0
        self.teeth_restored_frames = 0
        self.last_index = self.last_image = None
        engine.teeth_mode = teeth
        engine.begin(start_frame)

    def push(self, pcm, final=False):
        self.received_samples += len(pcm)
        self.pcm = np.concatenate([self.pcm, np.asarray(pcm, dtype=np.float32)])
        total = max(0, (self.received_samples - 80) // 640)
        if final:
            total = self.received_samples // 640
            needed = (total - self.base_frame) * 640 + 80
            self.pcm = np.pad(self.pcm, (0, max(0, needed - len(self.pcm))))
        eligible = total if final else max(0, total - self.lookahead)
        if eligible <= self.next_frame:
            return
        left = max(self.base_frame, self.next_frame - 100)
        features = self.engine.encode(self.pcm[(left - self.base_frame) * 640:])
        for index in range(self.next_frame, eligible):
            base_index = self.engine.cursor
            window = self.gather(features, index - left).numpy()
            if self.mask_after is not None:
                # Same input as training: nothing later than index+mask_after (half window is 10).
                window[10 + self.mask_after + 1:] = 0
            image, _ = self.engine.render(window)
            self.engine.sync()
            # EN: Lab diagnostics otherwise accumulate one entry per frame.
            # 中文：实时长对话不累积实验逐帧记录，防止内存随会话时长增长。
            self.engine.indices.clear()
            self.engine.teeth_rows.clear()
            if self.engine.teeth is not None:
                self.teeth_restored_frames += int(self.engine.teeth.last.get("replaced", False)) if self.engine.teeth_mode == "new" else 0
                self.engine.teeth.records.clear()
            self.next_frame = index + 1
            self.last_index, self.last_image = base_index, image
            yield base_index, image
        keep_from = max(self.base_frame, self.next_frame - 100)
        self.pcm = self.pcm[(keep_from - self.base_frame) * 640:]
        self.base_frame = keep_from
