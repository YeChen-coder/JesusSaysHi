"""Ingest the Gospels into RAGFlow: one document per BSB section, parent-child chunking.

Offline pipeline (re-runnable; documents already in the dataset are skipped):
  parse USFM -> clean and cross-check against bsb.txt -> one document per section heading
  -> upload with metadata (book, reference, parallels, red-letter share)
  -> RAGFlow chunks it: the section is the parent, each verse line a child; it adds
     LLM keywords and likely questions to every chunk, then builds the dense and full-text indexes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from config import RAW_BSB, ROOT, load_settings
from pericopes import read_sections
from ragflow_client import RagflowClient
from scripture import read_verses

USFM_DIR = RAW_BSB.parent / "usfm" / "bsb_usfm"
SECTIONS_DIR = ROOT / "data" / "sections"
DATASET = os.getenv("JESUS_RAGFLOW_DATASET", "BSB Gospels")


def dataset_settings() -> dict:
    # RAGFlow 1.0 builds a built-in ingestion pipeline (Parser -> GeneralChunker ->
    # Extractor -> Tokenizer) for "naive"; its settings are scoped per component, so
    # they are applied after creation by configure_pipeline().
    return {
        "name": DATASET, "parse_type": 1, "parser_id": "naive", "language": "English",
        "embedding_model": os.getenv("JESUS_RAGFLOW_EMBED", "text-embedding-3-small@default@OpenAI"),
    }


def pipeline_overrides(parser_config: dict) -> dict:
    """The component settings this project changes, keyed by the dataset's component ids."""
    changes = {}
    for component, params in parser_config.items():
        kind = component.split(":", 1)[0]
        if kind == "GeneralChunker":
            # A section (at most ~1,200 tokens) stays one parent chunk; each line
            # (header, parallels, one verse) is a child that retrieval can match.
            changes[component] = {**params, "chunk_token_size": 2048, "delimiters": ["\n"],
                                  "children_delimiters": ["\n"],
                                  "parent_child": {"use_parent_child": True, "children_delimiter": "\n"}}
        elif kind == "Extractor":
            # Chunk enrichment by the tenant's chat model: keywords and the questions a
            # section answers, which bridge how people ask and how scripture reads.
            changes[component] = {**params, "keywords": {**params.get("keywords", {}), "top_n": 5},
                                  "questions": {**params.get("questions", {}), "top_n": 3}}
        elif kind == "Tokenizer":
            changes[component] = {**params, "search_method": ["embedding", "full_text"]}
    return changes


def configure_pipeline(client: RagflowClient, dataset: dict) -> dict:
    changes = pipeline_overrides(dataset["parser_config"])
    if any(dataset["parser_config"].get(k) != v for k, v in changes.items()):
        client.update_dataset(dataset["id"], parser_config=changes)
        dataset = client.find_dataset(DATASET)
    applied = pipeline_overrides(dataset["parser_config"])
    if any(dataset["parser_config"].get(k) != v for k, v in applied.items()):
        raise RuntimeError(f"RAGFlow did not keep the pipeline settings: {json.dumps(dataset['parser_config'])[:800]}")
    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="ingest only the first N sections (a trial run)")
    parser.add_argument("--no-wait", action="store_true", help="start parsing and return")
    parser.add_argument("--replace", action="store_true",
                        help="delete these sections from the dataset first, then upload them again")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_settings()

    plain = {v.key: v.text for v in read_verses(RAW_BSB)}
    sections = read_sections(USFM_DIR, canonical=plain)[:args.limit]
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    for section in sections:  # the exact files uploaded, kept for inspection
        (SECTIONS_DIR / section.filename()).write_text(section.document(), encoding="utf-8")
    print(f"{len(sections)} sections, {sum(len(s.verses) for s in sections)} verses")

    client = RagflowClient()
    if client.find_dataset(DATASET) is None:
        client.create_dataset(**dataset_settings())
    dataset = configure_pipeline(client, client.find_dataset(DATASET))
    dataset_id = dataset["id"]
    print(f"dataset {DATASET!r}: {dataset_id}")

    existing = {doc["name"]: doc for doc in client.documents(dataset_id)}
    if args.replace:
        stale = [existing.pop(s.filename())["id"] for s in sections if s.filename() in existing]
        if stale:
            client.delete_documents(dataset_id, stale)
            print(f"deleted {len(stale)} documents to replace them")
    todo = [s for s in sections if s.filename() not in existing]
    for start in range(0, len(todo), 20):
        batch = todo[start:start + 20]
        uploaded = client.upload(dataset_id, [(s.filename(), s.document().encode("utf-8")) for s in batch])
        by_name = {doc["name"]: doc for doc in uploaded}
        for section in batch:
            client.set_metadata(dataset_id, by_name[section.filename()]["id"], section.metadata())
        print(f"uploaded {start + len(batch)}/{len(todo)}")

    documents = {doc["name"]: doc for doc in client.documents(dataset_id)}
    wanted = [documents[s.filename()] for s in sections]
    # RAGFlow 1.0 states: UNSTART, SCHEDULED, RUNNING, COMPLETED, FAILED. Only unstarted
    # or failed documents are (re)parsed, so a re-run never pays for enrichment twice.
    unparsed = [doc["id"] for doc in wanted if doc.get("ingestion_status") in (None, "", "UNSTART", "FAILED")]
    for start in range(0, len(unparsed), 20):  # one call for 482 documents timed out
        client.parse(dataset_id, unparsed[start:start + 20])
        print(f"scheduled {min(start + 20, len(unparsed))}/{len(unparsed)} for parsing")
    if args.no_wait:
        return
    started = time.monotonic()
    while True:
        documents = {doc["name"]: doc for doc in client.documents(dataset_id)}
        states = [documents[s.filename()] for s in sections]
        done = sum(d.get("ingestion_status") == "COMPLETED" for d in states)
        failed = [d["name"] for d in states if d.get("ingestion_status") == "FAILED"]
        print(f"  {done}/{len(states)} done, {len(failed)} failed, "
              f"{sum(d.get('chunk_count', 0) for d in states)} chunks ({time.monotonic() - started:.0f} s)")
        if failed:
            print("failed:", json.dumps(failed[:10]))
        if done + len(failed) == len(states):
            break
        time.sleep(10)


if __name__ == "__main__":
    main()
