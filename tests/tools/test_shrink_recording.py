"""Re-encoding a recording Windows wrote too big, frame for frame."""

import json

import numpy as np

from poker_engine.desktop import aa_recorder
from tools import shrink_recording


def big_recording(folder, segments=2, frames=12):
    folder.mkdir(parents=True)
    for number in range(segments):
        writer = aa_recorder.fourcc_writer("mp4v")(
            folder / f"segment_{number:04d}.mp4", 30, (320, 180))
        for tick in range(frames):
            frame = np.zeros((180, 320, 3), np.uint8)
            frame[:, 120:200] = (40, 90 + tick, 30)
            writer.write(frame)
        writer.release()
    (folder / "segments.csv").write_text("x\n", encoding="utf-8")
    (folder / "recording.json").write_text(json.dumps({"fourcc": "avc1",
                                                       "megabytes": 9.9}))
    return folder


def test_segments_are_written_again_and_the_old_ones_kept_aside(tmp_path):
    folder = big_recording(tmp_path / "rec" / "20261015-102047-live")
    keep = tmp_path / "originals"
    result = shrink_recording.shrink(folder, originals=keep, out=lambda text: None)
    assert result["skipped"] is False
    for number in range(2):
        name = f"segment_{number:04d}.mp4"
        assert shrink_recording.frames_in(folder / name) == 12
        assert (keep / folder.name / name).exists()
    assert not (folder / shrink_recording.WORK).exists()
    summary = json.loads((folder / "recording.json").read_text())
    assert summary["backend"] == "FFMPEG" and summary["fourcc"] in aa_recorder.FOURCCS
    assert summary["reencoded"]["from"] == ["avc1", None]
    assert (folder / "segments.csv").read_text() == "x\n"       # untouched
    # A second run leaves it alone.
    again = shrink_recording.shrink(folder, originals=keep, out=lambda text: None)
    assert again["skipped"] is True


def test_nothing_changes_when_frames_do_not_match(tmp_path, monkeypatch):
    folder = big_recording(tmp_path / "rec" / "x", segments=1)
    before = (folder / "segment_0000.mp4").read_bytes()
    monkeypatch.setattr(shrink_recording, "frames_in", lambda path: 0)
    try:
        shrink_recording.shrink(folder, originals=tmp_path / "o", out=lambda t: None)
    except RuntimeError as error:
        assert "帧数" in str(error)
    else:
        raise AssertionError("should refuse")
    assert (folder / "segment_0000.mp4").read_bytes() == before
    assert not (folder / shrink_recording.WORK).exists()
    assert json.loads((folder / "recording.json").read_text())["fourcc"] == "avc1"
