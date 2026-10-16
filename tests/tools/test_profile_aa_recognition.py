import json
import sys
import time

import cv2
import numpy as np

from tools import profile_aa_recognition as tool


def recording(folder, seconds=2, fps=30):
    """A recorder-style folder: one segment with a lit strip at 711-1208."""
    folder.mkdir()
    writer = cv2.VideoWriter(str(folder / "segment_0000.mp4"),
                             cv2.VideoWriter_fourcc(*"mp4v"), fps, (1920, 1080))
    for number in range(seconds * fps):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[:, 711:1209] = 40 + number
        writer.write(frame)
    writer.release()
    (folder / "segments.csv").write_text("segment_0000.mp4,0.0\n", encoding="utf-8")
    return folder


class SlowReader:
    """Stands in for AA8Reader: a scene check and a money read per frame."""

    def __init__(self):
        self.seen = []

    def scene(self, image):
        return float(image.mean()) > 10

    def money(self, image):
        return cv2.GaussianBlur(image, (5, 5), 1).sum()

    def read(self, image, frame, sample):
        assert image.shape == (1080, 498, 3)
        self.seen.append((frame, sample["pts_seconds"], sample["source_frame"]))
        supported = self.scene(image)
        self.money(image)
        return {"scene_supported": supported, "source_id": sample["source_id"],
                "money": float(image[0, 0, 0]) + self.shift}

    shift = 0


SlowReader.read.__code__ = SlowReader.read.__code__.replace(
    co_filename="aa_reader.py")


def test_strips_cut_the_phone_from_every_nth_frame(tmp_path):
    video = recording(tmp_path / "rec")
    got = list(tool.strips(video, start=0.5, step=4, count=5))
    assert len(got) == 5
    expected = [round(n / 30, 3) for n in (16, 20, 24, 28, 32)]
    assert [round(at, 3) for at, _, _ in got] == expected
    # Frame numbers skip the frames not read, like the capture card's counter.
    assert [number for _, number, _ in got] == [16, 20, 24, 28, 32]
    assert all(strip.shape == (1080, 498, 3) for _, _, strip in got)
    assert not list(tool.strips(video, start=0, step=1, count=50,
                                exclude=((0.0, 9.0),)))


def test_profile_times_each_frame_and_splits_the_reader(tmp_path):
    video = recording(tmp_path / "rec")
    readers = []

    def factory():
        readers.append(SlowReader())
        return readers[-1]

    result = tool.profile(video, factory, start=0, step=3, count=8)
    assert result["frames"] == 8 and result["table_frames"] == 8
    assert result["recognition_ms"]["n"] == 8 and result["profiled_ms"]["n"] == 8
    # Both readers saw the same frames in the same order.
    assert readers[0].seen == readers[1].seen
    (parent, step), = result["steps"].items()
    assert parent.endswith("(read)")
    names = [row["function"] for row in step["steps"]]
    assert any(name.endswith("(money)") for name in names)
    assert result["own_time"]
    json.dumps(result)


class SleepyReader(SlowReader):
    def read(self, image, frame, sample):
        time.sleep(0.02)  # the feed offers every 1/30 s; let it tick
        return super().read(image, frame, sample)


def test_profile_with_the_recorder_running(tmp_path):
    video = recording(tmp_path / "rec")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    # Six frames read in a few ms each (a fast runner) could all pass
    # before the recorder's first 1/30 s tick; at 20 ms each they cannot.
    result = tool.profile(video, SleepyReader, start=0, step=2, count=6,
                          load="recorder", scratch=scratch)
    assert result["recorder"]["offered"] > 0
    assert (scratch / "recording" / "recording.json").is_file()
    # Timed only: the profiler would also see the recorder's thread.
    assert result["profiled_ms"] is None and "steps" not in result


def test_profile_with_the_window_asking_for_its_state(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "POLL_SECONDS", 0.001)
    video = recording(tmp_path / "rec", seconds=4)
    result = tool.profile(video, SlowReader, start=0, step=1, count=60,
                          load="status")
    assert result["profiled_ms"] is None
    assert result["status"]["answers"] > 0
    assert result["status"]["path"] == "signal-json"
    # Only the signal window's keys (here scene_supported): a few bytes.
    assert result["status"]["kilobytes"]["n"] == result["status"]["answers"]
    assert result["status"]["kilobytes"]["max"] < result["payload_kilobytes"]["p50"]
    assert result["payload_kilobytes"]["n"] == 60


def test_the_status_is_answered_as_this_checkout_does_it(monkeypatch):
    from poker_engine.desktop import aa_session

    payload = {"pot": {"value": "七"}, "cards": None, "evidence": [1, 2.5]}
    text = json.dumps(payload, allow_nan=False)
    answers = {}
    path, keep, answer = tool.status_answer()
    answers[path] = answer(keep(text, payload))
    # Code from before the signal window asked for its part only.
    monkeypatch.delattr(aa_session, "signal_json")
    path, keep, answer = tool.status_answer()
    answers[path] = answer(keep(text, payload))
    # And from before the window kept the published JSON text.
    monkeypatch.setitem(sys.modules, "poker_engine.desktop.aa_server", None)
    path, keep, answer = tool.status_answer()
    answers[path] = answer(keep(text, payload))
    assert {path: json.loads(body) for path, body in answers.items()} == {
        "signal-json": {"payload": {"pot": {"value": "七"}, "cards": None}},
        "published-json": {"payload": payload},
        "copy-and-encode": {"payload": payload}}


def test_two_runs_compare_field_by_field(tmp_path):
    video = recording(tmp_path / "rec")
    first, second, third = (tmp_path / name for name in ("a", "b", "c"))
    tool.profile(video, SlowReader, start=0, step=3, count=8, hashes=first)
    timed = tool.profile(video, SlowReader, start=0, step=3, count=8, hashes=second,
                         profiled=False)
    assert timed["profiled_ms"] is None and timed["recognition_ms"]["n"] == 8
    assert tool.compare(first, second)["same"] is True

    class Shifted(SlowReader):
        shift = 1

    tool.profile(video, Shifted, start=0, step=3, count=8, hashes=third)
    result = tool.compare(first, third)
    assert result["same"] is False
    assert result["fields_differing"] == {"money": {"frames": 8, "first": 0}}
    assert tool.main(["compare", str(first), str(third)]) == 1


def test_log_totals(tmp_path):
    folder = tmp_path / "rec"
    folder.mkdir()
    rows = []
    for number in range(21):
        start = 100 + number * 0.4
        rows.append({"processed": number, "source_frame": number * 12,
                     "pts_seconds": number * 0.4,
                     "timing": {"recognition_started_at": start,
                                "source_read_started_at": start - 0.01,
                                "published_at": start + 0.35,
                                "host_source_received_at": start - 0.005,
                                "source_read_ms": 10, "recognition_ms": 300 + number,
                                "math_ms": 0.1, "advice_ms": 0.2},
                     "fields": {"scene_supported": number % 2 == 0}})
    rows[0]["code"] = "abc1234"
    (folder / "frames.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + "not json\n",
        encoding="utf-8")
    (folder / "recording.json").write_text(json.dumps({
        "fourcc": "mp4v", "backend": "FFMPEG", "recorded_seconds": 10,
        "offered_frames": 270, "skipped_frames": 30}), encoding="utf-8")
    (item,) = tool.log_command([folder])
    assert item["recording"]["card_frames_per_second"] == 30
    assert item["recording"]["recorder_skipped_share"] == 0.1
    (log,) = item["logs"]
    assert log["code"] == "abc1234" and log["rows"] == 21
    assert log["frames_per_second"] == 2.5
    assert log["card_frames_per_second"] == 30
    assert log["recognition_ms"]["p50"] == 310
    assert log["loop_ms"]["p50"] == 400
    assert log["after_publish_ms"]["p50"] == 40
    assert log["recognition_ms_table"]["n"] == 11
    assert log["solves"] is None


def test_log_counts_how_your_turn_and_river_solves_ended():
    def frame(**advice):
        return {"timing": {}, "fields": {"solver_advice": {
            "status": "ready", "decision": 9, "hand_id": 1, **advice}}}

    rows = [
        # Turn: the range rule first, then the solve 4.2 s after your turn.
        frame(street="turn", kind="multiway", heads_up=True, seconds=0.3),
        frame(street="turn", seconds=4.2),
        # River: still the range rule when you acted.
        frame(street="river", kind="multiway", heads_up=True, seconds=0.2),
        # Not counted: a multiway pot, the flop, a decision still computing.
        frame(street="turn", decision=12, kind="multiway", heads_up=False),
        frame(street="flop", decision=5, kind="multiway", heads_up=True),
        frame(street="river", decision=14, status="computing")]
    assert tool.solve_summary(rows) == {
        "solver": 1, "range_rule": 1, "solver_seconds": {
            "n": 1, "p10": 4.2, "p50": 4.2, "p90": 4.2, "mean": 4.2, "max": 4.2}}
    assert tool.solve_summary(rows[3:]) is None


def test_computer_describes_itself():
    about = tool.computer()
    assert about["logical_cpus"] and about["numpy"] and about["opencv"]
