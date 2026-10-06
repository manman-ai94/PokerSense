"""Record the capture card into 60-second H.264 segments with segments.csv.

Reads the card the same way live recognition does (OpenCV, AVFoundation on
macOS), so the recording has the frame rate the live pipeline sees. Frames are
written on a fixed 30 fps clock aligned to wall time: a late frame is
repeated and an early one dropped, so segment timestamps follow real time.
The output folder plays back with ``--replay-video`` and
``tools/measure_aa_realtime.py``. Run from Terminal on macOS (camera access).

    PYTHONPATH=src:. .venv/bin/python tools/record_aa_capture.py \\
        --minutes 20 --label spectate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import cv2

from poker_engine.data_paths import private_root
from poker_engine.perceptual.capture.capture_card_backend import (
    _CAP_CONSTANTS, default_capture_api)

FPS = 30
SIZE = (1920, 1080)


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


def record(out, *, index=0, api=None, seconds=1200, segment_seconds=60):
    api = api or default_capture_api()
    cap, frame = open_device(index, api)
    out.mkdir(parents=True, exist_ok=False)
    meta = {"device_index": index, "api": api, "fps": FPS, "size": list(SIZE),
            "requested_seconds": seconds,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    begin = time.monotonic()
    written = captured = 0
    segment = writer = None
    seg_start = seg_written = 0
    index_lines = []

    def close_segment():
        if writer is not None:
            writer.release()
            end = seg_start + seg_written / FPS
            index_lines.append(f"segment_{segment:04d}.mp4,{seg_start:.6f},{end:.6f}")
            (out / "segments.csv").write_text("\n".join(index_lines) + "\n",
                                              encoding="utf-8")

    try:
        while True:
            now = time.monotonic() - begin
            if now >= seconds:
                break
            if writer is None or seg_written >= segment_seconds * FPS:
                close_segment()
                segment = 0 if segment is None else segment + 1
                seg_start, seg_written = written / FPS, 0
                writer = cv2.VideoWriter(str(out / f"segment_{segment:04d}.mp4"),
                                         cv2.VideoWriter_fourcc(*"avc1"), FPS, SIZE)
            # Fill the fixed clock up to now with the newest frame.
            due = int(now * FPS) + 1
            while written < due and seg_written < segment_seconds * FPS:
                writer.write(frame)
                written += 1
                seg_written += 1
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
    finally:
        close_segment()
        cap.release()
        elapsed = time.monotonic() - begin
        meta.update(recorded_seconds=round(written / FPS, 3),
                    captured_frames=captured,
                    captured_fps=round(captured / elapsed, 2) if elapsed else None)
        (out / "recording.json").write_text(json.dumps(meta, indent=1),
                                            encoding="utf-8")
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--label", default="session")
    parser.add_argument("--device", type=int, default=0)
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
