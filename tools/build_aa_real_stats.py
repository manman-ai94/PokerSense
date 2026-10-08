"""Keep the AA real-player numbers the "AA 真人桌" opponents need, in the package.

    PYTHONPATH=src:. .venv/bin/python tools/build_aa_real_stats.py \\
        <aa_population_stats_v1.json of tools/aa_population_stats.py>

Copies, from the ALL group (every table size): the preflop rows (raise, call
and fold per kind of decision, overall and per position), the postflop rows
(per situation of ``spots.postflop_spot``), the bet and raise sizes, and the
per-position player shares (VPIP, raises, flops seen) used to check the bot.
Every row keeps its count ``n`` and grade; rows graded ``too_few`` are left
out. Only aggregate counts are kept: no hands, seats or players.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

OUT = (Path(__file__).resolve().parents[1]
       / "src/poker_engine/scoreboard/aa_real_stats_v1.json")
ACTIONS = ("raise", "call", "fold", "bet", "check")
PLAYER = ("vpip", "pfr", "rfi_raise", "rfi_limp", "saw_flop", "three_bet")


def shares(row):
    out = {"n": row["n"], "grade": row["grade"]}
    for action in ACTIONS:
        if isinstance(row.get(action), dict):
            out[action] = row[action]["share"]
    return out


def build(stats):
    group = stats["groups"]["ALL"]
    keep = {}
    for part in ("preflop", "postflop"):
        keep[part] = {key: shares(row) for key, row in sorted(group[part].items())
                      if row["grade"] != "too_few"}
    keep["sizes"] = {key: {"n": row["n"], "grade": row["grade"],
                           "median": row["median"]}
                     for key, row in sorted(group["sizes"].items())
                     if row["grade"] != "too_few"}
    keep["player"] = {key: {"n": row["n"], "grade": row["grade"],
                            "share": row["share"]}
                      for key, row in sorted(group["player"].items())
                      if key.split("|")[1] in PLAYER and row["grade"] != "too_few"}
    return {"schema_version": 1,
            "source": ("tools/aa_population_stats.py, version "
                       f"{stats.get('version', stats.get('schema_version'))}: "
                       f"{stats['hands_counted']} hands, "
                       f"{stats['video_minutes']} minutes of AA recordings"),
            "method": ("aggregate shares of AA players' decisions (all table sizes); "
                       "rows with fewer than 10 decisions left out"),
            **keep}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stats", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    data = build(json.loads(args.stats.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"{args.out}: {len(data['preflop'])} preflop, {len(data['postflop'])} "
          f"postflop rows, {len(data['sizes'])} sizes")


if __name__ == "__main__":
    main()
