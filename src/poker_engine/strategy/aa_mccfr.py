"""Bounded external-sampling MCCFR, offline only.

Uses SIMPLE multiplayer averaging (sampled next-player updates) with linear
iteration weights. For N>2 it is an empirical approximation, not an unbiased
full-tree average or a multiplayer Nash-convergence guarantee. Each whole sweep
is transactional: budget failure commits no partial regret or policy updates.

Normalization sums use sorted action IDs so JSON object ordering cannot alter
continuation. Floating arithmetic remains bound to the frozen Python runtime;
this is not a cross-version or cross-platform numerical identity guarantee.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import random
import time

from .aa_frozen_policy import action_ids, canonical_hash, information_key, make_policy


NUMERICAL_SEMANTICS = "canonical_action_sum_v1_runtime_bound"


class TrainingBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class TrainingBudget:
    max_nodes: int = 10000
    max_infosets: int = 100000
    max_depth: int = 256
    seconds: float = 30.0

    def __post_init__(self):
        if any(type(x) is not int or x <= 0 for x in
               (self.max_nodes, self.max_infosets, self.max_depth)):
            raise ValueError("invalid_training_count_budget")
        if (type(self.seconds) not in (int, float) or not math.isfinite(self.seconds)
                or self.seconds <= 0):
            raise ValueError("invalid_training_time_budget")


def _tuples(value):
    return tuple(_tuples(x) for x in value) if isinstance(value, list) else value


class ExternalSamplingMCCFR:
    def __init__(self, players, *, seed=0, budget=None, encoder=information_key,
                 menu=action_ids, clock=time.monotonic, binding=None,
                 encoder_id="aa_rank_texture_v1", update_regrets=True):
        self.players = tuple(players)
        if len(self.players) < 2 or len(set(self.players)) != len(self.players):
            raise ValueError("invalid_training_players")
        if type(update_regrets) is not bool:
            raise ValueError("update_regrets_must_be_boolean")
        self.update_regrets = update_regrets
        self.visits = {}
        self.seed = seed
        self.binding, self.encoder_id = deepcopy(binding), encoder_id
        self.budget = budget or TrainingBudget()
        self.encoder, self.menu, self.clock = encoder, menu, clock
        self.rng = random.Random(seed)
        self.regrets = {}
        self.average = {}
        self.iterations = 0
        self.total_nodes = 0
        self.last_attempt_nodes = 0

    @staticmethod
    def _strategy(values):
        positive = {action: max(0.0, value) for action, value in values.items()}
        total = sum(positive[action] for action in sorted(positive))
        return ({action: value / total for action, value in positive.items()}
                if total else {action: 1 / len(values) for action in values})

    def iterate(self, arena_factory):
        """factory(deal_seed) returns a fresh full-hand arena; one all-seat sweep."""
        deadline = self.clock() + self.budget.seconds
        rng_before = self.rng.getstate()
        regrets, average, visits = {}, {}, {}
        self.last_attempt_nodes = 0
        try:
            for traverser in self.players:
                arena = arena_factory(self.rng.randrange(2 ** 63))
                self._walk(arena, traverser, regrets, average, visits, deadline, 0)
            self._check(deadline, 0)
            merged_regrets = self._merge(self.regrets, regrets)
            merged_average = self._merge(self.average, average)
            self._check(deadline, 0)
        except BaseException:
            self.rng.setstate(rng_before)
            raise
        self.regrets, self.average = merged_regrets, merged_average
        for key, count in visits.items():
            self.visits[key] = self.visits.get(key, 0) + count
        self.iterations += 1
        self.total_nodes += self.last_attempt_nodes
        return {"iteration": self.iterations, "nodes": self.last_attempt_nodes,
                "infosets": len(self.regrets)}

    @staticmethod
    def _merge(base, delta):
        result = dict(base)
        for key, values in delta.items():
            target = dict(base.get(key, {a: 0.0 for a in values}))
            if set(target) != set(values):
                raise ValueError("checkpoint_menu_mismatch")
            for action, value in values.items():
                target[action] += value
                if not math.isfinite(target[action]):
                    raise ValueError("nonfinite_training_update")
            result[key] = target
        return result

    def _check(self, deadline, depth):
        if (self.clock() >= deadline or depth > self.budget.max_depth
                or self.last_attempt_nodes > self.budget.max_nodes):
            raise TrainingBudgetExceeded("whole_sweep_budget_exceeded")

    def _walk(self, arena, traverser, deltas, sums, visits, deadline, depth):
        self.last_attempt_nodes += 1
        self._check(deadline, depth)
        if arena.terminal:
            result = float(arena.terminal_returns()[traverser])
            if not math.isfinite(result):
                raise ValueError("nonfinite_terminal_utility")
            return result
        actor = arena.actor
        if actor not in self.players:
            raise ValueError("training_actor_not_registered")
        observation = arena.observe(actor)
        key, actions = self.encoder(observation), self.menu(observation)
        if not actions or len(actions) != len(set(actions)):
            raise ValueError("invalid_training_action_menu")
        base = self.regrets.get(key, {a: 0.0 for a in actions})
        if set(base) != set(actions):
            raise ValueError("information_set_menu_changed")
        if key not in self.regrets and key not in deltas:
            new_keys = sum(item not in self.regrets for item in deltas)
            if len(self.regrets) + new_keys >= self.budget.max_infosets:
                raise TrainingBudgetExceeded("information_set_budget_exceeded")
        visits[key] = visits.get(key, 0) + 1
        pending = deltas.setdefault(key, {a: 0.0 for a in actions})
        strategy = self._strategy(base)
        if actor != traverser:
            action = self.rng.choices(actions, [strategy[a] for a in actions])[0]
            if actor == self.players[(self.players.index(traverser) + 1)
                                     % len(self.players)]:
                total = sums.setdefault(key, {a: 0.0 for a in actions})
                for option in actions:
                    total[option] += (self.iterations + 1) * strategy[option]
            arena.step(action)
            return self._walk(
                arena, traverser, deltas, sums, visits, deadline, depth + 1)
        utilities = {}
        for action in actions:
            self._check(deadline, depth)
            child = arena.clone()
            child.step(action)
            utilities[action] = self._walk(
                child, traverser, deltas, sums, visits, deadline, depth + 1,
            )
        expected = sum(strategy[a] * utilities[a] for a in actions)
        if self.update_regrets:
            for action in actions:
                pending[action] += utilities[action] - expected
        return expected

    def average_policy(self):
        result = {}
        for key, values in self.average.items():
            total = sum(values[action] for action in sorted(values))
            if total:
                result[key] = {a: value / total for a, value in values.items()}
        return result

    def checkpoint(self):
        document = {
            "schema_version": 1, "kind": "AA_MCCFR_CHECKPOINT_V1",
            "players": list(self.players), "seed": self.seed,
            "iterations": self.iterations, "total_nodes": self.total_nodes,
            "regrets": deepcopy(self.regrets), "average": deepcopy(self.average),
            "rng_state": self.rng.getstate(), "status": "research_only",
            "algorithm": "external_sampling_simple_linear_v1",
            "numerical_semantics": NUMERICAL_SEMANTICS,
            "binding": deepcopy(self.binding), "encoder_id": self.encoder_id,
            "update_regrets": self.update_regrets,
            "committed_visits": dict(self.visits),
        }
        document["sha256"] = canonical_hash(document)
        return document

    @classmethod
    def restore(cls, document, **kwargs):
        data = deepcopy(document)
        if data.pop("sha256", None) != canonical_hash(data):
            raise ValueError("checkpoint_digest_mismatch")
        if (data.get("kind") != "AA_MCCFR_CHECKPOINT_V1"
                or data.get("schema_version") != 1
                or data.get("algorithm") != "external_sampling_simple_linear_v1"
                or data.get("status") != "research_only"):
            raise ValueError("unsupported_checkpoint")
        if data.get("numerical_semantics") not in (None, NUMERICAL_SEMANTICS):
            raise ValueError("unsupported_checkpoint_numerical_semantics")
        expected_binding = kwargs.pop("expected_binding", None)
        expected_encoder = kwargs.pop("expected_encoder", "aa_rank_texture_v1")
        if (data.get("binding") != expected_binding
                or data.get("encoder_id") != expected_encoder):
            raise ValueError("checkpoint_binding_or_encoder_mismatch")
        mode = data.get("update_regrets", True)
        if kwargs.pop("update_regrets", mode) != mode:
            raise ValueError("checkpoint_learning_mode_mismatch")
        result = cls(data["players"], seed=data["seed"], binding=expected_binding,
                     update_regrets=mode,
                     encoder_id=expected_encoder, **kwargs)
        for table in (data["regrets"], data["average"]):
            if not isinstance(table, dict):
                raise ValueError("invalid_checkpoint_table")
            for key, values in table.items():
                if not isinstance(key, str) or not key or not isinstance(values, dict):
                    raise ValueError("invalid_checkpoint_table_entry")
                if (not values or any(not isinstance(a, str) or not a for a in values)
                        or any(type(x) not in (int, float) or not math.isfinite(x)
                               for x in values.values())):
                    raise ValueError("invalid_checkpoint_values")
        if (not set(data["average"]) <= set(data["regrets"])
                or any(set(values) != set(data["regrets"][key])
                       for key, values in data["average"].items())):
            raise ValueError("checkpoint_average_regret_menu_mismatch")
        if any(value < 0 for values in data["average"].values()
               for value in values.values()):
            raise ValueError("negative_average_weight")
        visits = data.get("committed_visits", {})
        if (not isinstance(visits, dict) or not set(visits) <= set(data["regrets"])
                or any(type(count) is not int or count <= 0
                       for count in visits.values())):
            raise ValueError("invalid_checkpoint_visits")
        result.visits = dict(visits)
        result.regrets, result.average = data["regrets"], data["average"]
        result.iterations, result.total_nodes = data["iterations"], data["total_nodes"]
        if any(type(x) is not int or x < 0 for x in
               (result.iterations, result.total_nodes)):
            raise ValueError("invalid_checkpoint_counters")
        result.rng.setstate(_tuples(data["rng_state"]))
        return result

    def export(self, *, rules_fingerprint, table_size, stack_depth_bb,
               policy_factory=make_policy):
        if self.binding is not None and (
                self.binding.get("rules_fingerprint") != rules_fingerprint
                or self.binding.get("rules", {}).get("table_size") != table_size
                or self.binding.get("stack_depth_bb") != str(stack_depth_bb)):
            raise ValueError("export_training_scope_mismatch")
        document = policy_factory(
            rules_fingerprint=rules_fingerprint, table_size=table_size,
            stack_depth_bb=stack_depth_bb, policy=self.average_policy(),
            training={"algorithm": "external_sampling_simple_linear_v1",
                      "numerical_semantics": NUMERICAL_SEMANTICS,
                      "multiplayer_averaging": "SIMPLE_APPROXIMATION",
                      "seed": self.seed, "iterations": self.iterations,
                      "nodes": self.total_nodes,
                      "update_regrets": self.update_regrets,
                      "checkpoint_sha256": self.checkpoint()["sha256"],
                      "empirical_strength": "NOT_ASSESSED"},
        )
        if document.get("encoder") != self.encoder_id:
            raise ValueError("export_encoder_factory_mismatch")
        return document
