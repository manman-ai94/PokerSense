"""Test-only OWN collector, kept separate from production SIMPLE averages.

This component consumes the portable finite tree and an in-memory counter. It
creates no poker policy artifact and performs no persistence or experiment.
"""
from copy import deepcopy
import math

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from tests.strategy.aa_synthetic_regression_support import (
    ACTORS, FiniteArena, TraceTrainer, key, label,
)


class CollectorAbort(RuntimeError):
    """The fixed third-entry collector fault, distinct from the CI counter."""


def collect_own(trainer, counter, weight, *, abort_at=None, progress=None):
    """Visit every branch using only the pre-sweep strategy and own reach."""
    result = {} if progress is None else progress
    result.update(average={}, arrivals=[], visited_keys=[])
    snapshot = {k: trainer._strategy(row) for k, row in trainer.regrets.items()}
    visited, owners = set(), {}

    def visit(chance, history, reach):
        counter.tick("own_collector_state")
        row = {"chance": chance, "history": history,
               "self_reach": list(reach), "terminal": len(history) == 4}
        result["arrivals"].append(row)
        if not row["terminal"]:
            actor = ACTORS[len(history)]
            k, policy = key(chance, history), snapshot[key(chance, history)]
            if (set(policy) != {"L", "R"}
                    or any(not math.isfinite(p) or not 0 <= p <= 1
                           for p in policy.values())
                    or abs(math.fsum(policy.values()) - 1) > 1e-12):
                raise ValueError("invalid_synthetic_own_strategy")
            identity = actor, policy
            if k in owners and owners[k] != identity:
                raise ValueError("synthetic_own_information_set_conflict")
            owners[k] = identity
            visited.add(label(chance, history))
            row.update(actor=actor, key=k, policy=deepcopy(policy))
            if reach[actor] > 0:
                target = result["average"].setdefault(k, {"L": 0.0, "R": 0.0})
                if set(target) != set(policy):
                    raise ValueError("synthetic_own_menu_changed")
                for action in ("L", "R"):
                    target[action] += weight * reach[actor] * policy[action]
        if abort_at is not None and len(result["arrivals"]) == abort_at:
            raise CollectorAbort("frozen_mid_collector_abort")
        if row["terminal"]:
            return
        for action in ("L", "R"):
            child_reach = list(reach)
            child_reach[actor] *= policy[action]
            visit(chance, history + action, child_reach)

    for chance in (0, 1):
        visit(chance, "", [1.0, 1.0, 1.0])
    result["visited_keys"] = sorted(visited)
    assert len(result["arrivals"]) == 62 and len(visited) == 30
    return result


def _merge(base, delta):
    result = deepcopy(base)
    for k, row in delta.items():
        current = result.setdefault(k, {"L": 0.0, "R": 0.0})
        if set(row) != {"L", "R"} or set(current) != set(row):
            raise ValueError("synthetic_own_menu_changed")
        for action in ("L", "R"):
            current[action] += row[action]
            if not math.isfinite(current[action]) or current[action] < 0:
                raise ValueError("invalid_synthetic_own_quantity")
    return result


class OwnReachArm:
    """Atomically checkpoint separate OWN state and the unchanged trainer."""
    def __init__(self, trainer, counter):
        self.trainer, self.counter = trainer, counter
        self.average, self.collector_visits = {}, set()
        self.collector_sweeps = 0
        self.abort_collector_at = None
        self.temporary_collector = {}
        self.temporary_walk, self.sampled_arrivals = None, []
        self.temporary_rng = self.rng_at_rejected_entry = None
        self.attempted_walk_entries = self.rejected_walk_entry = 0

    def checkpoint(self):
        value = {"kind": "SYNTHETIC_OWN_CHECKPOINT_V1",
                 "average_contract": "own_reach_without_chance_or_opponents",
                 "production": self.trainer.checkpoint(),
                 "own_average": deepcopy(self.average),
                 "collector_visits": sorted(self.collector_visits),
                 "collector_sweeps": self.collector_sweeps}
        value["sha256"] = canonical_hash(value)
        return value

    @classmethod
    def restore(cls, checkpoint, counter, budget):
        saved = deepcopy(checkpoint)
        if saved.pop("sha256", None) != canonical_hash(saved):
            raise ValueError("synthetic_own_checkpoint_digest_mismatch")
        if (saved["kind"] != "SYNTHETIC_OWN_CHECKPOINT_V1"
                or saved["average_contract"]
                != "own_reach_without_chance_or_opponents"):
            raise ValueError("unsupported_synthetic_own_checkpoint")
        trainer = TraceTrainer.restore(
            saved["production"], expected_encoder="four-stage-synthetic-v1",
            limiter=counter, budget=budget)
        result = cls(trainer, counter)
        result.average = _merge({}, saved["own_average"])
        result.collector_visits = set(saved["collector_visits"])
        result.collector_sweeps = saved["collector_sweeps"]
        return result

    def iterate(self):
        before, trainer = self.checkpoint(), self.trainer
        budget, original_walk = trainer.budget, trainer._walk
        self.temporary_collector.clear()
        self.temporary_walk, self.sampled_arrivals = None, []
        self.temporary_rng = self.rng_at_rejected_entry = None
        self.attempted_walk_entries = self.rejected_walk_entry = 0
        trainer.trace.clear()
        trainer.temporary = None

        def observed_walk(arena, traverser, deltas, sums, visits, deadline, depth):
            self.attempted_walk_entries += 1
            if trainer.last_attempt_nodes + 1 == budget.max_nodes + 1:
                self.rejected_walk_entry = trainer.last_attempt_nodes + 1
                self.rng_at_rejected_entry = deepcopy(trainer.rng.getstate())
            try:
                return original_walk(arena, traverser, deltas, sums, visits,
                                     deadline, depth)
            except BaseException:
                # This runs before ExternalSamplingMCCFR.iterate restores RNG.
                if self.temporary_rng is None:
                    self.temporary_rng = deepcopy(trainer.rng.getstate())
                raise

        trainer._walk = observed_walk
        try:
            collected = collect_own(
                trainer, self.counter, trainer.iterations + 1,
                abort_at=self.abort_collector_at, progress=self.temporary_collector)
            updated = _merge(self.average, collected["average"])
            result = trainer.iterate(lambda seed: FiniteArena(seed % 2))
            self.average = updated
            self.collector_visits.update(collected["visited_keys"])
            self.collector_sweeps += 1
            return result
        except BaseException:
            self.temporary_walk = deepcopy(trainer.temporary)
            self.sampled_arrivals = deepcopy(trainer.trace)
            if self.temporary_rng is None:
                self.temporary_rng = deepcopy(trainer.rng.getstate())
            restored = self.restore(before, self.counter, budget)
            self.trainer, self.average = restored.trainer, restored.average
            self.collector_visits = restored.collector_visits
            self.collector_sweeps = restored.collector_sweeps
            raise
        finally:
            trainer._walk = original_walk

    def export(self):
        policy = {}
        for k, row in self.average.items():
            if (set(row) != {"L", "R"}
                    or any(not math.isfinite(v) or v < 0 for v in row.values())):
                raise ValueError("invalid_synthetic_own_quantity")
            total = math.fsum(row.values())
            if total:
                policy[k] = {action: row[action] / total for action in ("L", "R")}
        return {"kind": "SYNTHETIC_OWN_EXPORT_V1", "policy": policy,
                "checkpoint_sha256": self.checkpoint()["sha256"],
                "status": "synthetic_test_only"}
