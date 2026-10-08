"""Review: the scoreboard's per-strategy decision counts.

``score_deals`` reports, per strategy, the counts its policy object keeps
(for example how often range_multiway decided or fell back). The policy
objects are shared by name between the hero and the opponent pool, so in a
pool made of the strategy itself ("mirror") the hero's counts include every
opponent's decisions.
"""

from collections import Counter
import json
from pathlib import Path

from poker_engine.scoreboard import runner
from poker_engine.scoreboard.bots import _Policy

RULES = json.loads((Path(__file__).resolve().parents[2]
                    / "configs/game/aa-scoreboard-rules-v2.json").read_text(
                        encoding="utf-8"))


class Counting(_Policy):
    """Checks or calls every time and counts its decisions."""

    def __init__(self, name):
        self.name = name
        self.counts = Counter()

    def decide(self, observation, rng):
        self.counts["decided"] += 1
        return "check_call"


def test_decision_counts_count_only_the_strategys_own_decisions(monkeypatch):
    monkeypatch.setattr(runner, "make_policy", Counting)
    seeds = [1_000_000, 1_000_001]
    # The same play twice: the pool is the strategy itself, or an identical
    # policy under another name. The hero's decisions are the same.
    _, mirror = runner.score_deals(RULES, ("hero",), ("hero",), seeds, 1)
    _, twin = runner.score_deals(RULES, ("hero",), ("twin",), seeds, 1)
    assert twin["hero"]["decided"] > 0
    assert mirror["hero"] == twin["hero"]
