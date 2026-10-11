"""The shown hands checked against the ranges read for them, from frame logs."""

import json

from tools.aa_range_exclusion import compare_runs, main, session_exclusion
from tools.aa_session_report import session_report
from tools.aa_strategy_review import review

# Six players, dealer 5: small blind 0, big blind 1, straddle 2; seat 3 acts
# first, you (seat 4) fold. Seat 5 limps with aces, checks the flop and
# raises the turn; the straddle calls it down.
ACTIONS = [
    (10, "preflop", 3, "fold", "0"), (12, "preflop", 4, "fold", "0"),
    (14, "preflop", 5, "call", "4"), (16, "preflop", 0, "fold", "0"),
    (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "check", "0"),
    (30, "flop", 2, "check", "0"), (32, "flop", 5, "check", "0"),
    (40, "turn", 2, "raise", "10"), (42, "turn", 5, "raise", "40"),
    (44, "turn", 2, "call", "30"),
    (50, "river", 2, "check", "0"), (52, "river", 5, "check", "0"),
]
BOARD = ["Qh", "8d", "3c", "2s", "Jd"]
SHOWN = {"5": {"cards": ["Ah", "As"], "frame": 55},
         "3": {"cards": ["7c", "7d"], "frame": 55}}        # shown after folding


def rows(hand="hand_1"):
    result = []
    for frame in range(60):
        done = [list(a) + ["pot_rise"] for a in ACTIONS if a[0] <= frame]
        board = BOARD[:5 if frame >= 50 else 4 if frame >= 40 else 3 if frame >= 30
                      else 0]
        fields = {"scene_supported": True, "pot": "0" if frame < 3 else "19",
                  "participants": {str(seat): "active" for seat in range(6)},
                  "board": board + [None] * (5 - len(board)),
                  "stacks": {str(seat): "200" for seat in range(6)},
                  "hero_controls": {"visible": False}, "street": "preflop",
                  "actions_v1": {"hand_id": hand, "complete": True,
                                 "start": "pot_went_down", "dealer": 5,
                                 "actions": done}}
        if frame >= 55:
            fields["shown_cards"] = {"hand_id": hand, "seats": SHOWN, "unknown": []}
        result.append({"processed": frame, "pts_seconds": frame / 10,
                       "video_seconds": 100.0, "fields": fields})
    return result


def test_aces_limped_and_raised_later_were_out_of_the_range_from_the_limp():
    report = session_exclusion([("log", rows())])
    assert report["skipped"] == {"shown_after_folding": 1}
    (trace,) = report["traces"]
    assert (trace["hand_id"], trace["seat"], trace["replayed"]) == (
        "hand_1", 5, "whole")
    assert [(s["street"], s["action"]) for s in trace["steps"]] == [
        ("preflop", "call"), ("flop", "check"), ("turn", "raise"), ("river", "check")]
    assert trace["steps"][0]["excluded"] and trace["you_in"] is False
    assert trace["steps"][-1]["ends_hand"]
    for view in ("whole_hand", "before_end"):
        summary = report[view]
        assert (summary["all"]["excluded"], summary["all"]["hands"]) == (1, 1)
        assert summary["river"]["hands"] == 1 and summary["narrowed"]["hands"] == 1
        assert summary["first"] == {"preflop call": 1}
    (line,) = report["hands"]
    assert (line["out"], line["out_before_end"], line["video_seconds"]) == (
        "preflop call", "preflop call", 100.0)


def test_the_session_report_and_the_review_show_it_hand_by_hand():
    found = session_report([("log", rows())])
    hand = found["hands"][0]
    reads = {seat["seat"]: seat["range_read"] for seat in hand["shown_cards"]}
    assert reads[5]["out"] == "preflop call" and reads[5]["street"] == "river"
    assert reads[3] == {"skipped": "shown_after_folding"}
    summary = found["summary"]["range_exclusion"]
    assert summary["whole_hand"]["all"]["rate"] == 1.0
    assert summary["before_end"]["by_street"]["preflop"]["excluded"] == 1
    excluded = review([("log", rows())])["summary"]["range_exclusion"]["excluded"]
    assert [(item["seat"], item["cards"], item["out"]) for item in excluded] == [
        (5, "Ah As", "preflop call")]


def test_two_runs_over_the_same_logs_are_compared_and_saved(tmp_path, capsys):
    log = tmp_path / "rec" / "frames.jsonl"
    log.parent.mkdir()
    log.write_text("".join(json.dumps(row) + "\n" for row in rows()), encoding="utf-8")
    out = tmp_path / "one.json"
    main(["--frames", str(log), "--out", str(out)])
    assert "preflop call 1" in capsys.readouterr().out
    saved = json.loads(out.read_text(encoding="utf-8"))
    kept = json.loads(json.dumps(saved))
    for step in kept["traces"][0]["steps"]:
        step["excluded"] = False
    result = compare_runs(saved, kept)
    assert result["paired_hands"] == 1
    whole = result["whole_hand"]
    assert (whole["kept_now"], whole["change"]["all"]) == (1, -1.0)
