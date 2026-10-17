"""Recordings back to the owner: each finished recording folder, uploaded.

A recording folder (segments, ``frames.jsonl``, ``recording.json``,
``flywheel/``) goes to ``<cloud folder>/<machine>/<name>/`` once the recording
has stopped and its check-up sheet and session package
(``flywheel/package.json``, ``tools/session_package.py``) are written, in
three passes: first the package, the sheet and the other small files, then
the window's log (``frames.jsonl``), the video segments last: an AI reading
the cloud folder has a session's evidence long before its video. The
owner's Mac takes it back with ``tools/flywheel_sync.py pull``.

Two ways up, the same passes and files either way:

* ``rclone`` to ``<remote>:<folder>/<machine>/<name>/`` (a tester's PC: a
  remote with Google Drive's ``drive.file`` scope);
* a folder a cloud app keeps in sync on this computer (the owner's Mac:
  Google Drive for desktop under ``~/Library/CloudStorage``): the files are
  copied into ``<that folder>/<machine>/<name>/`` at the same limited speed
  and the app sends them on. Used when rclone has no remote here and the
  cloud folder is there (``drive`` in the settings, else the Google Drive
  desktop copy of ``folder`` when it exists); no new sign-in is needed.

* What and where come from a local file (``PokerSense_private/upload/
  settings.json``): ``enabled`` (the window's switch, on by default),
  ``remote`` (an rclone remote, ``pokersense-upload``), ``folder``
  (``PokerSense 同事数据``), ``machine`` (this computer's name in the cloud
  folder; the host name when not set), ``player`` (who plays at it, for the
  session package; the machine's name when not set), ``drive`` (a synced
  cloud folder to copy into instead of rclone), ``since`` (recordings whose
  folder name sorts before it stay here: a computer that starts uploading
  does not send its whole past at once) and ``bwlimit``. The login itself is
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
* Google Drive allows two folders of one name, and rclone makes one more
  when a folder is created by two transfers at once or a create is retried
  after a timeout (2026-10-15: 11 "PokerSense 同事数据" folders in one
  morning). So after the files and before ``upload.json``, ``rclone dedupe
  --dedupe-mode skip`` folds same-named folders into one, down to the
  recordings' ``flywheel/`` folders (rclone merges folders in every mode but
  ``list``; there is no "merge" mode, and rclone refuses one). Of the files
  it only removes extra copies of a file that are the same name and the same
  bytes, and leaves files that differ alone. Seeing only what this upload
  client created (scope ``drive.file``), it cannot reach anything else.
* After the files, a small ``upload.json`` (the file list with sizes) is
  written last, either way: a recording without it, or whose files do not
  match it, is still on its way and the pull leaves it alone.
* rclone is the one in the settings (``rclone``, a full path: ``flywheel_sync.py
  setup`` keeps the one it finds; passed over once it is gone, say after an
  upgrade), else the one on the window's PATH, else
  one in the usual places (on Windows ``C:\\rclone``, winget's links and the
  PATH as it is now in the registry: a window started before rclone was put
  on the PATH does not see it there).
* Without rclone's remote and without a synced cloud folder the window says
  "未配置上传" and looks again every few minutes; nothing else happens.
  Folders pulled from another machine (with ``pulled.json``) are never
  uploaded again.
* A recording waits while its sheet and package are being made
  (``flywheel/building``, ``aa_after_session``): the cloud never gets a
  folder without its package, or a package half written.
* Closing the window does what 停止 does (``aa_live_entry``): the recording
  is finished and what the window had left to send goes on in a process of
  its own, ``python -m poker_engine.desktop.aa_upload --root <recordings>``
  (one pass, then it ends). One upload at a time on this computer:
  ``upload/upload.lock``, let go when its process ends, however it ends.
"""

from __future__ import annotations

from fnmatch import fnmatch
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
IDLE_WAIT = 3600                 # a look now and then
UNSET_WAIT = 300                 # how often a window without rclone looks again
CHECK_EVERY = 60.0               # seconds a "configured" answer is kept
LOG_LIMIT = 1_000_000
LOG = "frames.jsonl"             # the window's log: the second pass
VIDEO = "segment_*.mp4"          # the video segments: the last pass
PASSES = (["--exclude", f"/{LOG}", "--exclude", f"/{VIDEO}"],
          ["--include", f"/{LOG}"], [])
CLOUD = Path("~/Library/CloudStorage")   # where Google Drive for desktop syncs
CHUNK = 1 << 20                  # bytes copied at a time into a synced folder
BUILDING = "flywheel/building"   # there while the sheet and the package are made
LOCK = "upload.lock"             # held by the one process uploading
LOCK_WAIT = 120.0                # how long the upload after a close waits for it

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
            "rclone": "", "player": "", "drive": "", "since": ""}


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
    settings["player"] = machine_name(settings["player"]) if settings["player"] else ""
    settings["remote"] = settings["remote"].rstrip(":") or REMOTE
    settings["folder"] = settings["folder"].strip("/") or FOLDER
    return settings


def merge_depth(settings):
    """How deep the folder merge looks: <folder>/<machine>/<recording>/flywheel,
    with ``folder`` itself maybe more than one level."""
    return len(settings["folder"].split("/")) + 3


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


def upload_pass(rel):
    """Which pass a file of a recording goes up in: 0 the package, the sheet
    and the other small files, 1 the window's log, 2 the video."""
    if rel == LOG:
        return 1
    return 2 if "/" not in rel and fnmatch(rel, VIDEO) else 0


def drive_folder(folder=FOLDER, cloud=CLOUD):
    """The Google Drive desktop copy of the cloud folder, if this computer has
    one (``~/Library/CloudStorage/GoogleDrive-*/<我的云端硬盘|My Drive>/<folder>``)."""
    for account in sorted(Path(cloud).expanduser().glob("GoogleDrive-*")):
        for mine in ("我的云端硬盘", "My Drive"):
            path = account / mine / folder
            if path.is_dir():
                return path
    return None


def rate(text):
    """Bytes per second of an rclone ``--bwlimit`` ("1M", "512K", "0"); 0 is
    no limit."""
    match = re.fullmatch(r"\s*([\d.]+)\s*([KMG]?)i?B?\s*", str(text or "0"), re.I)
    if not match:
        return 0
    scale = {"": 1024, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return int(float(match.group(1)) * scale[match.group(2).upper()])


def copy_slowly(source, target, limit, sleep=time.sleep, clock=time.monotonic):
    """Copy one file at no more than ``limit`` bytes a second (0: as fast as
    it goes), into ``target`` whole: a cut-off copy leaves only a ``.part``."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    start, sent = clock(), 0
    with open(source, "rb") as reading, open(part, "wb") as writing:
        while True:
            chunk = reading.read(CHUNK)
            if not chunk:
                break
            writing.write(chunk)
            sent += len(chunk)
            if limit:
                ahead = sent / limit - (clock() - start)
                if ahead > 0:
                    sleep(ahead)
    os.replace(part, target)


def building(folder, now=None):
    """Is the folder's sheet and package still being made? ``flywheel/building``
    is there from just before the process making them starts until it ends;
    one left behind by a process that never ended (the computer turned off)
    counts for ``REPORT_WAIT`` at most."""
    path = Path(folder) / BUILDING
    try:
        made = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - made < REPORT_WAIT


class FileLock:
    """An exclusive lock on a file between processes: let go by ``release``
    or when the process holding it ends, also when it is killed."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self, wait=0.0, *, sleep=time.sleep, clock=time.monotonic):
        """True once held; False when another process still holds it after
        ``wait`` seconds."""
        if self.handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        deadline = clock() + wait
        while True:
            try:
                _lock(handle)
            except OSError:
                if clock() >= deadline:
                    handle.close()
                    return False
                sleep(0.5)
                continue
            self.handle = handle
            return True

    def release(self):
        handle, self.handle = self.handle, None
        if handle is not None:
            try:
                _lock(handle, unlock=True)
            except OSError:
                pass
            handle.close()


def _lock(handle, unlock=False):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK if unlock
                       else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN if unlock
                    else fcntl.LOCK_EX | fcntl.LOCK_NB)


def finished(folder):
    """A recording that is done (``recording.json`` is written at the end) and
    was made on this computer."""
    folder = Path(folder)
    return (folder.is_dir() and (folder / "recording.json").exists()
            and not (folder / PULLED).exists())


def rclone_places():
    """Folders rclone is usually in when it is not on this process's PATH."""
    if os.name != "nt":
        return ["/opt/homebrew/bin", "/usr/local/bin"]
    places = []
    try:
        import winreg
        for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet"
                           r"\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, key) as handle:
                    value = winreg.QueryValueEx(handle, "Path")[0]
            except OSError:
                continue
            places += [os.path.expandvars(part) for part in str(value).split(";")
                       if part.strip()]
    except ImportError:
        pass
    local = os.environ.get("LOCALAPPDATA", "")
    programs = os.environ.get("ProgramFiles", r"C:\Program Files")
    places += [r"C:\rclone", os.path.join(programs, "rclone")]
    if local:
        places.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
    return places


def find_rclone(configured="", *, which=shutil.which, places=None):
    """The rclone to run: the configured one, the one on PATH, or one in the
    usual places; "" when there is none. A configured full path that is gone
    (an upgrade moved rclone to a new folder) is passed over."""
    if configured and not (os.path.isabs(configured)
                           and not os.path.isfile(configured)):
        return configured
    found = which("rclone")
    if found:
        return found
    name = "rclone.exe" if os.name == "nt" else "rclone"
    for folder in rclone_places() if places is None else places:
        path = Path(folder) / name
        if path.is_file():
            return str(path)
    return ""


_RUNNING = set()                 # rclone processes this window started


def run_process(args, timeout):
    """(return code, output) of ``args`` at low priority, without a window."""
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = (subprocess.BELOW_NORMAL_PRIORITY_CLASS
                                  | subprocess.CREATE_NO_WINDOW)
    elif shutil.which("nice"):
        args = ["nice", "-n", "10", *args]
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace",
                                   stdin=subprocess.DEVNULL, **extra)
    except OSError as exc:
        return 127, str(exc)
    _RUNNING.add(process)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return 124, "超时"
    finally:
        _RUNNING.discard(process)
    return process.returncode, (out or "") + (err or "")


def end_processes():
    """End the rclone processes this window started: on Windows one started
    without a window outlives the closed one, and would send a folder at the
    same time as the upload that takes over (``after_close``)."""
    for process in list(_RUNNING):
        try:
            process.kill()
        except OSError:
            pass


def scrub(text, lines=6):
    """The last lines of rclone's output, without anything about tokens."""
    kept = [line.strip() for line in str(text).splitlines()
            if line.strip() and "token" not in line.lower()]
    return "\n".join(kept[-lines:])


class Uploader:
    """Uploads the finished recordings under ``root``, one at a time."""

    def __init__(self, root, *, base=None, run=run_process, which=shutil.which,
                 places=None, delay=START_DELAY, retry_waits=RETRY_WAITS,
                 report_wait=REPORT_WAIT, clock=time.monotonic, cloud=CLOUD,
                 sleep=time.sleep):
        self.root = Path(root)
        self.cloud, self.sleep = cloud, sleep
        base = Path(base) if base else private_root() / "upload"
        self.settings_path = base / "settings.json"
        self.state_path = base / "state.json"
        self.log_path = base / "upload.log"
        self.lock_file = FileLock(base / LOCK)
        self.run, self.which, self.clock = run, which, clock
        self.places = places
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
        self.local = None              # the synced cloud folder, when used
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
                  "way": "folder" if self.local is not None else "rclone",
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
            ok = self.upload_once()
            if ok:
                self.failures = 0
                wait = IDLE_WAIT if self.configured else UNSET_WAIT
            else:
                wait = self.retry_waits[min(self.failures, len(self.retry_waits) - 1)]
                self.failures += 1
            self.wake.wait(wait)

    def upload_once(self, wait=0.0):
        """``upload_all`` while holding this computer's upload lock (False
        when another process, the upload after a closed window, holds it past
        ``wait`` seconds). Anything that goes wrong is a failed pass: logged,
        and tried again later, never the end of the upload thread."""
        if not self.lock_file.acquire(wait):
            return False
        try:
            return self.upload_all()
        except Exception as exc:              # noqa: BLE001 - tried again later
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._log(f"上传出错：{self.last_error}")
            return False
        finally:
            self.lock_file.release()

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
            self._wait_for_report(folder)       # the sheet and the package first
            if not self.upload(folder, settings):
                return False
            self.waiting -= 1
        return True

    def pending(self):
        """Finished recordings whose files are not the ones uploaded (none
        whose folder name sorts before ``since``)."""
        since = self.settings()["since"]
        state = self._state()
        with self.lock:
            extra = set(self.extra)
        folders = sorted(set(self.root.glob("*")) | extra, key=lambda path: path.name)
        todo = []
        for folder in folders:
            if not finished(folder) or folder.name[:len(since)] < since:
                continue
            done = state.get(folder.name)
            if done is None or done.get("digest") != manifest(folder)["digest"]:
                todo.append(folder)
        return todo

    def _copy(self, folder, settings, filters=()):
        """(return code, output) of an rclone copy of the folder as it is now
        (only the files ``filters`` let through)."""
        return self.run(
            [self._rclone(settings), "copy", str(folder),
             self.destination(settings, folder.name), *filters, "--checksum",
             "--transfers", "1", "--checkers", "2", "--retries", "3",
             "--low-level-retries", "10", "--contimeout", "30s",
             "--timeout", "5m", "--bwlimit", settings["bwlimit"] or "0",
             "--stats", "0", "--log-level", "NOTICE"], COPY_TIMEOUT)

    def _put(self, folder, settings, files, local):
        """The files into the synced cloud folder ``local``, in the three
        passes; True when all went through."""
        target = local / settings["machine"] / folder.name
        limit = rate(settings["bwlimit"])
        for which in range(len(PASSES)):
            for rel, size in files:
                if upload_pass(rel) != which:
                    continue
                there = target / rel
                if there.is_file() and there.stat().st_size == size:
                    continue
                copy_slowly(folder / rel, there, limit, sleep=self.sleep)
        return True

    def upload(self, folder, settings):
        """The folder in its three passes (the package and the sheet, the log,
        the video), then its ``upload.json``; True when all went through."""
        folder = Path(folder)
        # One answer for the whole upload: the window's status check may look
        # again (``_check``) while the files go up.
        local = self.local
        target = self.destination(settings, folder.name, local)
        files = manifest(folder)
        marker = {"machine": settings["machine"], "folder": folder.name,
                  "files": files["files"], "bytes": files["bytes"]}
        self.uploading = folder.name
        try:
            if local is not None:
                code, output = self._put_all(folder, settings, files, marker, local)
            else:
                code, output = self._send_all(folder, settings, marker)
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

    def _send_all(self, folder, settings, marker):
        """rclone: the three passes, the folder merge, ``upload.json``."""
        output = ""
        for filters in PASSES:
            code, more = self._copy(folder, settings, filters)
            output += more
            if code != 0:
                return code, output
        self._merge_folders(settings)
        marker["uploaded"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / MARKER
            local.write_text(json.dumps(marker, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            code, more = self.run([self._rclone(settings), "copyto", str(local),
                                   f"{self.destination(settings, folder.name)}/"
                                   f"{MARKER}", "--retries", "3",
                                   "--contimeout", "30s", "--timeout", "5m",
                                   "--stats", "0", "--log-level", "NOTICE"], 600)
        return code, output + more

    def _put_all(self, folder, settings, files, marker, local):
        """The synced cloud folder: the three passes, then ``upload.json``."""
        try:
            self._put(folder, settings, files["files"], local)
            marker["uploaded"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            write_json(local / settings["machine"] / folder.name / MARKER, marker)
        except OSError as exc:
            return 1, f"复制到云盘文件夹没成功：{exc}"
        return 0, ""

    def _merge_folders(self, settings):
        """Same-named folders on the remote merged into one, down to the
        recording folders; a failure is only logged (the pull waits for a
        recording whose files are not all next to its ``upload.json``)."""
        code, output = self.run(
            [self._rclone(settings), "dedupe", "--dedupe-mode", "skip",
             "--max-depth", str(merge_depth(settings)), f"{settings['remote']}:",
             "--retries", "3", "--contimeout", "30s", "--timeout", "5m",
             "--stats", "0", "--log-level", "NOTICE"], 600)
        if code != 0:
            self._log(f"同名文件夹没合并（{code}）\n{scrub(output)}")
        return code == 0

    def destination(self, settings, name, local=None):
        local = self.local if local is None else local
        if local is not None:
            path = local / settings["machine"]
            return str(path / name) if name else str(path)
        path = f"{settings['folder']}/{settings['machine']}"
        return f"{settings['remote']}:{path}/{name}" if name else (
            f"{settings['remote']}:{path}")

    def _rclone(self, settings):
        return find_rclone(settings["rclone"], which=self.which, places=self.places)

    def _check(self, settings):
        """Is rclone here with the remote, or else a synced cloud folder?
        Kept for ``CHECK_EVERY`` seconds."""
        rclone = self._rclone(settings)
        ok, local = False, None
        if rclone:
            code, output = self.run([rclone, "listremotes"], 30)
            ok = code == 0 and f"{settings['remote']}:" in output.split()
        if not ok:
            local = self._synced(settings)
            ok = local is not None
        # Set together at the end: an upload running meanwhile never sees
        # the answer half made.
        self.local, self.configured, self.checked = local, ok, self.clock()
        return ok

    def _synced(self, settings):
        """The synced cloud folder to copy into, or None: ``drive`` from the
        settings (made when its parent is there), else Google Drive for
        desktop's copy of ``folder``."""
        if settings["drive"]:
            path = Path(settings["drive"]).expanduser()
            return path if path.is_dir() or path.parent.is_dir() else None
        return drive_folder(settings["folder"], self.cloud)

    def _wait_for_report(self, folder):
        """Until the sheet and the package are written: the process this
        window started for them, else ``flywheel/building`` (made by a window
        since closed); one that hangs past ``report_wait``: upload what is
        there."""
        with self.lock:
            process = self.reports.pop(str(folder), None)
        if process is not None:
            try:
                process.wait(timeout=self.report_wait)
            except Exception:
                pass
            return
        deadline = self.clock() + self.report_wait
        while (building(folder) and not self.stopped.is_set()
               and self.clock() < deadline):
            self.sleep(2.0)

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


def main(argv=None):
    """The upload a closed window hands over: one pass over the finished
    recordings under ``--root`` (each after its sheet and package), then the
    process ends; the next window tries again what did not go through."""
    import argparse
    parser = argparse.ArgumentParser(description="上传录完的录像（关窗口后接着传）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base", type=Path)
    args = parser.parse_args(argv)
    uploader = Uploader(args.root, base=args.base, delay=0)
    return 0 if uploader.upload_once(wait=LOCK_WAIT) else 1


__all__ = ["BUILDING", "BWLIMIT", "CLOUD", "FileLock", "FOLDER", "LOCK", "MARKER",
           "PULLED", "REMOTE", "Uploader", "building", "copy_slowly", "current",
           "default_settings", "drive_folder", "end_processes", "find_rclone",
           "finished", "load_settings", "machine_name", "main", "manifest", "rate",
           "rclone_places", "run_process", "upload_pass", "write_json"]


if __name__ == "__main__":
    raise SystemExit(main())
