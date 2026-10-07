"""The AA preflop policy: equity table, values, and play that follows the table."""

from itertools import combinations
import json
from pathlib import Path

import pytest

from poker_engine.core.enums import Position
from poker_engine.scoreboard.bots import make_policy, position, raise_toward
from poker_engine.scoreboard.population import (MAX_CONTINUE, MIN_AA_DECISIONS,
                                                aa_factors, preflop_shares)
from poker_engine.scoreboard.preflop_policy import (AAPreflopPolicy, PreflopParams,
                                                    equity_table, from_name,
                                                    multiway, rake)
from poker_engine.scoreboard.strength import DECK, class_combos, hand_class
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

CONFIGS = Path(__file__).resolve().parents[2] / "configs/game"
RAKED = json.loads((CONFIGS / "aa-scoreboard-rules-v2.json")
                   .read_text(encoding="utf-8"))
HANDS = {}
for first, second in combinations(DECK, 2):
    HANDS.setdefault(hand_class((first, second)), [first, second])


def first_decision(rules=RAKED, seed=3):
    arena = AAFullHandArena(AARuleProfileV2.from_dict(rules))
    arena.reset(seed)
    return arena, arena.observe(arena.actor)


def with_hand(observation, name, **extra):
    return {**observation, "own_hole": HANDS[name], **extra}


def opened_share(policy, observation):
    """Share of all starting hands (by combinations) the policy raises."""
    raised = sum(class_combos(name) for name in HANDS
                 if policy.choose(with_hand(observation, name))["action"]
                 .startswith("raise_to"))
    return raised / 1326


def test_equity_table_matches_known_matchups():
    table = equity_table()
    row = table.index
    assert table.equity[row["AA"]][row["KK"]] == pytest.approx(0.82, abs=0.01)
    assert table.equity[row["AKs"]][row["KK"]] == pytest.approx(0.34, abs=0.01)
    assert table.versus("AA", 0, 1) == pytest.approx(0.852, abs=0.005)
    assert table.versus("72o", 0, 1) == pytest.approx(0.346, abs=0.005)
    # A band holding exactly the aces is the aces row, less card removal.
    assert table.versus("AKs", 0, 6 / 1326) == pytest.approx(
        table.equity[row["AKs"]][row["AA"]], abs=1e-9)
    # Against a strong range a hand does worse than against everything.
    assert table.versus("AKo", 0, 0.05) < table.versus("AKo", 0, 1)


def test_multiway_share_combines_heads_up_equities():
    assert multiway([0.6]) == pytest.approx(0.6)
    assert multiway([0.5, 0.5]) == pytest.approx(1 / 3)
    assert multiway([0.85, 0.85]) == pytest.approx(0.739, abs=0.01)


def test_rake_is_five_percent_rounded_down_and_capped():
    observation = {"rules": RAKED}
    assert rake(observation, 23) == 1
    assert rake(observation, 59) == 2
    assert rake(observation, 1000) == 10
    assert rake({"rules": {**RAKED, "rake_percent": "0"}}, 1000) == 0


def test_parameters_come_from_the_name():
    policy = from_name("aa_preflop@realize_ip=0.9:suited=0.1")
    assert policy.params == PreflopParams(realize_ip=0.9, suited=0.1)
    assert policy.adjusted and not from_name("aa_preflop_phh").adjusted
    assert make_policy("aa_preflop@crowd=0").params.crowd == 0
    with pytest.raises(ValueError):
        from_name("aa_preflop@speed=3")


def test_values_rank_strong_hands_above_weak_ones():
    _, observation = first_decision()
    policy = AAPreflopPolicy()
    aces = policy.choose(with_hand(observation, "AA"))
    trash = policy.choose(with_hand(observation, "72o"))
    assert aces["action"].startswith("raise_to") and aces["raise_to"]
    assert aces["values"]["raise"] > trash["values"]["raise"]
    assert trash["action"] == "fold"


def test_weak_hands_fold_to_an_all_in_and_aces_call():
    arena, observation = first_decision()
    jam = max((a for a in observation["legal_actions"] if a["kind"] == "raise_to"),
              key=lambda a: float(a["raise_to"]))
    arena.step(jam["id"])
    facing = arena.observe(arena.actor)
    policy = AAPreflopPolicy()
    assert policy.choose(with_hand(facing, "72o"))["action"] == "fold"
    assert policy.choose(with_hand(facing, "AA"))["action"] == "check_call"


def test_more_dead_money_opens_more_hands():
    no_ante = {**RAKED, "ante": "0", "ante_mode": "none"}
    _, small = first_decision(no_ante)
    _, large = first_decision()
    policy = AAPreflopPolicy()
    assert opened_share(policy, large) > opened_share(policy, small)


def test_a_mushroom_pool_widens_the_small_blind():
    arena, observation = first_decision()
    arena.step(raise_toward(observation, 0.5))       # first to act opens
    while position(arena.observe(arena.actor)) != Position.SB:
        arena.step("fold")
    facing = arena.observe(arena.actor)
    policy = AAPreflopPolicy()

    def continued(view):
        return sum(class_combos(name) for name in HANDS
                   if policy.choose(with_hand(view, name))["action"] != "fold")

    pooled = {**facing, "mushroom_pool": "60"}
    assert continued(pooled) > continued(facing)
    assert (policy.choose(with_hand(pooled, "72o"))["values"]["call"]
            > policy.choose(with_hand(facing, "72o"))["values"]["call"])


def test_aa_players_are_fitted_only_where_enough_was_seen():
    data = json.loads((Path(__file__).resolve().parents[2]
                       / "src/poker_engine/scoreboard/aa_preflop_stats_v1.json")
                      .read_text(encoding="utf-8"))
    fitted = {spot for spot, row in data["spots"].items()
              if row["n"] >= MIN_AA_DECISIONS}
    assert set(aa_factors()) <= fitted and "vs_open" in aa_factors()
    # AA players call an open more often than the 2009 players did ...
    assert preflop_shares("CO", "vs_open", True)[1] > preflop_shares("CO", "vs_open")[1]
    # ... and scaled shares never leave room for no folds at all.
    for name in ("SB", "BB", "EP", "BTN"):
        for spot in aa_factors():
            assert sum(preflop_shares(name, spot, True)) <= MAX_CONTINUE + 1e-9


def test_the_solver_strategy_can_sit_on_another_base():
    bot = make_policy("solver_turn+aa_preflop")
    assert bot.name == "solver_turn+aa_preflop"
    assert isinstance(bot.base, AAPreflopPolicy)
    assert bot.model.adjusted          # reads opponents as AA players
    plain = make_policy("solver_turn")
    assert type(plain.base).__name__ == "RfiTablePolicy" and not plain.model.adjusted
    split = make_policy("solver_turn+rfi_table/population")
    assert split.base.name == "rfi_table/population"
