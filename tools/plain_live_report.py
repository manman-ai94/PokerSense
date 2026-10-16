"""一页纸打法（``plain``）在实录上重放，和旧策略并排的数（第三期 B 的 PR 2）。

The window's frame logs of real sessions (``frames.jsonl``, or the same
gzipped) are replayed frame by frame on the recording's clock with this
checkout's code, twice:

* ``plain``: the window with the switch on (``aa_plain_advice``: the hand's
  state locked as it goes, a decision worked out once when the screen is
  read, 铁律 5 after 2 seconds without);
* ``old``: the window as it is by default (``AASolverAdvice``), its heads-up
  solve replaced by the range rule the window shows next to it (there is no
  TexasSolver here): the scoreboard's reference ``range_multiway@hu=1+aa_preflop``.
  The background work runs inline, so its timing is not the window's.

The advice the window showed while the session was played (``shown``) is
read from the log as it is.

Your turns are the frames with your buttons on screen, one hand and one
street at a time (``FLASH``: buttons while your seat still sits out, gone at
once, are not a turn). Buttons left on screen after you acted (the next
street's cards come while they show, or they show under ``BRIEF`` seconds
after your action and the next street follows) are counted apart. What you
did is your action on the street in the hand's history after the turn
began, else what the screen shows next (your seat folded; the next street
with you still in after a check button: 杜's window never reads a check).
For each recording, for 主人's and 杜's apart and in all, the summary
(totals only, nothing of a hand) gives:

* ``coverage``: turns with advice, without, 铁律 5 for want of a reading and
  what was missing, a changed answer within one decision (改口), the rough
  rule's answers (``old``), button to ready and ready to advice, and the
  plain path's cost per frame;
* ``preflop``: raises by plain and by old, by how strong your two cards are
  (169 classes, ``combo_percentile``), and the other answers;
* ``changed``: decisions whose action differs (plain against old), by street
  and by the plain rule that decided them;
* ``shown``: those changed decisions where every opponent still in showed
  his cards, both answers in big blinds against those cards
  (``aa_compare_advice.chips``);
* ``results``: your results with the luck out (``luck_results``): all hands,
  the hands you played as the window advised then (``shown``), and the hands
  in which every one of your decisions was what plain says now. You decided,
  not chance: only a hint;
* ``rules``: plain's rule ids at decisions and the ``unspecified`` cases;
* ``reading``: the four inputs plain cannot do without (your cards, the
  price, the pot, your stack): read within 2 seconds of your buttons, and
  read two ways (cards: two different readings in one hand as plain's state
  holds them, its ``card_conflict``; price, pot, stack: within one turn,
  while nothing at the table moves, each held ``MISREAD`` frames), with no
  hand labels to check against;
* ``abilities``: v3.1 section 7, first version: compliance with plain
  (size within 25%; looser and tighter apart), iron-rule violations, pots
  won after the flop and at showdown, the shown hands' place among the 169
  classes by the preflop action that set their range (mean, and how many
  fell outside the v3.1 range), and plain's share of the pot against how
  the hand went at showdown, in five bands, where you did what plain says.
  Each with the sample v3.1 asks for, ``不够`` below it. These sessions were
  played with the old advice: a baseline, not plain's own.

    PYTHONPATH=src:. .venv/bin/python tools/plain_live_report.py \\
        --frames <录像>/frames.jsonl [--frames <杜的>.jsonl.gz ...] \\
        [--name 主人=<录像名>,... --name 杜=...] --out <汇总.json>

A log whose name starts with ``du`` is 杜's unless ``--name`` says otherwise.
Only totals are written; the logs hold other players' hands and stay in the
private data folder.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from decimal import Decimal
import gzip
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop import aa_plain_advice as live  # noqa: E402
from poker_engine.desktop.aa_plain_advice import AAPlainAdvice  # noqa: E402
from poker_engine.desktop.aa_solver_advice import AASolverAdvice  # noqa: E402
from poker_engine.scoreboard import plain_policy  # noqa: E402
from poker_engine.scoreboard.solver_bot import Fallback  # noqa: E402
from poker_engine.scoreboard.strength import combo_percentile  # noqa: E402
from tools.aa_compare_advice import chips, shown_cards, shown_spot  # noqa: E402
from tools.aa_session_report import _Now  # noqa: E402
from tools import luck_results  # noqa: E402

HERO = "4"
FLASH = 0.5                 # seconds: buttons while you still sit out
BRIEF = 1.5                 # seconds: buttons left on after you acted
AFTER_FRAMES = 30           # frames after your buttons went to see what you did
MISREAD = 3                 # frames a second reading must hold to count
READ_SECONDS = 2.0          # "2 秒内读到"
BUCKETS = ((0.05, "前 5%"), (0.12, "5–12%"), (0.25, "12–25%"), (0.50, "25–50%"),
           (1.01, "后 50%"))
EQUITY_BUCKETS = (0.2, 0.4, 0.6, 0.8, 1.01)
AGGRESSIVE = {"bet": "raise", "raise": "raise", "all_in": "raise", "allin": "raise"}
# v3.1 第七节：多少样本才稳
ENOUGH = {"compliance": 400, "flops": 300, "showdowns": 300, "shown_class": 100,
          "equity_bucket": 60}
CLASSES = ("limp", "raise", "call_raise", "three_bet", "call_three_bet")
CLASS_WORD = {"limp": "平跟", "raise": "加注", "call_raise": "跟注了加注",
              "three_bet": "再加注 / 全下", "call_three_bet": "跟注了再加注"}
IRON = ("I1", "I2", "I3", "I4", "I5")
TARGETS = {"pot_won": 0.39, "showdown_won": 0.56}


class _NoSolver:
    """No heads-up solve in this replay: the range rule's answer stays."""

    def solved_spot(self, observation, salt):
        raise Fallback("no_solver_in_replay")


def load(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [row for row in (json.loads(line) for line in handle if line.strip())
                if row.get("fields")]


def log_name(path):
    path = Path(path)
    if path.name in ("frames.jsonl", "frames.jsonl.gz"):
        return path.parent.name
    return path.name.split(".")[0]


def act(action):
    """fold, check, call or raise (a bet or an all-in counts as a raise)."""
    action = str(action or "").lower()
    return AGGRESSIVE.get(action, action) or None


def first_row(report):
    rows = report.get("advice") or [{}]
    return rows[0] if rows else {}


def median(values):
    values = [value for value in values if value is not None]
    return round(statistics.median(values), 3) if values else None


def quantile(values, share):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return round(values[min(len(values) - 1, int(share * len(values)))], 3)


def share(part, whole):
    return None if not whole else round(part / whole, 4)


# -- replays -------------------------------------------------------------------

def replay_plain(rows):
    """(each row's plain report, ms each frame took, each hand's last state)."""
    now = [0.0]
    advice = AAPlainAdvice(clock=lambda: now[0])
    reports, cost, states = [], [], {}
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        started = time.perf_counter()
        reports.append(advice.observe_fields(row["fields"], row["processed"]))
        cost.append((time.perf_counter() - started) * 1000)
        if advice.state is not None:
            states[advice._hand_id] = (advice.state, advice.stakes())
    return reports, cost, states


def replay_old(rows):
    now = [0.0]
    advice = AASolverAdvice(_NoSolver(), _Now(), clock=lambda: now[0])
    reports = []
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        reports.append(advice.observe_fields(row["fields"], row["processed"]))
    return reports


def shown_reports(rows):
    return [row["fields"].get("solver_advice") or row["fields"].get("solver_advice_v1")
            or {} for row in rows]


# -- your turns ------------------------------------------------------------------

def final_actions(rows):
    """{hand_id: [action dicts]} as each hand's last row has them."""
    keys = ("frame", "street", "slot", "kind", "amount", "source")
    found = {}
    for row in rows:
        history = row["fields"].get("actions_v1")
        if history and history.get("hand_id") is not None:
            found[history["hand_id"]] = [dict(zip(keys, item))
                                         for item in history.get("actions") or ()]
    return found


def turns(rows):
    """Your turns: runs of rows of one hand and one street with your buttons."""
    found, current, key = [], None, None
    for index, row in enumerate(rows):
        fields = row["fields"]
        hand = (fields.get("actions_v1") or {}).get("hand_id")
        visible = (fields.get("hero_controls") or {}).get("visible")
        here = (hand, fields.get("street"))
        if not visible or hand is None or here != key:
            current = None
        key = here
        if visible and hand is not None:
            if current is None:
                current = {"hand_id": hand, "street": fields.get("street"),
                           "indexes": [],
                           "seated": (fields.get("participants") or {}).get(HERO)
                           != "waiting"}
                found.append(current)
            current["indexes"].append(index)
    for turn in found:
        first, last = rows[turn["indexes"][0]], rows[turn["indexes"][-1]]
        turn["start"] = first.get("pts_seconds") or 0.0
        turn["seconds"] = (last.get("pts_seconds") or 0.0) - turn["start"]
    return [turn for turn in found if turn.pop("seated") or turn["seconds"] >= FLASH]


def you_did(turn, rows, actions):
    """(your first action on the turn's street from its first frame on, its
    amount, how it was read): from the hand's action history, else from the
    screen after your buttons went (your seat folded; or the next street came
    with you still in after a check button: 杜's window never reads a check)."""
    frame = rows[turn["indexes"][0]]["processed"]
    done = next((item for item in actions.get(turn["hand_id"]) or ()
                 if str(item["slot"]) == HERO and item["street"] == turn["street"]
                 and item["frame"] is not None and item["frame"] >= frame), None)
    if done is not None:
        return act(done["kind"]), done.get("amount"), "history"
    controls = rows[turn["indexes"][0]]["fields"].get("hero_controls") or {}
    button = controls.get("button")
    for row in rows[turn["indexes"][-1] + 1:turn["indexes"][-1] + 1 + AFTER_FRAMES]:
        fields = row["fields"]
        if (fields.get("actions_v1") or {}).get("hand_id") != turn["hand_id"]:
            break
        if (fields.get("participants") or {}).get(HERO) == "folded":
            return "fold", None, "screen"
        if fields.get("street") != turn["street"]:
            if button == "check":
                return "check", None, "screen"
            return None, None, None
    return None, None, None


def lingering(turn, rows, actions):
    """Buttons left on screen after you acted on this street: the next street's
    cards come while they show, or they show briefly after your action and the
    next street follows."""
    need = live.BOARD_CARDS.get(turn["street"])
    if need is None:
        return True
    if any(len([card for card in rows[index]["fields"].get("board") or () if card])
           > need for index in turn["indexes"]):
        return True
    frame = rows[turn["indexes"][0]]["processed"]
    before = any(str(item["slot"]) == HERO and item["street"] == turn["street"]
                 and item["frame"] is not None and item["frame"] < frame
                 for item in actions.get(turn["hand_id"]) or ())
    after = rows[turn["indexes"][-1] + 1]["fields"] \
        if turn["indexes"][-1] + 1 < len(rows) else {}
    return before and turn["seconds"] < BRIEF and after.get("street") != turn["street"]


def hero_cards(rows, indexes):
    readings = Counter(" ".join(rows[index]["fields"]["hero"]) for index in indexes
                       if rows[index]["fields"].get("hero")
                       and all(rows[index]["fields"]["hero"]))
    return readings.most_common(1)[0][0].split() if readings else None


def bucket(cards):
    if not cards or len(cards) != 2 or cards[0] == cards[1]:
        return None
    try:
        place = combo_percentile(tuple(cards))
    except (KeyError, ValueError):
        return None
    return next(label for top, label in BUCKETS if place <= top)


def plain_turn(turn, reports):
    """The plain side of a turn: its decisions, first answer, timings."""
    ready = [(index, reports[index]) for index in turn["indexes"]
             if reports[index].get("status") == "ready"]
    item = {"advice": None, "changes": 0, "decisions": 0}
    if not ready:
        waiting = [reports[index] for index in turn["indexes"]
                   if reports[index].get("status") == "reading"]
        item["missing"] = Counter(key for report in waiting
                                  for key in report.get("missing") or ())
        return item
    seen = {}
    for index, report in ready:
        key = report.get("price")
        word = json.dumps(report.get("advice"), sort_keys=True)
        if key in seen and seen[key] != word:
            item["changes"] += 1
        seen.setdefault(key, word)
    first_index, first = ready[0]
    row = first.get("plain") or {}
    item.update(decisions=len(seen), index=first_index, report=first,
                advice=act(first_row(first).get("action")),
                to=first_row(first).get("to"), rule=row.get("rule"),
                unspecified=row.get("unspecified"), missing=row.get("missing"),
                equity=row.get("equity"), need=row.get("need"),
                seconds=first.get("seconds"), defaults=row.get("defaults") or [])
    return item


def other_turn(turn, reports, rows):
    """An old path's side of a turn: its last answer and how it got there."""
    ready = [(index, reports[index]) for index in turn["indexes"]
             if reports[index].get("status") == "ready"]
    if not ready:
        return {"advice": None}
    actions = [act(first_row(report).get("action")) for _, report in ready]
    changes = sum(1 for one, two in zip(actions, actions[1:]) if one != two)
    last_index, last = ready[-1]
    first_index, _ = ready[0]
    street = turn["street"]
    item = {"advice": actions[-1], "to": first_row(last).get("to"),
            "changes": changes,
            "kind": (last.get("kind")
                     or ("preflop" if street == "preflop" else "solver")),
            "first_seconds": round((rows[first_index].get("pts_seconds") or 0.0)
                                   - turn["start"], 3),
            "rough_first": (ready[0][1].get("kind") == "rough"),
            "report": last, "index": last_index}
    return item


# -- reading the four inputs plain cannot do without -----------------------------

def _held(values, frames=MISREAD):
    """The readings held at least ``frames`` frames in a row."""
    held, run, last = set(), 0, object()
    for value in values:
        run = run + 1 if value == last else 1
        last = value
        if value is not None and run >= frames:
            held.add(value)
    return held


def reading_turn(turn, rows):
    """{field: (read within 2 s, read two ways)} for one turn."""
    fields = [rows[index]["fields"] for index in turn["indexes"]]
    times = [(rows[index].get("pts_seconds") or 0.0) - turn["start"]
             for index in turn["indexes"]]
    controls = [f.get("hero_controls") or {} for f in fields]
    values = {
        "hero_cards": [" ".join(f["hero"]) if f.get("hero") and all(f["hero"])
                       and len(f["hero"]) == 2 else None for f in fields],
        "price": [live.price(c, None) for c in controls],
        "pot": [live._amount(f.get("pot")) for f in fields],
        "stack": [live._amount((f.get("stacks") or {}).get(HERO)) for f in fields]}
    cards = live.BOARD_CARDS.get(turn["street"]) or 0
    if cards:                                       # the board this street needs
        values["board"] = [" ".join((f.get("board") or [])[:cards])
                           if len([c for c in (f.get("board") or [])[:cards] if c])
                           == cards else None for f in fields]
    result = {"board": None}
    for name, series in values.items():
        need = 3 if name == "price" else 2
        within = None
        run, last = 0, object()
        for value, at in zip(series, times):
            run = run + 1 if value == last else 1
            last = value
            if value is not None and run >= need:
                within = at
                break
        result[name] = (within is not None and within <= READ_SECONDS,
                        len(_held(series)) > 1)
    return result


def card_conflicts(states):
    """{hand_id: your cards / a board card read two ways in the hand}, as plain
    sees it (each reading held ``live.STEADY`` frames, the last hand's cards
    still on screen at the start left out): plain's ``card_conflict``."""
    found = {}
    for hand, (state, _) in states.items():
        found[hand] = {"hero_read": bool(state.hero_seen),
                       "hero_two": len(state.hero_seen) > 1,
                       "board_read": any(state.board_seen),
                       "board_two": any(len(seen) > 1 for seen in state.board_seen)}
    return found


# -- abilities -----------------------------------------------------------------

def compliance(you, size, item):
    """(followed, which way): ``looser`` when you put in more than plain says."""
    order = {"fold": 0, "check": 1, "call": 1, "raise": 2}
    advice = item["advice"]
    if you is None or advice is None:
        return None, None
    if you == advice:
        if advice == "raise" and item.get("to") and size:
            try:
                to, done = float(item["to"]), float(size)
            except (TypeError, ValueError):
                return True, None
            if to > 0 and abs(done - to) > 0.25 * to:
                return False, "looser" if done > to else "tighter"
        return True, None
    if advice == "check" and you == "fold":
        return True, None           # 能过牌时弃牌：一样不投钱
    way = "looser" if order.get(you, 1) > order.get(advice, 1) else "tighter"
    return False, way


def shown_classes(rows, states):
    """[(the v3.1 preflop class, the shown hand's place, inside the range)] for
    every opponent who showed his cards, from the hand's state as plain read it."""
    found = []
    by_hand = defaultdict(list)
    for row in rows:
        hand = (row["fields"].get("actions_v1") or {}).get("hand_id")
        if hand is not None:
            by_hand[hand].append(row)
    for hand, hand_rows in by_hand.items():
        shown = shown_cards(hand_rows)
        if not shown or hand not in states:
            continue
        state, stakes = states[hand]
        observation = _end_observation(state, hand_rows[-1]["fields"], stakes)
        if observation is None:
            continue
        try:
            table = plain_policy.Table(observation)
        except Exception:
            continue
        for seat, cards in shown.items():
            if str(seat) == HERO or seat not in table.classes:
                continue
            kind, (low, high) = plain_policy.preflop_action(table, seat)
            if kind in (None, "bomb"):
                continue
            kind = "three_bet" if kind == "all_in" else kind
            try:
                place = combo_percentile(tuple(cards))
            except (KeyError, ValueError):
                continue
            found.append((kind, place, low < place <= high))
    return found


def _end_observation(state, fields, stakes):
    """The hand at its end as plain reads it, for its preflop: a price is made
    up on the river (it never touches the preflop rows)."""
    state = copy.copy(state)
    if state.hero is None:
        state.hero = ("2c", "2d")
    if state.stack_read(live.HERO) is None:
        state.stacks = {**state.stacks, live.HERO: (Decimal(1000000), 0)}
    fields = {**fields, "street": "river",
              "hero_controls": {"visible": True, "button": "call", "call_amount": "1"}}
    try:
        observation, _, _ = live.table_observation(state, fields, stakes)
    except Exception:
        return None
    return observation


# -- one log -------------------------------------------------------------------

def log_report(name, rows, *, luck=True):
    plain_reports, cost, states = replay_plain(rows)
    old_reports = replay_old(rows)
    played = shown_reports(rows)
    actions = final_actions(rows)
    conflicts = card_conflicts(states)
    items = []
    for turn in turns(rows):
        you, size, how = you_did(turn, rows, actions)
        item = {"log": name, "hand_id": turn["hand_id"], "street": turn["street"],
                "seconds": turn["seconds"],
                "real": not lingering(turn, rows, actions),
                "you": you, "size": size, "you_read": how,
                "cards": bucket(hero_cards(rows, turn["indexes"])),
                "plain": plain_turn(turn, plain_reports),
                "old": other_turn(turn, old_reports, rows),
                "shown": other_turn(turn, played, rows),
                "reading": reading_turn(turn, rows),
                "start": turn["start"], "indexes": turn["indexes"]}
        if item["plain"]["advice"] is not None:
            item["plain"]["waited"] = round(
                (rows[item["plain"]["index"]].get("pts_seconds") or 0.0)
                - turn["start"], 3)
        items.append(item)
    for item in items:
        new, old = item["plain"]["advice"], item["old"]["advice"]
        item["changed"] = new is not None and old is not None and new != old
        item["chips"] = None
        if item["changed"] and item["real"]:
            spot = shown_spot(rows, item["indexes"], item["hand_id"])
            if spot is not None:
                observation, pot_share, _ = spot
                big_blind = float(observation.get("big_blind") or 0) or None
                values = [chips({"action": side["advice"], "to": side.get("to")},
                                observation, pot_share)
                          for side in (item["plain"], item["old"])]
                if big_blind and None not in values:
                    item["chips"] = [value / big_blind for value in values]
    hands, _ = luck_results.hand_lines(name, rows) if luck else ([], [])
    agree = defaultdict(list)
    for item in items:
        if item["real"] and item["you"]:
            agree[item["hand_id"]].append(item["you"] == item["plain"]["advice"])
    for line in hands:
        marks = agree.get(line["hand_id"])
        line["plain_agrees"] = None if not marks else all(marks)
    return {"name": name, "turns": items, "cost": cost, "hands": hands,
            "conflicts": conflicts, "classes": shown_classes(rows, states),
            "pots": pots(rows, hands)}


def pots(rows, hands):
    """{hand_id: (saw the flop, at showdown, won)} for the hands with a result,
    bomb pots left out (everyone sees their flop)."""
    by_hand = defaultdict(list)
    for row in rows:
        hand = (row["fields"].get("actions_v1") or {}).get("hand_id")
        if hand is not None:
            by_hand[hand].append(row["fields"])
    found = {}
    for line in hands:
        fields = by_hand.get(line["hand_id"]) or []
        if line.get("bomb_pot") or not fields:
            continue
        flop = any(f.get("street") in ("flop", "turn", "river")
                   and (f.get("participants") or {}).get(HERO) in ("active", "all_in")
                   for f in fields)
        end = [f for f in fields if (f.get("participants") or {}).get(HERO)
               in ("active", "all_in", "folded")]
        still_in = bool(end) and (
            (end[-1].get("participants") or {}).get(HERO) != "folded")
        shown = shown_cards([{"fields": f} for f in fields])
        others = [seat for seat in shown if str(seat) != HERO]
        found[line["hand_id"]] = (flop, bool(still_in and others), line["bb"] > 0)
    return found


# -- totals --------------------------------------------------------------------

def coverage(items, cost):
    real = [item for item in items if item["real"]]
    extra = [item for item in items if not item["real"]]
    plain_ready = [item for item in real if item["plain"]["advice"] is not None]
    iron = [item for item in plain_ready if item["plain"].get("missing")]
    missing = Counter(key for item in iron for key in item["plain"]["missing"])
    not_ready = Counter(key for item in real if item["plain"]["advice"] is None
                        for key in (item["plain"].get("missing") or {}))
    waited = [item["plain"]["waited"] for item in plain_ready
              if not item["plain"].get("missing")]
    return {
        "turns": len(real),
        "buttons_after_you_acted": len(extra),
        "plain": {
            "with_advice": len(plain_ready),
            "without": len(real) - len(plain_ready),
            "without_share": share(len(real) - len(plain_ready), len(real)),
            "without_waiting_for": dict(not_ready.most_common()),
            "iron5_unread": len(iron),
            "iron5_share": share(len(iron), len(plain_ready)),
            "iron5_missing": dict(missing.most_common()),
            "changed_within_decision": sum(item["plain"]["changes"] for item in real),
            "rough": 0,
            "button_to_ready_median": median(waited),
            "button_to_ready_p90": quantile(waited, 0.9),
            "ready_to_advice_median": median(item["plain"]["seconds"]
                                             for item in plain_ready),
            "ready_to_advice_max": max((item["plain"]["seconds"] or 0
                                        for item in plain_ready), default=None),
            "frame_ms_median": median(cost), "frame_ms_p99": quantile(cost, 0.99),
            "frame_ms_max": round(max(cost), 2) if cost else None},
        "old": _other_coverage(real, "old"),
        "shown": _other_coverage(real, "shown")}


def _other_coverage(real, side):
    ready = [item for item in real if item[side]["advice"] is not None]
    return {"with_advice": len(ready), "without": len(real) - len(ready),
            "without_share": share(len(real) - len(ready), len(real)),
            "changed_within_turn": sum(item[side]["changes"] for item in ready),
            "rough_final": sum(item[side].get("kind") == "rough" for item in ready),
            "rough_first": sum(bool(item[side].get("rough_first")) for item in ready),
            "first_advice_median": median(item[side]["first_seconds"]
                                          for item in ready)}


def preflop(items):
    real = [item for item in items if item["real"] and item["street"] == "preflop"]
    result = {"decisions": len(real)}
    for side in ("plain", "old"):
        answered = [item for item in real if item[side]["advice"] is not None]
        result[side] = {
            "answers": dict(Counter(item[side]["advice"] for item in answered)),
            "raises_by_cards": dict(Counter(item["cards"] for item in answered
                                            if item[side]["advice"] == "raise"
                                            and item["cards"])),
            "in_by_cards": dict(Counter(item["cards"] for item in answered
                                        if item[side]["advice"] in ("raise", "call")
                                        and item["cards"]))}
    result["hands_by_cards"] = dict(Counter(item["cards"] for item in real
                                            if item["cards"]))
    return result


def changed(items):
    both = [item for item in items if item["real"] and item["plain"]["advice"]
            and item["old"]["advice"]]
    moved = [item for item in both if item["changed"]]
    priced = [item for item in moved if item["chips"] is not None]
    plain_bb = sum(item["chips"][0] for item in priced)
    old_bb = sum(item["chips"][1] for item in priced)
    return {
        "decisions_both": len(both), "changed": len(moved),
        "by_street": dict(Counter(item["street"] for item in moved)),
        "by_pair": dict(Counter(f"{item['old']['advice']}→{item['plain']['advice']}"
                                for item in moved).most_common()),
        "by_rule": dict(Counter(item["plain"]["rule"] for item in moved).most_common()),
        "shown": {"priced": len(priced),
                  "plain_better": sum(item["chips"][0] > item["chips"][1] + 1e-9
                                      for item in priced),
                  "plain_worse": sum(item["chips"][0] < item["chips"][1] - 1e-9
                                     for item in priced),
                  "plain_bb": round(plain_bb, 1), "old_bb": round(old_bb, 1),
                  "difference_bb": round(plain_bb - old_bb, 1),
                  "by_street": {street: round(sum(item["chips"][0] - item["chips"][1]
                                                  for item in priced
                                                  if item["street"] == street), 1)
                                for street in ("preflop", "flop", "turn", "river")},
                  "by_rule": _by_rule(priced)}}


def _by_rule(priced):
    """Shown-card difference per page rule: decisions, worse ones, bb."""
    found = defaultdict(lambda: {"decisions": 0, "plain_worse": 0,
                                 "difference_bb": 0.0})
    for item in priced:
        line = found[item["plain"]["rule"] or "?"]
        difference = item["chips"][0] - item["chips"][1]
        line["decisions"] += 1
        line["plain_worse"] += difference < -1e-9
        line["difference_bb"] += difference
    return {rule: dict(line, difference_bb=round(line["difference_bb"], 1))
            for rule, line in sorted(found.items(),
                                     key=lambda pair: pair[1]["difference_bb"])}


def results(hands):
    if not hands:
        return {"hands": 0}
    groups = {
        "all": hands,
        "followed_shown_advice": [line for line in hands if line["followed"] == "yes"],
        "as_plain_says": [line for line in hands if line.get("plain_agrees") is True],
        "not_as_plain_says": [line for line in hands
                              if line.get("plain_agrees") is False]}
    return {name: luck_results.part(lines) for name, lines in groups.items()}


def rules(items):
    decided = [item for item in items if item["real"]
               and item["plain"]["advice"] is not None]
    followed = Counter(item["plain"]["rule"] for item in decided
                       if item["you"] == item["plain"]["advice"])
    hits = Counter(item["plain"]["rule"] for item in decided)
    return {"hits": {rule: {"hits": count, "you_did_it": followed.get(rule, 0)}
                     for rule, count in hits.most_common()},
            "unspecified": dict(Counter(item["plain"]["unspecified"] for item in decided
                                        if item["plain"]["unspecified"]).most_common())}


def reading(items, conflicts):
    real = [item for item in items if item["real"]]
    fields = ("hero_cards", "price", "pot", "stack", "board")
    result = {"turns": len(real)}
    for name in fields:
        found = [item["reading"][name] for item in real
                 if item["reading"].get(name) is not None]
        result[name] = {"turns": len(found),
                        "within_2s": share(sum(one[0] for one in found), len(found)),
                        "read_two_ways": sum(one[1] for one in found)}
    hero = [one for one in conflicts.values() if one["hero_read"]]
    board = [one for one in conflicts.values() if one["board_read"]]
    result["hands_hero_two_ways"] = {"hands": len(hero),
                                     "two_ways": sum(o["hero_two"] for o in hero)}
    result["hands_board_two_ways"] = {"hands": len(board),
                                      "two_ways": sum(o["board_two"] for o in board)}
    for name, part in (("hero_cards", result["hands_hero_two_ways"]),
                       ("board", result["hands_board_two_ways"])):
        result.setdefault(name, {})["right_by_hand"] = share(
            part["hands"] - part["two_ways"], part["hands"])
    for name in ("price", "pot", "stack"):
        result[name]["right_by_turn"] = share(
            result[name]["turns"] - result[name]["read_two_ways"],
            result[name]["turns"])
    return result


def enough(count, key):
    return "够" if count >= ENOUGH[key] else "不够"


def abilities(items, pots_found, classes):
    real = [item for item in items if item["real"] and item["plain"]["advice"]
            and not item["plain"].get("missing")]
    marks = [compliance(item["you"], item["size"], item["plain"]) for item in real]
    marks = [mark for mark in marks if mark[0] is not None]
    old_marks = [compliance(item["you"], item["size"], item["shown"]) for item in items
                 if item["real"] and item["shown"]["advice"]]
    old_marks = [mark for mark in old_marks if mark[0] is not None]
    iron = [item for item in real if item["plain"]["rule"] in IRON]
    hands = [one for one in pots_found.values()]
    flops = [one for one in hands if one[0]]
    showdowns = [one for one in hands if one[1]]
    bands = defaultdict(list)
    for item in real:
        hand = pots_found.get((item["log"], item["hand_id"]))
        equity = item["plain"].get("equity")
        if (hand and hand[1] and equity is not None
                and item["you"] == item["plain"]["advice"]):
            top = next(top for top in EQUITY_BUCKETS if equity < top)
            bands[top].append((equity, hand[2]))
    by_class = {}
    for kind in CLASSES:
        found = [(place, inside) for name, place, inside in classes if name == kind]
        by_class[CLASS_WORD[kind]] = {
            "shown": len(found),
            "mean_place": (round(sum(p for p, _ in found) / len(found), 3)
                           if found else None),
            "outside_range": share(sum(not inside for _, inside in found), len(found)),
            "sample": enough(len(found), "shown_class")}
    return {
        "compliance": {"decisions": len(marks),
                       "rate": share(sum(m[0] for m in marks), len(marks)),
                       "looser": sum(m[1] == "looser" for m in marks),
                       "tighter": sum(m[1] == "tighter" for m in marks),
                       "sample": enough(len(marks), "compliance"),
                       "old_shown_rate": share(sum(m[0] for m in old_marks),
                                               len(old_marks))},
        "iron_rules": {"triggered": len(iron),
                       "you_did_otherwise": sum(item["you"] != item["plain"]["advice"]
                                                for item in iron),
                       "by_rule": dict(Counter(item["plain"]["rule"]
                                               for item in iron).most_common())},
        "pot_won_after_flop": {"flops": len(flops),
                               "rate": share(sum(o[2] for o in flops), len(flops)),
                               "target": TARGETS["pot_won"],
                               "sample": enough(len(flops), "flops")},
        "showdown_won": {"showdowns": len(showdowns),
                         "rate": share(sum(o[2] for o in showdowns), len(showdowns)),
                         "target": TARGETS["showdown_won"],
                         "sample": enough(len(showdowns), "showdowns")},
        "range_by_class": by_class,
        "equity_at_showdown": {
            f"{low:.0%}–{min(top, 1.0):.0%}": {
                "decisions": len(bands[top]),
                "mean_equity": (round(sum(e for e, _ in bands[top])
                                      / len(bands[top]), 3) if bands[top] else None),
                "won": share(sum(won for _, won in bands[top]), len(bands[top])),
                "sample": enough(len(bands[top]), "equity_bucket")}
            for low, top in zip((0.0,) + EQUITY_BUCKETS, EQUITY_BUCKETS)}}


def summarize(reports):
    items = [item for report in reports for item in report["turns"]]
    cost = [value for report in reports for value in report["cost"]]
    hands = [line for report in reports for line in report["hands"]]
    conflicts = {(report["name"], hand): value for report in reports
                 for hand, value in report["conflicts"].items()}
    classes = [one for report in reports for one in report["classes"]]
    pots_found = {(report["name"], hand): one for report in reports
                  for hand, one in report["pots"].items()}
    return {"logs": [report["name"] for report in reports],
            "coverage": coverage(items, cost), "preflop": preflop(items),
            "changed": changed(items), "results": results(hands),
            "rules": rules(items), "reading": reading(items, conflicts),
            "abilities": abilities(items, pots_found, classes)}


def _pct(value):
    return "—" if value is None else f"{value:.0%}"


def _num(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


ACT_WORD = {"fold": "弃", "check": "过牌", "call": "跟", "raise": "加注"}


def _pair_words(pair):
    old, new = pair.split("→")
    return f"{ACT_WORD.get(old, old)}→{ACT_WORD.get(new, new)}"


def _ci(part):
    pair = part.get("adjusted_ci95")
    return "—" if not pair else f"{pair[0]:+g} 到 {pair[1]:+g}"


def sheet(summary, who=""):
    """The summary in plain lines (Chinese), for the report to 主人."""
    cover = summary["coverage"]
    plain, old, shown = cover["plain"], cover["old"], cover["shown"]
    turns = cover["turns"]
    lines = [f"{who}{len(summary['logs'])} 段，轮到你 {turns} 次"
             f"（另有 {cover['buttons_after_you_acted']} 次是你动完后按钮还挂着，不算）"]
    lines.append(
        f"覆盖：一页纸 {plain['with_advice']}/{turns} 有建议（没有 {plain['without']} 次，"
        f"{_pct(plain['without_share'])}）；旧策略重放 {old['with_advice']}/{turns}；"
        f"当时窗口 {shown['with_advice']}/{turns}")
    lines.append(
        f"改口：一页纸 {plain['changed_within_decision']} 次；旧策略 "
        f"{old['changed_within_turn']} 次、当时窗口 {shown['changed_within_turn']} 次。"
        f"粗略：一页纸没有这一类；当时窗口最后还是粗略的 {shown['rough_final']} 次")
    missing = "、".join(f"{live.MISSING.get(key, key)} {count}"
                       for key, count in plain["iron5_missing"].items())
    lines.append(f"铁律 5（画面 2 秒没读稳）：{plain['iron5_unread']} 次，"
                 f"占有建议的 {_pct(plain['iron5_share'])}"
                 + (f"；缺：{missing}" if missing else ""))
    lines.append(
        f"速度：按钮出现到就绪中位 {_num(plain['button_to_ready_median'])} 秒"
        f"（九成 {_num(plain['button_to_ready_p90'])} 秒）；就绪到出建议中位 "
        f"{_num(plain['ready_to_advice_median'], 3)} 秒、最长 "
        f"{_num(plain['ready_to_advice_max'], 3)} 秒；每帧多花中位 "
        f"{_num(plain['frame_ms_median'], 2)} 毫秒、百分之一的帧超过 "
        f"{_num(plain['frame_ms_p99'], 1)} 毫秒")
    pre = summary["preflop"]
    raises = {side: pre[side]["answers"].get("raise", 0) for side in ("plain", "old")}
    ins = {side: (pre[side]["answers"].get("raise", 0)
                  + pre[side]["answers"].get("call", 0)) for side in ("plain", "old")}
    by = "；".join(f"{label} {pre['plain']['raises_by_cards'].get(label, 0)}/"
                  f"{pre['old']['raises_by_cards'].get(label, 0)}"
                  f"（共 {pre['hands_by_cards'].get(label, 0)} 手）"
                  for _, label in BUCKETS)
    lines.append(f"翻前 {pre['decisions']} 个决策：加注 一页纸 {raises['plain']} 次、"
                 f"旧 {raises['old']} 次；入池（加注或跟）一页纸 {ins['plain']}、旧 "
                 f"{ins['old']}。按牌力（一页纸/旧 加注次数）：{by}")
    moved = summary["changed"]
    streets = "、".join(f"{plain_policy.STREET_WORD.get(key, key)} {count}"
                       for key, count in moved["by_street"].items())
    pairs = "、".join(f"{_pair_words(pair)} {count}" for pair, count in
                     list(moved["by_pair"].items())[:5])
    lines.append(f"建议变了：{moved['changed']}/{moved['decisions_both']} 个决策"
                 f"（{streets}）；旧→一页纸最多的：{pairs}")
    priced = moved["shown"]
    lines.append(f"按亮牌算（变了的决策里对手都亮了牌的 {priced['priced']} 个）：一页纸 "
                 f"{priced['plain_bb']:+g}、旧 {priced['old_bb']:+g} 个大盲，差 "
                 f"{priced['difference_bb']:+g}（一页纸好 {priced['plain_better']} 个、差 "
                 f"{priced['plain_worse']} 个）")
    result = summary["results"]
    if result.get("all", {}).get("hands"):
        parts = []
        for key, label in (("all", "全部"), ("followed_shown_advice", "照当时窗口打的"),
                           ("as_plain_says", "你做的和一页纸一样的"),
                           ("not_as_plain_says", "和一页纸不一样的")):
            part = result[key]
            if part.get("hands"):
                parts.append(f"{label} {part['hands']} 手 "
                             f"{part['adjusted_bb_per_100']:+g}（{_ci(part)}）")
        lines.append("扣运气的成绩（bb/100，随时看都算数的 95% 区间）："
                     + "；".join(parts)
                     + "。是你自己选的怎么打，只作参考")
    read = summary["reading"]
    lines.append(
        f"识别（{read['turns']} 次轮到你）：手牌 2 秒内读到 "
        f"{_pct(read['hero_cards']['within_2s'])}，同一手读出两种 "
        f"{read['hands_hero_two_ways']['two_ways']}/"
        f"{read['hands_hero_two_ways']['hands']} 手；公共牌 2 秒内读到 "
        f"{_pct(read['board']['within_2s'])}（翻后 {read['board']['turns']} 次），"
        f"读出两种 {read['hands_board_two_ways']['two_ways']}/"
        f"{read['hands_board_two_ways']['hands']} 手；要跟的金额 2 秒内读到 "
        f"{_pct(read['price']['within_2s'])}；底池 {_pct(read['pot']['within_2s'])}；"
        f"你的筹码 {_pct(read['stack']['within_2s'])}")
    ability = summary["abilities"]
    comp = ability["compliance"]
    iron = ability["iron_rules"]
    won, sd = ability["pot_won_after_flop"], ability["showdown_won"]
    lines.append(
        f"能力（这些场是照旧建议打的，只当起点）：遵从率 {_pct(comp['rate'])}"
        f"（{comp['decisions']} 个决策，{comp['sample']}；偏松 {comp['looser']}、偏紧 "
        f"{comp['tighter']}；对当时窗口 {_pct(comp['old_shown_rate'])}）；铁律定的 "
        f"{iron['triggered']} 次里没照做 {iron['you_did_otherwise']} 次；翻后拿底池 "
        f"{_pct(won['rate'])}（{won['flops']} 次看翻牌，目标 ≥ 39%，{won['sample']}）；"
        f"摊牌赢 {_pct(sd['rate'])}（{sd['showdowns']} 次，目标 ≥ 56%，{sd['sample']}）")
    classes = "；".join(
        f"{name} {item['shown']} 次" + (
            f"、平均在前 {item['mean_place']:.0%}、范围外 {_pct(item['outside_range'])}"
            if item["shown"] else "")
        for name, item in ability["range_by_class"].items())
    lines.append(f"范围校准（亮牌，每类要 ≥ 100 次）：{classes}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", default=[],
                        help="a frames.jsonl (or .jsonl.gz); repeatable")
    parser.add_argument("--name", action="append", default=[],
                        help="主人=<log>,<log> or 杜=<log>,...: whose logs these are")
    parser.add_argument("--no-luck", action="store_true",
                        help="skip the results with the luck out (faster)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if not args.frames:
        parser.error("give --frames")
    owner = {}
    for item in args.name:
        who, _, names = item.partition("=")
        owner.update({name: who for name in names.split(",") if name})
    reports, groups = [], defaultdict(list)
    for path in args.frames:
        name = log_name(path)
        started = time.time()
        report = log_report(name, load(path), luck=not args.no_luck)
        who = owner.get(name) or ("杜" if name.startswith("du") else "主人")
        reports.append(report)
        groups[who].append(report)
        print(f"{name} ({who}): {len(report['turns'])} turns, "
              f"{time.time() - started:.0f} s", file=sys.stderr)
    summary = {"schema_version": 1,
               "by_log": {report["name"]: summarize([report]) for report in reports},
               "by_who": {who: summarize(group) for who, group in groups.items()},
               "all": summarize(reports)}
    if args.out:
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    for who, part in summary["by_who"].items():
        print("\n".join(sheet(part, f"{who}：")), end="\n\n")
    if len(summary["by_who"]) > 1:
        print("\n".join(sheet(summary["all"], "合计：")))


if __name__ == "__main__":
    main()
