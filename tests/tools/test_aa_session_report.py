"""The session report counts your decisions, the advice and why none came."""

from tools.aa_session_report import session_report


def row(frame, pts, *, hand="hand_0", turn=False, cards=("As", "Kd"), advice=None,
        published=None):
    return {"processed": frame, "pts_seconds": pts,
            "timing": {"published_at": pts if published is None else published},
            "fields": {"scene_supported": True, "hero": list(cards) if cards else None,
                       "participants": {"4": "active", "5": "active"},
                       "hero_controls": {"visible": turn}, "street": "preflop",
                       "actions_v1": {"hand_id": hand, "complete": False,
                                      "start": "boundary", "dealer": 5, "actions": []},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}


def test_decisions_advice_causes_and_stalls_are_counted():
    ready = {"status": "ready", "kind": "preflop", "advice": [{"action": "FOLD"}]}
    waiting = {"status": "idle", "reason": "waiting_for_last_action"}
    rows = ([row(f, f * 0.1) for f in range(5)]
            + [row(5, 0.5, turn=True, advice=waiting),
               row(6, 0.6, turn=True, advice=ready)]
            + [row(f, f * 0.1, hand="hand_9") for f in range(7, 12)]
            + [row(12, 1.2, hand="hand_9", turn=True, cards=None,
                   advice={"status": "idle", "reason": "your_cards_not_read"}),
               row(13, 1.3, hand="hand_9", published=5.0)])
    report = session_report([("log", rows)])
    summary = report["summary"]
    counts = summary["hands"], summary["your_decisions"], summary["advised"]
    assert counts == (2, 2, 1)
    assert summary["no_advice_causes"] == {"idle:your_cards_not_read": 1}
    assert summary["stalls_over_2s"] == 1
    first, second = report["hands"]
    assert first["decisions"][0]["first_ready"] == 0.1
    assert first["your_cards"] == "As Kd"
    assert second["decisions"][0]["cards_read"] is False
