"""Test-only checked deduplication of perfect-recall information sets."""
from fractions import Fraction
import itertools
import json
import math

from tests.strategy.aa_synthetic_status import classify_exception, finish


ACTORS = (1, 0, 2, 0)
PROFILES = {
    "A": ("1/2", "1/3", "2/3", "3/4"),
    "B": ("2/3", "3/4", "1/4", "1/3"),
    "C": ("1/4", "2/5", "4/5", "2/3"),
}


class SharedInfoContract(AssertionError):
    pass


def require(condition, reason):
    if not condition:
        raise SharedInfoContract(reason)


def observation(z, s, history):
    stage = len(history)
    actor = ACTORS[stage]
    return {"actor": actor, "private_signal": s if actor == 0 else z,
            "visible_prefix": list(history[:2]) if actor == 2 else [],
            "own_history": [history[1]] if stage == 3 else [],
            "decision": 1 if stage == 3 else 0, "menu": ["L", "R"]}


def information_id(obs):
    require(set(obs) == {"actor", "private_signal", "visible_prefix", "own_history",
                         "decision", "menu"}, "unapproved_observation_field")
    actor, signal = obs["actor"], obs["private_signal"]
    require(type(actor) is int and actor in (0, 1, 2), "invalid_actor")
    require(type(signal) is int and signal in (0, 1), "invalid_private_signal")
    require(obs["menu"] == ["L", "R"], "menu_mismatch")
    if actor == 0:
        own = obs["own_history"]
        require(own in ([], ["L"], ["R"]) and obs["decision"] == len(own)
                and obs["visible_prefix"] == [], "own_history_or_visibility_invalid")
        return f"P0/s={signal}/own={''.join(own)}"
    require(obs["own_history"] == [] and obs["decision"] == 0,
            "nonhero_own_history_invalid")
    if actor == 1:
        require(obs["visible_prefix"] == [], "player1_visibility_invalid")
        return f"P1/z={signal}"
    require(len(obs["visible_prefix"]) == 2
            and all(a in ("L", "R") for a in obs["visible_prefix"]),
            "player2_visibility_invalid")
    return f"P2/z={signal}/prefix={''.join(obs['visible_prefix'])}"


def policy(case, profile, obs):
    values = [float(Fraction(p)) for p in PROFILES[profile]]
    actor, signal = obs["actor"], obs["private_signal"]
    if actor == 1:
        left = 0.0 if case == "ZERO_OPPONENT" else (
            values[0] if signal == 0 else 1 - values[0])
    elif actor == 0 and obs["decision"] == 0:
        left = 0.0 if case == "ZERO_SELF" else (
            values[1] if signal == 0 else 1 - values[1])
    elif actor == 0:
        same = signal == int(obs["own_history"][0] == "R")
        left = values[3] if same else 1 - values[3]
    else:
        parity = signal + sum(a == "R" for a in obs["visible_prefix"])
        left = values[2] if parity % 2 == 0 else 1 - values[2]
    return {"L": left, "R": 1 - left}


def collect(case, profile, weight, tick, *, reverse=False, mutation=None,
            progress=None):
    """One physical traversal, one checked own-reach update per logical I.

    All duplicate arrivals must agree on the observable view, own action
    sequence, policy and own reach. Missing or imperfect recall is refused.
    Chance/opponent probabilities are absent from the own-reach quantity.
    """
    result = {} if progress is None else progress
    result.update(average={}, arrivals=[], registry={}, visible_to_key={},
                  visited_keys=[], positive_keys=[], physical_states=0)
    planned = [{"z": z, "s": s, "history": "".join(bits), "status": "NOT_RUN",
                "reason": "NOT_REACHED"}
               for z in (0, 1) for s in (0, 1) for depth in range(5)
               for bits in itertools.product("LR", repeat=depth)]
    result["planned_arrivals"] = planned
    catalogue = {(r["z"], r["s"], r["history"]): r for r in planned}
    actions = ("R", "L") if reverse else ("L", "R")
    atoms = list((z, s) for z in (0, 1) for s in (0, 1))
    if reverse:
        atoms.reverse()

    def visit(z, s, history, reaches):
        tick("shared_collector_state")
        result["physical_states"] += 1
        row = catalogue[(z, s, history)]
        row.update(self_reach=list(reaches), terminal=len(history) == 4,
                   status="INTERRUPTED")
        row.pop("reason", None)
        result["arrivals"].append(row)
        if len(history) == 4:
            row["status"] = "PASS"
            return
        obs = observation(z, s, history)
        if mutation == "MENU_MISMATCH" and z == 1 and len(history) == 1:
            obs["menu"] = ["L", "X"]
        row["observation"] = obs
        logical = information_id(obs)
        values = policy(case, profile, obs)
        if mutation == "POLICY_MISMATCH" and z == 1 and len(history) == 1:
            values = {"L": 0.25, "R": 0.75}
        if obs["actor"] == 0:
            if mutation == "LEAK_CHANCE":
                logical += f"/hidden_z={z}"
            if mutation == "LEAK_OPPONENT" and len(history) >= 1:
                logical += "/hidden_opponent=" + history[0]
            if mutation == "FORGET_OWN" and len(history) == 3:
                logical = f"P0/s={s}/second"
            if mutation == "FORGET_PRIVATE":
                logical = "P0/s=masked/own=" + "".join(obs["own_history"])
        require(set(values) == {"L", "R"}
                and all(math.isfinite(p) and 0 <= p <= 1 for p in values.values())
                and abs(math.fsum(values.values()) - 1) <= 1e-12,
                "invalid_policy")
        own_reach = reaches[obs["actor"]]
        fingerprint = json.dumps(obs, sort_keys=True, separators=(",", ":"))
        existing_id = result["visible_to_key"].get(fingerprint)
        require(existing_id in (None, logical), "hidden_information_in_key")
        result["visible_to_key"][fingerprint] = logical
        prior = result["registry"].get(logical)
        row.update(logical_key=logical, own_reach=own_reach, policy=values,
                   duplicate=prior is not None)
        if prior is not None:
            require(prior["signature"] == obs, "imperfect_recall_or_private_merge")
            require(prior["policy"] == values, "same_info_policy_changed")
            require(prior["own_reach"] == own_reach, "same_info_own_reach_changed")
            prior["physical_occurrences"] += 1
        else:
            require(len(result["registry"]) < 16, "information_set_growth_cap")
            result["registry"][logical] = {
                "signature": obs, "policy": values, "own_reach": own_reach,
                "physical_occurrences": 1, "collected_once": own_reach > 0}
        if own_reach > 0 and (prior is None or mutation == "SUM_EVERY_HISTORY"):
            quantity = result["average"].setdefault(logical, {"L": 0.0, "R": 0.0})
            for action in ("L", "R"):
                quantity[action] += weight * own_reach * values[action]
        row["status"] = "PASS"
        for action in actions:
            child = list(reaches)
            child[obs["actor"]] *= values[action]
            visit(z, s, history + action, child)

    try:
        for z, s in atoms:
            visit(z, s, "", [1.0, 1.0, 1.0])
    except Exception as exc:
        for row in result["arrivals"]:
            if row["status"] == "INTERRUPTED":
                finish(row, classify_exception(exc), str(exc))
        raise
    require(result["physical_states"] == 124, "physical_state_denominator")
    require(len(result["registry"]) == 16, "logical_info_denominator")
    result["visited_keys"] = sorted(result["registry"])
    result["positive_keys"] = sorted(result["average"])
    return result
