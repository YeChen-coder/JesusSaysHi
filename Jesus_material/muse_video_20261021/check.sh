#!/bin/sh
# Run check.py for the given item ids in the offline FeatherTalk container.
# usage: sh check.sh <id> [<id> ...]
D="$(cd "$(dirname "$0")" && pwd -W)"
U="C:/Users/yeche/Desktop/CodexRelatedProject/SpecterSaysHi/feathertalk_lab/upstream"
W="C:/Users/yeche/Desktop/CodexRelatedProject/SpecterSaysHi/feathertalk_lab/data/whisper"
MSYS_NO_PATHCONV=1 docker run --rm --network none -e OMP_NUM_THREADS=2 \
  -v "$U:/opt/FeatherTalk:ro" -v "$W:/whisper:ro" -v "$D:/w" \
  feathertalk-lab:local python /w/check.py "$@" 2>&1 | grep -E '^(speech|idle)_|Error|Traceback'
