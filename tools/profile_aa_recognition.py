"""Where the window's recognition time goes, on this computer.

``log`` reads window logs (``frames.jsonl`` in a recording folder, and its
``recording.json``) and prints totals only: frames read a second, the time
of each step of a frame (waiting for the card, recognition, table math,
advice), how many frames the card gave and the recorder skipped, and how
long the heads-up turn and river solves took.

``run`` reads a recording's frames one after another (every ``--step``-th
video frame, as the window samples them) and recognizes each twice: once
plainly timed, once under Python's profiler, which splits the time over the
reader's steps (scene, glyphs, money, cards, seats, ...). The same command on
two computers says which step makes one slower. ``--load recorder`` runs the
window's recorder at 30 frames a second alongside, as it does live;
``--load status`` asks for the window's state four times a second, as the
signal window does (``/api/status``, answered as this checkout answers it);
with a load the run is timed only (Python 3.12's profiler sees every
thread). ``--threads N`` limits OpenCV's and the math libraries' worker
threads to N. The reader uses the recognition bundle the window uses on
this computer (``app_update.installed_recognition`` in the window's data
folder: ``$POKERSENSE_DATA_ROOT/aa-live-state`` for a source checkout with a
data folder, else the per-version folder under ``%LOCALAPPDATA%``), and the
development profile ``DEFAULT_PROFILE`` only where none is installed (its
``G:/`` and old-checkout paths are mapped on the Mac, not on Windows, where
``G:/`` is a real drive); ``--profile`` names another. ``--hashes FILE``
writes a fingerprint of each frame's result, per field; ``compare A B``
says which fields differ between two runs (two versions of the code on the
same frames).

All print JSON lines of totals, function names and fingerprints, never
table data.

    PYTHONPATH=src:. .venv/bin/python tools/profile_aa_recognition.py log \\
        <recording folder or frames.jsonl> [...]
    PYTHONPATH=src:. .venv/bin/python tools/profile_aa_recognition.py run \\
        --video <recording folder> [--start 120] [--frames 300] [--step 4] \\
        [--load recorder|status] [--threads N] [--exclude 300-820] [--hashes FILE]
    PYTHONPATH=src:. .venv/bin/python tools/profile_aa_recognition.py compare A B
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

DEFAULT_PROFILE = "configs/reproduction/aa8_candidate_v2/factory.json"
INSTALLS = "PokerSense-AA"  # the window's per-version folders under %LOCALAPPDATA%
# The reader's own steps, whose callees are listed (file name, function).
PARENTS = (("aa_reader.py", "read"), ("aa8_candidate_v2.py", "read"),
           ("aa8_holdout_predict.py", "read"))
TOP = 25                    # functions listed by their own time
SOURCE_ID = "profile-aa-recognition"     # one source for both runs of a compare
POLL_SECONDS = 0.25         # the signal window asks again 250 ms after an answer
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")


# -- totals ---------------------------------------------------------------------

def quantile(values, share):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    return round(values[min(len(values) - 1, int(share * (len(values) - 1) + .5))], 1)


def spread(values):
    """{n, p10, p50, p90, mean, max} of the numbers in ``values``, or None."""
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {"n": len(values), "p10": quantile(values, .1), "p50": quantile(values, .5),
            "p90": quantile(values, .9), "mean": round(statistics.fmean(values), 1),
            "max": round(max(values), 1)}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# -- log ------------------------------------------------------------------------

def log_rows(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("timing"), dict):
                yield row


def log_summary(path):
    """Timing totals of one window log."""
    rows = list(log_rows(path))
    out = {"log": Path(path).name, "rows": len(rows)}
    if len(rows) < 2:
        return out
    out["code"] = next((row["code"] for row in rows if row.get("code")), None)
    timing = [row["timing"] for row in rows]
    pts = [row.get("pts_seconds") for row in rows]
    span = pts[-1] - pts[0] if _number(pts[0]) and _number(pts[-1]) else 0
    out["minutes"] = round(span / 60, 2)
    out["frames_per_second"] = round((len(rows) - 1) / span, 2) if span > 0 else None
    seq = [row.get("source_frame") for row in rows]
    if span > 0 and type(seq[0]) is int and type(seq[-1]) is int:
        out["card_frames_per_second"] = round((seq[-1] - seq[0]) / span, 2)
    starts = [item.get("recognition_started_at") for item in timing]
    out["loop_ms"] = spread([(b - a) * 1000 for a, b in zip(starts, starts[1:])
                             if _number(a) and _number(b)])
    for key in ("source_read_ms", "recognition_ms", "math_ms", "advice_ms"):
        out[key] = spread([item.get(key) for item in timing])
    # After publishing: the log line and the window's pause before the next read.
    out["after_publish_ms"] = spread([
        (b["source_read_started_at"] - a["published_at"]) * 1000
        for a, b in zip(timing, timing[1:])
        if _number(a.get("published_at")) and _number(b.get("source_read_started_at"))])
    table = [row.get("fields", {}).get("scene_supported") is True for row in rows]
    out["recognition_ms_table"] = spread(
        [item.get("recognition_ms") for item, on in zip(timing, table) if on])
    out["recognition_ms_not_table"] = spread(
        [item.get("recognition_ms") for item, on in zip(timing, table) if not on])
    out["over_1s"] = sum(1 for item in timing
                         if (item.get("recognition_ms") or 0) > 1000)
    by_part = {}
    for at, item in zip(pts, timing):
        if _number(at):
            by_part.setdefault(int((at - pts[0]) // 600), []).append(
                item.get("recognition_ms"))
    out["recognition_ms_p50_by_10min"] = [quantile(values, .5)
                                          for _, values in sorted(by_part.items())]
    out["solves"] = solve_summary(rows)
    return out


def solve_summary(rows):
    """Your heads-up turn and river decisions, by the last advice each
    showed: answered by the solver (and its seconds, from your turn to the
    answer) or by the range rule (the solve could not run, timed out, or
    was not done before you acted)."""
    last = {}
    for row in rows:
        advice = (row.get("fields") or {}).get("solver_advice") or {}
        if (advice.get("street") in ("turn", "river") and advice.get("decision")
                is not None and advice.get("status") == "ready"):
            last[advice.get("hand_id"), advice["decision"], advice["street"]] = advice
    solved = [item for item in last.values() if "kind" not in item]
    rule = [item for item in last.values()
            if item.get("kind") == "multiway" and item.get("heads_up") is True]
    if not solved and not rule:
        return None
    return {"solver": len(solved), "range_rule": len(rule),
            "solver_seconds": spread([item.get("seconds") for item in solved])}


def recording_summary(folder):
    """What the recorder wrote down about itself, or None."""
    path = Path(folder) / "recording.json"
    if not path.is_file():
        return None
    meta = json.loads(path.read_text(encoding="utf-8"))
    out = {key: meta.get(key) for key in (
        "code", "fourcc", "backend", "api", "recorded_seconds", "megabytes",
        "offered_frames", "skipped_frames")}
    seconds, offered = meta.get("recorded_seconds"), meta.get("offered_frames")
    if _number(seconds) and seconds > 0 and _number(offered):
        given = offered + (meta.get("skipped_frames") or 0)
        out["card_frames_per_second"] = round(given / seconds, 2)
        out["recorder_skipped_share"] = round(
            (meta.get("skipped_frames") or 0) / max(1, given), 3)
    return out


def log_command(paths):
    results = []
    for raw in paths:
        path = Path(raw)
        logs = [path] if path.is_file() else sorted(path.glob("frames.jsonl*"))
        folder = path if path.is_dir() else path.parent
        results.append({"folder": folder.name, "recording": recording_summary(folder),
                        "logs": [log_summary(log) for log in logs]})
    return results


# -- this computer --------------------------------------------------------------

def _cpu_name():
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:                       # noqa: BLE001 - only a description
        pass
    return platform.processor() or None


def _memory_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong),
                            ("page_free", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong),
                            ("virtual_free", ctypes.c_ulonglong),
                            ("extended", ctypes.c_ulonglong)]
            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.total / 1024 ** 3, 1)
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=5).stdout
            return round(int(out) / 1024 ** 3, 1)
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return round(int(line.split()[1]) / 1024 ** 2, 1)
    except Exception:                       # noqa: BLE001 - only a description
        pass
    return None


def computer():
    """The computer, Python and the math libraries the numbers come from."""
    import cv2
    import numpy as np
    blas = None
    try:
        config = np.show_config(mode="dicts")
        blas = config["Build Dependencies"]["blas"]["name"]
    except Exception:                       # noqa: BLE001 - older numpy
        pass
    parallel = [line.strip() for line in cv2.getBuildInformation().splitlines()
                if "Parallel framework" in line or line.strip().startswith("IPP:")]
    return {"platform": platform.platform(), "cpu": _cpu_name(),
            "logical_cpus": os.cpu_count(), "memory_gb": _memory_gb(),
            "python": platform.python_version(), "numpy": np.__version__,
            "blas": blas, "opencv": cv2.__version__,
            "opencv_threads": cv2.getNumThreads(), "opencv_build": parallel,
            "thread_limits": {key: os.environ[key] for key in THREAD_VARIABLES
                              if key in os.environ}}


# -- run ------------------------------------------------------------------------

def strips(video, *, start=0.0, step=4, count=300, exclude=()):
    """(timeline seconds, video frame number, phone strip) of every
    ``step``-th video frame from ``start``, ``count`` of them, outside
    ``exclude`` windows; cut exactly as the window cuts the capture card's
    picture. The frame number counts like the card's: it skips the frames
    not read."""
    import cv2
    from poker_engine.desktop.aa_video_source import video_segments
    from poker_engine.perceptual.capture.normalization import (
        NormalizationConfig, normalize)
    config = NormalizationConfig(
        rotate_degrees=0, source_size=(1920, 1080),
        crop_after_rotation=(711, 0, 1209, 1080), output_size=(498, 1080),
        version="aa8-capture-canvas-v1")         # as aa_sources.AACaptureSource
    given = 0
    segments = video_segments(video)
    for index, segment in enumerate(segments):
        end = segments[index + 1].start if index + 1 < len(segments) else None
        if end is not None and end <= start:
            continue
        capture = cv2.VideoCapture(str(segment.path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        number = 0
        try:
            while given < count:
                if not capture.grab():
                    break
                at = segment.start + number / fps
                number += 1
                if at < start or (number - 1) % step or any(
                        low <= at < high for low, high in exclude):
                    continue
                ok, frame = capture.retrieve()
                if not ok:
                    break
                given += 1
                yield at, round(at * fps), normalize(frame, config)
        finally:
            capture.release()
        if given >= count:
            return


class RecorderLoad:
    """The window's recorder fed the newest strip 30 times a second."""

    def __init__(self, folder):
        import threading
        from poker_engine.desktop.aa_recorder import AARecorder
        from poker_engine.perceptual.capture.normalization import NormalizationConfig
        normalization = NormalizationConfig(
            rotate_degrees=0, source_size=(1920, 1080),
            crop_after_rotation=(711, 0, 1209, 1080), output_size=(498, 1080),
            version="aa8-capture-canvas-v1")
        self.recorder = AARecorder(Path(folder) / "recording", normalization)
        self.latest = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._feed, daemon=True)
        self.thread.start()

    def _feed(self):
        began = time.monotonic()
        tick = 0
        while not self.stop_event.is_set():
            if self.latest is not None:
                self.recorder.offer(self.latest)
            tick += 1
            self.stop_event.wait(max(0.0, began + tick / 30 - time.monotonic()))

    def close(self):
        self.stop_event.set()
        self.thread.join()
        status = self.recorder.stop("profile_done")
        meta = self.recorder.meta
        return {"fourcc": meta.get("fourcc"), "backend": meta.get("backend"),
                "offered": self.recorder.offered, "skipped": self.recorder.skipped,
                "megabytes": status.get("megabytes")}


def status_answer():
    """How this checkout answers the signal window's ``/api/status``:
    (name, keep, answer). ``keep(text, payload)`` is what the window keeps
    of each frame's result when it publishes it (given its JSON text and
    the parsed result), ``answer(kept)`` the reply's bytes. Newest first:
    the signal window's part of the result kept as compact JSON and spliced
    into the reply (``?view=signal``); the whole text spliced in; or the
    result copied (``aa_session``) and encoded value by value (FastAPI)."""
    try:
        from poker_engine.desktop.aa_server import status_json
        from poker_engine.desktop.aa_session import EncodedJSON
    except ImportError:
        import copy
        from fastapi.encoders import jsonable_encoder

        def copied(payload):
            return json.dumps(jsonable_encoder({"payload": copy.deepcopy(payload)}),
                              ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
        return "copy-and-encode", lambda text, payload: payload, copied

    def spliced(kept):
        return status_json({"payload": EncodedJSON(kept)}).body
    try:
        from poker_engine.desktop.aa_session import signal_json
    except ImportError:
        return "published-json", lambda text, payload: text, spliced
    return "signal-json", lambda text, payload: signal_json(payload), spliced


class StatusLoad:
    """The signal window asking for the state: every ``POLL_SECONDS`` after
    an answer, the latest result answered as this checkout's ``/api/status``
    does it (``status_answer``)."""

    def __init__(self):
        import threading
        self.path, _, self.answer = status_answer()
        self.latest = None
        self.lock = threading.Lock()
        self.times, self.sizes = [], []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _poll(self):
        while not self.stop_event.wait(POLL_SECONDS):
            with self.lock:
                latest = self.latest
            if latest is None:
                continue
            began = time.perf_counter()
            body = self.answer(latest)
            self.times.append((time.perf_counter() - began) * 1000)
            self.sizes.append(len(body) / 1024)

    def close(self):
        self.stop_event.set()
        self.thread.join()
        return {"path": self.path, "answers": len(self.times),
                "ms": spread(self.times), "kilobytes": spread(self.sizes)}


def fingerprints(payload):
    """A short fingerprint of each field of a result: equal fingerprints,
    equal values. Only the fingerprints leave the computer."""
    import hashlib
    return {key: hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=str).encode()).hexdigest()[:16] for key, value in payload.items()}


def compare(first, second):
    """Which fields differ, in how many frames, between two ``--hashes`` files."""
    def rows(path):
        return [json.loads(line) for line in Path(path).read_text(
            encoding="utf-8").splitlines() if line.strip()]
    left, right = rows(first), rows(second)
    differ, missing = {}, {}
    for a, b in zip(left, right):
        if (a["at"], a["source_frame"]) != (b["at"], b["source_frame"]):
            raise SystemExit("the two runs did not read the same frames")
        for key in set(a["fields"]) | set(b["fields"]):
            if key not in a["fields"] or key not in b["fields"]:
                missing[key] = missing.get(key, 0) + 1
            elif a["fields"][key] != b["fields"][key]:
                differ.setdefault(key, {"frames": 0, "first": a["frame"]})
                differ[key]["frames"] += 1
    return {"frames": min(len(left), len(right)),
            "frame_counts": [len(left), len(right)],
            "same": not differ and not missing and len(left) == len(right),
            "fields_differing": differ, "fields_missing": missing}


def _label(function, root):
    file, line, name = function
    try:
        file = Path(file).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        file = Path(file).name
    return f"{file}:{line}({name})"


def breakdown(stats, frames, root):
    """Per-frame ms under each of the reader's steps, and the functions
    taking the most time of their own."""
    table = stats.stats
    children = {}
    for function, (_, _, _, _, callers) in table.items():
        for caller, edge in callers.items():
            children.setdefault(caller, []).append((function, edge))
    steps = {}
    for function in table:
        if not any(Path(function[0]).name == file and function[2] == name
                   for file, name in PARENTS):
            continue
        rows = sorted(children.get(function, ()), key=lambda item: -item[1][3])
        steps[_label(function, root)] = {
            "ms": round(table[function][3] * 1000 / frames, 2),
            "steps": [{"function": _label(child, root),
                       "ms": round(edge[3] * 1000 / frames, 2),
                       "calls": round(edge[1] / frames, 2)}
                      for child, edge in rows if edge[3] * 1000 / frames >= 0.2]}
    own = sorted(table.items(), key=lambda item: -item[1][2])[:TOP]
    return {"steps": steps,
            "own_time": [{"function": _label(function, root),
                          "ms": round(values[2] * 1000 / frames, 2),
                          "calls": round(values[1] / frames, 2)}
                         for function, values in own]}


def profile(video, reader_factory, *, start=0.0, step=4, count=300, exclude=(),
            load=None, scratch=None, hashes=None, profiled=True):
    """Recognize the strips twice (timed, then profiled); totals per frame.
    With a ``load``, or ``profiled`` false, the frames are only timed."""
    import cProfile
    import hashlib
    import pstats
    import cv2
    from poker_engine.desktop.aa_session import frame_summary
    timed = reader_factory()
    profiled = reader_factory() if load is None and profiled else None
    profiler = cProfile.Profile()
    recorder = RecorderLoad(scratch) if load == "recorder" else None
    status = StatusLoad() if load == "status" else None
    _, keep, _ = status_answer()
    times = {key: [] for key in ("recognition_ms", "profiled_ms", "hash_ms",
                                 "json_ms", "preview_ms", "summary_ms")}
    sizes = []
    table = 0
    frame = -1
    out = None if hashes is None else open(hashes, "w", encoding="utf-8")
    try:
        for frame, (at, number, image) in enumerate(strips(
                video, start=start, step=step, count=count, exclude=exclude)):
            if recorder is not None:
                recorder.latest = image
            began = time.perf_counter()
            sample = {"pts_seconds": at, "source_frame": number,
                      "source_id": SOURCE_ID,
                      "sha256": hashlib.sha256(image.tobytes()).hexdigest()}
            hashed = time.perf_counter()
            payload = timed.read(image, frame, sample)
            read = time.perf_counter()
            # Published as the window does: encoded, parsed again, and what
            # its status answers from kept.
            text = json.dumps(payload, allow_nan=False)
            payload = json.loads(text)
            kept = keep(text, payload)
            encoded = time.perf_counter()
            sizes.append(len(text) / 1024)
            if status is not None:
                with status.lock:
                    status.latest = kept
            cv2.imencode(".jpg", image)
            previewed = time.perf_counter()
            json.dumps(frame_summary(payload), ensure_ascii=False)
            summarized = time.perf_counter()
            table += payload.get("scene_supported") is True
            for key, low, high in (("hash_ms", began, hashed),
                                   ("recognition_ms", hashed, read),
                                   ("json_ms", read, encoded),
                                   ("preview_ms", encoded, previewed),
                                   ("summary_ms", previewed, summarized)):
                times[key].append((high - low) * 1000)
            if out is not None:
                out.write(json.dumps({"frame": frame, "at": round(at, 4),
                                      "source_frame": number,
                                      "fields": fingerprints(payload)}) + "\n")
            if profiled is None:
                continue
            began = time.perf_counter()
            profiler.enable()
            profiled.read(image, frame, sample)
            profiler.disable()
            times["profiled_ms"].append((time.perf_counter() - began) * 1000)
    finally:
        loads = {"recorder": recorder.close() if recorder is not None else None,
                 "status": status.close() if status is not None else None}
        if out is not None:
            out.close()
    frames = frame + 1
    if not frames:
        raise SystemExit("no frames read from the recording")
    result = {"frames": frames, "table_frames": table, "step": step,
              "start": start, "load": load, **loads,
              "payload_kilobytes": spread(sizes),
              **{key: spread(values) for key, values in times.items()}}
    if profiled is not None:
        result.update(breakdown(pstats.Stats(profiler), frames,
                                Path(__file__).resolve().parents[1]))
    return result


def window_states(environ=os.environ):
    """The data folders a window started from this checkout keeps its
    recognition bundle in (as ``packaging/aa_live_entry.default_state``)."""
    from poker_engine import __version__
    from poker_engine.data_paths import DATA_ROOT_ENV
    states = []
    data = environ.get(DATA_ROOT_ENV, "").strip()
    if data:
        states.append(Path(data).expanduser() / "aa-live-state")
    base = environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    states.append(root / INSTALLS / __version__)
    return states


def choose_profile(given=None, environ=os.environ):
    """(profile path, bundle digest or None, what it is): the one given,
    else the installed recognition bundle's (checked against its digest, as
    the window does), else the development profile."""
    if given is not None:
        return Path(given), None, {"profile": "given"}
    from poker_engine.desktop.app_update import installed_recognition
    for state in window_states(environ):
        found = installed_recognition(state)
        if found is not None:
            path, digest = found
            return path, digest, {"profile": "installed", "bundle": digest[:12]}
    return Path(DEFAULT_PROFILE), None, {"profile": "development"}


def _limit_threads(threads):
    """Before numpy and OpenCV load: at most ``threads`` worker threads."""
    for key in THREAD_VARIABLES:
        os.environ[key] = str(threads)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    log = commands.add_parser("log", help="timing totals of window logs")
    log.add_argument("paths", nargs="+", type=Path)
    run = commands.add_parser("run", help="profile recognition on a recording")
    run.add_argument("--video", type=Path, required=True)
    run.add_argument("--profile", type=Path,
                     help="the reader's profile (default: the installed "
                          "recognition bundle, else the development profile)")
    run.add_argument("--start", type=float, default=120.0,
                     help="seconds into the recording to begin (default 120)")
    run.add_argument("--frames", type=int, default=300)
    run.add_argument("--step", type=int, default=4,
                     help="every N-th video frame (4 = 7.5 a second, as on the Mac)")
    run.add_argument("--exclude", action="append", default=[],
                     help="seconds to skip, e.g. 300-820")
    run.add_argument("--load", choices=("recorder", "status"),
                     help="also run the window's recorder, or its state requests")
    run.add_argument("--threads", type=int,
                     help="limit OpenCV and math-library worker threads")
    run.add_argument("--timed-only", action="store_true",
                     help="time the frames without the profiled second pass")
    run.add_argument("--hashes", type=Path,
                     help="write each frame's per-field fingerprints here")
    pair = commands.add_parser("compare", help="fields that differ between two runs")
    pair.add_argument("first", type=Path)
    pair.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    if args.command == "log":
        for item in log_command(args.paths):
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if args.command == "compare":
        result = compare(args.first, args.second)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["same"] else 1
    if args.threads is not None:
        _limit_threads(args.threads)
    import cv2
    if args.threads is not None:
        cv2.setNumThreads(args.threads)
    import tempfile
    from poker_engine.desktop.aa_reader import AA8Reader
    from poker_engine.desktop.aa_video_source import parse_windows
    path, digest, which = choose_profile(args.profile)
    with tempfile.TemporaryDirectory(prefix="pokersense-profile-") as scratch:
        result = profile(args.video,
                         lambda: AA8Reader(path, bundle_sha256=digest),
                         start=args.start, step=args.step, count=args.frames,
                         exclude=parse_windows(args.exclude), load=args.load,
                         scratch=scratch, hashes=args.hashes,
                         profiled=not args.timed_only)
    print(json.dumps({"computer": computer(), "threads": args.threads,
                      "video": args.video.name, **which, **result},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
