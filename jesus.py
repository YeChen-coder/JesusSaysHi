"""Talk with JesusSaysHi: by voice (default) or typed text (--text).

    python jesus.py                      # microphone and speaker
    python jesus.py --text               # type; replies print with a faithfulness line
    python jesus.py --text --say "..."   # send scripted lines, one per reply, then exit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from openai import OpenAI

from config import INDEX_DIR, ROOT, embed_model, load_settings
from retrieval import ScriptureIndex, openai_embedder
from safety import CrisisCheck
from voice import Conversation


def setup_logging(text_mode: bool) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_dir / "jesus.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ]
    console = logging.StreamHandler()
    # Keep a typed chat readable; voice mode shows what the session is doing.
    console.setLevel(logging.WARNING if text_mode else logging.INFO)
    handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "openai", "agents", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def open_index(client: OpenAI):
    """RAGFlow (default) or the phase-1 local index, chosen by JESUS_RETRIEVER."""
    if os.getenv("JESUS_RETRIEVER", "ragflow").strip().lower() == "ragflow":
        from ragflow_retrieval import RagflowIndex

        return RagflowIndex.from_env()
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    if meta["embed_model"] != embed_model():
        raise SystemExit(f"Index was built with {meta['embed_model']}, not {embed_model()}; rebuild it")
    return ScriptureIndex.load(INDEX_DIR, openai_embedder(client, embed_model()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", action="store_true", help="type instead of speaking")
    parser.add_argument("--say", action="append", help="a scripted line (text mode; repeatable)")
    args = parser.parse_args()
    if args.say and not args.text:
        parser.error("--say needs --text")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_settings()
    setup_logging(args.text)
    # A query embedding normally takes ~0.2 s; fail fast instead of stalling a spoken turn.
    client = OpenAI(timeout=10, max_retries=1)
    index = open_index(client)

    conversation = Conversation(index, text_mode=args.text, say=args.say, crisis_check=CrisisCheck(client))
    try:
        asyncio.run(conversation.run())
    except KeyboardInterrupt:
        pass
    if args.text:
        print(f"\n[{conversation.summary()}]")


if __name__ == "__main__":
    main()
