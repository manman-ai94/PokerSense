"""Review 2026-10-08: the live reads (``aa_reads``, branch feat/live-reads).

A hand counts for the reads when its preflop replays; the replay fills in a
missed action from the seat states of the hand's last frame. At the end of a
hand nearly every seat that lost is shown folded, so a missed open raise of
a seat that later folded to a re-raise is counted as a fold: that seat's
VPIP and PFR both come out low.
"""

import pytest

aa_reads = pytest.importorskip("poker_engine.desktop.aa_reads")

# Six players, dealer 5: SB 0, BB 1, straddle 2; seat 3 acts first.
# Seat 3 opens to 12 (not read), you fold, seat 5 re-raises to 40, the
# blinds and the straddle fold, and seat 3 folds.
MISSED_OPEN = [(12, "preflop", 4, "fold", "0"), (14, "preflop", 5, "raise", "40"),
               (16, "preflop", 0, "fold", "0"), (18, "preflop", 1, "fold", "0"),
               (20, "preflop", 2, "fold", "0"), (22, "preflop", 3, "fold", "0")]


def _hand(actions):
    history = {"hand_id": "hand_1", "complete": True, "start": "pot_went_down",
               "dealer": 5, "actions": [list(a) + ["pot_rise"] for a in actions]}
    rows = []
    for frame in range(5, 30):
        states = {str(seat): "active" for seat in range(6)}
        for action in actions:
            if action[0] < frame and action[3] == "fold":
                states[str(action[2])] = "folded"
        rows.append({"processed": frame, "fields": {
            "pot": "19", "participants": states, "board": [None] * 5,
            "stacks": {},
            "actions_v1": {**history, "actions": [a for a in history["actions"]
                                                  if a[0] < frame]}}})
    return rows


def test_a_missed_open_raise_is_not_counted_as_a_fold():
    reads = aa_reads.AAReads()
    counted = reads.add_hand(_hand(MISSED_OPEN))
    seat = reads.snapshot().get("3")
    # Either the hand is left out, or seat 3 is counted as the raiser it was.
    assert not counted or (seat["vpip"], seat["pfr"]) == (1.0, 1.0), (
        f"seat 3 counted as {seat}")
