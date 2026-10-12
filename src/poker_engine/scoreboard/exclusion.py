"""Was an opponent's real hand still in the range the AI read for him?

The AI reads each opponent's range by veto (``ranges.opponent_ranges``,
which keeps at every action the hands the population model plays that way,
``solver_bot.kept``): a hand the model would have played differently drops
to weight 0 (to a floor for a seat whose reads show it bets more than the
model), and stays out for the rest of the hand. A real player who slow-plays
or calls down with a big hand once is read without the hand he holds. When
he shows his cards, whether they were still in the range says how often the
reading throws the truth away.

``exclusion_trace`` replays the reading of one shown seat with the code the
advice uses and records, after each of that seat's actions, the weight of
the hand it really held (relative to the range's largest weight). The hand
counts as excluded once that weight is at most ``EXCLUDED``. ``summarize``
turns traces into rates:

* ``all``: every shown hand;
* ``narrowed``: the hands whose range the reading cut at all (fewer hands
  above ``EXCLUDED`` than the board leaves);
* ``river``: the hands whose betting reached the river;
* ``you_in``: the hands where the observer (you) was still in at the end;
* ``by_street``: of the hands whose betting reached a street, the share
  whose real hand was out by the end of that street (a bomb pot, with no
  betting before the flop, counts as reaching the flop with nothing out);
* ``first``: where the excluded hands went out, as "street action".

``before_end`` leaves out the action that ended the hand (the last call at
a showdown): the reading as it stood when advice could last be asked for.

The same functions measure recordings (``tools/aa_range_exclusion.py``,
from the window's frame logs and the cards shown) and the scoreboard
(``runner.run_scoreboard(exclusion=...)``, where every hand's cards are
known; ``showdown_traces``). A change to the reading is judged by the rates
before and after on the same hands: ``compare``, or ``read`` to pass a
reading function under test.

Every reading here keeps its own cache: the one ``opponent_ranges`` shares
in a process is left as it was, so measuring never changes what a strategy
decides afterwards.
"""

from __future__ import annotations

import math

from poker_engine.solver.texassolver import all_combos, combo_key

from .population import PopulationBot
from .ranges import opponent_ranges
from .reads import Unread

EXCLUDED = 0.001            # relative weight at or below which a hand is out
STREETS = ("preflop", "flop", "turn", "river")
CATEGORIES = ("all", "narrowed", "river", "you_in")
Z = 1.96


def action_word(decision):
    """fold, check, call, bet or raise for an action of ``replay.public_replay``."""
    kind = decision.kind
    to_call = float(decision.observation["to_call"] or 0)
    if kind == "f":
        return "fold"
    if kind == "c":
        return "call" if to_call else "check"
    if decision.street != "preflop" and not to_call:
        return "bet"
    return "raise"


def reading_model(policy):
    """(model, sees reads) a strategy reads its opponents with: the
    ``model`` that ``range_multiway`` and the solver strategies keep, else
    the population model its base policy expects; no reads behind
    ``noreads+``."""
    sees = True
    while policy is not None:
        sees = sees and not isinstance(policy, Unread)
        model = getattr(policy, "model", None)
        if model is not None:
            return model, sees
        if hasattr(policy, "adjusted"):
            return PopulationBot(adjusted=policy.adjusted), sees
        policy = getattr(policy, "base", None)
    return PopulationBot(), sees


def exclusion_trace(observation, seat, cards, model, *, read=None,
                    threshold=EXCLUDED):
    """How the reading of ``seat`` treated the hand it really held.

    ``observation``: the hand as the AI sees it, from any seat but
    ``seat`` (terminal or not; its ``reads`` are used as the advice uses
    them). ``cards``: the two cards ``seat`` showed. ``read``: the reading
    function (default ``ranges.opponent_ranges``; one under test takes the
    same arguments).

    Returns a dict that JSON keeps: ``steps`` has, for each of the seat's
    actions, its place in the history (``index``), ``street``, ``action``,
    the real hand's relative ``weight``, the ``hands`` left above
    ``threshold``, whether the hand was ``excluded`` by then and whether the
    action ``ends_hand``; ``street`` is the hand's last betting street and
    ``combos`` the hands the board leaves.
    """
    read = read or opponent_ranges
    if seat == observation["observing_seat"]:
        raise ValueError("the observer's own hand is not read")
    if seat in observation["folded"]:
        raise ValueError(f"seat {seat} folded: its range is not read")
    board = tuple(observation["board"])
    key = combo_key(cards)
    if key[:2] in board or key[2:] in board or key[:2] == key[2:]:
        raise ValueError(f"cards {cards} do not fit the board {list(board)}")
    history = observation["public_history"]
    last = len(history) - 1 if observation.get("terminal") else None
    steps = []

    def record(decision, weights):
        if decision.seat != seat:
            return
        top = max(weights.values(), default=0.0)
        weight = weights.get(key, 0.0) / top if top > 0 else 0.0
        index = decision.action.get("index", len(steps))
        left = sum(value > threshold * top for value in weights.values())
        steps.append({"index": index, "street": decision.street,
                      "action": action_word(decision), "weight": round(weight, 6),
                      "hands": left, "excluded": weight <= threshold,
                      "ends_hand": index == last})

    read(observation, model, cache={}, trace=record)
    street = (history[-1]["street"] if observation.get("terminal") and history
              else observation["street"])
    return {"seat": seat, "cards": list(cards), "street": street,
            "combos": len(all_combos(board)),
            "you_in": observation["observing_seat"] not in observation["folded"],
            "steps": steps}


def outcome(trace, before_end=False):
    """(excluded, narrowed, first step that excluded it or None) of a trace."""
    steps = [step for step in trace["steps"]
             if not (before_end and step["ends_hand"])]
    first = next((step for step in steps if step["excluded"]), None)
    narrowed = bool(steps) and min(step["hands"] for step in steps) < trace["combos"]
    return first is not None, narrowed, first


def interval(hits, total):
    """95% Wilson interval of a share."""
    if not total:
        return None
    share, z2 = hits / total, Z * Z
    centre = (share + z2 / (2 * total)) / (1 + z2 / total)
    half = Z * math.sqrt(share * (1 - share) / total + z2 / (4 * total * total)) / (
        1 + z2 / total)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rate(hits, total):
    return {"hands": total, "excluded": hits,
            "rate": round(hits / total, 3) if total else None,
            "ci95": interval(hits, total)}


def summarize(traces, *, before_end=False):
    """Exclusion rates of ``traces`` (see the module notes)."""
    counts = {name: [0, 0] for name in CATEGORIES}
    streets = {street: [0, 0] for street in STREETS}
    first = {}
    for trace in traces:
        excluded, narrowed, step = outcome(trace, before_end)
        member = {"all": True, "narrowed": narrowed,
                  "river": trace["street"] == "river", "you_in": trace["you_in"]}
        for name in CATEGORIES:
            if member[name]:
                counts[name][0] += excluded
                counts[name][1] += 1
        reached = STREETS.index(trace["street"]) if trace["street"] in STREETS else 3
        out = STREETS.index(step["street"]) if step else None
        for at, street in enumerate(STREETS[:reached + 1]):
            streets[street][1] += 1
            streets[street][0] += out is not None and out <= at
        if step:
            label = f"{step['street']} {step['action']}"
            first[label] = first.get(label, 0) + 1
    return {**{name: rate(*counts[name]) for name in CATEGORIES},
            "by_street": {street: rate(*streets[street]) for street in STREETS},
            "first": dict(sorted(first.items(), key=lambda item: (-item[1], item[0]))),
            "before_end": before_end}


def compare(before, after, *, before_end=False):
    """Two readings of the same hands (traces in the same order): the rates of
    each and the hands one kept that the other excluded."""
    if len(before) != len(after):
        raise ValueError("compare needs the same hands read both ways")
    kept_now = excluded_now = 0
    for one, two in zip(before, after):
        was, _, _ = outcome(one, before_end)
        now, _, _ = outcome(two, before_end)
        kept_now += was and not now
        excluded_now += now and not was
    first, second = (summarize(traces, before_end=before_end)
                     for traces in (before, after))
    change = {name: None if first[name]["rate"] is None else
              round(second[name]["rate"] - first[name]["rate"], 3)
              for name in CATEGORIES}
    return {"before": first, "after": second, "change": change,
            "kept_now": kept_now, "excluded_now": excluded_now}


def measured_seats(seed, seats, count):
    """The ``count`` hero seats of a deal whose hands are measured on the
    scoreboard: a different first seat each deal."""
    start = seed % len(seats)
    return {seats[(start + offset) % len(seats)]
            for offset in range(min(count, len(seats)))}


def brief(trace, **where):
    """A trace in one line: where it was, the cards, the hand's last street
    and the action that first excluded the real hand (whole hand, and
    ``before_end``), None when it stayed in."""
    def label(step):
        return None if step is None else f"{step['street']} {step['action']}"

    _, narrowed, out = outcome(trace)
    *_, out_before_end = outcome(trace, before_end=True)
    return {**where, "seat": trace["seat"], "cards": " ".join(trace["cards"]),
            "street": trace["street"], "narrowed": narrowed, "out": label(out),
            "out_before_end": label(out_before_end)}


def showdown_traces(arena, observer, model, reads=None):
    """``exclusion_trace`` of every seat but ``observer`` still in at the end
    of a finished scoreboard hand (two or more seats left), whose cards are
    known there."""
    observation = arena.observe(observer)
    live = [seat for seat in observation["occupied_seats"]
            if seat not in observation["folded"]]
    if len(live) < 2:
        return []
    if reads is not None:
        observation["reads"] = reads
    return [exclusion_trace(observation, seat, arena.observe(seat)["own_hole"], model)
            for seat in live if seat != observer]


__all__ = ["CATEGORIES", "EXCLUDED", "STREETS", "action_word", "brief", "compare",
           "exclusion_trace", "interval", "measured_seats", "outcome", "reading_model",
           "showdown_traces", "summarize"]
