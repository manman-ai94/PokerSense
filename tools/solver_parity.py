"""Do two machines' TexasSolver builds give the same answers?

    # on each machine (same fixed synthetic spots, one solver thread):
    PYTHONPATH=src:. .venv/bin/python tools/solver_parity.py run --out <machine>.json
    # then, anywhere:
    PYTHONPATH=src:. .venv/bin/python tools/solver_parity.py compare mac.json windows.json

``run`` solves 16 fixed heads-up spots (8 turns, 8 rivers; synthetic ranges,
some combinations weighted apart from their class so the exact-combination
path is used) and writes, per spot, the first player's strategy for every
combination and the second player's after a check. ``compare`` reports per
spot the largest probability difference, the share of combinations whose
most frequent action agrees and each action's range-wide frequency.

Different compilers round floating point differently, so answers are close,
not identical; a spot passes when no probability differs by more than
``--tolerance`` (default 0.05) and the range-wide frequencies by more than
half of it.
"""

import argparse
import json
import platform
import sys
import time

from poker_engine.solver.texassolver import (
    TexasSolver, Spot, Tree, all_combos, node_at, solver_binary)

RANKS = "23456789TJQKA"

# (board, pot, stack, in-position range, out-of-position range)
SPOTS = [
    ("Qs Jh 2h 7c", 20, 80, "AA,KK,QQ,AKs,AQs,KQs,QJs,JTs,T9s,98s,AhKh*0.5", "JJ,TT,99,AJo,KJo,QTs,J9s,87s,76s"),
    ("Ah 8d 3c 5s", 12, 94, "88,55,33,A5s,A8s,K9s,QTs,JTs,T9s,KdQd*0.4", "AA,AK,AQ,AJ,AT,99,77,66"),
    ("Td 9d 4s 2c", 30, 70, "TT,99,44,AdKd,AdQd,KdQd,QJs,J8s,87s", "AA,KK,QQ,JJ,AT,KT,QT,T8s,98s,AhKh*0.3"),
    ("Kc Kd 6h 2s", 16, 120, "AK,KQ,K6s,66,22,AQs,AJs,QJs,JTs", "AA,QQ,JJ,TT,A6s,76s,65s,AcQc*0.6"),
    ("7h 6h 5c Jd", 24, 60, "98s,84s,77,66,55,JJ,AJs,KJs,QJs,Ah9h*0.5", "AA,KK,QQ,TT,AQ,AK,T9s,J9s"),
    ("As Ks 9c 4d", 40, 160, "AA,KK,99,AK,AQs,QJs,JTs,AsTs*0.5,QsJs*0.5", "QQ,JJ,TT,AJ,KQ,KJ,T9s,98s"),
    ("3d 3s 8h Qc", 10, 50, "QQ,88,AQ,KQ,QJs,Q9s,A8s,98s,87s", "AA,KK,JJ,TT,99,AK,AJ,KJ,8c7c*0.5"),
    ("Jc Tc 8d 2h", 18, 100, "JJ,TT,88,QJs,AcKc,AcQc,KcQc,Q9s,97s,9c7c*0.5", "AA,KK,QQ,AJ,KJ,JT,T9,99"),
    ("Qs Jh 2h 7c 3d", 40, 60, "AA,KK,QQ,AKs,AQs,KQs,QJs,JTs,T9s,65s,AhKh*0.5", "JJ,TT,99,AJo,KJo,QTs,J9s,87s"),
    ("Ah 8d 3c 5s Kd", 30, 70, "88,55,33,A5s,A8s,AK,KQs,QTs,JTs,64s", "AA,AQ,AJ,AT,99,77,66,KdQd*0.4"),
    ("Td 9d 4s 2c 6d", 60, 40, "TT,99,44,AdKd,AdQd,KdQd,QJs,87s,J8s", "AA,KK,QQ,JJ,AT,KT,QT,T8s,98s,AhKh*0.3"),
    ("Kc Kd 6h 2s 9c", 20, 100, "AK,KQ,K9s,66,99,AQs,AJs,QJs,JTs", "AA,QQ,JJ,TT,A9s,T9s,87s,AcQc*0.6"),
    ("7h 6h 5c Jd 2h", 50, 40, "98s,84s,77,66,55,JJ,AhKh,AhQh,KhQh,Ah9h*0.5", "AA,KK,QQ,TT,AJ,KJ,T9s,J9s"),
    ("As Ks 9c 4d 4h", 80, 120, "AA,KK,99,44,AK,AQs,QJs,JTs,AsTs*0.5", "QQ,JJ,TT,AJ,KQ,KJ,A4s,QsJs*0.5"),
    ("3d 3s 8h Qc Ad", 14, 46, "QQ,88,AQ,KQ,QJs,A8s,98s,A3s", "AA,KK,JJ,TT,99,AK,AJ,KJ,8c7c*0.5"),
    ("Jc Tc 8d 2h 5c", 36, 82, "JJ,TT,88,55,QJs,AcKc,AcQc,KcQc,Q9s,9c7c*0.5", "AA,KK,QQ,AJ,KJ,JT,T9,99"),
]
TREE = Tree(bets=(50, 100), raises=(100,), donks=(50,))


def _pairs(name):
    """The combinations of one range item, e.g. "AKs", "TT", "AhKh"."""
    if len(name) == 4:
        return [(name[:2], name[2:])]
    high, low = name[0], name[1]
    kind = name[2] if len(name) == 3 else ""
    suits = "cdhs"
    if high == low:
        return [(high + a, low + b) for i, a in enumerate(suits) for b in suits[i + 1:]]
    return [(high + a, low + b) for a in suits for b in suits
            if (kind != "s" or a == b) and (kind != "o" or a != b)]


def weights(text, board):
    """{solver combination key: weight} from "AA,AKs,AhKh*0.5"."""
    from poker_engine.solver.texassolver import combo_key
    result = {}
    for item in text.split(","):
        name, _, weight = item.partition("*")
        for pair in _pairs(name):
            if pair[0] in board or pair[1] in board:
                continue
            result[combo_key(pair)] = float(weight or 1.0)
    return result


def spots():
    for board, pot, stack, ip, oop in SPOTS:
        cards = tuple(board.split())
        yield board, Spot(board=cards, pot=pot, stack=stack,
                          range_ip=weights(ip, cards), range_oop=weights(oop, cards),
                          tree=TREE)


def _strategy(node):
    strategy = node["strategy"]
    return {"actions": strategy["actions"],
            "combos": {key: [round(p, 6) for p in values]
                       for key, values in sorted(strategy["strategy"].items())}}


def run(out, accuracy=0.3, iterations=300):
    binary = solver_binary()
    if binary is None:
        raise SystemExit("TexasSolver is not installed")
    report = {"machine": {"platform": platform.platform(), "python": sys.version.split()[0],
                          "binary": str(binary)},
              "settings": {"threads": 1, "accuracy": accuracy, "iterations": iterations},
              "spots": []}
    with TexasSolver(threads=1, accuracy=accuracy, max_iterations=iterations,
                     timeout=600) as solver:
        for board, spot in spots():
            started = time.monotonic()
            tree = solver.solve(spot)
            entry = {"board": board, "pot": spot.pot, "stack": spot.stack,
                     "seconds": round(time.monotonic() - started, 2),
                     "first": _strategy(tree)}
            if "CHECK" in (tree.get("childrens") or {}):
                entry["after_check"] = _strategy(node_at(tree, ["CHECK"]))
            report["spots"].append(entry)
            print(f"{board:16s} {entry['seconds']:6.2f} s", flush=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    return report


def _frequencies(strategy):
    combos = strategy["combos"].values()
    return [round(sum(values[i] for values in combos) / max(len(combos), 1), 4)
            for i in range(len(strategy["actions"]))]


def _node(a, b):
    if a["actions"] != b["actions"] or a["combos"].keys() != b["combos"].keys():
        return {"same_tree": False}
    diffs, agree = [], 0
    for key, left in a["combos"].items():
        right = b["combos"][key]
        diffs.append(max(abs(x - y) for x, y in zip(left, right)))
        agree += left.index(max(left)) == right.index(max(right))
    fa, fb = _frequencies(a), _frequencies(b)
    return {"same_tree": True, "max_diff": round(max(diffs), 4),
            "mean_diff": round(sum(diffs) / len(diffs), 5),
            "top_action_agrees": round(agree / len(diffs), 4),
            "frequency_diff": round(max(abs(x - y) for x, y in zip(fa, fb)), 4),
            "actions": a["actions"], "frequencies": [fa, fb]}


def compare(left, right, tolerance=0.05):
    rows = []
    for a, b in zip(left["spots"], right["spots"]):
        if a["board"] != b["board"]:
            raise SystemExit("the two files solved different spots")
        row = {"board": a["board"], "first": _node(a["first"], b["first"])}
        if "after_check" in a and "after_check" in b:
            row["after_check"] = _node(a["after_check"], b["after_check"])
        nodes = [n for n in (row["first"], row.get("after_check")) if n]
        row["pass"] = all(n["same_tree"] and n["max_diff"] <= tolerance
                          and n["frequency_diff"] <= tolerance / 2 for n in nodes)
        rows.append(row)
    return {"left": left["machine"], "right": right["machine"], "tolerance": tolerance,
            "passed": sum(r["pass"] for r in rows), "spots": len(rows), "rows": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    solve = commands.add_parser("run")
    solve.add_argument("--out", required=True)
    check = commands.add_parser("compare")
    check.add_argument("left")
    check.add_argument("right")
    check.add_argument("--tolerance", type=float, default=0.05)
    check.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.out)
        return 0
    with open(args.left, encoding="utf-8") as a, open(args.right, encoding="utf-8") as b:
        result = compare(json.load(a), json.load(b), args.tolerance)
    for row in result["rows"]:
        first = row["first"]
        print(f"{row['board']:16s} {'通过' if row['pass'] else '不同'}  "
              f"最大差 {first.get('max_diff')}  首选动作一致 {first.get('top_action_agrees')}  "
              f"频率差 {first.get('frequency_diff')}")
    print(f"共 {result['spots']} 个局面，{result['passed']} 个在误差 {result['tolerance']} 内一致")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=1)
    return 0 if result["passed"] == result["spots"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
