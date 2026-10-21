# Third-party components

The Python files under `vendor/feathertalk/` originate from
[FeatherTalk](https://github.com/anliyuan/FeatherTalk), commit
`ace1227ec0a367a983101bfc17d7e5fcf2bfb63f`. Their Apache 2.0 license is
preserved in `vendor/feathertalk/LICENSE`. The rest of this folder is the
standalone avatar runtime from GPTSaysHi, with verse cards added.

No model weights or video assets are stored here. The container mounts them
from `JESUS_AVATAR_ASSETS`: for now the SpecterSaysHi *gentleman* release
(FeatherTalk audio encoder, character checkpoint, idle frames, landmarks,
teeth and detail references), as a placeholder for the Jesus character.

PyTorch, MediaPipe, OpenCV, Librosa, Transformers, FastAPI, Uvicorn and
WebSockets retain their respective upstream licenses. Versions used by
the avatar container are pinned in `requirements-avatar.txt`.
