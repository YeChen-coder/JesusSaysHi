"""Map playback indices to unique native reference frames without copying them."""


class TimelineFrames:
    def __init__(self, frames, indices):
        self.unique = frames
        self.indices = indices
        if not len(indices) or any(int(index) < 0 or int(index) >= len(frames) for index in indices):
            raise ValueError('Playback timeline references an unavailable source frame')

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        return self.unique[int(self.indices[index])]
