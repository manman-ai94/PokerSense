"""Re-encode a recording that Windows wrote too big (26 GB an hour).

Before 2026-10-15 a Windows recording could be written by Media Foundation's
H.264 at a fixed 1 bit per pixel (``aa_recorder``): 18 minutes came to
7.95 GB, too big to upload. This writes each segment again with the encoder a
recording uses now (FFmpeg; ``mp4v`` without OpenH264), frame for frame, so
``segments.csv`` and ``frames.jsonl`` still line up with the video:

    PYTHONPATH=src;. .venv\\Scripts\\python.exe tools\\shrink_recording.py <录像文件夹> [...]

Each new segment is checked to have as many frames as the old one before
anything is replaced. The old segments are moved, not deleted, to
``PokerSense_private/upload/originals/<录像文件夹名>/`` (outside the
recordings folder, so they are never uploaded); delete them by hand once the
owner has the recording. ``recording.json`` keeps a note (``reencoded``).
A recording whose ``recording.json`` already names the FFmpeg backend is left
alone.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2  # noqa: E402

from poker_engine.data_paths import private_root  # noqa: E402
from poker_engine.desktop import aa_recorder  # noqa: E402

WORK = ".shrink"


def open_writer(path, fps, size, writers=aa_recorder.WRITERS):
    """The first writer that opens outside a refused backend: (writer,
    fourcc, backend)."""
    for factory in writers:
        writer = factory(path, fps, size)
        backend = aa_recorder.backend_of(writer) if writer.isOpened() else None
        if writer.isOpened() and backend not in aa_recorder.REFUSED_BACKENDS:
            return writer, getattr(factory, "fourcc", None), backend
        writer.release()
        if Path(path).exists():
            Path(path).unlink()
    raise RuntimeError("no video encoder opened")


def reencode(source, target, writers=aa_recorder.WRITERS):
    """Frames read and written, the encoder used: (count, fourcc, backend)."""
    capture = cv2.VideoCapture(str(source))
    fps = capture.get(cv2.CAP_PROP_FPS) or aa_recorder.FPS
    writer = fourcc = backend = None
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if writer is None:
                size = (frame.shape[1], frame.shape[0])
                writer, fourcc, backend = open_writer(target, fps, size, writers)
            writer.write(frame)
            count += 1
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    return count, fourcc, backend


def frames_in(path):
    capture = cv2.VideoCapture(str(path))
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    return count


def shrink(folder, *, originals=None, writers=aa_recorder.WRITERS, out=print):
    """Re-encode one recording folder in place; a summary dict."""
    folder = Path(folder)
    summary_path = folder / "recording.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("backend") == "FFMPEG":
        out(f"{folder.name}: 已经是新编码，不用压。")
        return {"folder": folder.name, "skipped": True}
    segments = sorted(folder.glob("segment_*.mp4"))
    if not segments:
        raise RuntimeError(f"{folder} 里没有录像片段")
    work = folder / WORK
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    before = sum(path.stat().st_size for path in segments)
    fourcc = backend = None
    for number, segment in enumerate(segments, 1):
        target = work / segment.name
        count, fourcc, backend = reencode(segment, target, writers)
        if count == 0 or frames_in(target) != count:
            shutil.rmtree(work, ignore_errors=True)
            raise RuntimeError(f"{segment.name} 压完帧数对不上，什么都没改")
        out(f"{folder.name}: {number}/{len(segments)} {segment.name} {count} 帧 "
            f"{segment.stat().st_size / 1e6:.0f} MB → "
            f"{target.stat().st_size / 1e6:.0f} MB")
    keep = Path(originals or private_root() / "upload" / "originals") / folder.name
    keep.mkdir(parents=True, exist_ok=True)
    for segment in segments:
        shutil.move(str(segment), str(keep / segment.name))
        os.replace(work / segment.name, segment)
    work.rmdir()
    after = sum(path.stat().st_size for path in segments)
    summary["reencoded"] = {"from": [summary.get("fourcc"), summary.get("backend")],
                            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                            "megabytes_before": round(before / 1e6, 1)}
    summary.update(fourcc=fourcc, backend=backend, megabytes=round(after / 1e6, 1))
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    out(f"{folder.name}: {before / 1e6:.0f} MB → {after / 1e6:.0f} MB；"
        f"原件在 {keep}")
    return {"folder": folder.name, "skipped": False, "before": before,
            "after": after, "originals": str(keep)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--originals", type=Path)
    args = parser.parse_args(argv)
    for folder in args.folders:
        shrink(folder, originals=args.originals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
