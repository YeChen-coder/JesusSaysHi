"""Build the Gospel passage index: parse BSB, cut passages, embed them, save to data/index/."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

import numpy as np
from openai import OpenAI

from config import INDEX_DIR, RAW_BSB, embed_model, load_settings
from retrieval import openai_embedder
from scripture import make_passages, read_verses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=5, help="verses per passage window")
    parser.add_argument("--stride", type=int, default=2, help="verses between window starts")
    args = parser.parse_args()

    if not RAW_BSB.is_file():
        sys.exit(f"Missing {RAW_BSB}. Download it from https://bereanbible.com/bsb.txt")
    load_settings()

    verses = read_verses(RAW_BSB)
    passages = make_passages(verses, args.size, args.stride)
    model = embed_model()
    print(f"{len(verses)} verses -> {len(passages)} passages; embedding with {model}")
    embeddings = openai_embedder(OpenAI(), model)([p.text for p in passages])

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(INDEX_DIR / "embeddings.npy", embeddings)
    (INDEX_DIR / "passages.json").write_text(
        json.dumps([p.to_json() for p in passages], ensure_ascii=False), encoding="utf-8")
    meta = {
        "source": RAW_BSB.name,
        "source_sha256": hashlib.sha256(RAW_BSB.read_bytes()).hexdigest(),
        "embed_model": model, "size": args.size, "stride": args.stride,
        "verses": len(verses), "passages": len(passages), "dimensions": int(embeddings.shape[1]),
    }
    (INDEX_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {INDEX_DIR} ({embeddings.nbytes / 1e6:.1f} MB of vectors)")


if __name__ == "__main__":
    main()
