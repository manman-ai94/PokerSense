import json

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
        self.seen.append((frame, sample["pts_seconds"]))
        supported = self.scene(image)
        self.money(image)
        return {"scene_supported": supported}


SlowReader.read.__code__ = SlowReader.read.__code__.replace(
    co_filename="aa_reader.py")


def test_strips_cut_the_phone_from_every_nth_frame(tmp_path):
    video = recording(tmp_path / "rec")
    got = list(tool.strips(video, start=0.5, step=4, count=5))
    assert len(got) == 5
    expected = [round(n / 30, 3) for n in (16, 20, 24, 28, 32)]
    assert [round(at, 3) for at, _ in got] == expected
    assert all(strip.shape == (1080, 498, 3) for _, strip in got)
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


def test_profile_with_the_recorder_running(tmp_path):
    video = recording(tmp_path / "rec")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = tool.profile(video, SlowReader, start=0, step=2, count=6,
                          load="recorder", scratch=scratch)
    assert result["recorder"]["offered"] > 0
    assert (scratch / "recording" / "recording.json").is_file()


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


def test_computer_describes_itself():
    about = tool.computer()
    assert about["logical_cpus"] and about["numpy"] and about["opencv"]
