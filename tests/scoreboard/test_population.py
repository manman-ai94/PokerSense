"""The population bot: real-player frequencies before the flop, calibrated after it."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard import population
from poker_engine.scoreboard.population import (PopulationBot, population_stats,
                                                preflop_band, preflop_shares,
                                                stats_position, threshold)
from poker_engine.scoreboard.runner import run_scoreboard
from poker_engine.scoreboard.strength import DECK, all_classes, preflop_table
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v1.json"

PREFLOP_SPOTS = ("rfi", "vs_limp", "vs_open", "vs_3bet_cold", "limp_vs_raise",
                 "call_vs_3bet", "open_vs_3bet", "3bet_vs_4bet")
LEGAL = [{"id": "fold", "kind": "fold", "raise_to": None},
         {"id": "check_call", "kind": "check_call", "raise_to": None},
         {"id": "raise_to:8", "kind": "raise_to", "raise_to": "8"},
         {"id": "raise_to:17", "kind": "raise_to", "raise_to": "17"},
         {"id": "raise_to:31", "kind": "raise_to", "raise_to": "31"},
         {"id": "raise_to:200", "kind": "raise_to", "raise_to": "200"}]


def observation(hole, *, seat, history=(), to_call="4", straddler=2, street="preflop",
                board=(), folded=()):
    """Dealer on seat 7: 0 SB, 1 BB, 2 UTG (straddle), 3 UTG+1 ... 7 BTN."""
    return {"street": street, "own_hole": hole, "board": list(board),
            "public_history": [{"actor": actor, "street": row_street, "kind": kind}
                               for row_street, actor, kind in history],
            "occupied_seats": list(range(8)), "dealer_seat": 7,
            "straddler_seat": straddler, "observing_seat": seat, "to_call": to_call,
            "pot": "23", "folded": list(folded),
            "bets": {str(s): "4" if s == 2 else "0" for s in range(8)},
            "legal_actions": LEGAL}


def cards(name):
    if len(name) == 2:
        return [name[0] + "s", name[1] + "d"]
    return [name[0] + "s", name[1] + ("s" if name[2] == "s" else "d")]


def test_stats_cover_every_spot_the_bot_asks_for():
    stats = population_stats()
    for name in ("EP", "LJ", "HJ", "CO", "BTN", "SB", "BB"):
        for spot in PREFLOP_SPOTS:
            raise_share, call_share = preflop_shares(name, spot)
            assert 0 < raise_share + call_share <= 1
    for street in ("flop", "turn", "river"):
        for width in ("hu", "multi"):
            for role in ("pfa", "other"):
                for facing in ("checked_to", "facing_bet", "facing_raise"):
                    row = stats[f"{street}|{width}|{role}|{facing}"]
                    shares = [value for key, value in row.items() if key != "n"]
                    assert row["n"] > 1000
                    assert sum(shares) == pytest.approx(1, abs=0.001)


def test_seats_use_the_real_position_that_plays_alike():
    assert [stats_position(observation(["As", "Ah"], seat=s)) for s in range(8)] == [
        "SB", "SB", "BB", "EP", "LJ", "HJ", "CO", "BTN"]
    assert [stats_position(observation(["As", "Ah"], seat=s, straddler=None))
            for s in range(8)] == ["SB", "BB", "EP", "EP", "LJ", "HJ", "CO", "BTN"]


def test_first_to_act_opens_the_measured_share_of_hands():
    bot = PopulationBot()
    decisions = {"raise": 0, "call": 0, "fold": 0}
    for index, first in enumerate(DECK):
        for second in DECK[index + 1:]:
            action = bot.preflop(observation([first, second], seat=3))
            kind = ("raise" if action.startswith("raise_to") else
                    "call" if action == "check_call" else "fold")
            decisions[kind] += 1
    raise_share, call_share = preflop_shares("EP", "rfi")
    assert decisions["raise"] / 1326 == pytest.approx(raise_share, abs=0.002)
    assert decisions["call"] / 1326 == pytest.approx(call_share, abs=0.002)


def test_a_reraised_opener_keeps_only_the_top_of_its_opening_range():
    bot = PopulationBot()
    opened = preflop_shares("EP", "rfi")[0]
    history = [("preflop", 3, "raise_to"), ("preflop", 4, "fold"),
               ("preflop", 5, "raise_to")]
    assert preflop_band(observation(["As", "Ah"], seat=3, history=history),
                        "EP") == (0.0, opened)
    table = preflop_table()["classes"]
    weakest_open = max((name for name in all_classes()
                        if table[name]["percentile"] <= opened),
                       key=lambda name: table[name]["percentile"])
    four_bet = bot.preflop(observation(["As", "Ah"], seat=3, history=history))
    assert four_bet.startswith("raise_to")
    assert bot.preflop(observation(cards(weakest_open), seat=3,
                                   history=history)) == "fold"


def test_a_limper_continues_from_its_limping_range():
    history = [("preflop", 3, "check_call"), ("preflop", 4, "raise_to")]
    raise_share, call_share = preflop_shares("EP", "rfi")
    low, high = preflop_band(observation(["9s", "9d"], seat=3, history=history), "EP")
    assert (low, high) == pytest.approx((raise_share, raise_share + call_share))


def test_threshold_reads_the_calibrated_quantiles(monkeypatch):
    monkeypatch.setattr(population, "calibration", lambda: {
        "flop|hu|pfa|checked_to": [i / 100 for i in range(101)],
        "flop|multi|facing_raise": [0.7] * 101, "flop|facing_bet": [0.6] * 101,
        "flop|multi": [0.5] * 101})
    assert threshold("flop|hu|pfa|checked_to", 0.7) == pytest.approx(0.3)
    assert threshold("flop|hu|pfa|checked_to", 1.5) == 0.0
    assert threshold("flop|multi|pfa|facing_raise", 0.2) == 0.7    # roles pooled
    assert threshold("flop|multi|pfa|facing_bet", 0.2) == 0.6      # widths pooled
    assert threshold("flop|multi|other|checked_to", 0.2) == 0.5    # whole street
    assert threshold("turn|hu|pfa|checked_to", 0.5) is None


def test_postflop_bets_hands_above_the_threshold_and_records_them(monkeypatch):
    monkeypatch.setattr(population, "calibration",
                        lambda: {"flop|hu|pfa|checked_to": [0.5] * 101})
    records = []
    bot = PopulationBot(recorder=records).for_game("test")
    history = [("preflop", 3, "raise_to"), ("preflop", 7, "check_call")]
    folded = [0, 1, 2, 4, 5, 6]
    strong = observation(["As", "Ah"], seat=3, history=history, to_call="0",
                         street="flop", board=["2c", "7d", "9h"], folded=folded)
    weak = observation(["3s", "4d"], seat=3, history=history, to_call="0",
                       street="flop", board=["Ac", "Kd", "Qh"], folded=folded)
    assert bot(strong).startswith("raise_to")
    assert bot(weak) == "check_call"
    assert [(spot, action) for spot, _, action in records] == [
        ("flop|hu|pfa|checked_to", "bet"), ("flop|hu|pfa|checked_to", "check")]
    assert records[0][1] > 0.5 > records[1][1]


def test_the_population_can_be_the_whole_opponent_pool():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, ["tag", "population"], deals=2,
                            pool=("population",), reference="tag")
    assert report["pool"] == ["population"]
    assert report["strategies"]["population"]["hands"] == 16
