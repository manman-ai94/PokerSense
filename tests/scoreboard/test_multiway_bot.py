"""Playing multiway pots after the flop by equity against every opponent's range."""

import json
from pathlib import Path
import random

import pytest

from poker_engine.scoreboard import multiway_bot
from poker_engine.scoreboard.bots import (_rng, make_policy, opponents_in_hand,
                                          raise_toward)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


class Base:
    adjusted = True

    def decide(self, observation, rng):
        return "base"


def spots(count=40):
    """Postflop observations from simulated AA hands: (heads-up, heads-up flop
    checked to, multiway checked to, multiway facing a bet)."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena, pool = AAFullHandArena(rules), make_policy("aa_population")
    found = {}
    for seed in range(count):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            if observation["street"] != "preflop":
                others = opponents_in_hand(observation)
                price = float(observation["to_call"] or 0)
                kind = ("heads_up" if others == 1 else
                        "facing" if price > 0 else "checked_to")
                found.setdefault(kind, observation)
                if others == 1 and price == 0 and observation["street"] == "flop":
                    found.setdefault("heads_up_flop", observation)
            if len(found) == 4:
                return found
            arena.step(pool.decide(observation, _rng("test", observation)))
    raise AssertionError(f"only found {sorted(found)}")


@pytest.fixture(scope="module")
def table():
    return spots()


def bot_with(monkeypatch, share, **params):
    monkeypatch.setattr(multiway_bot, "opponent_ranges", lambda observation, model: {})
    monkeypatch.setattr(multiway_bot, "ranges_equity",
                        lambda *args, **kwargs: (share, {}))
    return multiway_bot.RangeMultiwayBot(Base(), **params)


def test_only_multiway_pots_after_the_flop_are_played_by_range(monkeypatch, table):
    bot = bot_with(monkeypatch, 0.9)
    assert bot.decide(table["heads_up"], random.Random(0)) == "base"
    assert bot.decide(table["checked_to"], random.Random(0)) != "base"
    assert bot.counts["decided"] == 1


def test_bet_when_ahead_of_the_field_else_check(monkeypatch, table):
    spot = table["checked_to"]
    assert bot_with(monkeypatch, 0.45).decide(spot, random.Random(0)).startswith(
        "raise_to")
    assert bot_with(monkeypatch, 0.35).decide(spot, random.Random(0)).startswith(
        "raise_to")                             # the line is 0.3 since 2026-10-09
    assert bot_with(monkeypatch, 0.25).decide(spot, random.Random(0)) == "check_call"


def test_the_bet_is_the_pot_into_three_or_more_opponents(monkeypatch, table):
    spot = table["checked_to"]
    others = [seat for seat in spot["occupied_seats"]
              if seat != spot["observing_seat"]]
    two = {**spot, "folded": others[2:]}
    three = {**spot, "folded": others[3:]}
    assert opponents_in_hand(two) == 2 and opponents_in_hand(three) == 3
    pot, two_thirds = raise_toward(three, 1.0), raise_toward(two, 0.66)
    assert pot != two_thirds
    assert bot_with(monkeypatch, 0.9).decide(three, random.Random(0)) == pot
    assert bot_with(monkeypatch, 0.9).decide(two, random.Random(0)) == two_thirds
    assert bot_with(monkeypatch, 0.9, size3=0.66).decide(
        three, random.Random(0)) == raise_toward(three, 0.66)


def test_facing_a_bet_raise_call_or_fold_by_the_price(monkeypatch, table):
    spot = table["facing"]
    to_call = float(spot["to_call"])
    price = to_call / (float(spot["pot"]) + to_call)
    assert bot_with(monkeypatch, 0.7).decide(spot, random.Random(0)).startswith(
        "raise_to") or not any(a["kind"] == "raise_to" for a in spot["legal_actions"])
    assert bot_with(monkeypatch, price + 0.01).decide(spot, random.Random(0)) == (
        "check_call")
    assert bot_with(monkeypatch, price - 0.01).decide(spot, random.Random(0)) == "fold"
    assert bot_with(monkeypatch, price + 0.01, margin=0.03).decide(
        spot, random.Random(0)) == "fold"


def test_no_equity_falls_back_to_the_base_policy(monkeypatch, table):
    bot = bot_with(monkeypatch, None)
    assert bot.decide(table["checked_to"], random.Random(0)) == "base"
    assert bot.counts["no_equity"] == 1


def test_parameters_come_with_the_name():
    bot = make_policy("range_multiway@bet=0.4:raise=0.6:margin=0+aa_preflop")
    assert bot.params == {**multiway_bot.DEFAULTS, "bet": 0.4, "raise": 0.6,
                          "margin": 0.0}
    assert bot.name == "range_multiway@bet=0.4:raise=0.6:margin=0+aa_preflop"
    assert make_policy("range_multiway+aa_preflop").params == multiway_bot.DEFAULTS
    with pytest.raises(ValueError):
        make_policy("range_multiway@width=1+aa_preflop")


def test_with_hu_the_heads_up_flop_is_played_with_its_own_cuts(monkeypatch, table):
    spot = table["heads_up_flop"]
    assert bot_with(monkeypatch, 0.9).decide(spot, random.Random(0)) == "base"
    assert bot_with(monkeypatch, 0.6, hu=1).decide(spot, random.Random(0)).startswith(
        "raise_to")
    assert bot_with(monkeypatch, 0.5, hu=1).decide(spot, random.Random(0)) == (
        "check_call")                          # a multiway pot bets from 0.3
    turn = {**spot, "street": "turn"}           # the solver plays heads-up turns
    assert bot_with(monkeypatch, 0.9, hu=1).decide(turn, random.Random(0)) == "base"
    assert bot_with(monkeypatch, 0.9, hu=2).decide(turn, random.Random(0)).startswith(
        "raise_to")                             # unless every street is asked for
    assert multiway_bot.street_params(spot, multiway_bot.DEFAULTS)["bet"] == 0.55


@pytest.mark.parametrize("hole, board, weak", [
    (["Ad", "Ts"], ["Tc", "2s", "7d", "8h", "Qc"], True),      # second pair, river
    (["Ad", "Ts"], ["Tc", "2s", "7d"], True),                   # top pair
    (["As", "Ts"], ["Jd", "6c", "Jh"], True),                   # the board's pair
    (["7h", "2c"], ["Kd", "Ks", "7s"], True),                   # a pair is the board's
    (["Ah", "2c"], ["Kd", "Ks", "5s", "5c", "9h"], True),        # the board's two pair
    (["Ah", "2c"], ["9d", "9s", "9h"], True),                   # the board's trips
    (["Ah", "2c"], ["3d", "4s", "5h", "6c", "7d"], True),        # the board's straight
    (["Kh", "7c"], ["Kd", "7s", "2h"], False),                  # two pair of your own
    (["9h", "9c"], ["Kd", "9s", "2h"], False),                  # a set
    (["Ah", "2c"], ["Ad", "As", "5h"], False),                  # trips with your ace
    (["Ah", "Kh"], ["2h", "7h", "Qh"], False),                  # a flush
    (["Ah", "Kh"], ["2h", "7h"], False),                        # before the flop
])
def test_weak_hand_is_one_pair_or_less_of_your_own(hole, board, weak):
    assert multiway_bot.weak_hand(hole, board) is weak


def guard_spot(street="river", pot=120, to_call=0, hole=("Ad", "Ts")):
    """A decision with your pair of tens; the big blind is 2."""
    board = {"flop": ["Tc", "2s", "7d"], "turn": ["Tc", "2s", "7d", "8h"],
             "river": ["Tc", "2s", "7d", "8h", "Qc"]}[street]
    bets = {"4": "0", "5": str(to_call)}
    raises = [pot // 2, pot, 400] if not to_call else [to_call * 3, 400]
    return {"street": street, "pot": str(pot), "to_call": str(to_call),
            "rules": {"big_blind": "2"}, "own_hole": list(hole), "board": board,
            "bets": bets, "occupied_seats": [4, 5], "folded": [],
            "legal_actions": [
                {"id": "check_call", "kind": "check_call"},
                *[{"id": f"raise_to:{to}", "kind": "raise_to", "raise_to": str(to)}
                  for to in raises]]}


def test_guard_holds_a_pair_back_in_a_big_pot():
    guard = multiway_bot.guard_action
    river = guard_spot("river", pot=120)                   # 60 big blinds
    assert multiway_bot.guarded(river) == 60
    assert guard(river, "raise_to:60", 1.0) == "check_call"        # no river bet
    turn = guard_spot("turn", pot=120)
    assert guard(turn, "raise_to:120", 0.9) == "raise_to:60"       # half the pot
    assert guard(turn, "raise_to:60", 0.9) == "raise_to:60"
    facing = guard_spot("turn", pot=120, to_call=40)               # price 0.25
    assert guard(facing, "raise_to:120", 0.9) == "check_call"      # call, no raise
    assert guard(facing, "raise_to:120", 0.2) == "fold"
    assert guard(facing, "fold", 0.2) == "fold"


def test_guard_leaves_small_pots_strong_hands_and_its_off_switch():
    guard = multiway_bot.guard_action
    small = guard_spot("river", pot=58)                    # 29 big blinds
    assert multiway_bot.guarded(small) is None
    assert guard(small, "raise_to:29", 1.0) == "raise_to:29"
    two_pair = guard_spot("river", pot=120, hole=("Ts", "8c"))
    assert guard(two_pair, "raise_to:60", 0.9) == "raise_to:60"
    river = guard_spot("river", pot=120)
    off = {**multiway_bot.DEFAULTS, "guard": 0}
    assert guard(river, "raise_to:60", 1.0, off) == "raise_to:60"
    assert multiway_bot.choose(river, 1.0) == "check_call"
    assert multiway_bot.unguarded(river, 1.0) == "raise_to:60"


def river_spot(table, hole, board=("Ad", "7c", "2d", "Js", "4h")):
    """The multiway spot checked to you, on a river you choose."""
    spot = table["checked_to"]
    return {**spot, "street": "river", "own_hole": list(hole), "board": list(board)}


def opponents_of(spot):
    return [seat for seat in spot["occupied_seats"]
            if seat not in spot["folded"] and seat != spot["observing_seat"]]


def test_strengths_rank_every_hand_against_random_ones():
    board = ("Ad", "7c", "2d", "Js", "4h")
    one = multiway_bot.strengths(board, 1)
    ids = multiway_bot.CARD_ID
    nuts = one[(ids["3c"], ids["5c"])]                     # the straight
    air = one[(ids["6s"], ids["8h"])]                      # lower card first
    assert nuts > 0.99 and air < 0.1
    assert len(one) == 47 * 46 // 2
    three = multiway_bot.strengths(board, 3)
    pair = (ids["9s"], ids["Ac"])
    assert three[pair] == pytest.approx(one[pair] ** 3)


def test_bets_from_a_quarter_to_one_and_a_half_pots_are_weighed():
    spot = {**guard_spot("turn", pot=120), "observing_seat": 4}   # half, pot, all in
    assert multiway_bot.candidates(spot) == {"raise_to:60": 60.0,
                                             "raise_to:120": 120.0}
    other = [{"id": f"raise_to:{to}", "kind": "raise_to", "raise_to": str(to)}
             for to in (10, 170)]
    short = {**spot, "legal_actions": [*spot["legal_actions"], *other]}
    assert set(multiway_bot.candidates(short)) == {"raise_to:60", "raise_to:120",
                                                   "raise_to:170"}


def test_a_bigger_bet_is_called_by_fewer_hands(table):
    spot = table["checked_to"]
    seat, pot = opponents_of(spot)[0], float(spot["pot"])
    lines = [multiway_bot.continue_line(spot, seat, put, pot + put)[0]
             for put in (0.5 * pot, pot, 3 * pot)]
    assert lines[0] <= lines[1] <= lines[2] and lines[0] < lines[2]
    sticky = {**multiway_bot.DEFAULTS, "sticky": 1.5}
    assert multiway_bot.continue_line(spot, seat, pot, 2 * pot, sticky)[0] < lines[1]


def test_value_bet_when_worse_hands_call_check_when_only_better_ones_do(table):
    spot = river_spot(table, ["3c", "5c"])                  # the nuts
    weaker = {"AcKc": 1.0, "AhQh": 1.0, "JdJh": 1.0}
    ranges = {seat: weaker for seat in opponents_of(spot)[:1]}
    everyone = {**multiway_bot.DEFAULTS, "sticky": 100.0}    # every hand calls
    worth = multiway_bot.values(spot, ranges, everyone)
    assert max(worth, key=worth.get) != "check_call"
    assert multiway_bot.sized(spot, 1.0, ranges, everyone).startswith("raise_to")
    behind = river_spot(table, ["Kh", "Ks"])
    better = {"3c5c": 1.0, "AcJc": 1.0, "7h7s": 1.0}
    ranges = {seat: better for seat in opponents_of(behind)[:1]}
    assert multiway_bot.sized(behind, 0.0, ranges, everyone) == "check_call"


def test_a_bet_everyone_folds_to_wins_the_pot(table):
    spot = river_spot(table, ["8h", "6s"])
    better = {"AcJc": 1.0, "7h7s": 1.0}
    ranges = {seat: better for seat in opponents_of(spot)[:2]}
    nobody = {**multiway_bot.DEFAULTS, "sticky": 0.0}        # every hand folds
    worth = multiway_bot.values(spot, ranges, nobody)
    pot = float(spot["pot"])
    assert all(worth[action] == pytest.approx(pot) for action in worth
               if action != "check_call")
    assert worth["check_call"] == pytest.approx(0.0)


def test_facing_a_bet_without_the_price_folds_and_sizing_off_plays_the_lines(table):
    spot = {**table["facing"], "street": "river", "own_hole": ["8h", "6s"],
            "board": ["Ad", "7c", "2d", "Js", "4h"]}
    hands = ({"AcJc": 1.0}, {"7h7s": 1.0}, {"AhAs": 1.0})
    ranges = dict(zip(opponents_of(spot), hands))
    assert multiway_bot.sized(spot, 0.0, ranges) == "fold"
    off = {**multiway_bot.DEFAULTS, "sizing": 0.0}
    assert multiway_bot.unguarded(spot, 0.9, off, ranges=ranges) == (
        multiway_bot.lines(spot, 0.9))
