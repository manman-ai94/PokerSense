"""Check how many rebuilt hands replay on the simulated AA table.

The solver strategy needs each hand as a replay on the AA table
(``poker_engine.desktop.aa_solver_input``). This runs that replay for every
complete hand of a measurement log and reports how many fit, why the rest
stop, how often the dealer had to come from the betting order, and whether
the opening pot matches the antes, blinds and straddle:

    python tools/check_aa_solver_input.py --frames <log>/frames.jsonl

Use a log whose ``actions_v1`` comes from the current history layer (rebuild
an older log with ``tools/replay_aa_action_history.py``).
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.desktop.aa_solver_input import check_hand  # noqa: E402


def hands(rows):
    """Rows grouped by the rebuilt hand they belong to, in order."""
    grouped = {}
    for row in rows:
        history = (row.get("fields") or {}).get("actions_v1")
        if history:
            grouped.setdefault(history["hand_id"], []).append(row)
    return grouped


def summarize(results):
    complete = [r for r in results if r["complete"]]
    return {"hands": len(results), "complete_hands": len(complete),
            "replayed_fully": sum(r["status"] == "ok" for r in complete),
            "stopped": dict(Counter(r["reason"] for r in complete
                                    if r["status"] != "ok")),
            "dealer_from": dict(Counter(r["dealer_source"] for r in complete
                                        if r["status"] == "ok")),
            "players": dict(Counter(str(r["players"]) for r in complete)),
            "opening_pot_matches": sum(r["opening_pot_matches"] for r in complete)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.frames.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    results = [check_hand(part) for part in hands(rows).values()]
    print(json.dumps({"summary": summarize(results), "hands": results},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
