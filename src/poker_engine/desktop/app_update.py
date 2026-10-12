"""Update check for the installed Windows build: one manifest, one installer.

The manifest is a small JSON file at a configurable address (a cloud-drive
share link, an HTTPS URL or a local/UNC path)::

    {"schema": "pokersense-update-v1", "product": "PokerSense-AA",
     "version": "0.3.0", "published": "...", "commit": "...", "notes": "...",
     "installer": {"url": "...", "sha256": "<64 hex>", "bytes": 123}}

The installer is downloaded next to the user's data, its size and sha256 are
checked against the manifest, and only then is it started (Inno Setup, silent,
waiting for this process to exit and reopening the program afterwards).

A release may also list the private recognition bundle, uploaded separately
(``tools/pack_aa_recognition.py``), never inside the installer::

    "recognition": {"url": "...", "sha256": "<zip>", "bytes": 123,
                    "manifest_sha256": "<bundle-manifest.json>"}

``sync_recognition`` fetches it on first start and whenever a release lists
another one: zip size and sha256 checked, unpacked into the user's data
folder, the bundle validated against ``manifest_sha256`` (``aa_bundle``), and
only then made current. The trusted digest is kept outside the bundle folder.
Nothing here ever reads repository credentials; the manifest address is the
only configuration.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, url2pathname, urlopen
import zipfile


SCHEMA = "pokersense-update-v1"
PRODUCT = "PokerSense-AA"
CONFIG_NAME = "update-config.json"
URL_ENV = "POKERSENSE_UPDATE_URL"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 ** 3
RECOGNITION_DIR = "recognition"
RECOGNITION_CURRENT = "current.json"
CHUNK = 1024 * 1024
TIMEOUT = 20
USER_AGENT = "PokerSense-AA-updater"

_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?")
_HASH = re.compile(r"[0-9a-f]{64}")
_DRIVE_FILE = re.compile(r"/file/d/([A-Za-z0-9_-]+)")


class UpdateError(Exception):
    """A check or download that must not install anything."""


def parse_version(text):
    """``X.Y.Z`` or ``X.Y.Z.devN`` as a sortable tuple; a dev build sorts
    before its release."""
    match = _VERSION.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match:
        raise UpdateError(f"版本号格式不对：{text!r}")
    major, minor, patch, dev = match.groups()
    release = (int(major), int(minor), int(patch))
    return release + ((0, int(dev)) if dev is not None else (1, 0))


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def direct_url(url):
    """A download address for a share link: Google Drive and Dropbox pages
    become their direct-download form; anything else is returned as given.

    ``rclone link`` on Google Drive often yields ``…/open?id=…``, which is a
    viewer page (browsers may 404/400). Releases should store the usercontent
    form in ``latest.json``; downloads still call this before HTTP so older
    manifests with ``open?id=`` keep working."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    query = parse_qs(parts.query)
    if host in {"drive.google.com", "docs.google.com"}:
        found = _DRIVE_FILE.search(parts.path)
        file_id = found.group(1) if found else (query.get("id") or [None])[0]
        if file_id:
            return ("https://drive.usercontent.google.com/download?" + urlencode(
                {"id": file_id, "export": "download", "confirm": "t"}))
    if host.endswith("dropbox.com"):
        query["dl"] = ["1"]
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(query, doseq=True), ""))
    return url


def _local_path(url):
    parts = urlsplit(url)
    if parts.scheme == "file":
        path = url2pathname(parts.path)
        return Path(f"//{parts.netloc}{path}" if parts.netloc else path)
    if parts.scheme in {"http", "https"}:
        return None
    if len(parts.scheme) == 1 or not parts.scheme:       # C:\..., \\server\...
        return Path(url)
    raise UpdateError(f"不支持的地址：{url}")


class _Response:
    def __init__(self, stream, content_type, length):
        self.stream, self.content_type, self.length = stream, content_type, length

    def read(self, size=-1):
        return self.stream.read(size)

    def close(self):
        self.stream.close()


def open_url(url, timeout=TIMEOUT):
    """An open byte stream for an HTTP(S) address or a local/UNC path."""
    path = _local_path(url)
    if path is not None:
        try:
            return _Response(path.open("rb"), "", path.stat().st_size)
        except OSError as error:
            raise UpdateError(f"打不开 {path}：{error}") from error
    request = Request(direct_url(url), headers={"User-Agent": USER_AGENT})
    try:
        response = urlopen(request, timeout=timeout)
    except OSError as error:
        raise UpdateError(f"连不上更新地址：{error}") from error
    length = response.headers.get("Content-Length")
    return _Response(response, response.headers.get("Content-Type", ""),
                     int(length) if length and length.isdigit() else None)


def _not_a_web_page(response):
    if response.content_type.split(";")[0].strip().lower() == "text/html":
        response.close()
        raise UpdateError("下载到的是网页，不是文件：链接可能没共享给“知道链接的人”，"
                          "或云盘的下载次数超了")


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise UpdateError("版本清单格式不对")
    if data.get("product") != PRODUCT:
        raise UpdateError("版本清单不是这个程序的")
    parse_version(data.get("version"))
    installer = data.get("installer")
    if (not isinstance(installer, dict)
            or not isinstance(installer.get("url"), str) or not installer["url"]
            or not isinstance(installer.get("sha256"), str)
            or not _HASH.fullmatch(installer["sha256"])
            or type(installer.get("bytes")) is not int
            or not 0 < installer["bytes"] <= MAX_INSTALLER_BYTES):
        raise UpdateError("版本清单里安装包的地址、大小或 sha256 不对")
    recognition = data.get("recognition")
    if recognition is not None and (
            not isinstance(recognition, dict)
            or not isinstance(recognition.get("url"), str) or not recognition["url"]
            or not isinstance(recognition.get("sha256"), str)
            or not _HASH.fullmatch(recognition["sha256"])
            or not isinstance(recognition.get("manifest_sha256"), str)
            or not _HASH.fullmatch(recognition["manifest_sha256"])
            or type(recognition.get("bytes")) is not int
            or not 0 < recognition["bytes"] <= MAX_INSTALLER_BYTES):
        raise UpdateError("版本清单里识别资源包的地址、大小或 sha256 不对")
    return data


def fetch_manifest(url, opener=open_url):
    response = opener(url)
    try:
        _not_a_web_page(response)
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    finally:
        response.close()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateError("版本清单太大")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise UpdateError("版本清单不是 JSON：链接可能没共享或地址不对") from error
    return validate_manifest(data)


def check(url, current, opener=open_url):
    """What the update address says about ``current``; never raises."""
    if not url:
        return {"status": "UNCONFIGURED", "current": current}
    try:
        manifest = fetch_manifest(url, opener)
    except UpdateError as error:
        return {"status": "ERROR", "current": current, "error": str(error)}
    newer = is_newer(manifest["version"], current)
    return {"status": "AVAILABLE" if newer else "UP_TO_DATE", "current": current,
            "latest": manifest["version"], "notes": manifest.get("notes", ""),
            "published": manifest.get("published", ""), "manifest": manifest}


def fetch_verified(url, target, sha256, size, opener=open_url, progress=None,
                   what="安装包"):
    """``url`` saved as ``target`` once its size and sha256 match; a partial
    or wrong file is deleted, never kept."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest, received = hashlib.sha256(), 0
    response = opener(direct_url(url))
    try:
        _not_a_web_page(response)
        with partial.open("wb") as handle:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                received += len(chunk)
                if received > size:
                    raise UpdateError("下载的文件比清单里写的大")
                digest.update(chunk)
                handle.write(chunk)
                if progress:
                    progress(received, size)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    if received != size:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"下载不完整：{received} / {size} 字节")
    if digest.hexdigest() != sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"{what}的 sha256 和清单不一致，已删除，没有安装")
    os.replace(partial, target)
    return target


def download(manifest, folder, opener=open_url, progress=None):
    """The installer saved under ``folder`` after its size and sha256 match
    the manifest; a partial or wrong file is deleted, never returned."""
    installer = validate_manifest(manifest)["installer"]
    folder = Path(folder)
    target = folder / f"PokerSense-AA-Setup-{manifest['version']}.exe"
    fetch_verified(installer["url"], target, installer["sha256"], installer["bytes"],
                   opener, progress)
    for old in folder.glob("PokerSense-AA-Setup-*.exe*"):
        if old != target:
            old.unlink(missing_ok=True)
    return target


def safe_extract(archive, target):
    """Unpack a zip into ``target`` (which must not exist), refusing absolute
    paths, ``..``, drive letters and backslashes."""
    target = Path(target)
    if target.exists():
        raise UpdateError(f"{target} 已经存在")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        for info in members:
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not name or "\\" in name or ":" in name or name.startswith("/")
                    or any(part in ("", ".", "..") for part in parts)):
                raise UpdateError(f"资源包里有不安全的路径：{name!r}")
        for info in members:
            if info.is_dir():
                continue
            destination = target.joinpath(*PurePosixPath(info.filename).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(info))
    return target


def installed_recognition(state):
    """(profile.json, trusted manifest digest) of the recognition bundle made
    current in the data folder ``state``, or None."""
    root = Path(state) / RECOGNITION_DIR
    try:
        current = json.loads((root / RECOGNITION_CURRENT).read_text("utf-8"))
        digest = current["manifest_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        return None
    profile = root / digest / "profile.json"
    return (profile, digest) if profile.is_file() else None


def _validate_bundle(profile, digest):
    from .aa_bundle import validate_bundle
    return validate_bundle(profile, digest)


def sync_recognition(url, state, *, opener=open_url, validate=_validate_bundle,
                     progress=None, manifest=None):
    """Make the recognition bundle the release lists current in ``state``.

    Returns {"status": ...}: UNCONFIGURED, NOT_PUBLISHED, UP_TO_DATE,
    INSTALLED or ERROR. On any error the bundle in use stays as it was."""
    if not url and manifest is None:
        return {"status": "UNCONFIGURED"}
    try:
        manifest = fetch_manifest(url, opener) if manifest is None else (
            validate_manifest(manifest))
    except UpdateError as error:
        return {"status": "ERROR", "error": str(error)}
    entry = manifest.get("recognition")
    if entry is None:
        return {"status": "NOT_PUBLISHED"}
    digest = entry["manifest_sha256"]
    current = installed_recognition(state)
    if current is not None and current[1] == digest:
        return {"status": "UP_TO_DATE", "manifest_sha256": digest}
    root = Path(state) / RECOGNITION_DIR
    archive = root / "download.zip"
    staging = root / (digest + ".new")
    try:
        fetch_verified(entry["url"], archive, entry["sha256"], entry["bytes"],
                       opener, progress, what="识别资源包")
        if staging.exists():
            shutil.rmtree(staging)
        safe_extract(archive, staging)
        try:
            validate(staging / "profile.json", digest)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UpdateError(f"识别资源包校验没通过：{error}") from error
        final = root / digest
        if final.exists():
            shutil.rmtree(final)
        os.replace(staging, final)
        pointer = root / (RECOGNITION_CURRENT + ".part")
        pointer.write_text(json.dumps({"manifest_sha256": digest,
                                       "sha256": entry["sha256"]}) + "\n", "utf-8")
        os.replace(pointer, root / RECOGNITION_CURRENT)
    except (UpdateError, OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        return {"status": "ERROR", "error": str(error)}
    finally:
        archive.unlink(missing_ok=True)
    for old in root.iterdir():
        if old.is_dir() and old.name != digest:
            shutil.rmtree(old, ignore_errors=True)
    return {"status": "INSTALLED", "manifest_sha256": digest}


def installer_command(installer, pid, relaunch=True):
    """Inno Setup, silent with a progress window; it waits for ``pid`` to
    exit (``/WAITPID``, see packaging/pokersense.iss) before replacing files."""
    return [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/WAITPID={pid}", f"/RELAUNCH={1 if relaunch else 0}"]


def start_installer(installer, pid=None, relaunch=True, popen=subprocess.Popen):
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return popen(installer_command(installer, os.getpid() if pid is None else pid,
                                   relaunch),
                 close_fds=True, creationflags=flags)


def install_root():
    """The installed program's folder, or None when running from source."""
    return Path(sys.executable).resolve().parent if getattr(
        sys, "frozen", False) else None


def can_install():
    return os.name == "nt" and install_root() is not None


def configured_url(explicit=None, environ=os.environ, root=None):
    """``--update-url``, else ``$POKERSENSE_UPDATE_URL``, else the
    ``update-config.json`` the release build wrote next to the program."""
    if explicit:
        return explicit
    if environ.get(URL_ENV, "").strip():
        return environ[URL_ENV].strip()
    root = install_root() if root is None else root
    if root is None:
        return None
    try:
        value = json.loads((Path(root) / CONFIG_NAME).read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None
    url = value.get("manifest_url") if isinstance(value, dict) else None
    return url.strip() if isinstance(url, str) and url.strip() else None


class Updater:
    """The window's view of updates: one background check at startup, a
    re-check on request, and one install at a time."""

    def __init__(self, url, current, folder, *, opener=open_url,
                 starter=start_installer, allowed=can_install, exit_soon=None,
                 clock=time.time):
        self.url, self.current, self.folder = url, current, Path(folder)
        self.opener, self.starter, self.allowed = opener, starter, allowed
        self.exit_soon = exit_soon
        self.clock = clock
        self.lock = threading.Lock()
        self.state = {"status": "UNCONFIGURED" if not url else "NOT_CHECKED",
                      "current": current}
        self.checked_at = None
        self.installing = False

    def snapshot(self):
        with self.lock:
            state = {key: value for key, value in self.state.items()
                     if key != "manifest"}
            return {**state, "configured": bool(self.url),
                    "can_install": bool(self.allowed()),
                    "checked_at": self.checked_at, "installing": self.installing}

    def refresh(self):
        result = check(self.url, self.current, self.opener)
        with self.lock:
            if not self.installing:
                self.state = result
            self.checked_at = self.clock()
        return self.snapshot()

    def check_in_background(self):
        if not self.url:
            return None
        thread = threading.Thread(target=self.refresh, daemon=True,
                                  name="pokersense-update-check")
        thread.start()
        return thread

    def _progress(self, received, total):
        with self.lock:
            self.state = {**self.state, "received": received, "total": total}

    def install(self):
        """Download, verify, start the installer and ask the program to exit.
        Returns the snapshot; errors leave the program running as it was."""
        if not self.allowed():
            raise UpdateError("只有装好的 Windows 版能自己更新")
        with self.lock:
            if self.installing:
                return self.snapshot()
            self.installing = True
        try:
            result = check(self.url, self.current, self.opener)
            if result["status"] != "AVAILABLE":
                with self.lock:
                    self.state = result
                    self.installing = False
                return self.snapshot()
            with self.lock:
                self.state = {**result, "status": "DOWNLOADING"}
            path = download(result["manifest"], self.folder, self.opener,
                            self._progress)
            self.starter(path)
        except (UpdateError, OSError) as error:
            with self.lock:
                self.state = {"status": "ERROR", "current": self.current,
                              "error": str(error)}
                self.installing = False
            return self.snapshot()
        with self.lock:
            self.state = {**self.state, "status": "INSTALLING"}
        if self.exit_soon is not None:
            self.exit_soon()
        return self.snapshot()


def run_console_update(url, current, folder, *, opener=open_url,
                       starter=start_installer, allowed=can_install,
                       out=print):
    """``PokerSense-AA.exe --update-now``: the Start-menu "check for updates"
    shortcut. Returns (exit code, whether the installer was started)."""
    if not url:
        out("[更新] 这个版本没有配置更新地址，请找给你安装包的人要新安装包。")
        return 3, False
    out(f"[更新] 现在的版本：{current}，正在检查……")
    result = check(url, current, opener)
    if result["status"] == "ERROR":
        out(f"[更新] 检查失败：{result['error']}")
        return 4, False
    if result["status"] == "UP_TO_DATE":
        out(f"[更新] 已经是最新版（{result['latest']}）。")
        return 0, False
    out(f"[更新] 有新版 {result['latest']}。")
    if not allowed():
        out("[更新] 只有装好的 Windows 版能自己更新。")
        return 5, False
    out("[更新] 正在下载……")
    shown = [-1]

    def progress(received, total):
        percent = received * 100 // total
        if percent >= shown[0] + 10 or received == total:
            shown[0] = percent
            out(f"[更新] 已下载 {percent}%")

    try:
        path = download(result["manifest"], folder, opener, progress)
        out("[更新] 安装包校验通过（sha256 一致），开始安装；装完会自动打开。")
        starter(path)
    except (UpdateError, OSError) as error:
        out(f"[更新] 没有更新：{error}")
        return 4, False
    return 0, True
