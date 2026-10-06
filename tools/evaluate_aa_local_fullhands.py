"""Frozen, bounded synthetic full-hand local-model diagnostics; never live advice."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

from poker_engine.strategy.aa_arena_evaluation import (
    _cluster_interval, check_call_policy, evaluate_paired, min_raise_policy,
    pot_raise_policy,
)
from poker_engine.strategy.aa_external_local_policy import ExternalLocalResearchPolicy
from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_policy_encoding_v2 import encode_decision_v2
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools.aa_full_hand_lab import DEFAULT_RULES, read_json, rules_for
from tools import screen_aa_local_policy as screen


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SEEDS = tuple(range(8200000, 8200030))
DEVELOPMENT_SEEDS = (4441, 4442)
OPPONENTS = {"check_call": check_call_policy, "min_raise": min_raise_policy,
             "pot_raise": pot_raise_policy}
MAX_BATCH_SECONDS = 2400
LIMITS = {"max_batches": 2, "max_load_attempts_per_model_per_batch": 2,
          "load_seconds": 120, "warmup_seconds": 10, "forward_seconds": 10,
          "timely_ms": 300, "max_actions": 1000, "bootstrap_samples": 1000,
          "bootstrap_seed": 81171, "policy_seed": 7719,
          "batch_seconds_cap": 2400, "outer_reserve_seconds": 10,
          "inner_reserve_seconds": 25}


def _shards(seeds):
    result = [{"id": f"m{model}-n{n}-{opponent}-s{seed}", "model": model,
               "table_size": n, "opponent": opponent, "seed": seed,
               "expected_pairs": n}
              for model in range(2) for n in (6, 7, 8)
              for opponent in OPPONENTS for seed in seeds]
    return [{**row, "index": index, "policy_seed": LIMITS["policy_seed"] + index}
            for index, row in enumerate(result)]


def freeze(output, model_08b, model_2b, upstream_package, *, development=False):
    output = Path(output)
    if output.exists():
        raise ValueError("freeze_requires_new_output_directory")
    seeds = DEVELOPMENT_SEEDS if development else EVALUATION_SEEDS
    manifest = {
        "schema_version": 1, "kind": "AA_LOCAL_FULLHAND_DIAGNOSTIC_V1",
        "sample_kind": "DEVELOPMENT_CONTROL" if development else "NEW_SYNTHETIC_DEALS",
        "seeds": list(seeds), "rules": {str(n): rules_for(DEFAULT_RULES, n).to_dict()
                                        for n in (6, 7, 8)},
        "stack_depth_bb": "100", "opponents": list(OPPONENTS),
        "baseline": "check_call", "limits": LIMITS, "shards": _shards(seeds),
        "policy_salt_derivation": (
            "integer 7719 + frozen shard index; never model input"),
        "shard_attempt_policy": "ONE_ATTEMPT_INTERRUPTED_SHARDS_BLOCK_NO_REPLAY",
        "models": [screen._manifest_model(path, spec) for path, spec in
                   zip((model_08b, model_2b), screen.MODEL_SPECS)],
        "upstream": {"directory": str(Path(upstream_package).resolve()),
                     "commit": screen.UPSTREAM_COMMIT, "files": screen.UPSTREAM_FILES},
        "runtime_identity": screen.runtime_identity(), "clock": screen.clock_identity(),
        "source_sha256": screen._source_hashes(),
        # Warmup is an already exposed engineering query, never a new deal.
        "warmup": screen.frozen_queries()[0],
        "expected_pairs": 2 * len(seeds) * 21 * len(OPPONENTS),
        "strategy_eligible": False, "advice_emitted": False,
        "strength": "NOT_ASSESSED", "sanity_gate": "SEPARATE_REQUIRED_REPORT",
    }
    manifest = deepcopy(manifest)
    manifest["sha256"] = canonical_hash(manifest)
    output.mkdir(parents=True)
    (output / "shards").mkdir()
    (output / "attempts").mkdir()
    screen._atomic(output / "manifest.json", manifest)
    screen._atomic(output / "state.json", {
        "manifest_sha256": manifest["sha256"], "batches": [], "active_shard": None,
        "attempts": {}, "committed": {},
    })
    write_report(output, manifest=manifest)
    return manifest


def load_manifest(output):
    data = read_json(Path(output) / "manifest.json")
    raw = {key: value for key, value in data.items() if key != "sha256"}
    if canonical_hash(raw) != data.get("sha256"):
        raise ValueError("manifest_digest_mismatch")
    seeds = (DEVELOPMENT_SEEDS if data.get("sample_kind") == "DEVELOPMENT_CONTROL"
             else EVALUATION_SEEDS)
    if (data.get("sample_kind") not in ("DEVELOPMENT_CONTROL", "NEW_SYNTHETIC_DEALS")
            or data.get("baseline") != "check_call"
            or data.get("stack_depth_bb") != "100"
            or data.get("strategy_eligible") is not False
            or data.get("advice_emitted") is not False
            or data.get("strength") != "NOT_ASSESSED"
            or data.get("sanity_gate") != "SEPARATE_REQUIRED_REPORT"
            or data.get("shard_attempt_policy")
            != "ONE_ATTEMPT_INTERRUPTED_SHARDS_BLOCK_NO_REPLAY"
            or data.get("policy_salt_derivation")
            != "integer 7719 + frozen shard index; never model input"
            or data.get("warmup") != screen.frozen_queries()[0]
            or data.get("seeds") != list(seeds) or data.get("shards") != _shards(seeds)
            or data.get("expected_pairs") != 2 * len(seeds) * 21 * len(OPPONENTS)
            or data.get("limits") != LIMITS or data.get("opponents") != list(OPPONENTS)
            or data.get("runtime_identity") != screen.runtime_identity()
            or data.get("clock") != screen.clock_identity()
            or data.get("source_sha256") != screen._source_hashes()
            or data.get("upstream", {}).get("files") != screen.UPSTREAM_FILES
            or data.get("upstream", {}).get("commit") != screen.UPSTREAM_COMMIT):
        raise ValueError("frozen_protocol_source_or_runtime_mismatch")
    for n in (6, 7, 8):
        if data["rules"][str(n)] != rules_for(DEFAULT_RULES, n).to_dict():
            raise ValueError("frozen_rules_mismatch")
    if len(data.get("models", [])) != 2:
        raise ValueError("frozen_models_mismatch")
    for actual, expected in zip(data["models"], screen.MODEL_SPECS):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("frozen_models_mismatch")
    return data


@contextmanager
def exclusive(output):
    """Kernel lease releases on process death; stale PID files cannot own a study."""
    path = Path(output) / ".study.lock"
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("study_already_running") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class WorkerBackedResearchPolicy:
    """Every for_game creates a separate exact-state cache; receipts retain misses."""

    def __init__(self, rules, model, client, *, deadline, sink=lambda games: None):
        self.rules, self.model, self.client = rules, model, client
        self.deadline, self.sink = deadline, sink
        self.games = []
        self.available = True
        self.validator = ExternalLocalResearchPolicy(
            rules, lambda req: None, model_id=model["id"],
            model_revision=model["revision"])

    def inspect_lookup(self, observation):
        return self.validator.inspect_lookup(observation)

    def for_game(self, salt):
        if not isinstance(salt, str) or re.fullmatch(r"[0-9a-f]{64}", salt) is None:
            raise ValueError("independent_policy_salt_required")
        game = {"index": len(self.games), "observing_seat": None, "opportunities": []}
        self.games.append(game)
        current = {}

        def scorer(request):
            row = current["row"]
            remaining = self.deadline - time.perf_counter()
            if not self.available:
                row["failure"] = "MODEL_UNAVAILABLE"
                raise ValueError("external_model_unavailable")
            if remaining <= 0:
                row["failure"] = "BATCH_BUDGET_EXHAUSTED"
                raise TimeoutError("batch_budget_exhausted")
            query = {"observation": row["observation"], "request": request,
                     "request_sha256": canonical_hash(request),
                     "exact_key": row["exact_key"]}
            response = self.client.query(
                query, min(LIMITS["forward_seconds"], remaining))
            row["worker_response"] = deepcopy(response)
            if response["status"] != "VALID":
                row["failure"] = response["status"]
                if response["status"] in ("TIMEOUT", "OOM", "ERROR"):
                    self.available = False
                raise ValueError("external_model_" + response["status"].lower())
            return response["scores"]

        adapter = ExternalLocalResearchPolicy(
            self.rules, scorer, model_id=self.model["id"],
            model_revision=self.model["revision"])
        rows = {}

        def decide(observation):
            started = time.perf_counter()
            key = adapter.inspect_lookup(observation).get("information_key")
            if key is not None and key in rows:
                row = rows[key]
                row["cache_calls"] += 1
                result = adapter(observation)
                row["cache_latency_ms"].append((time.perf_counter() - started) * 1000)
                self.sink(self.games)
                return result
            row = {"index": len(game["opportunities"]),
                   "street": observation.get("street"),
                   "observation": deepcopy(observation), "request": None,
                   "exact_key": None, "action": None, "worker_response": None,
                   "failure": None, "first_decision_ms": None, "timely": False,
                   "cache_calls": 0, "cache_latency_ms": []}
            game["observing_seat"] = observation.get("observing_seat")
            game["opportunities"].append(row)
            current["row"] = row
            self.sink(self.games)
            try:
                row["request"] = adapter.prepare_request(observation)
                row["exact_key"] = encode_decision_v2(observation)["exact_key"]
                action = adapter(observation)
                if row["worker_response"].get("action") != action:
                    raise ValueError("worker_action_score_mismatch")
                row["action"] = action
                rows[key] = row
                return action
            except Exception as exc:
                row["failure"] = row["failure"] or str(exc)
                raise
            finally:
                row["first_decision_ms"] = (time.perf_counter() - started) * 1000
                row["timely"] = (row["action"] is not None
                                 and row["first_decision_ms"] <= LIMITS["timely_ms"]
                                 and row["worker_response"]["elapsed_ms"]
                                 <= LIMITS["timely_ms"])
                self.sink(self.games)
        return decide


def validate_opportunity(opportunity, rules, model, *, complete):
    """Recompute menu, exact input and timing classifications from raw receipts."""
    obs = opportunity["observation"]
    if opportunity["street"] != obs["street"]:
        raise ValueError("opportunity_street_mismatch")
    count = opportunity["cache_calls"]
    latencies = opportunity["cache_latency_ms"]
    if (type(count) is not int or count < 0 or count != len(latencies)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   or value < 0 for value in latencies)):
        raise ValueError("invalid_repeat_cache_receipt")
    if opportunity["request"] is not None:
        adapter = ExternalLocalResearchPolicy(
            rules, lambda request: None, model_id=model["id"],
            model_revision=model["revision"])
        if (adapter.prepare_request(obs) != opportunity["request"]
                or encode_decision_v2(obs)["exact_key"] != opportunity["exact_key"]):
            raise ValueError("opportunity_input_identity_mismatch")
    action = opportunity["action"]
    if complete and action is None:
        raise ValueError("complete_opportunity_action_missing")
    timely = False
    if action is not None:
        response = opportunity["worker_response"]
        if (response["status"] != "VALID" or response["action"] != action
                or opportunity["failure"] is not None
                or opportunity["request"] is None):
            raise ValueError("successful_opportunity_response_mismatch")
        ids = [row["id"] for row in opportunity["request"]["options"]]
        if screen.select_action(response["scores"], ids) != action:
            raise ValueError("opportunity_action_scores_mismatch")
        elapsed = (opportunity["first_decision_ms"], response["elapsed_ms"])
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
               for value in elapsed):
            raise ValueError("invalid_first_decision_timing")
        timely = all(value <= LIMITS["timely_ms"] for value in elapsed)
        if complete and count != 1:
            raise ValueError("completed_opportunity_repeat_probe_missing")
    if opportunity["timely"] is not timely:
        raise ValueError("opportunity_timely_classification_mismatch")


def evaluate_shard(shard, manifest, client, *, deadline, sink):
    rules = AARuleProfileV2.from_dict(manifest["rules"][str(shard["table_size"])])
    policy = WorkerBackedResearchPolicy(
        rules, manifest["models"][shard["model"]], client, deadline=deadline, sink=sink)
    result = evaluate_paired(
        rules, policy, check_call_policy,
        {shard["opponent"]: OPPONENTS[shard["opponent"]]},
        seeds=[shard["seed"]], candidate_id=manifest["models"][shard["model"]]["id"],
        baseline_id="check_call", bootstrap_samples=LIMITS["bootstrap_samples"],
        bootstrap_seed=LIMITS["bootstrap_seed"], policy_seed=shard["policy_seed"],
        max_actions=LIMITS["max_actions"], record_diagnostics=True)
    if len(policy.games) != shard["table_size"]:
        raise ValueError("candidate_game_receipt_count_mismatch")
    for row, game in zip(result["rows"], policy.games):
        row["local_model_receipt"] = game
        row["timely_complete"] = (
            row["status"] == "COMPLETE"
            and all(item["timely"] for item in game["opportunities"]))
    return result, policy.available


def _load_client(spec, manifest, batch, output, state, deadline, client_factory):
    attempts = batch["models"][spec["id"]]["loads"]
    if len(attempts) >= LIMITS["max_load_attempts_per_model_per_batch"]:
        return None
    attempt = {"index": len(attempts), "status": "STARTED", "warmup": None}
    attempts.append(attempt)
    screen._atomic(output / "state.json", state)
    client = None
    started = time.perf_counter()
    try:
        client = client_factory(
            spec, manifest["upstream"], runtime=manifest["runtime_identity"])
        ready = client.receive(
            min(LIMITS["load_seconds"], deadline - time.perf_counter()))
        attempt["ready"] = ready
        if ready["status"] != "READY":
            raise ValueError("model_load_" + ready["status"])
        screen.validate_ready(
            ready, spec, manifest["upstream"], manifest["runtime_identity"])
        attempt["warmup"] = client.query(
            manifest["warmup"],
            min(LIMITS["warmup_seconds"], deadline - time.perf_counter()))
        if attempt["warmup"]["status"] != "VALID":
            raise ValueError("model_warmup_" + attempt["warmup"]["status"])
        attempt["status"] = "READY"
        return client
    except Exception as exc:
        attempt.update(status="FAILED", reason=str(exc))
        if client is not None:
            client.close()
        return None
    finally:
        attempt["elapsed_ms"] = (time.perf_counter() - started) * 1000
        screen._atomic(output / "state.json", state)


def _read_state(output, manifest):
    state = read_json(output / "state.json")
    if state.get("manifest_sha256") != manifest["sha256"]:
        raise ValueError("state_manifest_mismatch")
    descriptors = {shard["id"]: shard for shard in manifest["shards"]}
    ids = set(descriptors)
    if set(state["committed"]) - ids or set(state["attempts"]) - ids:
        raise ValueError("unknown_state_shard")
    for name, digest in state["committed"].items():
        if canonical_hash(read_json(output / "shards" / (name + ".json"))) != digest:
            raise ValueError("committed_shard_changed")
    # Atomic shard rename may precede the state update. Recover it, never replay.
    for path in (output / "shards").glob("*.json"):
        if path.stem not in ids:
            raise ValueError("unknown_committed_shard")
        record = read_json(path)
        validate_shard_record(record, descriptors[path.stem], manifest)
        state["committed"].setdefault(path.stem, canonical_hash(record))
    return state


def commit_failed(output, manifest, state, shard, batch, reason):
    """Consume a failed first attempt permanently; retain its partial receipts."""
    attempts = state["attempts"][shard["id"]]
    journal = output / "attempts" / attempts[-1]["file"]
    games = read_json(journal).get("games", []) if journal.exists() else []
    rows = []
    for hero in range(shard["table_size"]):
        game = games[hero] if hero < len(games) else {
            "index": hero, "observing_seat": None, "opportunities": []}
        rows.append({"hero": hero, "status": "BLOCKED", "delta_bb": None,
                     "seed": shard["seed"], "table_size": shard["table_size"],
                     "opponent": shard["opponent"],
                     "timely_complete": False, "local_model_receipt": game,
                     "candidate": {"status": "BLOCKED", "error": reason,
                                   "return_chips": None},
                     "baseline": {"status": "NOT_ASSESSED", "return_chips": None}})
    result = {"status": "BLOCKED", "expected_pairs": shard["table_size"],
              "blocked_pairs": shard["table_size"], "complete_pairs": 0, "rows": rows,
              "failure": reason}
    record = {"manifest_sha256": manifest["sha256"], "shard": shard, "batch": batch,
              "result": result, "attempt_files": [row["file"] for row in attempts]}
    screen._atomic(output / "shards" / (shard["id"] + ".json"), record)
    state["committed"][shard["id"]] = canonical_hash(record)
    attempts[-1].update(
        status="INTERRUPTED" if reason == "BLOCKED_INTERRUPTED" else "FAILED",
        reason=reason)


def validate_shard_record(record, shard, manifest):
    """Check protocol and all seat identities before recovery or aggregation."""
    if (record.get("manifest_sha256") != manifest["sha256"]
            or record.get("shard") != shard):
        raise ValueError("shard_manifest_mismatch")
    result = record["result"]
    n = shard["table_size"]
    rows = result["rows"]
    if [row["hero"] for row in rows] != list(range(n)):
        raise ValueError("shard_hero_identity_mismatch")
    interrupted = "failure" in result
    if interrupted and (result["status"] != "BLOCKED"
                        or any(row["status"] != "BLOCKED" for row in rows)):
        raise ValueError("interrupted_shard_cannot_be_complete")
    if not interrupted:
        protocol = result["protocol"]
        required = {"seeds": [shard["seed"]], "opponents": [shard["opponent"]],
                    "candidate_id": manifest["models"][shard["model"]]["id"],
                    "baseline_id": "check_call", "rules": manifest["rules"][str(n)],
                    "policy_seed": shard["policy_seed"],
                    "max_actions": LIMITS["max_actions"],
                    "bootstrap_samples": LIMITS["bootstrap_samples"],
                    "bootstrap_seed": LIMITS["bootstrap_seed"]}
        if (any(protocol.get(key) != value for key, value in required.items())
                or result["protocol_sha256"] != canonical_hash(protocol)):
            raise ValueError("shard_evaluation_protocol_mismatch")
        depth = Fraction(manifest["rules"][str(n)]["big_blind"]) * 100
        if (set(protocol["starting_stacks"]) != {str(hero) for hero in range(n)}
                or any(Fraction(value) != depth
                       for value in protocol["starting_stacks"].values())):
            raise ValueError("shard_starting_stack_mismatch")
    for row in rows:
        if any(row.get(key) != shard[key]
               for key in ("table_size", "seed", "opponent")):
            raise ValueError("shard_row_identity_mismatch")
        if row["status"] not in ("COMPLETE", "BLOCKED"):
            raise ValueError("invalid_shard_row_status")
        left, right = row["candidate"], row["baseline"]
        if row["status"] == "COMPLETE":
            if left["status"] != "COMPLETE" or right["status"] != "COMPLETE":
                raise ValueError("incomplete_paired_branch")
            expected = (_fraction(left["return_chips"])
                        - _fraction(right["return_chips"]))
            expected /= Fraction(manifest["rules"][str(n)]["big_blind"])
            if _fraction(row["delta_bb"]) != expected:
                raise ValueError("paired_return_delta_mismatch")
        elif row["delta_bb"] is not None:
            raise ValueError("blocked_pair_has_ev")
        game = row["local_model_receipt"]
        if (game["index"] != row["hero"]
                or game["observing_seat"] not in (None, row["hero"])):
            raise ValueError("model_game_receipt_identity_mismatch")
        opportunities = game["opportunities"]
        if row["status"] == "COMPLETE" and not opportunities:
            raise ValueError("complete_hero_opportunities_missing")
        if [item["index"] for item in opportunities] != list(range(len(opportunities))):
            raise ValueError("opportunity_indices_mismatch")
        if not interrupted:
            diagnostic = left["hero_opportunities"]
            if (len(diagnostic) != len(opportunities)
                    or any(item["street"] != receipt["street"] for item, receipt in
                           zip(diagnostic, opportunities))):
                raise ValueError("evaluator_hero_opportunities_mismatch")
        for opportunity in opportunities:
            obs = opportunity["observation"]
            if obs["actor"] != row["hero"] or obs["observing_seat"] != row["hero"]:
                raise ValueError("model_opportunity_actor_mismatch")
            validate_opportunity(
                opportunity, AARuleProfileV2.from_dict(manifest["rules"][str(n)]),
                manifest["models"][shard["model"]],
                complete=row["status"] == "COMPLETE")
        if row["timely_complete"] != (row["status"] == "COMPLETE" and all(
                opportunity["timely"] for opportunity in game["opportunities"])):
            raise ValueError("timely_complete_receipt_mismatch")
    complete = sum(row["status"] == "COMPLETE" for row in rows)
    if (result["expected_pairs"] != n or result["complete_pairs"] != complete
            or result["blocked_pairs"] != n - complete
            or result["status"] != ("COMPLETE" if complete == n else "BLOCKED")):
        raise ValueError("shard_pair_denominator_mismatch")


def run_batch(output, *, batch_seconds=2400, client_factory=screen.WorkerClient,
              asset_verifier=screen.verify_assets):
    if type(batch_seconds) is not int or not 1 <= batch_seconds <= MAX_BATCH_SECONDS:
        raise ValueError("invalid_batch_budget")
    started = time.perf_counter()
    deadline = started + batch_seconds - min(25, batch_seconds / 5)
    output = Path(output)
    with exclusive(output):
        manifest = load_manifest(output)
        state = _read_state(output, manifest)
        if len(state["batches"]) >= LIMITS["max_batches"]:
            raise ValueError("frozen_batch_limit_reached")
        if state["active_shard"] is not None:
            old = state["active_shard"]
            if old["id"] not in state["committed"]:
                shard = next(s for s in manifest["shards"] if s["id"] == old["id"])
                commit_failed(output, manifest, state, shard, old["batch"],
                              "BLOCKED_INTERRUPTED")
            else:
                state["attempts"][old["id"]][-1]["status"] = "COMMITTED"
            state["active_shard"] = None
        for previous in state["batches"]:
            if previous["status"] == "RUNNING":
                previous["status"] = "INTERRUPTED"
        batch = {"index": len(state["batches"]), "status": "RUNNING",
                 "models": {spec["id"]: {"loads": [], "asset_status": "NOT_RUN"}
                            for spec in manifest["models"]}, "elapsed_seconds": None}
        state["batches"].append(batch)
        screen._atomic(output / "state.json", state)
        client, current_model = None, None
        try:
            for shard in manifest["shards"]:
                if shard["id"] in state["committed"]:
                    continue
                if time.perf_counter() >= deadline:
                    break
                attempts = state["attempts"].setdefault(shard["id"], [])
                if attempts:
                    continue
                spec = manifest["models"][shard["model"]]
                model_state = batch["models"][spec["id"]]
                if current_model != shard["model"]:
                    if client is not None:
                        client.close()
                    client, current_model = None, shard["model"]
                    try:
                        asset_verifier(spec, manifest["upstream"])
                        model_state["asset_status"] = "READY"
                    except Exception as exc:
                        model_state.update(
                            asset_status="MODEL_NOT_READY", reason=str(exc))
                    screen._atomic(output / "state.json", state)
                if model_state["asset_status"] != "READY":
                    continue
                if client is None:
                    client = _load_client(spec, manifest, batch, output, state,
                                          deadline, client_factory)
                if client is None:
                    continue
                attempt_path = (output / "attempts"
                                / f"{shard['id']}-b{batch['index']}.json")
                attempt = {"batch": batch["index"], "status": "RUNNING",
                           "file": attempt_path.name}
                attempts.append(attempt)
                state["active_shard"] = {"id": shard["id"], "batch": batch["index"]}
                screen._atomic(output / "state.json", state)

                def sink(games):
                    screen._atomic(attempt_path, {
                        "manifest_sha256": manifest["sha256"], "shard": shard,
                        "batch": batch["index"], "games": games})

                sink([])
                try:
                    result, available = evaluate_shard(
                        shard, manifest, client, deadline=deadline, sink=sink)
                    record = {"manifest_sha256": manifest["sha256"], "shard": shard,
                              "batch": batch["index"], "result": result,
                              "attempt_files": [row["file"] for row in attempts]}
                    validate_shard_record(record, shard, manifest)
                    screen._atomic(output / "shards" / (shard["id"] + ".json"), record)
                    state["committed"][shard["id"]] = canonical_hash(record)
                    attempt["status"] = "COMMITTED"
                    if not available:
                        client.close()
                        client = None
                except Exception as exc:
                    commit_failed(output, manifest, state, shard, batch["index"],
                                  "SHARD_EXECUTION_FAILED:" + str(exc))
                    client.close()
                    client = None
                state["active_shard"] = None
                batch["elapsed_seconds"] = time.perf_counter() - started
                screen._atomic(output / "state.json", state)
            batch["status"] = "FINISHED"
        finally:
            if client is not None:
                client.close()
            batch["elapsed_seconds"] = time.perf_counter() - started
            screen._atomic(output / "state.json", state)
            write_report(output, manifest=manifest, state=state)
        return state


def _fraction(value):
    return Fraction(value["numerator"], value["denominator"])


def write_report(output, *, manifest=None, state=None):
    output = Path(output)
    manifest = manifest or load_manifest(output)
    state = state or _read_state(output, manifest)
    groups, all_rows = [], []
    for model in range(2):
        for n in (6, 7, 8):
            for opponent in OPPONENTS:
                shards = [s for s in manifest["shards"]
                          if (s["model"], s["table_size"], s["opponent"])
                          == (model, n, opponent)]
                rows, clusters, interrupted = [], [], 0
                streets = {s: {"observed": 0, "valid": 0, "timely": 0, "failed": 0}
                           for s in ("preflop", "flop", "turn", "river")}
                for shard in shards:
                    interrupted += sum(a["status"] in ("INTERRUPTED", "FAILED")
                                       for a in state["attempts"].get(shard["id"], []))
                    if shard["id"] not in state["committed"]:
                        attempted = bool(state["attempts"].get(shard["id"]))
                        history = [batch["models"][manifest["models"][model]["id"]]
                                   for batch in state["batches"]]
                        unavailable = any(
                            entry["asset_status"] == "MODEL_NOT_READY"
                            or (len(entry["loads"]) >= 2 and all(
                                load["status"] == "FAILED" for load in entry["loads"]))
                            for entry in history)
                        pending = ("BLOCKED_INTERRUPTED" if attempted else
                                   "NOT_RUN_MODEL_UNAVAILABLE" if unavailable
                                   else "NOT_RUN")
                        rows.extend({"shard": shard["id"], "hero": hero,
                                     "status": pending, "timely_complete": False,
                                     "delta_bb": None} for hero in range(n))
                        continue
                    record = read_json(output / "shards" / (shard["id"] + ".json"))
                    validate_shard_record(record, shard, manifest)
                    branch_rows = record["result"]["rows"]
                    if len(branch_rows) != n:
                        raise ValueError("committed_pair_denominator_mismatch")
                    if all(row["status"] == "COMPLETE" for row in branch_rows):
                        clusters.append(float(sum(_fraction(row["delta_bb"])
                                                  for row in branch_rows) / n * 100))
                    for row in branch_rows:
                        opportunities = row["local_model_receipt"]["opportunities"]
                        for opportunity in opportunities:
                            stats = streets[opportunity["street"]]
                            stats["observed"] += 1
                            stats["valid"] += opportunity["action"] is not None
                            stats["timely"] += opportunity["timely"]
                            stats["failed"] += opportunity["action"] is None
                        rows.append({"shard": shard["id"], "hero": row["hero"],
                                     "status": row["status"],
                                     "delta_bb": row["delta_bb"],
                                     "timely_complete": row["timely_complete"]})
                expected = len(shards) * n
                complete = sum(row["status"] == "COMPLETE" for row in rows)
                timely = sum(row["timely_complete"] for row in rows)
                metrics = (complete == expected and len(clusters) == len(shards)
                           and not interrupted)
                groups.append({
                    "model": manifest["models"][model]["id"], "table_size": n,
                    "opponent": opponent, "expected_pairs": expected,
                    "complete_pairs": complete, "timely_complete_pairs": timely,
                    "complete_fraction": complete / expected,
                    "timely_complete_fraction": timely / expected,
                    "prior_failed_or_interrupted_attempts": interrupted,
                    "blocked_pairs": sum(row["status"].startswith("BLOCKED")
                                         for row in rows),
                    "not_run_pairs": sum(row["status"].startswith("NOT_RUN")
                                         for row in rows),
                    "streets": streets,
                    "delta_net_bb100": (sum(clusters) / len(clusters)
                                        if metrics else None),
                    "ci95_delta_net_bb100": _cluster_interval(
                        clusters, LIMITS["bootstrap_samples"], LIMITS["bootstrap_seed"])
                    if metrics else None,
                    "evidence": "SYNTHETIC_DIAGNOSTIC_NOT_STRENGTH_ACCEPTANCE",
                })
                all_rows.extend(rows)
    report = {"manifest_sha256": manifest["sha256"],
              "expected_pairs": manifest["expected_pairs"],
              "reported_pairs": len(all_rows), "groups": groups, "pairs": all_rows,
              "complete_pairs": sum(g["complete_pairs"] for g in groups),
              "timely_complete_pairs": sum(g["timely_complete_pairs"] for g in groups),
              "batches": state["batches"], "strategy_eligible": False,
              "advice_emitted": False, "overall_ev": None,
              "strategy_qualification": (
                  "NOT_ASSESSED_REQUIRES_SEPARATE_SANITY_AND_STRENGTH"),
              "latency_scope": "LOCAL_POLICY_ONLY_NOT_CAPTURE_TO_DISPLAY",
              "opportunity_scope": "OBSERVED_PREFIX_SUFFIX_UNKNOWN_AFTER_FAILURE"}
    if report["reported_pairs"] != report["expected_pairs"]:
        raise ValueError("whole_study_denominator_mismatch")
    report["execution_status"] = ("COMPLETE" if report["complete_pairs"]
                                  == report["expected_pairs"] else "PARTIAL")
    screen._atomic(output / "report.json", report)
    return report


def supervised_run(output, batch_seconds=2400):
    if type(batch_seconds) is not int or not 1 <= batch_seconds <= MAX_BATCH_SECONDS:
        raise ValueError("invalid_batch_budget")
    output = Path(output).resolve()
    invocation = uuid.uuid4().hex
    started = time.perf_counter()
    result = screen.run_bounded(
        [sys.executable, "-m", "tools.evaluate_aa_local_fullhands", "_run",
         "--output", str(output), "--batch-seconds", str(batch_seconds)],
        seconds=batch_seconds - min(10, batch_seconds / 5), cwd=ROOT,
        log_path=output / ("batch-" + invocation + ".log"))
    result["helper_elapsed_seconds"] = result["elapsed_seconds"]
    result["elapsed_seconds"] = time.perf_counter() - started
    result["clock"] = screen.clock_identity()
    screen._atomic(output / ("supervisor-" + invocation + ".json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "_run", "report"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-08b", type=Path)
    parser.add_argument("--model-2b", type=Path)
    parser.add_argument("--upstream-package", type=Path)
    parser.add_argument("--batch-seconds", type=int, default=2400)
    args = parser.parse_args()
    if args.phase == "freeze":
        if None in (args.model_08b, args.model_2b, args.upstream_package):
            parser.error("freeze requires both model paths and upstream package")
        manifest = freeze(args.output, args.model_08b, args.model_2b,
                          args.upstream_package)
        print(json.dumps({"manifest_sha256": manifest["sha256"], "pairs": 3780}))
    elif args.phase == "run":
        print(json.dumps(supervised_run(args.output, args.batch_seconds)))
    elif args.phase == "report":
        with exclusive(args.output):
            report = write_report(args.output)
        print(json.dumps({"pairs": report["reported_pairs"],
                          "complete": report["complete_pairs"]}))
    else:
        run_batch(args.output, batch_seconds=args.batch_seconds)


if __name__ == "__main__":
    main()
