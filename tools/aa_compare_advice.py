"""Replay a recording's advice twice, before and after a reading change, and
show the decisions where it differs (or the hands you ask for).

The window writes ``frames.jsonl`` into each recording folder; the advice is
worked out again from it with this checkout's code twice:

* ``before``: opponents' preflop ranges read as the population model plays
  (``aa_preflop@slowplay=0:bluff=0``: a limp or a call never holds a hand
  the model would raise, as until 2026-10-12);
* ``after``: read with slow play and bluffs (``preflop_reading``).

As in ``aa_session_report.replayed_advice`` a heads-up solve is not run (it
comes back at once as check or call) unless ``--solver`` is given, which
needs TexasSolver installed and takes about a minute per flop. The range
rule's answer next to a solve is shown either way.

    PYTHONPATH=src:. .venv/bin/python tools/aa_compare_advice.py \\
        --frames <recording>/frames.jsonl [--frames ...] [--recordings <folder>] \\
        [--hero "A♦ 9♠" --hero QsJc ...] [--hand hand_123 ...] [--all] \\
        [--out compare.json]

``--hero`` and ``--hand`` list every decision of the hands they pick;
without them the decisions whose last answer changed are listed, or with
``--all`` every decision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_advice import AASolverAdvice  # noqa: E402
from poker_engine.scoreboard.preflop_policy import (  # noqa: E402
    AAPreflopPolicy, PreflopParams)
from poker_engine.scoreboard.preflop_reading import BLUFF, SLOWPLAY  # noqa: E402
from tools.aa_session_report import _Now, _Solved, load, plain  # noqa: E402
from tools.aa_strategy_review import mode  # noqa: E402

HERO = "4"
SUITS = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
# "after" is the limp-raise reading, opt-in since 2026-10-13 (the window reads
# as "before" until this comparison on recordings shows "after" helps).
READINGS = {"before": PreflopParams(slowplay=0.0, bluff=0.0),
            "after": PreflopParams(slowplay=SLOWPLAY, bluff=BLUFF)}


def cards_of(text):
    """{"Ad", "9s"} from "A♦ 9♠", "Ad9s", "ad 9S" or "10d 9s"."""
    text = "".join(SUITS.get(char, char) for char in str(text)).replace("10", "T")
    text = "".join(text.split())
    if len(text) != 4:
        raise ValueError(f"not two cards: {text!r}")
    return {text[0].upper() + text[1].lower(), text[2].upper() + text[3].lower()}


def replay(rows, params, solver=False):
    """Each row's advice report, worked out again with ``params``."""
    now = [0.0]
    advice = AASolverAdvice(None if solver else _Solved(), _Now(),
                            preflop=AAPreflopPolicy(params), clock=lambda: now[0])
    result = []
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        result.append(advice.observe_fields(row["fields"], row["processed"]))
    return result


def answer(report, street):
    """The answer a ready report shows: kind, action, share of the pot and,
    before the flop, every option's worth in big blinds."""
    rows = report.get("advice") or [{}]
    kind = report.get("kind") or ("preflop" if street == "preflop" else "solver")
    item = {"kind": kind, "action": plain(rows[0].get("action")),
            "share": (report.get("range_equity") or {}).get("value")}
    if rows[0].get("to"):
        item["to"] = rows[0]["to"]
    if report.get("options"):
        item["options"] = {row["action"]: row["big_blinds"]
                           for row in report["options"]}
    return item


def turns(rows):
    """Your turns: consecutive rows of one hand with your buttons on screen,
    each with its rows' indexes."""
    found, current, hand = [], None, None
    for index, row in enumerate(rows):
        history = row["fields"].get("actions_v1") or {}
        visible = (row["fields"].get("hero_controls") or {}).get("visible")
        if not visible or history.get("hand_id") != hand:
            current = None
        hand = history.get("hand_id")
        if visible and hand is not None:
            if current is None:
                current = []
                found.append(current)
            current.append(index)
    return found


def decision(name, rows, indexes, before, after, final):
    fields = [rows[index]["fields"] for index in indexes]
    street = mode(f.get("street") for f in fields)
    hero = mode(" ".join(f["hero"]) for f in fields
                if f.get("hero") and all(f["hero"]))
    controls = [f.get("hero_controls") or {} for f in fields]
    last = final[rows[indexes[-1]]["fields"]["actions_v1"]["hand_id"]]
    start = rows[indexes[0]]["processed"]
    keys = ("frame", "street", "slot", "kind", "amount", "source")
    done = next((item for item in (dict(zip(keys, a)) for a in last["actions"])
                 if str(item["slot"]) == HERO and item["street"] == street
                 and item["frame"] >= start), None)
    item = {"log": name, "hand_id": last["hand_id"], "street": street, "hero": hero,
            "board": mode(" ".join(c for c in f.get("board") or () if c)
                          for f in fields) or "",
            "pot": mode(f.get("pot") for f in fields),
            "to_call": mode(c.get("call_amount") for c in controls),
            "video_seconds": rows[indexes[0]].get("video_seconds"),
            "you_did": None if done is None else plain(done["kind"])}
    for label, reports in (("before", before), ("after", after)):
        ready = [answer(reports[index], street) for index in indexes
                 if reports[index].get("status") == "ready"]
        item[label] = ready[-1] if ready else None
    actions = [(item[label] or {}).get("action") for label in ("before", "after")]
    item["changed"] = actions[0] != actions[1]
    return item


def compare(logs, *, heroes=(), hands=(), every=False, solver=False):
    """The decisions chosen, each with its last answer before and after."""
    wanted = [cards_of(text) for text in heroes]
    result = []
    for name, rows in logs:
        rows = [row for row in rows if row.get("fields")]
        reports = {label: replay(rows, params, solver)
                   for label, params in READINGS.items()}
        final = {}          # each hand's actions as its last row has them
        for row in rows:
            history = row["fields"].get("actions_v1")
            if history and history.get("hand_id") is not None:
                final[history["hand_id"]] = history
        for indexes in turns(rows):
            item = decision(name, rows, indexes, reports["before"], reports["after"],
                            final)
            chosen = ((not wanted or set((item["hero"] or "").split()) in wanted)
                      and (not hands or item["hand_id"] in hands))
            if chosen and (item["changed"] or wanted or hands or every):
                result.append(item)
    return result


def line(answer):
    if not answer:
        return "no advice"
    text = f"{answer['kind']} {answer['action']}"
    if answer.get("to"):
        text += f" to {answer['to']}"
    if answer.get("share") is not None:
        text += f" (share {answer['share']:.0%})"
    if answer.get("options"):
        text += " | " + ", ".join(f"{name} {value:+.1f}bb"
                                  for name, value in answer["options"].items())
    return text


def report(items):
    out = []
    for item in items:
        out.append(f"{item['log']} {item['hand_id']} {item['street']}"
                   f" hero {item['hero']} board [{item['board']}] pot {item['pot']}"
                   f" to call {item['to_call']} you did {item['you_did']}"
                   + ("  CHANGED" if item["changed"] else ""))
        out.append(f"  before: {line(item['before'])}")
        out.append(f"  after : {line(item['after'])}")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", default=[])
    parser.add_argument("--recordings", type=Path, action="append", default=[],
                        help="a folder: every frames.jsonl under it (repeatable)")
    parser.add_argument("--hero", action="append", default=[],
                        help='your two cards, e.g. "A♦ 9♠" or Ad9s (repeatable)')
    parser.add_argument("--hand", action="append", default=[],
                        help="a hand_id from the log (repeatable)")
    parser.add_argument("--all", action="store_true",
                        help="without --hero or --hand: every decision, not only "
                        "the changed ones")
    parser.add_argument("--solver", action="store_true",
                        help="run TexasSolver for heads-up turns and rivers")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    paths = list(args.frames)
    for folder in args.recordings:
        paths += sorted(Path(folder).expanduser().rglob("frames.jsonl"))
    if not paths:
        parser.error("no frames.jsonl: give --frames or --recordings")
    logs = [(str(path.parent.name), load(path)) for path in paths]
    items = compare(logs, heroes=args.hero, hands=args.hand, every=args.all,
                    solver=args.solver)
    print(report(items) or "no decision chosen")
    changed = sum(item["changed"] for item in items)
    print(f"{len(items)} decisions, {changed} with another answer after the change")
    if args.out:
        args.out.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
