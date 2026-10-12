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
                                                    Table, equity_table, from_name,
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


def test_decisions_are_kept_per_situation_and_hand_class():
    _, observation = first_decision()
    policy = AAPreflopPolicy()
    first = policy.choose({**observation, "own_hole": ["Ah", "Kh"]})
    first["values"]["raise"] = -1.0          # a caller's change stays its own
    again = policy.choose({**observation, "own_hole": ["Ad", "Kd"]})
    assert again == policy._choose({**observation, "own_hole": ["Ad", "Kd"]})
    assert again["values"]["raise"] != -1.0


def test_weak_hands_fold_to_an_all_in_and_aces_call():
    arena, observation = first_decision()
    jam = max((a for a in observation["legal_actions"] if a["kind"] == "raise_to"),
              key=lambda a: float(a["raise_to"]))
    arena.step(jam["id"])
    facing = arena.observe(arena.actor)
    policy = AAPreflopPolicy()
    assert policy.choose(with_hand(facing, "72o"))["action"] == "fold"
    assert policy.choose(with_hand(facing, "AA"))["action"] == "check_call"


def jam_first(stacks, then=()):
    """The first player (seat 3) goes all in; ``then``: the next actions."""
    arena = AAFullHandArena(AARuleProfileV2.from_dict(RAKED), starting_stacks=stacks)
    arena.reset(3)
    observation = arena.observe(arena.actor)
    jam = max((a for a in observation["legal_actions"] if a["kind"] == "raise_to"),
              key=lambda a: float(a["raise_to"]))
    arena.step(jam["id"])
    for step in then:
        observation = arena.observe(arena.actor)
        arena.step(step(observation) if callable(step) else step)
    return arena.observe(arena.actor)


DEEP_BEHIND_JAM = {seat: 500 for seat in range(8)} | {3: 222}     # 111 bb jam, 250 bb
SHORT_JAMS = [{seat: 200 for seat in range(8)} | {3: short} for short in (24, 40)]


@pytest.mark.parametrize("stacks", [DEEP_BEHIND_JAM, *SHORT_JAMS])
@pytest.mark.parametrize("hand", ["Q7o", "72o", "64o"])
def test_weak_hands_do_not_raise_over_an_all_in(stacks, hand):
    facing = with_hand(jam_first(stacks, ["fold"]), hand)
    assert facing["observing_seat"] == 5 and facing["stacks"]["3"] == "0"
    choice = AAPreflopPolicy().choose(facing)
    # The raise is possible, but the all-in player is still in the pot.
    assert choice["raise_to"] is not None
    assert choice["values"]["raise"] < 0
    assert choice["action"] == "fold"


@pytest.mark.parametrize("stacks", [DEEP_BEHIND_JAM, *SHORT_JAMS])
def test_aces_still_play_for_stacks_over_an_all_in(stacks):
    facing = with_hand(jam_first(stacks, ["fold"]), "AA")
    choice = AAPreflopPolicy().choose(facing)
    assert choice["values"]["call"] > 0 and choice["values"]["raise"] > 0
    assert choice["action"].startswith("raise_to")


def test_a_raise_over_an_all_in_is_not_won_outright():
    facing = with_hand(jam_first(DEEP_BEHIND_JAM, ["fold"]), "72o")
    table = Table(facing, PreflopParams())
    target = table.raise_action()[1]
    # Even if everyone behind folds, the hand still has to beat the jammer.
    nobody_calls = table.field({3: table.band(3)}, [], target - table.bets[5])
    assert nobody_calls < 0 < table.won(table.pot + table.to_call, 1.0)


def short_all_in_raised_over(hand="AA"):
    stacks = {seat: 200 for seat in range(8)} | {3: 44, 4: 600}
    return with_hand(jam_first(stacks, [lambda o: raise_toward(o, 1.0)]), hand)


def test_a_call_counts_a_short_all_in_that_was_raised_over():
    facing = short_all_in_raised_over()
    assert facing["stacks"]["3"] == "0" and facing["bets"]["3"] == "42"
    assert float(facing["stacks"]["4"]) > 0
    table = Table(facing, PreflopParams())
    assert 3 not in table.behind() and table.bets[3] < table.top
    seen = []
    showdown = table.showdown
    table.showdown = lambda mine, levels, *rest: (seen.append(set(levels)),
                                                  showdown(mine, levels, *rest))[1]
    with_short = table.call_value()
    assert seen and all({3, 4} <= players for players in seen)
    # The same chips in the middle with the short player folded instead:
    # one opponent fewer to beat, so the call is worth more.
    folded = {**facing, "folded": [*facing["folded"], 3]}
    assert Table(folded, PreflopParams()).call_value() > with_short + 1


def test_side_pots_go_only_to_the_players_who_covered_them():
    facing = short_all_in_raised_over()
    table = Table(facing, PreflopParams())
    top = table.top
    dead = table.pot - sum(table.bets.values())
    assert dead == 16                                   # the eight antes
    # Seats 0-2 (blinds and straddle) fold; the hand calls the raise.
    pots = table.pots(top, {3: 42.0, 4: top})
    assert all(players == [3, 4, 5] for _, players, _ in pots[:4])
    main = sum(chips for chips, players, _ in pots if 3 in players)
    side = sum(chips for chips, players, _ in pots if 3 not in players)
    assert main == dead + 1 + 2 + 4 + 3 * 42
    assert side == 2 * (top - 42) and pots[-1][1] == [4, 5]
    assert not any(refund for _, _, refund in pots)
    # A short player sure to win takes only the main pot: the hand still
    # gets half the side pot from an even opponent, less its part of the rake.
    total = main + side
    back = table.showdown(top, {3: 42.0, 4: top}, {3: 1e9, 4: 1.0}, 1.0)
    assert back == pytest.approx(0.5 * (side - rake(facing, total) * side / total),
                                 rel=1e-6)
    # Raising 100 more with only the short player in (seat 4 folds): its
    # chips are won outright, the 100 nobody matched come back without rake.
    pots = table.pots(top + 100, {3: 42.0})
    assert pots[-1] == (100.0, [5], True)
    assert pots[-2] == (2 * (top - 42), [5], False)
    raked = main + 2 * (top - 42)
    back = table.showdown(top + 100, {3: 42.0}, {3: 1e9}, 1.0)
    assert back == pytest.approx(
        100 + 2 * (top - 42) * (1 - rake(facing, raked) / raked), rel=1e-6)


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
