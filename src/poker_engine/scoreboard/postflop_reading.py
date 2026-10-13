"""How a seat's postflop actions narrow its range, for reading it.

After the flop the population model (``population.PopulationBot``) plays by
equity thresholds: it bets above one, checks below it; facing a bet it
raises above one, calls above another and folds the rest. Reading a player
with it as a veto (``solver_bot.kept``) throws out, at each action, every
hand the model would have played otherwise: a check leaves no hand the model
bets, a bet no hand it checks. Real players slow-play and bluff. Of the
opponents who showed their cards at the end of a hand in fourteen recordings
of 2026-10, the reading had thrown out the hand shown for most of those who
reached the river, and the six who only checked and called with two pair or
better were all thrown out; the AI then saw near-certain wins and bet big
into them.

The reading here keeps, at each postflop action, the hands the model plays
otherwise with a weight instead of 0 (as ``preflop_reading`` does before the
flop):

* ``slow``: at a check or a call, the hands the model would bet or raise;
* ``loose``: at a call, the hands the model would fold;
* ``bluff``: at a bet or a raise, the hands the model would check or fold.

The weights are per street (``WEIGHTS``) and were fitted to the shown hands
(``tools/aa_postflop_reading_weights.py``), not to the scoreboard, whose
players play exactly as the model. A seat whose reads show it bets clearly
more than the model keeps, as before, at least its floor
(``ranges.floor``) of every hand.
"""

from __future__ import annotations

from .replay import kind_of, with_hole

STREETS = ("flop", "turn", "river")
KINDS = ("slow", "loose", "bluff")
# {kind: (flop, turn, river)}, from the shown hands (see the module notes).
WEIGHTS = {"slow": (0.7, 0.7, 0.5), "loose": (0.2, 0.5, 0.2),
           "bluff": (0.2, 0.4, 0.3)}
VETO = {kind: (0.0, 0.0, 0.0) for kind in KINDS}
# Hands left below this share of the range's largest weight are dropped (the
# share at which ``exclusion`` counts a hand as out): they barely move an
# equity, and every hand kept is asked about again at each later action.
PRUNE = 0.001


def otherwise(taken, model_kind):
    """None when the model plays a hand as the seat did, else which kind of
    hand the seat played otherwise than the model."""
    if model_kind == taken:
        return None
    if taken == "c":
        return "slow" if model_kind == "r" else "loose"
    return "bluff"


def weights_of(model):
    """The weights ``model`` reads postflop actions with: its own
    ``postflop_reading`` if it has one, else ``WEIGHTS``."""
    return getattr(model, "postflop_reading", None) or WEIGHTS


def key_of(weights):
    """The weights as a hashable value, for cache keys."""
    return tuple(tuple(weights[kind]) for kind in KINDS)


def soft_kept(weights, decision, decide, reading=None):
    """``weights`` after ``decision`` read without veto: a hand ``decide``
    plays as the seat did keeps its weight, any other hand the share
    ``reading`` gives its kind on this street (``WEIGHTS`` by default);
    hands left at ``PRUNE`` of the largest weight or less are dropped."""
    reading = WEIGHTS if reading is None else reading
    street = STREETS.index(decision.street)
    taken = decision.kind
    result = {}
    for key, weight in weights.items():
        choice = decide(with_hole(decision.observation, (key[:2], key[2:])))
        model_kind = (max(choice, key=choice.get) if isinstance(choice, dict)
                      else kind_of(choice))
        kind = otherwise(taken, model_kind)
        share = 1.0 if kind is None else reading[kind][street]
        if share:
            result[key] = weight * share
    top = max(result.values(), default=0.0)
    return {key: weight for key, weight in result.items() if weight > PRUNE * top}


__all__ = ["KINDS", "PRUNE", "STREETS", "VETO", "WEIGHTS", "key_of", "otherwise",
           "soft_kept", "weights_of"]
