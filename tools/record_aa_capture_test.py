"""Bounded, video-only capture-card recording. No recognizers or advice loaded."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from poker_engine.data_paths import private_root as data_private_root


def record(output, duration=1800):
    if type(duration) is not int or not 1 <= duration <= 1800:
        raise ValueError("duration must be 1..1800 seconds")
    private_root = data_private_root().resolve(strict=True)
    output = output.resolve()
    if output.parent != private_root:
        raise ValueError("record only in a new direct child of the private root")
    if shutil.disk_usage(private_root).free < 25 * 1024 ** 3:
        raise ValueError("at least 25 GiB free required before recording")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg missing")
    output.mkdir(exist_ok=False)
    status = {"state": "starting", "recorder_pid": os.getpid(),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "device": "UGREEN 25854",
              "expected_platform": "AA_phone_8seat_unvalidated",
              "duration_limit_seconds": duration, "size_limit_bytes": 20 * 1024 ** 3,
              "minimum_free_bytes": 20 * 1024 ** 3,
              "audio": False, "recognition_running": False,
              "strategy_running": False,
              "codec": "original MJPEG packets; no additional video encoding",
              "timestamp_note": "container timestamps are not phone clock or latency"}

    def write_status():
        temporary = output / "status.tmp"
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(output / "status.json")

    write_status()
    started = time.monotonic()
    command = [ffmpeg, "-hide_banner", "-n", "-nostats", "-stats_period", "1",
               "-progress", str(output / "progress.log"),
               "-f", "dshow", "-rtbufsize", "256M", "-video_size", "1920x1080",
               "-framerate", "30", "-vcodec", "mjpeg", "-i", "video=UGREEN 25854",
               "-map", "0:v:0", "-an", "-c:v", "copy", "-t", str(duration),
               "-f", "segment", "-segment_time", "60", "-reset_timestamps", "0",
               "-segment_list", str(output / "segments.csv"),
               "-segment_list_type", "csv", str(output / "segment_%04d.mkv")]
    with (output / "capture.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        status["capture_pid"] = process.pid
        reason = "duration_or_source_end"
        try:
            while process.poll() is None:
                segments = list(output.glob("segment_*.mkv"))
                size = sum(p.stat().st_size for p in segments)
                status.update(state="recording" if size else "starting",
                              recorded_bytes=size, segment_files=len(segments),
                              updated_utc=datetime.now(timezone.utc).isoformat())
                write_status()
                if (output / "STOP").exists():
                    reason = "user_stop"
                    break
                if size >= status["size_limit_bytes"]:
                    reason = "size_limit"
                    break
                if shutil.disk_usage(private_root).free < status["minimum_free_bytes"]:
                    reason = "low_disk_space"
                    break
                if time.monotonic() - started > duration + 20:
                    reason = "wall_clock_limit"
                    break
                time.sleep(1)
        finally:
            if process.poll() is None:
                try:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                    process.wait(timeout=15)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
                    reason += "_forced_termination"
            process.stdin.close()
            status.update(state="stopped" if process.returncode == 0 else "failed",
                          stop_reason=reason, exit_code=process.returncode,
                          ended_utc=datetime.now(timezone.utc).isoformat())
            write_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=1800)
    args = parser.parse_args()
    record(args.output, args.duration)
