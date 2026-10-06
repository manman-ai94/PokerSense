"""Measurement summaries from synthetic frame-log rows (no recording needed)."""

from tools.measure_aa_realtime import compare_gold, percentiles, summarize

ALL_IN = {str(slot): "active" for slot in range(8)}


def row(processed, frame, pts, *, received, published, hero=("Ah", "Kd"),
        board=(None,) * 5, street="preflop", pot="30", visible=False,
        call=None, math=None, participants=None):
    return {
        "processed": processed, "source_frame": frame, "source_video_pts": pts,
        "timing": {"host_source_received_at": received, "published_at": published,
                   "recognition_ms": 50.0, "math_ms": 1.0},
        "fields": {"hero": list(hero), "board": list(board), "street": street,
                   "pot": pot, "actor": 4,
                   "participants": dict(participants or ALL_IN),
                   "stacks": {"4": "100"},
                   "hero_controls": {"visible": visible, "call_amount": call},
                   "table_math": math or {
                       "equity": {"available": True},
                       "pot_odds": {"available": False, "reason": "not_hero_turn"},
                       "spr": {"available": True}}},
    }


def test_percentiles_use_nearest_rank():
    assert percentiles([]) is None
    result = percentiles(list(range(1, 101)))
    assert result == {"n": 100, "p50": 50, "p95": 95, "max": 100}


def test_summary_counts_drops_latency_and_coverage():
    rows = [
        row(0, 0, 10.0, received=1.00, published=1.08),
        row(1, 3, 10.1, received=1.10, published=1.20, hero=(None, None),
            visible=True, call=None),
        row(2, 5, 10.2, received=1.20, published=1.29, visible=True, call="10"),
    ]
    summary = summarize(rows)
    assert summary["frames_processed"] == 3 and summary["frames_arrived"] == 6
    assert summary["frames_dropped_fraction"] == 0.5
    assert summary["latency_ms"]["arrival_to_published"]["max"] == 100.0
    assert summary["coverage"]["hero_cards"] == round(2 / 3, 4)
    assert summary["coverage"]["all_participants"] == 1.0
    assert summary["hero_turn_frames"] == 2
    assert summary["call_amount_read_on_hero_turn"] == 0.5
    assert summary["table_math"]["pot_odds"] == {
        "available": 0.0, "reasons": {"not_hero_turn": 3}}
    assert summary["all_participants_known"] == {
        "hero_card_frames": 1.0, "hero_card_frames_with_actor": 1.0,
        "hero_turn_frames": 1.0}
    assert summary["equity_available_hero_in_hand"] == 1.0


def test_gold_agreement_counts_correct_wrong_unknown_and_unmatched():
    rows = [row(0, 0, 50.0, received=1.0, published=1.1,
                participants={**ALL_IN, "1": "unknown", "2": "waiting"}),
            row(1, 1, 80.0, received=2.0, published=2.1,
                board=("5h", "6c", "6s", None, None), street=None, pot="99")]
    known = {"status": "KNOWN"}
    gold = {"checkpoints": [
        {"pts_seconds": "50.000000", "fields": {
            "hero_cards": {**known, "value": ["Ah", "Kd"]},
            "board_cards": {**known, "value": []},
            "street": {**known, "value": "preflop"},
            "pot": {**known, "value": "30"},
            "actor": {**known, "value": 4},
            "stacks": {**known, "value": {"4": "100", "6": {"status": "NA"}}},
            "participation": {**known, "value": {
                "4": "active", "0": None, "1": "folded", "2": "empty"}}}},
        {"pts_seconds": "80.000000", "fields": {
            "hero_cards": {**known, "value": ["Ah", "Kd"]},
            "board_cards": {**known, "value": ["5h", "6c", "6s"]},
            "street": {**known, "value": "flop"},
            "pot": {**known, "value": "173"},
            "actor": {"status": "UNKNOWN", "value": None},
            "stacks": {**known, "value": {}},
            "participation": {**known, "value": {}}}},
        {"pts_seconds": "200.000000", "fields": {}},
    ]}
    result = compare_gold(rows, gold)
    fields = result["fields"]
    assert fields["board_cards"] == {"correct": 2}   # preflop [] is a reading
    assert fields["street"] == {"correct": 1, "unknown": 1}
    assert fields["pot"] == {"correct": 1, "wrong": 1}
    assert fields["actor"] == {"correct": 1}
    assert fields["stacks"] == {"correct": 1}
    assert fields["participation"] == {"correct": 1, "unknown": 1, "wrong": 1}
    assert result["checkpoints"][0]["mismatches"] == {
        "participation:1": {"expected": "folded", "actual": "unknown"},
        "participation:2": {"expected": "empty", "actual": "waiting"}}
    assert fields["hero_cards"] == {"correct": 2, "no_frame": 1}
    assert result["checkpoints"][1]["mismatches"]["pot"] == {
        "expected": "173", "actual": "99"}
