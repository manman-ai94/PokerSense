#!/bin/sh
# Play an AA recording on the observation page at recorded pace, as if it
# were the live capture card. Optional first argument: another recording (a
# video file, or a recorder folder with segments.csv). Windows to skip come
# from POKERSENSE_SKIP (e.g. "300-820"); the default recording always skips
# 300-820s, its untouched holdout and previously evaluated window.
cd "$(dirname "$0")/../.." || exit 1
DATA="${POKERSENSE_DATA_ROOT:-$HOME/Projects/PokerSense_data}"
DEFAULT="$DATA/PokerSense_private/aa_phone_record_20260909_031030_54322c62"
VIDEO="${1:-$DEFAULT}"
SKIP="${POKERSENSE_SKIP:-}"
if [ "$VIDEO" = "$DEFAULT" ]; then
  SKIP="300-820"
fi
if [ ! -x .venv/bin/python ]; then
  echo "[AA] .venv is missing. Set it up first (see AGENTS.md)." >&2
  exit 1
fi
set -- --profile configs/reproduction/aa8_candidate_v2/factory.json \
  --replay-video "$VIDEO" --state "$DATA/aa-live-state"
if [ -n "$SKIP" ]; then
  set -- "$@" --replay-video-exclude "$SKIP"
fi
exec .venv/bin/python packaging/aa_live_entry.py "$@"
