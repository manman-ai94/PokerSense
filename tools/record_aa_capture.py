"""Record the capture card into 60-second H.264 segments with segments.csv.

Reads the card the same way live recognition does (OpenCV, AVFoundation on
macOS), so the recording has the frame rate the live pipeline sees. Frames are
written on a fixed 30 fps clock aligned to wall time: a late frame is
repeated and an early one dropped, so segment timestamps follow real time
(``aa_recorder.SegmentWriter``; the live service records the same way).
The output folder plays back with ``--replay-video`` and
``tools/measure_aa_realtime.py``. Run from Terminal on macOS (camera access).

The device is the one that shows the phone (``aa_recorder.picture``: the
phone's screen between black bars), tried in order from 0 unless
``--device`` names one; the Mac's own camera also gives 1920x1080 and can
be device 0. Nothing is recorded when no device shows the phone, or with
less than ``MIN_FREE_GB`` free; a recording stops at ``STOP_FREE_GB``.
Closing the Terminal window finishes the last segment like Ctrl-C does.

    PYTHONPATH=src:. .venv/bin/python tools/record_aa_capture.py \\
        --minutes 20 --label spectate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import time

import cv2

from poker_engine.data_paths import private_root
from poker_engine.desktop import aa_recorder
from poker_engine.desktop.aa_recorder import SegmentWriter, picture
from poker_engine.perceptual.capture.capture_card_backend import (
    _CAP_CONSTANTS, default_capture_api)

FPS = 30
SIZE = (1920, 1080)
DEVICES = range(4)          # device numbers tried for the phone
LOOK_SECONDS = 3            # how long a device may show black before it counts
NO_PHONE = "没找到采集卡画面，录像没有开始。"
HINT = "（采集卡要接好，手机要亮屏并切到“屏幕镜像”。）"


def open_device(index, api):
    cap = cv2.VideoCapture(index, _CAP_CONSTANTS[api])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, SIZE[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, SIZE[1])
    cap.set(cv2.CAP_PROP_FPS, FPS)
    ok, frame = cap.read()
    if not ok or frame.shape[1::-1] != SIZE:
        cap.release()
        raise SystemExit(f"device {index} did not give a {SIZE[0]}x{SIZE[1]} frame "
                         "(on macOS run from Terminal and allow camera access)")
    return cap, frame


def look(cap, frame, clock=time.monotonic):
    """The first frame showing the phone, or None (see ``picture``)."""
    until = clock() + LOOK_SECONDS
    while True:
        seen = picture(frame)
        if seen == "phone":
            return frame
        if seen == "other" or clock() >= until:
            return None
        ok, frame = cap.read()
        if not ok:
            return None


def find_phone(api, devices=DEVICES):
    """(device number, capture, first phone frame) of the first device that
    shows the phone; SystemExit with a plain message when none does."""
    for index in devices:
        try:
            cap, frame = open_device(index, api)
        except SystemExit:
            continue
        phone = look(cap, frame)
        if phone is not None:
            return index, cap, phone
        cap.release()
    raise SystemExit(NO_PHONE + HINT)


class WindowClosed(Exception):
    """The Terminal window closed or the process was asked to stop."""


def _closed(signum, frame):
    raise WindowClosed(signal.Signals(signum).name)


def _catch_window_close():
    """Closing the window (SIGHUP) or a stop request (SIGTERM) ends the
    recording like Ctrl-C; the handlers there were before, to put back."""
    handlers = {}
    for name in ("SIGHUP", "SIGTERM"):
        if hasattr(signal, name):
            try:
                handlers[name] = signal.signal(getattr(signal, name), _closed)
            except ValueError:          # not the main thread
                pass
    return handlers


def record(out, *, index=None, api=None, seconds=1200, segment_seconds=60):
    api = api or default_capture_api()
    free = aa_recorder.free_bytes(out.parent)
    if free < aa_recorder.MIN_FREE_GB * aa_recorder.GB:
        raise SystemExit(f"硬盘只剩 {int(free // aa_recorder.GB)} GB，不到 "
                         f"{aa_recorder.MIN_FREE_GB} GB，录像没有开始。先腾出一些空间。")
    index, cap, frame = find_phone(api, DEVICES if index is None else (index,))
    print(f"[AA] device {index} shows the phone", flush=True)
    out.mkdir(parents=True, exist_ok=False)
    meta = {"device_index": index, "api": api, "fps": FPS, "size": list(SIZE),
            "device_check": "phone_between_black_bars",
            "requested_seconds": seconds,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    begin = time.monotonic()
    captured = 0
    segments = SegmentWriter(out, fps=FPS, size=SIZE, segment_seconds=segment_seconds)
    handlers = _catch_window_close()
    checked = None
    try:
        while True:
            now = time.monotonic() - begin
            if now >= seconds:
                break
            # Fill the fixed clock up to now with the newest frame.
            segments.offer(frame, now)
            if segments.segment != checked:          # a new segment began
                checked = segments.segment
                free = aa_recorder.free_bytes(out)
                if free < aa_recorder.STOP_FREE_GB * aa_recorder.GB:
                    meta["stopped_reason"] = "low_disk_space"
                    break
            ok, latest = cap.read()
            if not ok:
                meta["stopped_reason"] = "device_read_failed"
                break
            frame, captured = latest, captured + 1
            if captured % (10 * FPS) == 0:
                print(f"[AA] {now:7.1f}s  captured {captured}  "
                      f"({captured / max(now, 1e-6):.1f} fps)", flush=True)
    except KeyboardInterrupt:
        meta["stopped_reason"] = "interrupted"
    except WindowClosed as closed:
        meta["stopped_reason"] = f"window_closed_{closed}"
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
        segments.close()
        cap.release()
        elapsed = time.monotonic() - begin
        meta.update(recorded_seconds=round(segments.seconds, 3),
                    captured_frames=captured,
                    captured_fps=round(captured / elapsed, 2) if elapsed else None)
        (out / "recording.json").write_text(json.dumps(meta, indent=1),
                                            encoding="utf-8")
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--label", default="session")
    parser.add_argument("--device", type=int, default=None,
                        help="device number; by default the first that shows the phone")
    parser.add_argument("--api", default=None)
    parser.add_argument("--out-root", type=Path,
                        default=private_root() / "aa-mac-recordings")
    args = parser.parse_args(argv)
    label = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.label)
    out = args.out_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    print(f"[AA] recording {args.minutes} min into {out} (Ctrl-C stops early)")
    meta = record(out, index=args.device, api=args.api,
                  seconds=args.minutes * 60)
    print(f"[AA] done: {json.dumps(meta)}")


if __name__ == "__main__":
    main()
