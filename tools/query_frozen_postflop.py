"""Query the reviewed frozen synthetic river via an opt-in offline entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.strategy.frozen_postflop import (  # noqa: E402
    DEFAULT_SOLUTION,
    FrozenLookupError,
    FrozenPostflopProvider,
    MAX_REQUEST_BYTES,
    decode_request,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--solution", type=Path, default=DEFAULT_SOLUTION)
    parser.add_argument("--hero-combo", help="Override only the example hero combo")
    args = parser.parse_args(argv)
    try:
        with args.request.open("rb") as stream:
            request = decode_request(stream.read(MAX_REQUEST_BYTES + 1))
        if args.hero_combo is not None:
            if type(request) is not dict or type(request.get("decision")) is not dict:
                raise FrozenLookupError("decision_schema_mismatch")
            request["decision"]["hero_combo"] = args.hero_combo
        response = FrozenPostflopProvider(args.solution).query_json(request)
    except (OSError, FrozenLookupError) as exc:
        reason = (str(exc) if isinstance(exc, FrozenLookupError)
                  else "request_unavailable")
        response = {"schema_version": 1, "type": "FrozenPostflopResponse",
                    "status": "REJECTED", "reasons": [reason], "candidate": None,
                    "advice_emitted": False, "strategy_eligible": False,
                    "live_eligible": False}
    print(json.dumps(response, indent=2, allow_nan=False))
    return 0 if response["status"] == "HIT_EXACT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
