"""Starting stacks of different depths: drawn per seat and deal, side pots settled."""

from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.allin_ev import _rake_share, runout_ev, settle
from poker_engine.scoreboard.bomb import Bomb
from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.mushroom import Mushroom
from poker_engine.scoreboard.runner import lineup, play_hand, run_scoreboard
from poker_engine.scoreboard.stacks import Stacks
from poker_engine.scoreboard.strength import _EVALUATE_7, CARD_ID
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

CONFIGS = Path(__file__).resolve().parents[2] / "configs/game"
RULES = AARuleProfileV2.from_dict(json.loads(
    (CONFIGS / "aa-scoreboard-rules-v2.json").read_text(encoding="utf-8")))
FREE = AARuleProfileV2.from_dict(json.loads(
    (CONFIGS / "aa-scoreboard-rules-v1.json").read_text(encoding="utf-8")))

# Per-deal results (big blinds per hand) of main at 8784e47, before the option
# existed. Without ``stacks`` the scoreboard must give exactly these.
BEFORE_RAKED = [
    [5000000, {"aa_preflop": -0.1875, "always_call": -63.898438}],
    [5000001, {"aa_preflop": 8.228101, "always_call": -26.341471}],
    [5000002, {"aa_preflop": 27.265625, "always_call": -17.82919}],
    [5000003, {"aa_preflop": -6.3125, "always_call": 7.820431}],
    [5000004, {"aa_preflop": 10.625, "always_call": -44.046875}],
    [5000005, {"aa_preflop": -10.875, "always_call": 155.154613}]]
BEFORE_PLAIN = [
    [3000000, {"tag": -0.0625, "always_call": 0.6875}],
    [3000001, {"tag": 3.375, "always_call": -14.4375}],
    [3000002, {"tag": -0.0625, "always_call": -0.3125}],
    [3000003, {"tag": -0.0625, "always_call": -85.1875}]]


def test_without_stacks_the_results_are_what_they_were():
    raked = run_scoreboard(RULES, ["aa_preflop", "always_call"], deals=6, base_seed=5,
                           pool=("aa_real", "maniac"), reference="always_call",
                           mushroom=Mushroom(3, 0.135), bomb=Bomb(7, 0.5))
    assert raked["per_deal"] == BEFORE_RAKED and raked["stacks"] is None
    plain = run_scoreboard(RULES, ["tag", "always_call"], deals=4, base_seed=3,
                           reference="always_call")
    assert plain["per_deal"] == BEFORE_PLAIN
    assert plain["strategies"]["tag"]["bb_per_100"] == 79.69


def test_uniform_stacks_fall_in_the_range_and_follow_the_seed():
    stacks = Stacks(25, 250)
    seats = tuple(range(8))
    drawn = [stacks.chips(seed, seats, Decimal(2)) for seed in range(300)]
    assert drawn == [stacks.chips(seed, seats, Decimal(2)) for seed in range(300)]
    values = [int(chips) for deal in drawn for chips in deal.values()]
    assert min(values) >= 50 and max(values) <= 500          # 25 and 250 big blinds
    assert min(values) < 70 and max(values) > 480            # the whole range is used
    assert len(set(values)) > 300
    assert all(len(set(deal.values())) > 1 for deal in drawn)   # seats differ
    assert drawn[0] != drawn[1]
    # whole chips of the table: half big blinds when a big blind is one chip
    assert set(Stacks(1.5, 1.5).chips(1, seats, 1, Decimal("0.5")).values()) == {"1.5"}


def test_stack_choices_and_settings():
    stacks = Stacks.parse("25,40,100")
    assert stacks == Stacks(choices=(25.0, 40.0, 100.0)) and stacks.smallest == 25
    drawn = {chips for seed in range(50)
             for chips in stacks.chips(seed, range(8), 2).values()}
    assert drawn == {"50", "80", "200"}
    assert Stacks.parse("25-250") == Stacks(25, 250)
    for kept in (Stacks(25, 250), stacks):
        assert Stacks.from_dict(kept.to_dict()) == kept
    for bad in (lambda: Stacks(0, 10), lambda: Stacks(30, 20),
                lambda: Stacks(choices=(10, -1)), lambda: Stacks.parse("a-b")):
        with pytest.raises(ValueError):
            bad()


def test_the_arena_takes_a_hands_stacks_and_goes_back_to_its_own():
    arena = AAFullHandArena(RULES)
    deep = {seat: str(100 + 10 * seat) for seat in arena.occupied_seats}
    observation = arena.reset(3, stacks=deep).observe(0)
    assert observation["starting_stacks"] == {str(s): v for s, v in deep.items()}
    assert arena.reset(3).observe(0)["starting_stacks"] == {
        str(seat): "200" for seat in arena.occupied_seats}
    with pytest.raises(ValueError):          # the straddler cannot post 4
        arena.reset(3, stacks={**deep, 2: "3"})
    with pytest.raises(ValueError):
        arena.reset(3, stacks={0: "100"})


def test_runs_with_stacks_repeat_and_play_the_drawn_stacks(monkeypatch):
    stacks = Stacks(25, 250)
    kwargs = {"deals": 3, "base_seed": 4, "reference": "always_call",
              "pool": ("maniac",), "stacks": stacks}
    one = run_scoreboard(RULES, ["tag", "always_call"], workers=1, **kwargs)
    two = run_scoreboard(RULES, ["tag", "always_call"], workers=2, chunk=1, **kwargs)
    assert one["per_deal"] == two["per_deal"]
    assert one["stacks"] == {"low_big_blinds": 25, "high_big_blinds": 250}
    plain = run_scoreboard(RULES, ["tag", "always_call"], deals=3, base_seed=4,
                           reference="always_call", pool=("maniac",))
    assert plain["per_deal"] != one["per_deal"]

    seen = []
    real = AAFullHandArena.reset

    def reset(self, seed, **options):
        seen.append((seed, options.get("stacks")))
        return real(self, seed, **options)

    monkeypatch.setattr(AAFullHandArena, "reset", reset)
    run_scoreboard(RULES, ["tag"], deals=2, base_seed=4, pool=("maniac",),
                   stacks=stacks)
    seats = tuple(range(8))
    assert len(seen) == 2 * 8                    # every seat of each deal as hero
    assert all(chips == stacks.chips(seed, seats, RULES.big_blind)
               for seed, chips in seen)


def test_bomb_posts_must_be_below_every_stack():
    with pytest.raises(ValueError):
        run_scoreboard(RULES, ["tag"], deals=2, pool=("nit",),
                       stacks=Stacks(5, 50), bomb=Bomb(7, 0.5))


def deck(holes, board):
    """A 52-card deck that deals ``holes`` (SB first) and ``board`` with burns."""
    first = [card for hole in holes for card in hole]
    flop, turn, river = board[:3], board[3], board[4]
    used = set(first) | set(board)
    rest = [rank + suit for rank in "23456789TJQKA" for suit in "cdhs"
            if rank + suit not in used]
    burns, rest = rest[:3], rest[3:]
    return first + [burns[0], *flop, burns[1], turn, burns[2], river] + rest


def test_three_stacks_all_in_split_into_main_and_side_pots():
    # seats 3, 4, 5 have 25, 60 and 150 big blinds and AA, KK, QQ; the others fold
    stacks = {seat: "200" for seat in range(8)} | {3: "50", 4: "120", 5: "300"}
    holes = [("4c", "5c"), ("6c", "Tc"), ("Jc", "Qc"), ("As", "Ah"),
             ("Ks", "Kh"), ("Qs", "Qh"), ("4d", "5d"), ("6d", "Td")]
    arena = AAFullHandArena(RULES).reset(
        1, stacks=stacks, deck=deck(holes, ["2d", "7c", "9h", "3s", "8d"]))
    while not arena.terminal:
        seat = arena.actor
        legal = arena.observe(seat)["legal_actions"]
        if seat in (3, 4):
            arena.step(next(a["id"] for a in reversed(legal)
                            if a["kind"] == "raise_to"))
        else:
            arena.step("check_call" if seat == 5 else "fold")
    result = arena.terminal_returns()
    # main pot 167 (antes 16, dead blinds and straddle 13, 3 x 46): AA;
    # side pot 140 (2 x 70): KK; QQ keeps the other 180 chips.
    # Rake 10 (capped at 5 big blinds) is shared in proportion: 1670/307, 1400/307.
    assert result[3] == 167 - 50 - Fraction(1670, 307)
    assert result[4] == 140 - 120 - Fraction(1400, 307)
    assert result[5] == -120
    assert {seat: result[seat] for seat in (0, 1, 2, 6, 7)} == {
        0: -3, 1: -4, 2: -6, 6: -2, 7: -2}
    assert sum(result.values()) == -10
    assert arena.observe(5)["stacks"]["5"] == "180"
    pots = arena.terminal_result()["pots"]
    assert [pot["winners"] for pot in pots] == [[3]] * 5 + [[4]]
    # The all-in EV settles the same layers the same way.
    contributions = [float(value) for value in arena._contributions]
    board = [CARD_ID[card] for card in ("2d", "7c", "9h", "3s", "8d")]
    ranks = {i: _EVALUATE_7(*(CARD_ID[card] for card in holes[i]), *board)
             for i in (3, 4, 5)}
    expected = settle(contributions, ranks, _rake_share(RULES, arena._contributions))
    assert expected == pytest.approx([float(result[i]) for i in range(8)])


def test_hands_with_drawn_stacks_settle_every_side_pot():
    stacks, arena, side = Stacks(25, 250), AAFullHandArena(RULES), 0
    seats = arena.occupied_seats
    bots = {name: make_policy(name) for name in ("maniac", "always_call")}
    for seed in range(40):
        styles = lineup(seed, ("maniac", "always_call"), seats)
        deciders = {seat: bots[styles[seat]].for_game(f"{seed}:{seat}")
                    for seat in seats}
        drawn = stacks.chips(seed, seats, RULES.big_blind)
        hand = play_hand(arena, seed, deciders, 0, all_in_ev=False, stacks=drawn)
        result, settlement = arena.terminal_returns(), arena.terminal_result()
        assert float(result[0]) == hand.value
        rake = Fraction(settlement["rake"]["numerator"],
                        settlement["rake"]["denominator"])
        assert sum(result.values()) + rake == 0
        assert all(-result[seat] <= int(drawn[seat]) for seat in seats)
        winners = {tuple(pot["winners"]) for pot in settlement["pots"]}
        side += len(winners) > 1
        expected = runout_ev(arena, seed=seed)
        if expected is not None:
            assert all(-expected[seat] <= int(drawn[seat]) for seat in seats)
            assert sum(expected.values()) < 0          # only the rake leaves
    assert side >= 3          # pots won by different players came up


def test_free_tables_conserve_chips_with_drawn_stacks():
    stacks, arena = Stacks(25, 250), AAFullHandArena(FREE)
    seats = arena.occupied_seats
    bot = make_policy("always_call")
    for seed in range(10):
        drawn = stacks.chips(seed, seats, FREE.big_blind)
        deciders = {seat: bot.for_game(f"{seed}:{seat}") for seat in seats}
        play_hand(arena, seed, deciders, 0, all_in_ev=False, stacks=drawn)
        assert sum(arena.terminal_returns().values()) == 0
        expected = runout_ev(arena, seed=seed)
        if expected is not None:
            assert sum(expected.values()) == pytest.approx(0, abs=1e-6)
