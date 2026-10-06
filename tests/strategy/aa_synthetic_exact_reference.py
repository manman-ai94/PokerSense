"""Independent terminal-sum Fraction oracle for six portable frozen profiles.

Only the standard library is imported. The payoff, policy, and reach definitions
are local; neither the production walker nor a test collector is consulted.
SIMPLE is the production next-player collector's expectation. Its differences
from own reach are tested as collector limitations, not masked test failures.
"""
from collections.abc import Callable
from fractions import Fraction
from itertools import product


ACTORS = (1, 0, 2, 0)
ACTIONS = ("L", "R")
CASES = ("FULL_POSITIVE", "ZERO_PREFIX", "SMALL_PREFIX", "ZERO_SELF")
CHANCE_PROBABILITY = Fraction(1, 2)


def frozen_probabilities(case, profile):
    if case not in CASES or profile != "A":
        raise ValueError("unknown frozen case or profile")
    values = (Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(3, 4))
    if case == "ZERO_PREFIX":
        return (Fraction(0), *values[1:])
    if case == "SMALL_PREFIX":
        return (Fraction(1, 1024), *values[1:])
    if case == "ZERO_SELF":
        return (values[0], Fraction(0), *values[2:])
    return values


def utility(chance, history):
    """Evaluate the complete terminal word directly, without walking a tree."""
    if (type(chance) is not int or chance not in (0, 1)
            or not isinstance(history, str) or len(history) != 4
            or any(action not in ACTIONS for action in history)):
        raise ValueError("utility requires chance 0/1 and a four-action word")
    b0, b1, b2, b3 = (int(action == "R") for action in history)
    u0 = ((2 * chance - 1) * (1 + 2 * b1 - 3 * b3)
          + 2 * b0 * b3 - b2 + b1 * b2)
    u1 = (1 - 2 * chance) * (2 * b0 - 1) + b2 * (1 + b3) - 2 * b1
    return Fraction(u0), Fraction(u1), Fraction(-u0 - u1)


def _action_probability(probabilities, stage, action):
    return probabilities[stage] if action == "L" else 1 - probabilities[stage]


def _product(values):
    result = Fraction(1)
    for value in values:
        result *= value
    return result


def reference(case, profile, weight, tick: Callable[[str], None]):
    """Sum terminal utilities, then derive each actor's counterfactual regret.

    Regrets use chance times the other players' prefix reach. Own averages use
    only the actor's prefix reach. SIMPLE averages use chance times the prefix
    reach of players other than the actor's designated previous traverser.
    The linear iteration weight applies to averages alone.
    """
    if type(weight) is int:
        weight = Fraction(weight)
    if not isinstance(weight, Fraction) or weight <= 0:
        raise ValueError("weight must be a positive exact rational")
    probabilities = frozen_probabilities(case, profile)
    words = tuple("".join(word) for word in product(ACTIONS, repeat=4))
    payoffs = {}
    for chance in (0, 1):
        for word in words:
            tick("rational_reference_terminal")
            payoffs[chance, word] = utility(chance, word)

    regrets, own_average, simple_average, infosets = {}, {}, {}, {}
    for chance in (0, 1):
        for stage, actor in enumerate(ACTORS):
            for prefix in product(ACTIONS, repeat=stage):
                tick("rational_reference_information_set")
                history = "".join(prefix)
                name = f"{chance}:{history}"
                policy = {action: _action_probability(probabilities, stage, action)
                          for action in ACTIONS}
                action_values = {}
                for action in ACTIONS:
                    forced_prefix = history + action
                    value = Fraction(0)
                    for word in words:
                        if not word.startswith(forced_prefix):
                            continue
                        tick("rational_reference_terminal_summand")
                        continuation = _product(
                            _action_probability(probabilities, j, word[j])
                            for j in range(stage + 1, 4))
                        value += continuation * payoffs[chance, word][actor]
                    action_values[action] = value
                node_value = sum((policy[a] * action_values[a] for a in ACTIONS),
                                 Fraction(0))
                own_reach = _product(
                    _action_probability(probabilities, j, history[j])
                    for j in range(stage) if ACTORS[j] == actor)
                external_reaches = {
                    traverser: CHANCE_PROBABILITY * _product(
                        _action_probability(probabilities, j, history[j])
                        for j in range(stage) if ACTORS[j] != traverser)
                    for traverser in range(3)}
                traverser = (actor - 1) % 3
                regrets[name] = {
                    action: external_reaches[actor]
                    * (action_values[action] - node_value) for action in ACTIONS}
                own_average[name] = {
                    action: weight * own_reach * policy[action]
                    for action in ACTIONS}
                simple_average[name] = {
                    action: weight * external_reaches[traverser] * policy[action]
                    for action in ACTIONS}
                infosets[name] = {
                    "chance": chance, "history": history, "stage": stage,
                    "actor": actor, "traverser": traverser, "policy": policy,
                    "action_values": action_values, "node_value": node_value,
                    "counterfactual_reach": external_reaches[actor],
                    "own_reach": own_reach,
                    "simple_reach": external_reaches[traverser]}
    return {"expected_regrets": regrets, "own_reach_average": own_average,
            "simple_average": simple_average, "infosets": infosets}
