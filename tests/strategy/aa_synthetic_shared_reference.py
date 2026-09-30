"""Independent exact own-reach oracle for the portable public shared-infoset fixture.

Only the standard library is imported. The oracle lists the sixteen distinct
information sets directly: it does not visit physical tree nodes, call a
candidate collector, or use a production trainer. Each information set receives
one contribution, including zero rows. Chance and opponent reach are absent.

The four hidden (z, s) atoms have sixty physical decision occurrences and
sixty-four terminals. P1 sees z; P0 sees s and its own earlier action; P2 sees
z and the opponent/first-P0 action prefix, but never s. The actor order is
(1, 0, 2, 0), and both actions are legal at every decision.

Hand calculation for FULL/A/weight 1: each first-decision mass is 1;
P0/s=0/own=L has mass 1/3 and row (1/4, 1/12);
P0/s=0/own=R has mass 2/3 and row (1/6, 1/2).
For s=1 the corresponding masses are 2/3 and 1/3, with rows
(1/6, 1/2) and (1/4, 1/12). P1/P2 masses are always 1.
"""

from collections.abc import Callable
from fractions import Fraction
from typing import Any


ACTORS = (1, 0, 2, 0)
ACTIONS = ("L", "R")
CASES = ("FULL", "ZERO_OPPONENT", "ZERO_SELF", "CHANCE_SKEW")
PROFILES = {
    "A": (Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(3, 4)),
    "B": (Fraction(2, 3), Fraction(3, 4), Fraction(1, 4), Fraction(1, 3)),
    "C": (Fraction(1, 4), Fraction(2, 5), Fraction(4, 5), Fraction(2, 3)),
}
PROFILE_WEIGHTS = {"A": 1, "B": 2, "C": 3}
UNIQUE_INFORMATION_SETS = 16
PHYSICAL_DECISIONS = 60
PHYSICAL_TERMINALS = 64


def _catalogue() -> tuple[tuple[str, dict[str, Any], int], ...]:
    """List observations by actor family, without any physical-history walk."""
    rows = []
    for z in (0, 1):
        rows.append((
            f"P1/z={z}",
            {"actor": 1, "private_signal": z, "visible_prefix": [],
             "own_history": [], "decision": 0, "menu": ["L", "R"]},
            2,
        ))
    for s in (0, 1):
        rows.append((
            f"P0/s={s}/own=",
            {"actor": 0, "private_signal": s, "visible_prefix": [],
             "own_history": [], "decision": 0, "menu": ["L", "R"]},
            4,
        ))
        for own_action in ACTIONS:
            rows.append((
                f"P0/s={s}/own={own_action}",
                {"actor": 0, "private_signal": s, "visible_prefix": [],
                 "own_history": [own_action], "decision": 1,
                 "menu": ["L", "R"]},
                8,
            ))
    for z in (0, 1):
        for opponent_action in ACTIONS:
            for first_self_action in ACTIONS:
                rows.append((
                    f"P2/z={z}/prefix={opponent_action}{first_self_action}",
                    {"actor": 2, "private_signal": z,
                     "visible_prefix": [opponent_action, first_self_action],
                     "own_history": [], "decision": 0, "menu": ["L", "R"]},
                    2,
                ))
    return tuple(rows)


def _first_self_left(case: str, profile: str, signal: int) -> Fraction:
    if case == "ZERO_SELF":
        return Fraction(0)
    base = PROFILES[profile][1]
    return base if signal == 0 else 1 - base


def _local_left(
    case: str, profile: str, observation: dict[str, Any]
) -> Fraction:
    """Calculate L's probability from this information set's observation."""
    actor = observation["actor"]
    signal = observation["private_signal"]
    base = PROFILES[profile]
    if actor == 1:
        if case == "ZERO_OPPONENT":
            return Fraction(0)
        return base[0] if signal == 0 else 1 - base[0]
    if actor == 0:
        if observation["decision"] == 0:
            return _first_self_left(case, profile, signal)
        own_action = observation["own_history"][0]
        return base[3] if signal == int(own_action == "R") else 1 - base[3]
    opponent_action, first_self_action = observation["visible_prefix"]
    parity = (
        signal + int(opponent_action == "R") + int(first_self_action == "R")
    )
    return base[2] if parity % 2 == 0 else 1 - base[2]


def _hidden_atoms(case: str) -> dict[str, Fraction]:
    """Expose the independent chance law; it never enters an average row."""
    z0 = Fraction(1, 8) if case == "CHANCE_SKEW" else Fraction(1, 2)
    s0 = Fraction(2, 5) if case == "CHANCE_SKEW" else Fraction(1, 2)
    return {
        f"z={z}/s={s}": (z0 if z == 0 else 1 - z0)
        * (s0 if s == 0 else 1 - s0)
        for z in (0, 1)
        for s in (0, 1)
    }


def reference(
    case: str,
    profile: str,
    weight: int | Fraction,
    tick: Callable[[str], None],
) -> dict[str, Any]:
    """Return sixteen exact rows, signatures, own masses and local policies.

    ``masses`` contains the acting player's reach before the profile weight;
    ``expected_averages`` contains weight * own reach * local probability.
    Zero rows remain present so callers can distinguish absent positive rows
    from missing information sets. There are exactly sixteen budget ticks,
    one per distinct information set, including unreachable own histories.
    """
    if case not in CASES or profile not in PROFILES:
        raise ValueError("unknown frozen shared-infoset case or profile")
    if type(weight) is int:
        weight = Fraction(weight)
    if not isinstance(weight, Fraction) or weight <= 0:
        raise ValueError("weight must be a positive exact rational")
    if not callable(tick):
        raise TypeError("tick must be the caller's budget callback")

    expected_averages = {}
    info_signatures = {}
    masses = {}
    policy = {}
    physical_occurrences = {}
    for identifier, observation, occurrences in _catalogue():
        tick("shared_infoset_reference_information_set")
        left = _local_left(case, profile, observation)
        own_mass = Fraction(1)
        if observation["actor"] == 0 and observation["decision"] == 1:
            first_left = _first_self_left(
                case, profile, observation["private_signal"]
            )
            own_mass = (first_left if observation["own_history"] == ["L"]
                        else 1 - first_left)
        row = {"L": left, "R": 1 - left}
        policy[identifier] = row
        masses[identifier] = own_mass
        info_signatures[identifier] = observation
        physical_occurrences[identifier] = occurrences
        expected_averages[identifier] = {
            action: weight * own_mass * row[action] for action in ACTIONS
        }

    return {
        "expected_averages": expected_averages,
        "info_signatures": info_signatures,
        "masses": masses,
        "policy": policy,
        "physical_occurrences": physical_occurrences,
        "chance_atoms": _hidden_atoms(case),
    }
