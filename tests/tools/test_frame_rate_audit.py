"""Separating what a slow computer's frame rate costs from everything else."""

import json

from tests.desktop.test_aa_solver_input import ACTIONS, rows as hand_rows
from tools.frame_rate_audit import (cards_wait, frame_rate, longest_gap, main, thin,
                                    where)


def log(frames=40, step=0.1, jump_at=None):
    """A fast log: a frame every ``step`` seconds, the numbering jumping by
    two at ``jump_at`` (a reader restart)."""
    rows, processed = [], 0
    for frame in range(frames):
        if frame == jump_at:
            processed += 1
        rows.append({"processed": processed, "pts_seconds": round(frame * step, 3),
                     "fields": {"pot": "23", "hero": None, "actions_tail": []}})
        processed += 1
    return rows


def test_a_thinned_log_reads_as_a_slow_reader_writes_it():
    thinned = thin(log(jump_at=21), 2.5)
    assert [row["pts_seconds"] for row in thinned][:4] == [0.0, 0.4, 0.8, 1.2]
    numbers = [row["processed"] for row in thinned]
    # Numbered on one by one; the restart stays a break, kept at once.
    assert numbers[:5] == [0, 1, 2, 3, 4]
    assert 2.1 in [row["pts_seconds"] for row in thinned]
    breaks = [b - a for a, b in zip(numbers, numbers[1:]) if b - a != 1]
    assert breaks == [2]
    assert 2.4 < frame_rate(thinned)["frames_per_second"] < 2.8
    assert frame_rate(log())["frames_per_second"] == 10.0
    # No rate: every frame, numbered as before.
    assert [row["processed"] for row in thin(log(), None)] == list(range(40))


def test_badges_land_on_the_first_kept_frame_after_they_were_confirmed():
    rows = log()
    call = {"frame": 5, "confirmed_at": 6, "slot": 3, "kind": "call"}
    check = {"frame": 7, "confirmed_at": 9, "slot": 2, "kind": "check"}
    for row in rows[6:]:
        row["fields"]["actions_tail"] = [call]
    for row in rows[9:]:
        row["fields"]["actions_tail"] = [call, check]
    thinned = thin(rows, 2.5)
    kept = {row["pts_seconds"]: row for row in thinned}
    # Frame 6 was not kept; frame 8 (0.8 s) is the first kept one after it.
    assert kept[0.8]["fields"]["actions_tail"] == [
        {**call, "frame": 2, "confirmed_at": 2}]
    assert kept[1.2]["fields"]["actions_tail"][1] == {**check, "frame": 3,
                                                      "confirmed_at": 3}
    # 杜's window reads no check badge.
    assert thin(rows, 2.5, checks=False)[-1]["fields"]["actions_tail"] == [
        {**call, "frame": 2, "confirmed_at": 2}]
    assert thin(rows, None, checks=False)[-1]["fields"]["actions_tail"] == [call]


def test_bets_in_front_of_blind_seats_go_unread():
    rows = log(4)
    for row in rows:
        row["fields"]["street_wagers"] = {"1": "4", "3": "4", "7": "8"}
    thinned = thin(rows, None, blind_wagers=(1, 7))
    assert all(row["fields"]["street_wagers"] == {"3": "4"} for row in thinned)
    assert rows[0]["fields"]["street_wagers"] == {"1": "4", "3": "4", "7": "8"}


def test_a_slow_reader_reads_your_cards_later():
    rows = log()
    for row in rows:
        frame = round(row["pts_seconds"] * 10)
        row["fields"]["hero_controls"] = {"visible": frame >= 8}
        row["fields"]["street"] = "preflop"
        if frame >= 10:
            row["fields"]["hero"] = ["As", "Kd"]
    assert cards_wait(rows) == {"decisions": 1, "median": 0.2, "p90": 0.2}
    thinned = thin(rows, 2.5)
    # Kept frames at 0.8, 1.2, 1.6, 2.0, 2.4: the cards show from 1.2 on to
    # the fast reader, three kept frames later (2.4) to the slow one.
    assert [row["fields"]["hero"] for row in thinned][3:7] == [
        None, None, None, ["As", "Kd"]]
    assert cards_wait(thinned) == {"decisions": 1, "median": 1.6, "p90": 1.6}
    assert thin(rows, None)[10]["fields"]["hero"] == ["As", "Kd"]


def test_stops_and_rises_are_counted_by_the_frame_gap_next_to_them():
    def hand(actions, gap):
        rows = hand_rows()
        for row in rows:
            row["fields"]["actions_v1"] = {
                **row["fields"]["actions_v1"],
                "actions": [list(a) + ["no_chips"] for a in actions]}
            row["fields"]["scene_supported"] = True
            frame = row["processed"]
            row["pts_seconds"] = round(frame * 0.1 + (gap if frame >= 16 else 0), 3)
        return rows

    fine = where(hand(ACTIONS, 0.0), rebuild=False)
    assert fine["pairs_by_gap"]["<=0.25s"] == [len(ACTIONS) - 1, 0]
    # Seat 0's fold went unread across a 0.8 second gap: the replay stops at
    # seat 1's fold, the pair from seat 5's call to it.
    missed = ACTIONS[:3] + ACTIONS[4:]
    stopped = where(hand(missed, 0.8), rebuild=False)
    assert stopped["pairs_by_gap"]["<=1.0s"] == [1, 1]
    assert stopped["pairs_by_gap"]["<=0.25s"] == [2, 0]
    assert stopped["stopped_at_seat"] == {"1": 1}
    # The pot's one rise (19 to 23) comes with seat 5's call: explained.
    assert sum(pair[0] for pair in fine["rises_by_gap"].values()) == 1
    assert sum(pair[1] for pair in fine["rises_by_gap"].values()) == 0
    assert longest_gap({1: 0.0, 2: 0.1, 3: 0.9, 9: 5.0}, 1, 3) == 0.8


def test_the_report_has_counts_only(tmp_path):
    rows = log(30)
    path = tmp_path / "rec" / "frames.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    out = tmp_path / "audit.json"
    main(["--frames", str(path), "--slow", "2.5,20", "--blind-wagers", "1,7",
          "--full-variants", "--no-advice", "--out", str(out)])
    report = json.loads(out.read_text())["rec"]
    assert report["as_recorded"]["frames_per_second"] == 10.0
    # 20 frames a second is faster than the log: not run.
    assert sorted(report["configurations"]) == [
        "2.5/du_like", "2.5/no_checks", "2.5/plain", "full/du_like", "full/no_checks"]
    assert "postflop_rough_or_none" not in report["as_recorded"]


def test_only_the_variants_asked_for_run(tmp_path):
    path = tmp_path / "rec" / "frames.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(row) + "\n" for row in log(30)))
    out = tmp_path / "audit.json"
    main(["--frames", str(path), "--slow", "2.5", "--variants", "plain",
          "--no-advice", "--out", str(out)])
    assert sorted(json.loads(out.read_text())["rec"]["configurations"]) == ["2.5/plain"]
