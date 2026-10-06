#!/bin/sh
# Record the capture card into 60-second segments with a segments.csv index,
# playable by start-aa-video.command and tools/measure_aa_realtime.py.
# Runs in Terminal, which holds the camera permission.
# Usage: record-aa-capture.command [minutes] [label]
cd "$(dirname "$0")/../.." || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "[AA] .venv is missing. Set it up first (see AGENTS.md)." >&2
  exit 1
fi
PYTHONPATH=src:. exec .venv/bin/python tools/record_aa_capture.py \
  --minutes "${1:-20}" --label "${2:-session}"
