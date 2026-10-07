"""Rebuild the betting history offline from a real-time measurement log.

A real-time measurement (``tools/measure_aa_realtime.py``) takes as long as
the recording. The log keeps, per processed frame, what the history layer
reads: pot, board-card street, dealer, board and hero cards, seat states,
stacks and the latest reader actions. This feeds those fields through
``AAActionHistory`` again, so a change to the layer can be checked on whole
recordings in seconds:

    python tools/replay_aa_action_history.py --frames <log>/frames.jsonl \\
        --out <new>/frames.jsonl
    python tools/check_aa_action_history.py --frames <new>/frames.jsonl ...

The rebuilt history replaces ``actions_v1`` in each row; everything else is
copied. It matches the live run except when one frame added more than three
reader actions (the log keeps the latest three) or a reader error reset the
history without a time gap.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.desktop.aa_action_history import AAActionHistory  # noqa: E402
from poker_engine.desktop.aa_session import _actions_v1  # noqa: E402

GAP_SECONDS = 1.0           # the reader starts over after a longer gap


def payload(fields, actions):
    """The reader fields the history layer uses, rebuilt from a log row."""
    return {"scene_supported": fields.get("scene_supported"),
            "pot": {"value": fields.get("pot")},
            "street_v1": {"street": fields.get("street")},
            "dealer_seat": fields.get("dealer"),
            "cards": {"board_slots": fields.get("board"), "hero": fields.get("hero")},
            "seat_states_v1": {"seats": {
                slot: {"state": state}
                for slot, state in (fields.get("participants") or {}).items()}},
            "stacks": {slot: {"value": value}
                       for slot, value in (fields.get("stacks") or {}).items()},
            "action_history_candidate": actions}


def replay(rows):
    """The log rows with ``actions_v1`` rebuilt by the current history layer."""
    history, actions, seen, last = AAActionHistory(), [], set(), None
    result = []
    for row in rows:
        fields = row.get("fields") or {}
        processed, pts = row.get("processed"), row.get("pts_seconds")
        if last is not None and (processed != last[0] + 1
                                 or pts - last[1] > GAP_SECONDS):
            history.reset()
            actions, seen = [], set()
        last = (processed, pts)
        for action in fields.get("actions_tail") or ():
            key = (action.get("frame"), action.get("slot"), action.get("kind"),
                   action.get("confirmed_at"))
            if key not in seen:
                seen.add(key)
                actions.append(action)
        rebuilt = history.observe(payload(fields, actions[-256:]), processed)
        result.append({**row, "fields": {**fields, "actions_v1": _actions_v1(rebuilt)}})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.frames.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in replay(rows):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"frames": len(rows), "out": str(args.out)}))


if __name__ == "__main__":
    main()
