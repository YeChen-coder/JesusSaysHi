"""Ease the visible lower-face residual into the same moving idle base."""
import cv2
import numpy as np


class IdleTransition:
    def __init__(self, engine, last_index, last_image, frames):
        self.engine = engine
        self.frames = frames
        self.step = 0
        self.last_index = last_index
        self.last_image = last_image
        x1, y1, x2, y2 = engine.bboxes[last_index]
        # Use the final composited face, including teeth repair. Transport only
        # its change from the idle image, leaving the moving head/body intact.
        idle = engine.idle_frame(last_index) if hasattr(engine, 'idle_frame') else engine.frames[last_index]
        delta = last_image[y1:y2, x1:x2].astype(np.float32) - idle[y1:y2, x1:x2]
        self.delta = cv2.resize(delta, (152, 152), interpolation=cv2.INTER_LINEAR)

    def next_frame(self):
        if self.step >= self.frames:
            raise StopIteration
        index = self.engine.cursor
        self.engine.cursor = (index + 1) % self.engine.count
        self.step += 1
        progress = self.step / self.frames
        weight = 1 - progress * progress * (3 - 2 * progress)
        image = self.engine.idle_frame(index) if hasattr(self.engine, 'idle_frame') else self.engine.frames[index].copy()
        if self.step < self.frames:
            x1, y1, x2, y2 = self.engine.bboxes[index]
            delta = cv2.resize(self.delta, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LINEAR)
            image[y1:y2, x1:x2] = np.rint(image[y1:y2, x1:x2] + delta * weight).clip(0, 255).astype(np.uint8)
        # The final image is exactly the corresponding idle frame before JPEG.
        self.last_index, self.last_image = index, image
        return index, image
