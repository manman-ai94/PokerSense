"""Reading preflop ranges with slow play: a limp-raise is not a medium hand.

All hands here are synthetic: an eight-seat 2/4/8(4) table, 100 big blinds
(400 chips) each.
"""

from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
import random

import pytest

from poker_engine.scoreboard.bots import _rng, make_policy, raise_toward
from poker_engine.scoreboard.population import PopulationBot, actions
from poker_engine.scoreboard.preflop_policy import (AAPreflopPolicy, PreflopParams,
                                                    equity_table)
from poker_engine.scoreboard.preflop_reading import (BLUFF, HONEST, SLOWPLAY,
                                                     PopulationReader, Range,
                                                     reading_model, split)
from poker_engine.scoreboard.ranges import opponent_ranges
from poker_engine.scoreboard.replay import public_replay, replay_deck
from poker_engine.scoreboard.solver_bot import kept
from poker_engine.scoreboard.strength import (DECK, class_combos, hand_class,
                                              preflop_percentile)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
TWO_FOUR = {**json.loads(RULES.read_text(encoding="utf-8")),
            "small_blind": "2", "big_blind": "4", "straddle_amount": "8", "ante": "4"}
HANDS = {}
for first, second in combinations(DECK, 2):
    HANDS.setdefault(hand_class((first, second)), [first, second])
PREMIUM = ("AA", "KK", "QQ", "AKs", "AKo")
HONEST_POLICY = PreflopParams(slowplay=0.0, bluff=0.0)


def table(script, stack=400):
    """The decision after ``script`` at 2/4/8(4); seat 3 acts first (after
    the straddle, seat 2), the dealer is seat 7. Each step is "c" (check or
    call), "f" (fold) or a raise of that share of the pot."""
    arena = AAFullHandArena(AARuleProfileV2.from_dict(TWO_FOUR),
                            starting_stacks={seat: stack for seat in range(8)})
    arena.reset(3)
    for step in script:
        observation = arena.observe(arena.actor)
        arena.step({"c": "check_call", "f": "fold"}.get(step)
                   or raise_toward(observation, step))
    return arena.observe(arena.actor)


# Seat 3 limps; you raise; seat 3 re-raises. Your seat, then the spot.
LIMP_RAISES = {
    # You raise from the button, the limper re-raises the pot (or 3x).
    "button": ["c", "f", "f", "f", 0.5, "f", "f", "f", 1.0],
    "button_3x": ["c", "f", "f", "f", 0.5, "f", "f", "f", 0.6],
    # Two limpers; the first re-raises, the second still to act.
    "two_limpers": ["c", "c", "f", "f", 0.5, "f", "f", "f", 1.0, "f"],
    # The cutoff raises the limp, you call on the button, the limper re-raises
    # and the cutoff folds.
    "called_a_raise": ["c", "f", "f", 0.5, "c", "f", "f", "f", 1.0, "f"],
    # You raise from the straddle (out of position).
    "straddle": ["c", "f", "f", "f", "f", "f", "f", 0.5, 1.0],
}


def limp_raise(name="button"):
    observation = table(LIMP_RAISES[name])
    assert [kind for actor, kind in actions(observation, "preflop")
            if actor == 3][:2] == ["c", "r"]
    return observation


def choose(observation, hand, params=None):
    policy = AAPreflopPolicy(params) if params else AAPreflopPolicy()
    return policy.choose({**observation, "own_hole": HANDS[hand]})


def flat(hands):
    return [value for part in hands.parts for value in part]


def by_class(weights):
    result = defaultdict(float)
    for key, weight in weights.items():
        result[hand_class((key[:2], key[2:]))] += weight
    return result


# -- ranges -------------------------------------------------------------------

def test_a_range_splits_strongest_first_by_weight():
    hands = Range([(0.0, 0.2, 0.5), (0.2, 0.6, 1.0)])
    assert hands.mass() == pytest.approx(0.5)
    assert flat(hands.cut(0.0, 0.05)) == pytest.approx([0.0, 0.1, 0.5])
    assert flat(hands.cut(0.05, 0.2)) == pytest.approx([0.1, 0.2, 0.5, 0.2, 0.3, 1.0])
    parts = split(hands, 0.2, 0.4, slowplay=0.0)
    assert parts["r"].mass() == pytest.approx(0.1)
    assert parts["c"].mass() == pytest.approx(0.2)
    assert parts["f"].mass() == pytest.approx(0.2)
    # Slow play: the raising hands are in the calls at that much weight.
    slow = split(hands, 0.2, 0.4, slowplay=0.4)
    assert slow["c"].weight(0.1) == pytest.approx(0.2)
    assert slow["c"].mass() == pytest.approx(0.2 + 0.4 * 0.1)
    # Bluffs: a fifth of the raises come from the hands that call or fold,
    # at the same weight per hand.
    bluffing = split(hands, 0.2, 0.4, slowplay=0.0, bluff=0.2)
    assert bluffing["r"].mass() == pytest.approx(0.1 / 0.8)
    assert bluffing["r"].weight(0.55) > 0
    assert bluffing["r"].weight(0.35) == pytest.approx(bluffing["r"].weight(0.55))


def test_the_honest_split_is_the_band_the_population_model_plays():
    # One band, no slow play: the same cut as low + share x width.
    hands = Range([(0.2, 0.6, 1.0)])
    parts = split(hands, 0.25, 0.5, slowplay=0.0)
    assert flat(parts["r"]) == pytest.approx([0.2, 0.3, 1.0])
    assert flat(parts["c"]) == pytest.approx([0.3, 0.5, 1.0])


def test_equity_against_a_weighted_range_is_the_weighted_average():
    table_ = equity_table()
    aces, rest = 6 / 1326, 0.3
    mixed = Range([(0.0, aces, 1.0), (0.1, rest, 1.0)])
    alone = table_.versus_range("KK", Range([(0.0, aces, 1.0)]))
    assert alone == pytest.approx(table_.versus("KK", 0.0, aces))
    assert alone < table_.versus_range("KK", mixed) < table_.versus("KK", 0.1, rest)


def test_a_reading_model_gives_chances_and_kept_multiplies_by_them():
    observation = limp_raise()
    limp = next(d for d in public_replay(observation) if d.seat == 3)
    every = {"AhAs": 1.0, "KhQd": 1.0, "7d2c": 1.0}
    weights = kept(every, limp, lambda obs: PopulationReader(adjusted=True).decide(
        obs, _rng("test", obs)))
    assert weights["AhAs"] == pytest.approx(SLOWPLAY)      # slow-played aces
    assert weights["KhQd"] == 1.0 and "7d2c" not in weights
    honest = kept(every, limp, lambda obs: PopulationBot(adjusted=True).decide(
        obs, _rng("test", obs)))
    assert set(honest) == {"KhQd"}


def test_without_slow_play_or_bluffs_the_reading_is_the_population_model():
    rules = AARuleProfileV2.from_dict(TWO_FOUR)
    arena = AAFullHandArena(rules)
    pool = make_policy("aa_population")
    honest, model = PopulationReader(adjusted=True, slowplay=0.0, bluff=0.0), \
        PopulationBot(adjusted=True)
    rng = random.Random(4)
    checked = 0
    for seed in range(30):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            if observation["street"] != "preflop":
                break
            can_raise = any(a["kind"] == "raise_to"
                            for a in observation["legal_actions"])
            for cards in (rng.sample(DECK, 2) for _ in range(20)):
                seen = {**observation, "own_hole": cards}
                chances = honest.decide(seen, None)
                if chances and can_raise:   # in the range it got here with
                    action = model.decide(seen, None)
                    kind = "f" if action == "fold" else \
                        "r" if action.startswith("raise_to") else "c"
                    assert chances == {kind: 1.0}
                    checked += 1
            arena.step(pool.decide(observation, _rng("pool", observation)))
    assert checked > 1000


def test_the_scoreboard_players_still_play_honestly():
    assert type(make_policy("aa_population")) is PopulationBot
    assert type(reading_model(True, HONEST)) is PopulationBot
    reader = make_policy("range_multiway@hu=1+aa_preflop").model
    assert isinstance(reader, PopulationReader) and reader.adjusted
    assert reader.reading == (SLOWPLAY, BLUFF)
    old = make_policy("range_multiway@hu=1+aa_preflop@slowplay=0:bluff=0").model
    assert type(old) is PopulationBot
    assert isinstance(make_policy("solver_turn+aa_preflop").model, PopulationReader)


# -- the limp-raise -----------------------------------------------------------

def test_a_limp_raise_range_holds_the_big_hands():
    observation = {**limp_raise(), "own_hole": ["2c", "3d"]}
    honest = by_class(opponent_ranges(observation, PopulationBot(adjusted=True))[3])
    # The old reading: only medium hands (A7s, A8s, A9o, KQo), no big ones.
    assert set(honest) == {"A7s", "A8s", "A9o", "KQo"}
    weights = by_class(opponent_ranges(observation, PopulationReader(adjusted=True))[3])
    total = sum(weights.values())
    for name in PREMIUM:
        assert weights[name] > 0
    # Aces, kings, queens and big slick make up about a third of it ...
    assert 0.25 < sum(weights[name] for name in PREMIUM) / total < 0.45
    # ... every combination of them as likely as any hand in the range ...
    per_combo = {name: weight / class_combos(name) for name, weight in weights.items()}
    assert per_combo["AA"] == pytest.approx(max(per_combo.values()))
    # ... the medium hands the old reading kept are a small part, and a few
    # weak hands are in as bluffs (a fifth of the weight is hands that would
    # call or fold, spread evenly).
    assert (weights["A9o"] + weights["KQo"]) / total < 0.05
    weak = sum(weight for name, weight in weights.items()
               if preflop_percentile(HANDS[name]) > 0.3)
    assert 0.05 < weak / total < 0.2


def test_hands_that_would_call_can_limp_raise_too():
    # The bluffs come from the hands that call the raise as well as from
    # those that fold: KQs, KJs or 66 limp-raise now and then (shown on AA
    # tables), each combination far less often than aces.
    weights = by_class(opponent_ranges({**limp_raise(), "own_hole": ["2c", "3d"]},
                                       PopulationReader(adjusted=True))[3])
    per_combo = {name: weight / class_combos(name) for name, weight in weights.items()}
    for name in ("KQs", "KJs", "66", "KQo"):
        assert 0 < per_combo[name] < per_combo["AA"] / 5


def shove_over_a_re_raise():
    """Seat 3 limps, the button raises, seat 3 re-raises, the button raises
    again and seat 3 goes all in, 112 big blinds deep: the button has 159 to
    call into 779 (needs 17%)."""
    arena = AAFullHandArena(AARuleProfileV2.from_dict(TWO_FOUR),
                            starting_stacks={seat: 450 for seat in range(8)})
    arena.reset(3)
    for step in ["c", "f", "f", "f", 0.5, "f", "f", "f", 1.0, 0.2]:
        seen = arena.observe(arena.actor)
        arena.step({"c": "check_call", "f": "fold"}.get(step)
                   or raise_toward(seen, step))
    seen = arena.observe(arena.actor)
    arena.step(max((a for a in seen["legal_actions"] if a["kind"] == "raise_to"),
                   key=lambda a: float(a["raise_to"]))["id"])
    observation = arena.observe(arena.actor)
    assert [kind for actor, kind in actions(observation, "preflop")
            if actor == 3] == ["c", "r", "r"]
    assert observation["observing_seat"] == 7
    assert float(observation["to_call"]) == 159
    return observation


def test_an_all_in_after_a_limp_raise_is_not_only_aces_and_kings():
    observation = shove_over_a_re_raise()
    weights = by_class(opponent_ranges({**observation, "own_hole": ["2c", "3d"]},
                                       PopulationReader(adjusted=True))[3])
    total = sum(weights.values())
    # Mostly aces and kings still, but a fifth of it is the rest of the
    # limp-raise range: queens, jacks, AK, AQ and a few bluffs.
    assert 0.5 < (weights["AA"] + weights["KK"]) / total < 0.8
    for name in ("QQ", "JJ", "TT", "AKo", "AQs"):
        assert weights[name] > 0
    # So a hand that needs 17% calls by price; it folded against aces and
    # kings alone.
    assert choose(observation, "KQo")["action"] == "check_call"
    for hand in ("AA", "QQ", "JJ"):
        assert choose(observation, hand)["action"] == "check_call"


def test_call_then_re_raise_keeps_the_big_hands_too():
    # The cutoff opens, the button calls, the small blind 3-bets, the button
    # re-raises (call_vs_3bet): the button's range has the slow-played hands.
    observation = table(["f", "f", "f", 0.5, "c", 1.0, "f", "f", "f", 1.0])
    history = actions(observation, "preflop")
    assert history[-1] == (7, "r") and (7, "c") in history
    weights = by_class(opponent_ranges({**observation, "own_hole": ["2c", "3d"]},
                                       PopulationReader(adjusted=True))[7])
    total = sum(weights.values())
    assert sum(weights[name] for name in PREMIUM) / total > 0.25


@pytest.mark.parametrize("spot", ["button", "button_3x"])
@pytest.mark.parametrize("hand", ["KQo", "AQs"])
def test_medium_hands_call_a_limp_raise_rather_than_shove(spot, hand):
    observation = limp_raise(spot)
    old = choose(observation, hand, HONEST_POLICY)
    new = choose(observation, hand)
    if hand == "AQs":
        assert old["action"].startswith("raise_to")       # the old all in
    assert not new["action"].startswith("raise_to")
    assert new["values"]["raise"] < old["values"]["raise"]


@pytest.mark.parametrize("spot", sorted(LIMP_RAISES))
@pytest.mark.parametrize("hand", ["A9o", "QJo", "A3s"])
def test_weaker_hands_never_re_raise_a_limp_raise(spot, hand):
    observation = limp_raise(spot)
    choice = choose(observation, hand)
    assert not choice["action"].startswith("raise_to")
    assert choice["values"]["raise"] < max(choice["values"]["call"], 0.0)


@pytest.mark.parametrize("spot", sorted(LIMP_RAISES))
@pytest.mark.parametrize("hand", ["AA", "KK"])
def test_aces_and_kings_still_get_it_in(spot, hand):
    observation = limp_raise(spot)
    choice = choose(observation, hand)
    assert choice["action"].startswith("raise_to")
    assert choice["raise_to"] == max(float(a["raise_to"])
                                     for a in observation["legal_actions"]
                                     if a["kind"] == "raise_to")


def test_after_calling_a_limp_raise_the_flop_is_played_against_big_hands():
    """You raise from the straddle and call the limp-raise; you act first on
    a king-high flop, against the range read before the flop."""
    from poker_engine.scoreboard.ranges import ranges_equity
    arena = AAFullHandArena(AARuleProfileV2.from_dict(TWO_FOUR),
                            starting_stacks={seat: 400 for seat in range(8)})
    arena.reset(3, deck=replay_deck([{"cards": ["Kc", "7d", "2s"]}], 8))
    for step in LIMP_RAISES["straddle"] + ["c"]:
        observation = arena.observe(arena.actor)
        arena.step({"c": "check_call", "f": "fold"}.get(step)
                   or raise_toward(observation, step))
    observation = arena.observe(arena.actor)
    assert observation["street"] == "flop" and observation["observing_seat"] == 2
    shares = {}
    for hole in (("Kd", "Qh"), ("Ad", "Qh")):
        seen = {**observation, "own_hole": list(hole)}
        for name, model in (("old", PopulationBot(adjusted=True)),
                            ("new", PopulationReader(adjusted=True))):
            shares[hole[0][0], name], _ = ranges_equity(
                hole, seen["board"], opponent_ranges(seen, model), trials=4000, seed=1)
    # Top pair still ahead of most of it (pairs below, bluffs), not of all.
    assert shares["K", "new"] < shares["K", "old"] - 0.04
    # Ace high was a coin flip against the medium hands; now it is behind.
    assert shares["A", "old"] > 0.45 and shares["A", "new"] < 0.4


def test_a_wrapped_policy_reads_with_its_base_parameters():
    from poker_engine.scoreboard.bots import make_policy
    from poker_engine.scoreboard.preflop_reading import reading_of
    assert reading_of(make_policy("noreads+aa_preflop@slowplay=0:bluff=0")) == (0, 0)
