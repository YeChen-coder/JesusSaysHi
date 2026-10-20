"""Ask the index a question from the command line and print the passages it returns."""

from __future__ import annotations

import argparse
import json
import time

from openai import OpenAI

from config import INDEX_DIR, embed_model, load_settings, rewrite_model
from retrieval import MODES, ScriptureIndex, openai_embedder, rewrite_query


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--mode", choices=MODES, default="dense")
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--rewrite", action="store_true", help="rewrite the question into themes first")
    args = parser.parse_args()

    load_settings()
    client = OpenAI()
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    if meta["embed_model"] != embed_model():
        raise SystemExit(f"Index was built with {meta['embed_model']}, not {embed_model()}; rebuild it")
    index = ScriptureIndex.load(INDEX_DIR, openai_embedder(client, embed_model()))

    query = args.question
    if args.rewrite:
        started = time.perf_counter()
        query = rewrite_query(client, query, rewrite_model())
        print(f"rewrite ({(time.perf_counter() - started) * 1000:.0f} ms): {query}\n")

    started = time.perf_counter()
    passages = index.search(query, args.k, args.mode)
    print(f"{args.mode} search: {(time.perf_counter() - started) * 1000:.0f} ms\n")
    for passage in passages:
        print(f"{passage.ref}\n  {passage.numbered()}\n")


if __name__ == "__main__":
    main()
