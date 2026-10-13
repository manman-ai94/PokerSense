"""Replay a recording's advice twice, before and after a reading change, and
show the decisions where it differs (or the hands you ask for).

The window writes ``frames.jsonl`` into each recording folder; the advice is
worked out again from it with this checkout's code twice. With
``--change preflop`` (the default):

* ``before``: opponents' preflop ranges read as the population model plays
  (``aa_preflop@slowplay=0:bluff=0``: a limp or a call never holds a hand
  the model would raise, as until 2026-10-12);
* ``after``: read with slow play and bluffs (``preflop_reading``).

With ``--change postflop`` both read preflop as the window does, and

* ``before``: postflop actions read by veto (``postflop_reading.VETO``, as
  until 2026-10-13);
* ``after``: read with the weights of ``postflop_reading.WEIGHTS``.

With ``--change sizing`` both read as the window does, and

* ``before``: postflop bets and raises by the lines of the share of the pot
  (``range_multiway`` with ``sizing=0``, as until 2026-10-13);
* ``after``: by what each size is worth against the hands that call it
  (``multiway_bot.sized``).

It also counts, over every postflop decision (changed or not) in a pot of 30
big blinds or more where every opponent still in showed his cards, the bets
and raises advised while behind those cards (share under a half) before and
after: the bets the hands that went on beat.

Where every opponent still in at a decision showed his cards at the end of
the hand, ``shown`` values each answer in chips against those cards: your
share of the pot against them on the board of the decision (the rest of the
board dealt at random), a fold 0, a check or call that share of the pot
after calling less the call, a bet or raise the same with every opponent
still in calling it (they did go on to show their cards).

As in ``aa_session_report.replayed_advice`` a heads-up solve is not run (it
comes back at once as check or call) unless ``--solver`` is given, which
needs TexasSolver installed and takes about a minute per flop. The range
rule's answer next to a solve is shown either way.

    PYTHONPATH=src:. .venv/bin/python tools/aa_compare_advice.py \\
        --frames <recording>/frames.jsonl [--frames ...] [--recordings <folder>] \\
        [--hero "A♦ 9♠" --hero QsJc ...] [--hand hand_123 ...] [--all] \\
        [--change preflop|postflop|sizing] [--out compare.json]

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

from decimal import Decimal  # noqa: E402

from poker_engine.desktop.aa_solver_advice import AASolverAdvice  # noqa: E402
from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    HERO as HERO_SEAT, hand_facts, table_observation)
from poker_engine.scoreboard import multiway_bot  # noqa: E402
from poker_engine.scoreboard.postflop_reading import VETO, WEIGHTS  # noqa: E402
from poker_engine.scoreboard.ranges import ranges_equity  # noqa: E402
from poker_engine.solver.texassolver import combo_key  # noqa: E402
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
# --change postflop: (preflop params, postflop weights) before and after.
POSTFLOP = {"before": (PreflopParams(), VETO), "after": (PreflopParams(), WEIGHTS)}
SHOWN_TRIALS = 20000
BIG_POT = 30                # big blinds: the big-pot guard's line


def cards_of(text):
    """{"Ad", "9s"} from "A♦ 9♠", "Ad9s", "ad 9S" or "10d 9s"."""
    text = "".join(SUITS.get(char, char) for char in str(text)).replace("10", "T")
    text = "".join(text.split())
    if len(text) != 4:
        raise ValueError(f"not two cards: {text!r}")
    return {text[0].upper() + text[1].lower(), text[2].upper() + text[3].lower()}


def replay(rows, params, solver=False, postflop=None, sizing=None):
    """Each row's advice report, worked out again with ``params`` (and the
    postflop reading weights ``postflop``, else the default; ``sizing`` 0 or
    1: ``range_multiway``'s, else the default)."""
    if sizing is not None:
        default = multiway_bot.DEFAULTS["sizing"]
        multiway_bot.DEFAULTS["sizing"] = sizing
        try:
            return replay(rows, params, solver, postflop)
        finally:
            multiway_bot.DEFAULTS["sizing"] = default
    now = [0.0]
    advice = AASolverAdvice(None if solver else _Solved(), _Now(),
                            preflop=AAPreflopPolicy(params), clock=lambda: now[0])
    if postflop is not None:
        advice._range_model().postflop_reading = postflop
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


def shown_cards(rows):
    """{seat: two cards} the hand's last reading of the cards shown."""
    shown = next((row["fields"]["shown_cards"] for row in reversed(rows)
                  if row["fields"].get("shown_cards")), None) or {}
    return {int(seat): value["cards"]
            for seat, value in (shown.get("seats") or {}).items()
            if len(value.get("cards") or ()) == 2 and all(value["cards"])}


def chips(answer, observation, share):
    """What ``answer`` is worth in chips now against shown cards (see the
    module notes), or None for an answer it cannot price."""
    if not answer or not answer.get("action"):
        return None
    me = str(observation["observing_seat"])
    to_call = Decimal(observation["to_call"] or 0)
    pot = Decimal(observation["pot"])
    action = answer["action"]
    if action == "fold" and to_call:
        return 0.0
    if action in ("fold", "check", "call"):
        put = min(to_call, Decimal(observation["stacks"][me]))
        return float(Decimal(share) * (pot + put) - put)
    if action != "raise" or not answer.get("to"):
        return None
    mine = Decimal(observation["bets"][me])
    put = min(Decimal(str(answer["to"])) - mine, Decimal(observation["stacks"][me]))
    level = mine + put
    final = pot + put
    for seat in observation["occupied_seats"]:
        if str(seat) == me or seat in observation["folded"]:
            continue
        final += max(Decimal(0), min(level - Decimal(observation["bets"][str(seat)]),
                                     Decimal(observation["stacks"][str(seat)])))
    return float(Decimal(share) * final - put)


def shown_value(rows, indexes, item):
    """{"cards", "share", "before", "after"}: both answers in chips against the
    cards the opponents still in showed, or None when one of them did not."""
    hand = item["hand_id"]
    start = next(i for i in range(indexes[0], -1, -1)
                 if ((rows[i]["fields"].get("actions_v1") or {}).get("hand_id")
                     != hand) or i == 0)
    hand_rows = [row for row in rows[start:] if
                 (row["fields"].get("actions_v1") or {}).get("hand_id") == hand]
    shown = shown_cards(hand_rows)
    if not shown:
        return None
    moment = rows[indexes[0]]["processed"]
    upto = [row for row in hand_rows if row["processed"] <= moment]
    try:
        observation = table_observation(hand_facts(upto), HERO_SEAT)
    except Exception:
        return None
    if observation is None or not all(observation["own_hole"]):
        return None
    live = [seat for seat in observation["occupied_seats"]
            if seat not in observation["folded"] and seat != HERO_SEAT]
    if not live or any(seat not in shown for seat in live):
        return None
    board = tuple(observation["board"])
    ranges = {seat: {combo_key(shown[seat]): 1.0} for seat in live}
    share, _ = ranges_equity(tuple(observation["own_hole"]), board, ranges,
                             trials=SHOWN_TRIALS)
    if share is None:
        return None
    big_blind = float(observation["rules"]["big_blind"])
    result = {"cards": {str(seat): " ".join(shown[seat]) for seat in live},
              "share": round(share, 3),
              "pot_big_blinds": round(float(observation["pot"]) / big_blind, 1)}
    for label in ("before", "after"):
        value = chips(item[label], observation, share)
        result[label] = None if value is None else round(value, 1)
    return result


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


def compare(logs, *, heroes=(), hands=(), every=False, solver=False, change="preflop"):
    """The decisions chosen, each with its last answer before and after."""
    wanted = [cards_of(text) for text in heroes]
    result = []
    for name, rows in logs:
        rows = [row for row in rows if row.get("fields")]
        if change == "postflop":
            reports = {label: replay(rows, params, solver, weights)
                       for label, (params, weights) in POSTFLOP.items()}
        elif change == "sizing":
            reports = {label: replay(rows, PreflopParams(), solver, sizing=sizing)
                       for label, sizing in (("before", 0.0), ("after", 1.0))}
        else:
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
            listed = item["changed"] or wanted or hands or every
            postflop = change == "sizing" and item["street"] != "preflop"
            if chosen and (listed or postflop):
                item["shown"] = shown_value(rows, indexes, item)
                item["listed"] = bool(listed)
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


def behind_in_big_pots(items):
    """{"before", "after"}: bets and raises advised in pots of ``BIG_POT`` big
    blinds or more while behind the cards the opponents showed."""
    count = {"before": 0, "after": 0}
    for item in items:
        shown = item.get("shown")
        if (not shown or shown["share"] >= 0.5
                or shown["pot_big_blinds"] < BIG_POT):
            continue
        for label in count:
            count[label] += (item[label] or {}).get("action") in ("bet", "raise")
    return count


def report(items):
    out = []
    for item in items:
        if not item.get("listed", True):
            continue
        out.append(f"{item['log']} {item['hand_id']} {item['street']}"
                   f" hero {item['hero']} board [{item['board']}] pot {item['pot']}"
                   f" to call {item['to_call']} you did {item['you_did']}"
                   + ("  CHANGED" if item["changed"] else ""))
        out.append(f"  before: {line(item['before'])}")
        out.append(f"  after : {line(item['after'])}")
        if item.get("shown"):
            shown = item["shown"]
            out.append(f"  shown {shown['cards']} share {shown['share']:.0%}: "
                       f"before {shown['before']} after {shown['after']} chips")
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
    parser.add_argument("--change", choices=("preflop", "postflop", "sizing"),
                        default="preflop",
                        help="which reading change to compare (see above)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    paths = list(args.frames)
    for folder in args.recordings:
        paths += sorted(Path(folder).expanduser().rglob("frames.jsonl"))
    if not paths:
        parser.error("no frames.jsonl: give --frames or --recordings")
    logs = [(str(path.parent.name), load(path)) for path in paths]
    items = compare(logs, heroes=args.hero, hands=args.hand, every=args.all,
                    solver=args.solver, change=args.change)
    print(report(items) or "no decision chosen")
    changed = sum(item["changed"] for item in items)
    items_listed = [item for item in items if item.get("listed", True)]
    print(f"{len(items_listed)} decisions, {changed} with another answer after the "
          "change")
    if args.change == "sizing":
        behind = behind_in_big_pots(items)
        print(f"bets and raises in pots of {BIG_POT}+ big blinds behind the shown "
              f"cards: before {behind['before']}, after {behind['after']}")
    priced = [item["shown"] for item in items
              if item["changed"] and item.get("shown")
              and None not in (item["shown"]["before"], item["shown"]["after"])]
    if priced:
        better = sum(one["after"] > one["before"] for one in priced)
        worse = sum(one["after"] < one["before"] for one in priced)
        print(f"changed decisions priced against shown cards: {len(priced)}, "
              f"after better {better}, worse {worse}; chips before "
              f"{sum(one['before'] for one in priced):+.0f}, after "
              f"{sum(one['after'] for one in priced):+.0f}")
    if args.out:
        args.out.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
