"""How much a scoreboard opponent plays like the real AA players.

The scoreboard can only tell how a strategy fares against AA players as far as
its opponents play like them. This measures that on recordings: each hand of a
frame log that replays on the AA table (``tools/sim_fidelity.py``) is put to an
opponent model seat by seat. The seat is read the way the AI reads a range
(``ranges``), but with the opponent model itself, as the scoreboard plays it:

* the seat could hold any two cards the board and your own cards leave;
* at each of its actions the model plays every one of those hands: the share
  of the seat's weight on the hands that take each action is the model's
  forecast for that decision; each hand's weight is then multiplied by how
  often the model takes the action the seat really took (a model that mixes,
  as ``noisy``, keeps part of a hand);
* when the seat showed its cards at the end, the share of its final weight on
  those cards says how well the model's play explains them.

Two scores, both log losses in nats (lower is better):

* ``actions``: minus the log of the forecast probability of the action the
  seat took, per decision;
* ``cards``: minus the log of the shown hand's share of the final range,
  relative to a random hand (0: the model's play says nothing about the cards;
  below 0: it narrowed the range around them; above 0: it pushed them out).

Together they are the log likelihood of what the recordings show under the
model: what the players did and the cards they showed (a seat shows because
of the betting, so showing adds no selection; the few losers who muck at the
showdown are left out). A model that never takes an action a real player
took would give it probability 0: every forecast is mixed with ``FLOOR`` of
a uniform guess over the seat's options, so such a miss costs a large but
finite score and is counted (``impossible``); the seat's weights then stay
as they were, as the range reading does.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math

from poker_engine.solver.texassolver import all_combos, combo_key

from .bots import _rng
from .replay import kind_of, public_replay, with_hole
from .spots import KINDS, postflop_spot, preflop_spot

FLOOR = 0.02            # share of a uniform guess in every forecast
EXCLUDED = 0.001        # relative weight at or below which a hand is out
SALT = "fidelity"
KIND_NAMES = ("f", "c", "r")
# Price buckets: the call as a share of the pot after calling (what a call
# needs to win). A bet of a third of the pot asks 20%, three quarters 30%,
# twice the pot 40%.
PRICE_EDGES = (0.2, 0.3, 0.4)
PRICE_NAMES = ("small", "medium", "large", "huge")


def chances(model, observation, rng):
    """{kind: probability} of the model's action with the observation's hand:
    ``model.distribution`` when it mixes, else its one decision."""
    mix = getattr(model, "distribution", None)
    if mix is not None:
        return mix(observation, rng)
    return {kind_of(model.decide(observation, rng)): 1.0}


def options(observation):
    """The kinds of action open to the seat: fold only facing a bet, raise
    only when the table allows one."""
    facing = float(observation["to_call"] or 0) > 0
    can_raise = any(action["kind"] == "raise_to"
                    for action in observation["legal_actions"])
    return tuple(kind for kind, open_ in zip(KIND_NAMES, (facing, True, can_raise))
                 if open_)


def floored(forecast, kinds):
    """``forecast`` mixed with ``FLOOR`` of a uniform guess over ``kinds``."""
    return {kind: (1 - FLOOR) * forecast.get(kind, 0.0) + FLOOR / len(kinds)
            for kind in kinds}


def price_bucket(price):
    for edge, name in zip(PRICE_EDGES, PRICE_NAMES):
        if price < edge:
            return name
    return PRICE_NAMES[-1]


def features(decision):
    """What kind of decision this was, for the tables of ``summarize``."""
    observation = decision.observation
    seat, street = decision.seat, decision.street
    to_call = float(observation["to_call"] or 0)
    pot = float(observation["pot"])
    stack = float(observation["stacks"][str(seat)])
    found = {"street": street, "facing": to_call > 0,
             "price": round(to_call / (pot + to_call), 4) if to_call else 0.0,
             "all_in": bool(to_call) and to_call >= stack,
             "spr": round(stack / pot, 2) if pot else None,
             "bomb": observation.get("bomb_pot") is not None}
    if street == "preflop":
        found["spot"] = preflop_spot([(row["actor"], KINDS[row["kind"]])
                                      for row in observation["public_history"]], seat)
        return found
    rows = observation["public_history"]
    aggressor = None
    for row in rows:
        if row["street"] == "preflop" and row["kind"] == "raise_to":
            aggressor = row["actor"]
    now = [(row["actor"], KINDS[row["kind"]])
           for row in rows if row["street"] == street]
    opponents = len(observation["occupied_seats"]) - len(observation["folded"]) - 1
    found["spot"] = postflop_spot(street, now, seat, opponents, aggressor)
    return found


def score_hand(observation, model, *, skip=(), shown=None, dead=(), salt=SALT):
    """(decisions, cards) records of one replayed hand under ``model``.

    ``observation``: the hand from any seat (``public_replay`` takes it to the
    end of its history). ``skip``: seats whose decisions are not scored (your
    own seat; seats with an action filled in by the replay on that street,
    given as (seat, street)). ``shown``: {seat: two cards} shown at the end.
    ``dead``: cards known not to be in any opponent's hand (your own).
    """
    shown = shown or {}
    dead = set(dead)
    every = [key for key in all_combos()
             if key[:2] not in dead and key[2:] not in dead]
    weights = {}
    decisions, cards = [], []
    for decision in public_replay(observation):
        seat = decision.seat
        if seat in skip:
            continue
        board = set(decision.observation["board"])
        before = weights.get(seat)
        if before is None:
            before = dict.fromkeys(every, 1.0)
        live = _live(before, board) or _live(dict.fromkeys(every, 1.0), board)
        total = sum(live.values())
        forecast = dict.fromkeys(KIND_NAMES, 0.0)
        after = {}
        for key, weight in live.items():
            hole = with_hole(decision.observation, (key[:2], key[2:]))
            probs = chances(model, hole, _rng(salt, hole))
            for kind, share in probs.items():
                forecast[kind] += weight * share
            share = probs.get(decision.kind, 0.0)
            if share:
                after[key] = weight * share
        forecast = {kind: value / total for kind, value in forecast.items()}
        kinds = options(decision.observation)
        mixed = floored(forecast, kinds)
        if (seat, decision.street) not in skip:
            decisions.append({
                **features(decision), "seat": seat, "action": decision.kind,
                "forecast": {kind: round(value, 4) for kind, value in forecast.items()},
                "loss": -math.log(mixed[decision.kind]),
                "impossible": forecast[decision.kind] == 0.0})
        weights[seat] = after if after else live
    board = set(observation["board"])
    for seat, held in sorted(shown.items()):
        final = weights.get(seat)
        key = combo_key(held)
        if final is None or key[:2] in board or key[2:] in board:
            continue
        if key[:2] in dead or key[2:] in dead:
            continue
        live = _live(final, board) or _live(dict.fromkeys(every, 1.0), board)
        total, top = sum(live.values()), max(live.values())
        share = live.get(key, 0.0) / total
        count = sum(1 for other in every
                    if other[:2] not in board and other[2:] not in board)
        mixed = (1 - FLOOR) * share + FLOOR / count
        cards.append({"seat": seat, "street": observation["street"],
                      "loss": -math.log(mixed * count),
                      "excluded": live.get(key, 0.0) <= EXCLUDED * top,
                      "combos": count})
    return decisions, cards


def _live(weights, board):
    """The weights of the hands the board leaves; a seat whose range the
    board has emptied starts again from every hand (``score_hand``)."""
    return {key: weight for key, weight in weights.items()
            if weight > 0 and key[:2] not in board and key[2:] not in board}


def cells(record):
    """The table rows a decision record counts in (``summarize``)."""
    street = record["street"]
    if street == "preflop":
        spot = record["spot"]
        group = {"rfi": "first_in", "vs_limp": "after_limpers",
                 "vs_open": "facing_raise"}.get(spot, "reraised")
        return ["preflop", f"preflop|{group}"]
    width, _, facing = record["spot"].split("|")[1:]
    rows = ["postflop", street, f"{street}|{width}|{facing}", f"{width}|{facing}"]
    if facing != "checked_to":
        rows.append(f"facing|{width}|{price_bucket(record['price'])}")
        rows.append(f"facing|{price_bucket(record['price'])}")
        if record["all_in"]:
            rows.append("facing|all_in")
    return rows


def summarize(decisions, cards=()):
    """Per table row: count, real shares, the model's mean forecast, mean log
    loss and how many real actions the model never takes; and the cards.

    ``guess`` is the loss of a forecast that knows only the row's real shares
    (their entropy): a model whose loss is not below it says nothing about
    which hands take which action there, and one above it misleads."""
    rows = defaultdict(lambda: {"n": 0, "loss": 0.0, "impossible": 0,
                                "real": Counter(), "model": Counter()})
    for record in decisions:
        for name in ["all", *cells(record)]:
            row = rows[name]
            row["n"] += 1
            row["loss"] += record["loss"]
            row["impossible"] += record["impossible"]
            row["real"][record["action"]] += 1
            for kind, value in record["forecast"].items():
                row["model"][kind] += value
    table = {}
    for name, row in sorted(rows.items()):
        n = row["n"]
        real = [row["real"][kind] / n for kind in KIND_NAMES]
        table[name] = {"n": n, "loss": round(row["loss"] / n, 4),
                       "guess": round(-sum(p * math.log(p) for p in real if p), 4),
                       "impossible": row["impossible"],
                       "real": {kind: round(share, 3)
                                for kind, share in zip(KIND_NAMES, real)},
                       "model": {kind: round(row["model"][kind] / n, 3)
                                 for kind in KIND_NAMES}}
    shown = list(cards)
    summary = {"decisions": table}
    if shown:
        summary["cards"] = {
            "n": len(shown),
            "loss": round(sum(item["loss"] for item in shown) / len(shown), 4),
            "excluded": sum(item["excluded"] for item in shown)}
    return summary


__all__ = ["EXCLUDED", "FLOOR", "PRICE_NAMES", "cells", "chances", "features",
           "floored", "options", "price_bucket", "score_hand", "summarize"]
