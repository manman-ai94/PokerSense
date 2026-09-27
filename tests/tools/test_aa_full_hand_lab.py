import json

import pytest

from tools.aa_full_hand_lab import (
    DEFAULT_PROTOCOL, DEFAULT_RULES, main, read_json, rules_for, run_training,
)


def test_cli_full_street_smoke_and_exclusive_output(tmp_path):
    output = tmp_path / "run"
    assert main(["smoke", "--players", "8", "--hands", "1",
                 "--output", str(output)]) == 0
    report = read_json(output / "report.json")
    assert set(report["hands"][0]["streets"]) == {"preflop", "flop", "turn", "river"}
    assert not report["strategy_eligible"]
    with pytest.raises(FileExistsError):
        main(["smoke", "--output", str(output)])


def test_training_cli_checkpoint_is_scope_bound_and_resumable(tmp_path):
    output = tmp_path / "train"
    main(["train", "--players", "6", "--depth", "4", "--iterations", "1",
          "--seconds", "15", "--output", str(output)])
    report = read_json(output / "report.json")
    assert report["status"] == "COMPLETE_RESEARCH_RUN"
    saved = read_json(output / "checkpoint.json")
    assert saved == read_json(output / "latest-checkpoint.json")
    assert saved["trainer"]["binding"] == saved["binding"]
    changed = json.loads(json.dumps(saved))
    changed["binding"]["stack_depth_bb"] = "100"
    with pytest.raises(ValueError, match="binding"):
        run_training(rules_for(DEFAULT_RULES, 6), depth=100,
                     protocol=read_json(DEFAULT_PROTOCOL), iterations=1, seed=1103,
                     seconds=15, max_nodes=10000, max_infosets=100000, resume=changed)


def test_zero_completed_sweep_is_not_reported_as_trained_success(tmp_path):
    output = tmp_path / "blocked"
    main(["train", "--max-nodes", "1", "--output", str(output)])
    report = read_json(output / "report.json")
    assert report["status"] == "BUDGET_EXHAUSTED"
    assert report["completed_sweeps_total"] == 0
    assert report["policy_infosets"] == 0
    assert read_json(output / "policy.json")["status"] == "research_only"
