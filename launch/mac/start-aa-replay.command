#!/bin/sh
# Start the AA observation page on macOS and replay a restored frame pool.
# Double-click in Finder, or run from a terminal. Optional first argument:
# another frame-pool directory (a folder containing samples.json).
cd "$(dirname "$0")/../.." || exit 1
DATA="${POKERSENSE_DATA_ROOT:-$HOME/Projects/PokerSense_data}"
POOL="${1:-$DATA/PokerSense_private/aa8_first_hand_full_v1}"
if [ ! -x .venv/bin/python ]; then
  echo "[AA] .venv is missing. Set it up first (see AGENTS.md)." >&2
  exit 1
fi
exec .venv/bin/python packaging/aa_live_entry.py \
  --profile configs/reproduction/aa8_candidate_v2/factory.json \
  --replay-pool "$POOL" \
  --state "$DATA/aa-live-state"
