"""The AA mushroom pool: the dealer posts, the small blind takes it with the pot."""

import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.mushroom import Mushroom, pool_result, small_blind
from poker_engine.scoreboard.runner import play_hand, run_scoreboard
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


def rules():
    return AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))


def test_the_carried_pool_is_drawn_per_deal_with_its_long_run_spread():
    mushroom = Mushroom(post=3, take=0.25)
    assert mushroom.pool(11, 2.0) == mushroom.pool(11, 2.0)
    pools = [mushroom.pool(seed, 2.0) for seed in range(20000)]
    assert {post for post, _ in pools} == {6.0}
    carried = [carry for _, carry in pools]
    assert all(carry % 6 == 0 for carry in carried)
    # k posts with chance 0.25 * 0.75 ** k: on average 3 posts.
    assert sum(carried) / len(carried) == pytest.approx(18, rel=0.05)
    assert sum(carry == 0 for carry in carried) / len(carried) == pytest.approx(
        0.25, abs=0.01)
    with pytest.raises(ValueError):
        Mushroom(post=3, take=0)


def scripted(moves):
    """Deciders that play ``moves[seat]`` (an action id) or check/call."""
    def decider(seat):
        def decide(observation):
            seen.append(observation)
            legal = {action["id"] for action in observation["legal_actions"]}
            move = moves.get(seat, "check_call")
            return move if move in legal else "check_call"
        return decide
    seen = []
    return {seat: decider(seat) for seat in range(8)}, seen


def test_the_dealer_pays_and_the_small_blind_wins_the_pool_with_the_pot():
    arena = AAFullHandArena(rules())
    sb, dealer = small_blind(arena), arena.dealer_seat
    mushroom = Mushroom(post=3, take=0.5)
    post, carried = mushroom.pool(5, 2.0)
    # Everyone but the small blind folds: it wins the pot and the pool.
    moves = {seat: "fold" for seat in range(8) if seat != sb}
    deciders, seen = scripted(moves)
    without = {seat: play_hand(arena, 5, deciders, seat)[0] for seat in range(8)}
    deciders, seen = scripted(moves)
    with_pool = {seat: play_hand(arena, 5, deciders, seat, mushroom=mushroom)[0]
                 for seat in range(8)}
    assert with_pool[sb] - without[sb] == pytest.approx(carried + post)
    assert with_pool[dealer] - without[dealer] == pytest.approx(-post)
    assert all(with_pool[seat] == without[seat] for seat in range(8)
               if seat not in (sb, dealer))
    assert {row["mushroom_pool"] for row in seen} == {f"{carried + post:g}"}
    # The small blind folds: the dealer still pays, nobody takes the pool.
    deciders, _ = scripted({sb: "fold"})
    assert play_hand(arena, 5, deciders, sb, mushroom=mushroom)[0] == play_hand(
        arena, 5, scripted({sb: "fold"})[0], sb)[0]


def test_fewer_than_four_players_have_no_pool():
    def table(seats):
        return SimpleNamespace(occupied_seats=seats, dealer_seat=seats[-1],
                               _seats=seats[1:-1] + seats[:1] + seats[-1:])
    four, three = table((0, 1, 2, 3)), table((0, 1, 2))
    shares = {0: 0.5, 1: 0.5}
    assert pool_result(four, Mushroom(), 12.0, 6.0, 1, shares) == 9.0
    assert pool_result(four, Mushroom(), 12.0, 6.0, 3, shares) == -6.0
    assert pool_result(three, Mushroom(), 12.0, 6.0, 1, shares) == 0.0
    assert pool_result(three, Mushroom(), 12.0, 6.0, 2, shares) == 0.0


def test_a_blind_policy_does_not_see_the_pool():
    class Seen:
        def decide(self, observation, rng):
            return sorted(observation)
    blind = make_policy("nomushroom+always_call")
    blind.base = Seen()
    assert "mushroom_pool" not in blind.decide({"mushroom_pool": "6", "pot": "9"},
                                               random.Random(0))


def test_the_report_names_the_pool_and_the_small_blind_plays_for_it():
    report = run_scoreboard(rules(), ["aa_preflop", "nomushroom+aa_preflop"], deals=6,
                            base_seed=2, reference="nomushroom+aa_preflop",
                            pool=("aa_population",), mushroom=Mushroom())
    assert report["mushroom"] == {"post_big_blinds": 3.0, "take": 0.135}
    plain = run_scoreboard(rules(), ["aa_preflop", "nomushroom+aa_preflop"], deals=6,
                           base_seed=2, reference="nomushroom+aa_preflop",
                           pool=("aa_population",))
    assert plain["mushroom"] is None
    # Without the pool, the blind policy is the policy.
    assert plain["versus_reference"]["aa_preflop"]["delta_bb_per_100"] == 0
