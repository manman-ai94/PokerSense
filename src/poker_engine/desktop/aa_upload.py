"""Recordings back to the owner: each finished recording folder, uploaded.

A recording folder (segments, ``frames.jsonl``, ``recording.json``,
``flywheel/``) goes with ``rclone`` to ``<remote>:<folder>/<machine>/<name>/``
once its check-up sheet is written (``aa_after_session``). The owner's Mac
takes it back with ``tools/flywheel_sync.py pull``.

* What and where come from a local file (``PokerSense_private/upload/
  settings.json``): ``enabled`` (the window's switch, on by default),
  ``remote`` (an rclone remote, ``pokersense-upload``), ``folder``
  (``PokerSense 同事数据``), ``machine`` (this computer's name in the cloud
  folder; the host name when not set) and ``bwlimit``. The login itself is
  rclone's own config on this computer: no key is in this file, the
  repository or the log.
* Upload runs on its own thread, one recording at a time, in an rclone
  process at low priority with limited bandwidth. A failure never touches the
  recording: it is logged (``upload/upload.log``), shown in the window and
  tried again later.
* What was uploaded is kept in ``upload/state.json``: each recording's file
  list with sizes. A recording whose files differ from that list (never
  uploaded, cut off, or a sheet written afterwards) is uploaded again; rclone
  sends only the files whose size or checksum differ. So the next start
  finishes what the last one did not.
* After the files, a small ``upload.json`` (the file list with sizes) is
  written last: a recording without it, or whose files do not match it, is
  still on its way and the pull leaves it alone.
* Without rclone or without the remote the window says "未配置上传" and
  nothing else happens. Folders pulled from another machine (with
  ``pulled.json``) are never uploaded again.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from ..data_paths import private_root

REMOTE = "pokersense-upload"
FOLDER = "PokerSense 同事数据"
MARKER = "upload.json"           # written last, in the cloud folder only
PULLED = "pulled.json"           # in a folder the owner pulled from elsewhere
BWLIMIT = "1M"                   # bytes per second: leaves room for the game
START_DELAY = 30.0               # seconds after start before the first look
RETRY_WAITS = (60, 300, 900, 1800)
REPORT_WAIT = 1800               # longest wait for the check-up sheet
COPY_TIMEOUT = 3 * 3600
IDLE_WAIT = 3600                 # a look now and then (rclone set up meanwhile)
CHECK_EVERY = 60.0               # seconds a "configured" answer is kept
LOG_LIMIT = 1_000_000

_CURRENT = None


def current():
    """The uploader the window started, or None."""
    return _CURRENT


def machine_name(text):
    """A folder name for this computer: letters (any script), digits, - and _."""
    name = re.sub(r"[^\w\-]+", "-", str(text or "")).strip("-_")
    return name[:40] or "machine"


def default_settings():
    return {"enabled": True, "remote": REMOTE, "folder": FOLDER,
            "machine": machine_name(socket.gethostname()), "bwlimit": BWLIMIT,
            "rclone": ""}


def load_settings(path):
    settings = default_settings()
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key == "enabled" and type(value) is bool:
                settings[key] = value
            elif key in settings and key != "enabled" and isinstance(value, str):
                settings[key] = value.strip()
    settings["machine"] = machine_name(settings["machine"] or socket.gethostname())
    settings["remote"] = settings["remote"].rstrip(":") or REMOTE
    settings["folder"] = settings["folder"].strip("/") or FOLDER
    return settings


def write_json(path, value):
    """Write ``path`` whole or not at all."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


def manifest(folder):
    """The folder's files with their sizes, sorted, and a digest of the list."""
    folder = Path(folder)
    files = sorted([path.relative_to(folder).as_posix(), path.stat().st_size]
                   for path in folder.rglob("*") if path.is_file())
    digest = hashlib.sha256(json.dumps(files).encode("utf-8")).hexdigest()
    return {"files": files, "bytes": sum(size for _, size in files),
            "digest": digest}


def finished(folder):
    """A recording that is done (``recording.json`` is written at the end) and
    was made on this computer."""
    folder = Path(folder)
    return (folder.is_dir() and (folder / "recording.json").exists()
            and not (folder / PULLED).exists())


def run_process(args, timeout):
    """(return code, output) of ``args`` at low priority, without a window."""
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = (subprocess.BELOW_NORMAL_PRIORITY_CLASS
                                  | subprocess.CREATE_NO_WINDOW)
    elif shutil.which("nice"):
        args = ["nice", "-n", "10", *args]
    try:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, **extra)
    except subprocess.TimeoutExpired:
        return 124, "超时"
    except OSError as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def scrub(text, lines=6):
    """The last lines of rclone's output, without anything about tokens."""
    kept = [line.strip() for line in str(text).splitlines()
            if line.strip() and "token" not in line.lower()]
    return "\n".join(kept[-lines:])


class Uploader:
    """Uploads the finished recordings under ``root``, one at a time."""

    def __init__(self, root, *, base=None, run=run_process, which=shutil.which,
                 delay=START_DELAY, retry_waits=RETRY_WAITS, report_wait=REPORT_WAIT,
                 clock=time.monotonic):
        self.root = Path(root)
        base = Path(base) if base else private_root() / "upload"
        self.settings_path = base / "settings.json"
        self.state_path = base / "state.json"
        self.log_path = base / "upload.log"
        self.run, self.which, self.clock = run, which, clock
        self.delay, self.retry_waits, self.report_wait = delay, retry_waits, report_wait
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.reports = {}              # folder -> the check-up sheet's process
        self.extra = set()             # submitted folders outside ``root``
        self.uploading = None
        self.waiting = 0
        self.failures = 0
        self.last_error = None
        self.configured = None
        self.checked = None            # clock of the last "configured" check
        self.thread = None

    # -- the window's side ---------------------------------------------------------

    def start(self):
        global _CURRENT
        _CURRENT = self
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True,
                                           name="pokersense-upload")
            self.thread.start()
        return self

    def stop(self):
        global _CURRENT
        self.stopped.set()
        self.wake.set()
        if _CURRENT is self:
            _CURRENT = None

    def submit(self, folder, wait_for=None):
        """A recording just stopped: upload it once ``wait_for`` (the process
        writing its check-up sheet) has ended."""
        folder = Path(folder)
        with self.lock:
            if wait_for is not None:
                self.reports[str(folder)] = wait_for
            if folder.parent != self.root:
                self.extra.add(folder)
        self.wake.set()

    def settings(self):
        return load_settings(self.settings_path)

    def set_enabled(self, on):
        """The window's switch, kept in the settings file."""
        try:
            stored = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        stored = stored if isinstance(stored, dict) else {}
        stored["enabled"] = bool(on)
        write_json(self.settings_path, stored)
        self.checked = None
        self.wake.set()
        return self.status()

    def status(self):
        settings = self.settings()
        state = self._state()
        if self.configured is None or self.checked is None or (
                self.clock() - self.checked > CHECK_EVERY):
            self._check(settings)
        status = {"available": True, "enabled": settings["enabled"],
                  "configured": self.configured, "machine": settings["machine"],
                  "destination": self.destination(settings, ""),
                  "uploading": self.uploading, "waiting": self.waiting,
                  "uploaded": len(state), "last_error": self.last_error}
        status["message"] = self.message(status)
        return status

    @staticmethod
    def message(status):
        if not status["enabled"]:
            return "录像自动上传：已关。录像只存在这台电脑上。"
        if not status["configured"]:
            return "未配置上传：录像只存在这台电脑上（不影响录像和建议）。"
        if status["uploading"]:
            return f"正在上传录像 {status['uploading']}（后台慢慢传，不影响打牌）。"
        if status["last_error"]:
            return ("上次上传没成功，稍后自动再试；录像都在这台电脑上。"
                    f"原因：{status['last_error']}")
        if status["waiting"]:
            return f"录像自动上传：开。还有 {status['waiting']} 场等着传。"
        return f"录像自动上传：开。已传 {status['uploaded']} 场，没有等着传的。"

    # -- the upload thread ---------------------------------------------------------

    def _loop(self):
        if self.stopped.wait(self.delay):
            return
        while not self.stopped.is_set():
            self.wake.clear()
            ok = self.upload_all()
            if ok:
                self.failures = 0
                wait = IDLE_WAIT
            else:
                wait = self.retry_waits[min(self.failures, len(self.retry_waits) - 1)]
                self.failures += 1
            self.wake.wait(wait)

    def upload_all(self):
        """One pass: every recording that needs it, oldest first. False when
        one failed (the rest wait for the next pass)."""
        settings = self.settings()
        if not settings["enabled"] or not self._check(settings):
            return True                         # nothing to retry until set up
        todo = self.pending()
        self.waiting = len(todo)
        for folder in todo:
            if self.stopped.is_set():
                return True
            self._wait_for_report(folder)
            if not self.upload(folder, settings):
                return False
            self.waiting -= 1
        return True

    def pending(self):
        """Finished recordings whose files are not the ones uploaded."""
        state = self._state()
        with self.lock:
            extra = set(self.extra)
        folders = sorted(set(self.root.glob("*")) | extra, key=lambda path: path.name)
        todo = []
        for folder in folders:
            if not finished(folder):
                continue
            done = state.get(folder.name)
            if done is None or done.get("digest") != manifest(folder)["digest"]:
                todo.append(folder)
        return todo

    def upload(self, folder, settings):
        """rclone copy of the folder, then its ``upload.json``; True when both
        went through."""
        folder = Path(folder)
        rclone = self._rclone(settings)
        target = self.destination(settings, folder.name)
        files = manifest(folder)
        self.uploading = folder.name
        try:
            code, output = self.run(
                [rclone, "copy", str(folder), target, "--checksum",
                 "--transfers", "1", "--checkers", "2", "--retries", "3",
                 "--low-level-retries", "10", "--contimeout", "30s",
                 "--timeout", "5m", "--bwlimit", settings["bwlimit"] or "0",
                 "--stats", "0", "--log-level", "NOTICE"], COPY_TIMEOUT)
            if code == 0:
                marker = {"machine": settings["machine"], "folder": folder.name,
                          "files": files["files"], "bytes": files["bytes"],
                          "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                with tempfile.TemporaryDirectory() as temp:
                    local = Path(temp) / MARKER
                    local.write_text(json.dumps(marker, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
                    code, more = self.run([rclone, "copyto", str(local),
                                           f"{target}/{MARKER}", "--retries", "3",
                                           "--contimeout", "30s", "--timeout", "5m",
                                           "--stats", "0", "--log-level", "NOTICE"],
                                          600)
                output += more
        finally:
            self.uploading = None
        if code != 0:
            reason = scrub(output, 1) or f"rclone 退出码 {code}"
            self.last_error = reason
            self._log(f"{folder.name} 没传完（{code}）\n{scrub(output)}")
            return False
        self.last_error = None
        state = self._state()
        state[folder.name] = {"digest": files["digest"], "bytes": files["bytes"],
                              "files": len(files["files"]), "to": target,
                              "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        write_json(self.state_path, state)
        self._log(f"{folder.name} 已上传：{len(files['files'])} 个文件，"
                  f"{files['bytes'] / 1e6:.1f} MB → {target}")
        return True

    @staticmethod
    def destination(settings, name):
        path = f"{settings['folder']}/{settings['machine']}"
        return f"{settings['remote']}:{path}/{name}" if name else (
            f"{settings['remote']}:{path}")

    def _rclone(self, settings):
        return settings["rclone"] or self.which("rclone") or ""

    def _check(self, settings):
        """Is rclone here with the remote? Kept for ``CHECK_EVERY`` seconds."""
        rclone = self._rclone(settings)
        ok = False
        if rclone:
            code, output = self.run([rclone, "listremotes"], 30)
            ok = code == 0 and f"{settings['remote']}:" in output.split()
        self.configured, self.checked = ok, self.clock()
        return ok

    def _wait_for_report(self, folder):
        with self.lock:
            process = self.reports.pop(str(folder), None)
        if process is None:
            return
        try:
            process.wait(timeout=self.report_wait)
        except Exception:               # a sheet that hangs: upload what is there
            pass

    def _state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def _log(self, text):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > LOG_LIMIT:
                old = self.log_path.read_text(encoding="utf-8", errors="replace")
                self.log_path.write_text(old[-LOG_LIMIT // 2:], encoding="utf-8")
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        except OSError:
            pass


__all__ = ["BWLIMIT", "FOLDER", "MARKER", "PULLED", "REMOTE", "Uploader", "current",
           "default_settings", "finished", "load_settings", "machine_name",
           "manifest", "run_process", "write_json"]
