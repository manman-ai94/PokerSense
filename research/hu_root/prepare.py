"""Prepare three synthetic TOML inputs; never starts an external program."""
import argparse
import json
from pathlib import Path

from .adapter import config_digest, config_toml, expected_root_actions, request_config
from .fixtures import CASES, native_root


def prepare_files(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for case in CASES:
        _, context = native_root(case)
        config = request_config(context)
        path = destination / (case.name + ".toml")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(config_toml(config))
        records.append({
            "name": case.name, "config_sha256": config_digest(config),
            "board": config["board"], "starting_pot_chips": case.pot,
            "per_player_stack_chips": case.stack, "BB_chips": 2,
            "street": context.street.value, "dealt": 2, "active": 2,
            "positive_live_combos": [len(context.hero_range.combo_weights),
                                     len(context.villain_ranges[0].combo_weights)],
            "model_ROOT_actions": [(kind, str(amount) if amount is not None else None)
                                   for kind, amount in expected_root_actions(config)],
            "status": "PREPARED_NOT_RUN", "new_solves": 0,
        })
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps({"cases": prepare_files(args.output), "solver_executions": 0},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
