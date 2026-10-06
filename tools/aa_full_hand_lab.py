"""Bounded offline arena/train/evaluate CLI. Never captures, pays, or deploys."""
from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import time

from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from poker_engine.strategy.aa_frozen_policy import FrozenResearchPolicy, canonical_hash
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_arena_evaluation import (
    check_call_policy, check_fold_policy, min_raise_policy, pot_raise_policy,
    evaluate_paired,
)
from poker_engine.strategy.aa_mccfr import (
    ExternalSamplingMCCFR, TrainingBudget, TrainingBudgetExceeded,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = ROOT / "configs/game/aa-shadow-rules-v2.json"
DEFAULT_PROTOCOL = ROOT / "configs/strategy/evaluation/aa-full-hand-protocol-v1.json"


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True,
                  indent=2, allow_nan=False)
        stream.write("\n")


def checkpoint_writer(directory):
    def save(value):
        temporary = directory / "latest-checkpoint.pending.json"
        target = directory / "latest-checkpoint.json"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
        temporary.replace(target)
    return save


def rules_for(path, players):
    data = read_json(path)
    data["table_size"] = players
    rules = AARuleProfileV2.from_dict(data)
    if rules.verification_status != "simulation":
        raise ValueError("lab_requires_simulation_rules")
    return rules


def provenance(rules, depth, protocol):
    return {"rules": rules.to_dict(), "rules_fingerprint": rules.fingerprint,
            "stack_depth_bb": str(depth), "protocol_sha256": canonical_hash(protocol),
            "source_kind": "AA_ARENA_SYNTHETIC_V1",
            "strategy_eligible": False, "advice_emitted": False,
            "real_hand_acceptance": "PENDING", "empirical_strength": "NOT_ASSESSED"}


def run_training(rules, *, depth, protocol, iterations, seed, seconds, max_nodes,
                 max_infosets, resume=None, checkpoint_sink=None):
    binding = provenance(rules, depth, protocol)
    kwargs = {"budget": TrainingBudget(
        max_nodes=max_nodes, max_infosets=max_infosets, seconds=seconds)}
    if resume is None:
        trainer = ExternalSamplingMCCFR(
            range(rules.table_size), seed=seed, binding=binding, **kwargs)
    else:
        if resume.get("binding") != binding:
            raise ValueError("checkpoint_rules_depth_or_protocol_mismatch")
        trainer = ExternalSamplingMCCFR.restore(
            resume["trainer"], expected_binding=binding, **kwargs)
        if trainer.seed != seed:
            raise ValueError("checkpoint_seed_mismatch")
        if trainer.players != tuple(range(rules.table_size)):
            raise ValueError("checkpoint_players_mismatch")
    stacks = (rules.big_blind * Decimal(str(depth)),) * rules.table_size

    def factory(deal_seed):
        # Disjoint numeric domain from frozen evaluation/confirmation deals.
        return AAFullHandArena(rules, starting_stacks=stacks).reset(
            (deal_seed % (2 ** 62)) + 2 ** 62,
        )

    deadline = time.monotonic() + seconds
    attempts = []
    for _ in range(iterations):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            attempts.append({"status": "BUDGET_EXHAUSTED", "reason": "run_deadline"})
            break
        trainer.budget = replace(trainer.budget, seconds=remaining)
        try:
            row = trainer.iterate(factory)
            attempts.append({"status": "COMPLETE", **row})
            if checkpoint_sink is not None:
                checkpoint_sink({"binding": binding, "trainer": trainer.checkpoint()})
        except TrainingBudgetExceeded as exc:
            attempts.append({"status": "BUDGET_EXHAUSTED", "reason": str(exc),
                             "discarded_nodes": trainer.last_attempt_nodes})
            break
    complete = len(attempts) == iterations and all(
        row["status"] == "COMPLETE" for row in attempts)
    result = {"binding": binding, "attempts": attempts,
              "status": "COMPLETE_RESEARCH_RUN" if complete else "BUDGET_EXHAUSTED",
              "completed_sweeps_total": trainer.iterations,
              "policy_infosets": len(trainer.average_policy()),
              "strategy_quality": "NOT_ASSESSED", "promotion": "NOT_REQUESTED"}
    checkpoint = {"binding": binding, "trainer": trainer.checkpoint()}
    return result, checkpoint, trainer.export(
        rules_fingerprint=rules.fingerprint, table_size=rules.table_size,
        stack_depth_bb=depth,
    )


def smoke(rules, hands):
    summaries = []
    for seed in range(hands):
        arena = AAFullHandArena(rules).reset(seed)
        opportunities, streets = 0, set()
        while not arena.terminal:
            if opportunities >= 1000:
                raise ValueError("smoke_hand_action_budget")
            obs = arena.observe(arena.actor)
            streets.add(obs["street"])
            arena.step(check_call_policy(obs))
            opportunities += 1
        returns = arena.terminal_returns()
        summaries.append({"seed": seed, "opportunities": opportunities,
                          "streets": sorted(streets),
                          "net_chips": {str(k): str(v) for k, v in returns.items()},
                          "total_fee_chips": str(-sum(returns.values()))})
    return {"table_size": rules.table_size, "rules_fingerprint": rules.fingerprint,
            "hands": summaries, "strategy_eligible": False,
            "status": "ENGINE_SMOKE_ONLY", "strategy_strength": "NOT_ASSESSED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("smoke", "train", "evaluate"))
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--players", type=int, choices=(6, 7, 8), default=8)
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hands", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1103)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--max-nodes", type=int, default=10000)
    parser.add_argument("--max-infosets", type=int, default=100000)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--blocks", type=int)
    args = parser.parse_args(argv)
    if min(args.depth, args.hands, args.iterations) <= 0:
        parser.error("counts and depth must be positive")
    rules = rules_for(args.rules, args.players)
    protocol = read_json(args.protocol)
    if protocol.get("protocol_id") != "AA_FULL_HAND_PROSPECTIVE_V1":
        parser.error("unknown protocol")
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "protocol.json", protocol)
    write_new(args.output / "rules.json", rules.to_dict())
    if args.command == "smoke":
        report = smoke(rules, args.hands)
    elif args.command == "train":
        report, checkpoint, policy = run_training(
            rules, depth=args.depth, protocol=protocol,
            iterations=args.iterations, seed=args.seed, seconds=args.seconds,
            max_nodes=args.max_nodes, max_infosets=args.max_infosets,
            resume=read_json(args.resume) if args.resume else None,
            checkpoint_sink=checkpoint_writer(args.output),
        )
        write_new(args.output / "checkpoint.json", checkpoint)
        write_new(args.output / "policy.json", policy)
    else:
        if args.candidate is None:
            parser.error("evaluate requires --candidate")
        document = read_json(args.candidate)
        if document.get("stack_depth_bb") != str(args.depth):
            parser.error("candidate starting depth mismatch")
        frozen = FrozenResearchPolicy(document)
        blocks = (args.blocks if args.blocks is not None else
                  protocol["paired_blocks_per_player_count_per_opponent"])
        if blocks <= 0:
            parser.error("blocks must be positive")
        start = protocol["evaluation_seed_start"]
        report = evaluate_paired(
            rules, frozen, check_fold_policy,
            {"check_call": check_call_policy, "min_raise": min_raise_policy,
             "pot_raise": pot_raise_policy},
            seeds=list(range(start, start + blocks)), candidate_id=frozen.sha256,
            baseline_id="check_fold_v1",
            bootstrap_samples=protocol["bootstrap_samples"],
            starting_stacks=(rules.big_blind * args.depth,) * rules.table_size,
        )
        report["protocol_sample_complete"] = (
            blocks == protocol["paired_blocks_per_player_count_per_opponent"])
        report["promotion"] = (
            "BLOCKED_PENDING_MULTI_SEED_AND_INDEPENDENT_CONFIRMATION")
    write_new(args.output / "report.json", report)
    print(json.dumps({"report": str((args.output / "report.json").resolve()),
                      "status": report.get("status"), "strategy_eligible": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
