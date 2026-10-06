#!/bin/sh
# Open the AA observation page with the capture card enabled (AVFoundation).
# Run it from Finder or Terminal: macOS gives camera access to Terminal, so
# the first run asks to allow Terminal to use the camera.
cd "$(dirname "$0")/../.." || exit 1
DATA="${POKERSENSE_DATA_ROOT:-$HOME/Projects/PokerSense_data}"
if [ ! -x .venv/bin/python ]; then
  echo "[AA] .venv is missing. Set it up first (see AGENTS.md)." >&2
  exit 1
fi
exec .venv/bin/python packaging/aa_live_entry.py \
  --profile configs/reproduction/aa8_candidate_v2/factory.json \
  --allow-capture --state "$DATA/aa-live-state" "$@"
