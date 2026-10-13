"""How a seat's postflop actions narrow its range, for reading it.

After the flop the population model (``population.PopulationBot``) plays by
equity thresholds: it bets above one, checks below it; facing a bet it
raises above one, calls above another and folds the rest. Reading a player
with it as a veto (``solver_bot.kept``) throws out, at each action, every
hand the model would have played otherwise: a check leaves no hand the model
bets, a bet no hand it checks. Real players slow-play and bluff: of the 149
opponents who showed their cards while still in at the end of a hand in nine
recordings of 2026-10-08 to 10-10, the reading had thrown out the hand shown
for 86 (62 of the 81 who reached the river), 48 of them after the flop; the
AI then saw near-certain wins and bet big into them.

The reading here keeps, at each postflop action, the hands the model plays
otherwise with a weight instead of 0 (as ``preflop_reading`` does before the
flop):

* ``slow``: at a check or a call, the hands the model would bet or raise;
* ``loose``: at a call, the hands the model would fold;
* ``bluff``: at a bet or a raise, the hands the model would check or fold.

The weights are per street (``WEIGHTS``). The shown hands
(``tools/aa_postflop_reading_weights.py``) are the evidence for them: at a
check 43% (flop), 55% (turn) and 44% (river) of the hands shown were hands
the model bets; at a bet about a quarter were hands it checks. The weights
that make the shown hands most likely (``FITTED``) are slow 1.0 / 1.0 / 0.7,
loose 0.2 / 0.7 / - (no river calls the model folds were shown), bluff
0.2 / 0.4 / 0.3. Hands shown at a showdown are not all hands, though: a
strong hand that checked is more likely to get there than a weak one, which
often folds later and is never seen, so the fit overstates them.

On the scoreboard every player plays exactly as the model, so there the veto
is exact and any weight costs. Against the AA real-player table (1000 deals,
paired with the veto reading) slow 0.7 / 0.7 / 0.5 with the loose and bluff
weights above lost 61.5 bb/100 [-87, -36], half of all of them 32 [-51, -13];
the loose and bluff weights alone lost 58 [-83, -33] and kept only a few
more shown hands, slow play alone 18 [-31, -5]. What is used is slow play at
half that, 0.35 / 0.35 / 0.25 (-3.3 [-14, +7]: not clearly worse), and no
loose or bluff weight: a bet or a call still throws out the hands the model
plays otherwise, as before. A seat whose reads show it bets clearly more
than the model keeps, as before, at least its floor (``ranges.floor``) of
every hand at every action, which is its bluff weight.
"""

from __future__ import annotations

from .replay import kind_of, with_hole

STREETS = ("flop", "turn", "river")
KINDS = ("slow", "loose", "bluff")
# {kind: (flop, turn, river)}: the shown hands' best fit, and what is used
# (see the module notes for why it is smaller).
# No river call of a hand the model folds was shown: the flop's loose weight.
FITTED = {"slow": (1.0, 1.0, 0.7), "loose": (0.2, 0.7, 0.2),
          "bluff": (0.2, 0.4, 0.3)}
WEIGHTS = {"slow": (0.35, 0.35, 0.25), "loose": (0.0, 0.0, 0.0),
           "bluff": (0.0, 0.0, 0.0)}
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


def veto_from_name(name, make_policy):
    """``vetoread+<policy>``: the policy reading postflop actions by veto, as
    until 2026-10-13 (every model it or its base policies read with gets
    ``VETO``), for comparing the two readings on the same deals."""
    policy = make_policy(name.partition("+")[2])
    part = policy
    while part is not None:
        if getattr(part, "model", None) is not None:
            part.model.postflop_reading = VETO
        part = getattr(part, "base", None)
    policy.name = name
    return policy


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


__all__ = ["FITTED", "KINDS", "PRUNE", "STREETS", "VETO", "WEIGHTS", "key_of",
           "otherwise", "soft_kept", "veto_from_name", "weights_of"]
