"""Each opponent's entry and raise rates over the live session's hands."""

from poker_engine.desktop.aa_reads import AAReads, tag

# Six players, dealer 5: small blind 0, big blind 1, straddle 2; seat 3 acts
# first. Seat 3 raises, you (seat 4) fold, seat 5 calls, the blinds fold and
# the straddle calls; on the flop everyone checks.
RAISED = [(10, "preflop", 3, "raise", "12"), (12, "preflop", 4, "fold", "0"),
          (14, "preflop", 5, "call", "12"), (16, "preflop", 0, "fold", "0"),
          (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "call", "8"),
          (30, "flop", 2, "check", "0"), (32, "flop", 3, "check", "0"),
          (34, "flop", 5, "check", "0")]
# Seat 3 limps, the rest fold to the straddle, who checks its option.
LIMPED = [(10, "preflop", 3, "call", "4"), (12, "preflop", 4, "fold", "0"),
          (14, "preflop", 5, "fold", "0"), (16, "preflop", 0, "fold", "0"),
          (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "check", "0")]


def hand(actions, hand_id="hand_1", empty=(), complete=True, pot="19"):
    history = {"hand_id": hand_id, "complete": complete, "start": "pot_went_down",
               "dealer": 5, "actions": [list(a) + ["pot_rise"] for a in actions]}
    states = {str(seat): "empty" if seat in empty else "active" for seat in range(6)}
    rows = []
    for frame in range(5, 40):
        board = ["Ah", "Kd", "7c", None, None] if frame >= 25 else [None] * 5
        rows.append({"processed": frame, "fields": {
            "pot": pot, "participants": states, "board": board, "stacks": {},
            "actions_v1": {**history, "actions": [a for a in history["actions"]
                                                  if a[0] < frame]}}})
    return rows


def test_calls_and_raises_count_blinds_and_checks_do_not():
    reads = AAReads()
    assert reads.add_hand(hand(RAISED)) and reads.add_hand(hand(LIMPED, "hand_2"))
    assert reads.hands == 2
    snapshot = reads.snapshot()
    assert "4" not in snapshot                      # your own seat
    assert snapshot["3"] == {"hands": 2, "vpip": 1.0, "pfr": 0.5}
    assert snapshot["5"] == {"hands": 2, "vpip": 0.5, "pfr": 0.0}
    assert snapshot["2"] == {"hands": 2, "vpip": 0.5, "pfr": 0.0}   # straddle check
    assert snapshot["0"] == {"hands": 2, "vpip": 0.0, "pfr": 0.0}


def test_hands_that_do_not_replay_through_the_preflop_do_not_count():
    reads = AAReads()
    assert not reads.add_hand(hand(RAISED[:3]))     # preflop still going
    assert not reads.add_hand(hand(RAISED, complete=False))
    assert not reads.add_hand(hand(RAISED[1:]))     # seat 3's raise missed
    assert not reads.add_hand([]) and reads.snapshot() == {} and reads.hands == 0


def test_a_bomb_pot_has_no_preflop_decisions_to_count():
    # Everyone put in 14 (84 for six) and the flop came at once.
    bomb = [(30 + seat, "flop", seat, "check", "0") for seat in range(5)] + [
        (36, "flop", 5, "raise", "20")]
    reads = AAReads()
    assert not reads.add_hand(hand(bomb, pot="84"))
    assert reads.snapshot() == {} and reads.hands == 0


def test_a_seat_read_empty_starts_over():
    reads = AAReads()
    reads.add_hand(hand(RAISED))
    reads.add_hand(hand(LIMPED, "hand_2", empty=(3,)))
    assert "3" not in reads.snapshot()              # left during the hand
    reads.reset()
    assert reads.snapshot() == {}


def test_a_word_shows_once_the_hands_are_clear_and_stays_while_it_fits():
    assert tag(9, 9, 9) is None                     # too few hands
    assert tag(10, 3, 3) is None                    # 30% raises: not clear yet
    assert tag(15, 7, 7) == "raises"
    assert tag(15, 11, 2) == "loose"
    assert tag(30, 3, 1) == "tight"
    assert tag(15, 6, 2) is None                    # an ordinary AA player
    assert tag(12, 7, 1) is None and tag(12, 7, 1, "loose") == "loose"
    assert tag(12, 5, 1, "loose") is None           # fell back behind the line


def test_the_window_gets_each_seats_numbers_and_word():
    reads = AAReads()
    for index in range(10):
        reads.add_hand(hand(RAISED, f"hand_{index}"))
    labels = reads.labels()
    assert labels["3"] == {"hands": 10, "vpip": 1.0, "pfr": 1.0, "tag": "raises"}
    assert labels["5"]["tag"] == "loose" and labels["0"]["tag"] == "tight"
    assert "4" not in labels
