"""Second-seat acceptance from synthetic frame rows and frames (no recording needed)."""

import gzip
import json

import numpy as np

from tools.p30_acceptance import (
    DEFAULT_BASELINE, build_baseline, compare, field_coverage, find_strip,
    main, markdown, strip_check)

SEATS = {"0": "active", "1": "folded", "2": "waiting", "3": "empty",
         "4": "active", "5": "active", "6": "all_in", "7": "folded"}
STACKS = {"0": "100", "1": "80", "2": "60", "3": None, "4": "90", "5": "70",
          "6": "0", "7": "50"}


def frame(*, supported=True, hero=("As", "Kd"), board=(None,) * 5, pot="20",
          street="preflop", actor=1, dealer=2, seats=None, stacks=None,
          controls=None):
    return {"fields": {
        "scene_supported": supported, "hero": list(hero) if hero else None,
        "board": list(board), "street": street, "pot": pot, "actor": actor,
        "dealer": dealer, "participants": dict(seats or SEATS),
        "stacks": dict(stacks or STACKS),
        "hero_controls": controls or {"visible": False, "button": None,
                                      "call_amount": None}}}


def turn(amount="8", button="call"):
    return frame(actor=4, controls={"visible": True, "button": button,
                                    "call_amount": amount})


def test_coverage_counts_each_field_over_the_frames_it_applies_to():
    rows = [frame(), frame(pot=None, dealer=None, actor=None),
            frame(board=("2c", "3d", "4h", None, None), street="flop"),
            frame(board=("2c", "3d", None, None, None), street=None),
            frame(supported=False, pot=None, street=None),
            frame(seats={**SEATS, "7": "unknown"}, stacks={**STACKS, "0": None}),
            turn(), turn(amount=None)]
    result = field_coverage(rows)
    assert result["table"] == {"value": round(7 / 8, 4), "n": 8}
    assert result["pot"]["value"] == round(6 / 7, 4)
    assert result["street"]["value"] == round(6 / 7, 4)
    assert result["board"] == {"value": 0.5, "n": 2}  # 3 cards ok, 2 cards not
    assert result["dealer"]["value"] == round(6 / 7, 4)
    assert result["actor"]["value"] == round(6 / 7, 4)
    assert result["seats"]["value"] == round(6 / 7, 4)
    # seated: 0, 1, 2, 4, 5, 7 (empty, all-in, unknown skipped); one unread
    assert result["stacks"] == {"value": round(40 / 41, 4), "n": 41}
    assert result["hero_cards"]["value"] == 1.0
    assert result["hero_button"] == {"value": 1.0, "n": 2}
    assert result["call_amount"] == {"value": 0.5, "n": 2}
    assert result["spectating"] is False


def test_spectating_recording_leaves_your_turn_unmeasured():
    rows = [frame(hero=None) for _ in range(10)]
    measured = field_coverage(rows)
    assert measured["spectating"] is True
    baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    result = compare(measured, baseline)
    verdicts = {row["key"]: row["verdict"] for row in result["rows"]}
    assert verdicts["hero_cards"] == verdicts["hero_button"] == "量不了"
    assert verdicts["call_amount"] == "量不了"
    assert verdicts["pot"] == "通过"
    assert result["overall"] == "没量全"


def _measured(**values):
    measured = {key: {"value": 0.99, "n": 1000} for key in (
        "table", "pot", "street", "board", "stacks", "dealer", "actor", "seats",
        "hero_cards", "hero_button", "call_amount")}
    for key, value in values.items():
        measured[key] = {"value": value, "n": 1000}
    measured["spectating"] = False
    return measured


BASE = {"realtime": {"label": "test", "metrics": {
    "table": 0.9, "pot": 0.9, "street": 0.9, "board": 0.9, "stacks": 0.9,
    "dealer": 0.8, "actor": 0.7, "seats": 0.9, "hero_cards": 0.6,
    "hero_button": 1.0, "call_amount": 0.92}},
    "seat_states": {"metrics": {"all_known_supported": 0.88,
                                "all_known_while_acting": 0.99}}}


def test_lines_are_ninety_percent_of_baseline_and_ninety_five_on_your_turn():
    strip = {"frames": 10, "strip": [711, 1209], "matches_samsung": True}
    seats = {"all_known_supported": 0.80, "all_known_while_acting": 0.99}
    # call amount: 95% of the Samsung's 92% is 87.4%; button: 95% of 100%
    passed = compare(_measured(pot=0.81, call_amount=0.875, hero_button=0.95),
                     BASE, seats, strip)
    assert passed["overall"] == "通过"
    lines = {row["key"]: row["line"] for row in passed["rows"]}
    assert lines["call_amount"] == 0.874 and lines["hero_button"] == 0.95
    failed = compare(_measured(pot=0.80, call_amount=0.873, hero_button=0.949),
                     BASE, seats, strip)
    verdicts = {row["key"]: row["verdict"] for row in failed["rows"]}
    assert verdicts["pot"] == verdicts["call_amount"] == "不通过"
    assert verdicts["hero_button"] == "不通过"
    assert failed["overall"] == "不通过"
    assert "| 底池 |" in markdown(failed, BASE)


def test_strip_elsewhere_fails_and_too_few_turn_frames_is_unmeasured():
    measured = _measured()
    measured["call_amount"] = {"value": 1.0, "n": 12}
    strip = {"frames": 10, "strip": [700, 1220], "matches_samsung": False}
    result = compare(measured, BASE, None, strip)
    rows = {row["key"]: row for row in result["rows"]}
    assert rows["strip"]["verdict"] == "不通过"
    assert rows["strip"]["value"] == "700–1219"
    assert rows["call_amount"]["verdict"] == "量不了"
    assert "12" in rows["call_amount"]["note"]
    assert result["overall"] == "不通过"


def _picture(left, right, level=60):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image[:, left:right] = level
    image[500:520, left + 5:left + 40] = 0  # dark detail inside the screen
    return image


def test_find_strip_and_strip_check_against_the_samsung_columns():
    assert find_strip(_picture(711, 1209)) == (711, 1209)
    assert find_strip(np.zeros((1080, 1920, 3), dtype=np.uint8)) is None
    same = strip_check([_picture(711, 1209), _picture(712, 1209),
                        np.zeros((1080, 1920, 3), dtype=np.uint8)])
    assert same["strip"] == [711, 1209] and same["matches_samsung"] is True
    assert same["picture"] == {"phone": 2, "dark": 1}
    moved = strip_check([_picture(690, 1230)] * 3)
    assert moved["strip"] == [690, 1230] and moved["width"] == 540
    assert moved["matches_samsung"] is False
    assert moved["picture"] == {"other": 3}  # the window would not see a phone
    assert strip_check([np.zeros((1080, 1920, 3), dtype=np.uint8)])["strip"] is None


def test_baseline_command_pools_frame_logs(tmp_path):
    plain, packed = tmp_path / "a.jsonl", tmp_path / "b.jsonl.gz"
    plain.write_text("\n".join(json.dumps(r) for r in [frame(), turn()]) + "\n",
                     encoding="utf-8")
    with gzip.open(packed, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(frame(pot=None)) + "\n")
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"coverage": {"all_known_supported": 0.8,
                                              "all_known_while_acting": 0.9}}))
    out = tmp_path / "baseline.json"
    assert main(["baseline", "--frames", str(plain), str(packed),
                 "--seat-states", str(seats), "--label", "x", "--out", str(out)]) == 0
    baseline = json.loads(out.read_text(encoding="utf-8"))
    assert baseline["realtime"]["frames"] == 3
    assert baseline["realtime"]["metrics"]["pot"] == round(2 / 3, 4)
    assert baseline["seat_states"]["metrics"]["all_known_while_acting"] == 0.9
    assert build_baseline([plain])["realtime"]["metrics"]["call_amount"] == 1.0


def test_committed_baseline_has_every_line():
    baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    metrics = baseline["realtime"]["metrics"]
    assert all(isinstance(metrics[key], float) for key in (
        "table", "pot", "street", "board", "stacks", "dealer", "actor", "seats",
        "hero_cards", "hero_button", "call_amount"))
    assert set(baseline["seat_states"]["metrics"]) == {
        "all_known_supported", "all_known_while_acting"}


def test_run_with_a_measured_log_writes_the_table(tmp_path):
    import cv2
    import pytest

    video = tmp_path / "p30.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 2,
                             (1920, 1080))
    if not writer.isOpened():
        pytest.skip("no MJPG writer")
    for _ in range(6):
        writer.write(_picture(711, 1209))
    writer.release()
    frames = tmp_path / "frames.jsonl"
    frames.write_text("\n".join(json.dumps(frame(hero=None)) for _ in range(20)),
                      encoding="utf-8")
    out = tmp_path / "out"
    code = main(["run", "--video", str(video), "--frames", str(frames),
                 "--out", str(out), "--skip-seat-check"])
    assert code == 1  # spectating: your turn unmeasured, so not a pass
    report = json.loads((out / "acceptance.json").read_text(encoding="utf-8"))
    assert report["strip"]["strip"] == [711, 1209]
    assert report["acceptance"]["overall"] == "没量全"
    assert "手机画面位置" in (out / "验收表.md").read_text(encoding="utf-8")
