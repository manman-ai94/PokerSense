"""Offline replay of the betting history from a measurement log."""

from tools.replay_aa_action_history import replay


def log_rows(pts_step=0.1, gap_at=None):
    rows = []
    call = {"frame": 5, "confirmed_at": 6, "slot": 3, "kind": "call", "glyph": "call",
            "amount": None, "street": None, "epoch": 0, "status": "OBSERVED_GLYPH"}
    pts = 0.0
    for frame in range(30):
        pts += 5.0 if frame == gap_at else pts_step
        rows.append({"processed": frame, "pts_seconds": pts, "fields": {
            "scene_supported": True, "pot": "23" if frame < 4 else "27",
            "street": "preflop", "dealer": 7, "board": [None] * 5, "hero": [],
            "participants": {"3": "active"}, "stacks": {},
            "actions_tail": [call] if frame >= 6 else [], "actions_v1": None}})
    return rows


def test_the_history_is_rebuilt_from_logged_fields():
    rows = replay(log_rows())
    last = rows[-1]["fields"]["actions_v1"]
    assert last["start"] == "first_hand_seen"
    assert last["actions"] == [[5, "preflop", 3, "call", "4", "pot_rise"]]
    assert rows[-1]["fields"]["pot"] == "27"          # other fields are kept


def test_a_time_gap_starts_the_history_over():
    rows = replay(log_rows(gap_at=20))
    assert rows[19]["fields"]["actions_v1"]["hand_id"] == "hand_0"
    after = rows[-1]["fields"]["actions_v1"]
    assert after["hand_id"] == "hand_20" and after["complete"] is False
