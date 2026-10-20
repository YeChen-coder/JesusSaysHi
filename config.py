"""Load local settings. The OpenAI key stays in the existing EBO .env and is read at runtime."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW_BSB = ROOT / "data" / "raw" / "bsb.txt"
INDEX_DIR = ROOT / "data" / "index"


def load_env_file(path: Path, allowed: set[str] | None = None) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if allowed is None or name in allowed:
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))


def load_settings() -> None:
    load_env_file(ROOT / "config.local.env")
    existing = os.getenv("JESUS_EXISTING_ENV")
    if existing:
        load_env_file(Path(existing), {"OPENAI_API_KEY"})


def embed_model() -> str:
    return os.getenv("JESUS_EMBED_MODEL", "text-embedding-3-small")


def rewrite_model() -> str:
    return os.getenv("JESUS_REWRITE_MODEL", "gpt-5.4-mini")
