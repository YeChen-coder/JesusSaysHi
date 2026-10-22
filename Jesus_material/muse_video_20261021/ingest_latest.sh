#!/bin/sh
# Ingest the newest Muse download in ~/Downloads as <item_id>.
# usage: sh ingest_latest.sh <item_id> <muse_thread_url>
set -e
cd "$(dirname "$0")"
f=$(ls -t "$USERPROFILE"/Downloads/media-generation-*.mp4 | head -1)
MSYS_NO_PATHCONV=1 python -I ingest.py "$1" "$f" "$2"
