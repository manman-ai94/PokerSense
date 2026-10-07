"""Calibration helpers of the population bot, on synthetic decision records."""

import json

import pytest

from tools.calibrate_population_bot import (MIN_SAMPLES, dump, largest_gap, measured,
                                            quantiles)


def test_quantiles_per_spot_with_pooled_fallbacks():
    spot, rare = "flop|hu|pfa|checked_to", "flop|hu|other|facing_raise"
    records = [(spot, i / 400, "bet") for i in range(400)]
    records += [(rare, 0.5, "call")] * (MIN_SAMPLES - 1)
    table, samples = quantiles(records)
    assert samples == {spot: 400, "flop|hu|checked_to": 400, "flop|checked_to": 400,
                       rare: MIN_SAMPLES - 1, "flop|hu|facing_raise": MIN_SAMPLES - 1,
                       "flop|facing_raise": MIN_SAMPLES - 1,
                       "flop|hu": 400 + MIN_SAMPLES - 1}
    # Too few samples for the rare spot and its narrower pools.
    assert set(table) == {spot, "flop|hu|checked_to", "flop|checked_to", "flop|hu"}
    assert len(table[spot]) == 101
    assert table[spot][0] == 0.0 and table[spot][-1] == 0.9975
    assert table[spot] == sorted(table[spot])


def test_measured_puts_the_bot_next_to_the_real_players():
    spot = "flop|hu|pfa|checked_to"
    rows = measured([(spot, 0.9, "bet")] * 3 + [(spot, 0.1, "check")])
    assert rows[0]["spot"] == spot and rows[0]["n"] == 4
    assert rows[0]["bot"] == {"bet": 0.75, "check": 0.25}
    assert set(rows[0]["players"]) >= {"bet", "check"}


def test_largest_gap_covers_decisions_only_one_side_took():
    row = {"bot": {"bet": 0.6, "check": 0.4},
           "players": {"bet": 0.7, "check": 0.25, "fold": 0.05}}
    assert largest_gap(row) == pytest.approx(0.15)


def test_dump_keeps_number_lists_on_one_line():
    data = {"quantiles": {"flop|hu": [0.0, 0.25, 1, 1e-05]}, "note": "x"}
    text = dump(data)
    assert '"flop|hu": [0.0, 0.25, 1, 1e-05]' in text
    assert json.loads(text) == data
