"""Update path of an installed AA program, end to end, on a Windows runner.

A local HTTP server plays the cloud folder. The installed program must:
refuse an installer whose sha256 does not match (nothing started), say it is
up to date for its own version, show "update available" in the window's
/api/update, and for a newer version download, verify and start the
installer, which waits for the program to exit and installs again.

The recognition bundle the manifest lists (a synthetic one here, built the way
tools/pack_aa_recognition.py packs the private one) must be fetched on first
start and by "check for updates", refused on a wrong sha256, left alone when
already current, and turn the capture card on.
"""

import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
NEWER = "99.0.0"


def manifest(version, url, data, sha256=None, recognition=None):
    body = {"schema": "pokersense-update-v1", "product": "PokerSense-AA",
            "version": version, "published": "2026-01-01T00:00:00Z",
            "commit": "smoke", "notes": "smoke test",
            "installer": {"url": url, "bytes": len(data),
                          "sha256": sha256 or hashlib.sha256(data).hexdigest()}}
    if recognition is not None:
        body["recognition"] = recognition
    return body


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def synthetic_recognition(root, out):
    """A bundle with the real layout and hashes but no private pixels (the
    same shape as tests/desktop/test_aa_bundle.py), packed for upload."""
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    from poker_engine.desktop.aa_bundle import FILES, export_bundle, required_frames
    from tools.pack_aa_recognition import pack
    spec = {"audit": "a" * 64}
    for key, needed in required_frames().items():
        folder = root / key
        (folder / "frames").mkdir(parents=True)
        spec[key] = str(folder)
        frame_key = "source_frame" if key == "bomb_pool" else "global_frame"
        frames = range(min(needed), max(needed) + 1) if key in (
            "source", "context_source") else needed
        rows = []
        for frame in frames:
            data = (key + str(frame)).encode()
            row = {frame_key: frame, "file": f"frames/{frame}.png",
                   "sha256": hashlib.sha256(data).hexdigest(),
                   "pts_seconds": str(frame / 30),
                   "split" if key == "bomb_pool" else "role": "development"}
            rows.append(row)
            if frame in needed:
                (folder / row["file"]).write_bytes(data)
        identity = "source_sha256" if key == "bomb_pool" else "audit_sha256"
        _write_json(folder / "samples.json", {
            identity: "b" * 64 if key == "bomb_pool" else "a" * 64, "samples": rows})
    for key in FILES:
        suffix = ".npz" if key in ("bank_path", "heads_path") else ".json"
        path = root / (key + suffix)
        _write_json(path, {})
        spec[key] = str(path)
        if key == "heads_path":
            _write_json(path.with_suffix(".json"), {"format": "mlp-v1", "heads": {}})
    _write_json(Path(spec["profile_path"]), {
        "canvas": [498, 1080], "hero_slot": 4,
        "slots": [{"slot": i} for i in range(8)]})
    _write_json(Path(spec["reservations"]), {
        "source_sha256": "b" * 64, "reserved_inclusive_intervals": [[9000, 9100]],
        "known_exploration_frames": [], "known_development_inclusive_intervals": []})
    profile = root / "reader.json"
    _write_json(profile, spec)
    export_bundle(profile, root / "bundle")
    return pack(root / "bundle", out)


def serve(folder):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def run(exe, *arguments, timeout=120):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run([str(exe), *arguments], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=flags)


def setup_running(name):
    if os.name != "nt":
        return False
    listed = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                            capture_output=True, text=True).stdout
    return name.lower() in listed.lower()


def window_status(exe, state, url, screenshot=None):
    """Start the window with the update address; /api/update, with what
    /api/build and /api/status say and the console output."""
    ready = state / "ready.json"
    ready.unlink(missing_ok=True)           # left by an earlier start
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (state / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(exe), "--no-browser", "--port", "0", "--state", str(state),
             "--ready-file", str(ready), "--update-url", url],
            stdout=log, stderr=log, creationflags=flags)
        try:
            status = read_window(process, state, ready, screenshot)
        finally:
            process.terminate()
            process.wait(timeout=20)
    status["log"] = (state / "server.log").read_text("utf-8", errors="replace")
    return status


def read_window(process, state, ready, screenshot):
    deadline = time.monotonic() + 90
    while not ready.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError((state / "server.log").read_text("utf-8"))
        time.sleep(0.1)
    base = json.loads(ready.read_text("utf-8"))["base"]
    while True:
        with urlopen(base + "api/update", timeout=5) as response:
            status = json.load(response)
        if status["status"] != "NOT_CHECKED":
            break
        if time.monotonic() > deadline:
            raise RuntimeError("update check never finished")
        time.sleep(0.2)
    with urlopen(base + "update_banner.js", timeout=5) as response:
        assert b"update-banner" in response.read()
    with urlopen(base + "api/build", timeout=5) as response:
        status["build"] = json.load(response)
    with urlopen(base + "api/status", timeout=5) as response:
        status["window"] = json.load(response)
    if screenshot:
        status["screenshot"] = take_screenshot(base, screenshot)
    return status


def take_screenshot(url, path):
    """The window as Edge (or Chrome) shows it, headless; best effort."""
    candidates = [Path(os.environ.get(name, "")) / tail for name, tail in (
        ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
        ("ProgramFiles", "Microsoft/Edge/Application/msedge.exe"),
        ("ProgramFiles", "Google/Chrome/Application/chrome.exe"))]
    browser = next((c for c in candidates if c.is_file()), None)
    if browser is None:
        return {"saved": False, "error": "no browser"}
    path = Path(path).resolve()
    with tempfile.TemporaryDirectory(prefix="pokersense-shot-") as profile:
        try:
            result = subprocess.run(
                [str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={profile}", "--hide-scrollbars",
                 "--window-size=1366,820", "--virtual-time-budget=10000",
                 f"--screenshot={path}", url],
                capture_output=True, text=True, errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            return {"saved": path.is_file(), "error": "timeout"}
    return {"saved": path.is_file(), "browser": browser.name,
            "returncode": result.returncode, "stderr": result.stderr[-400:]}


def smoke(exe, installer, screenshot=None):
    exe = Path(exe).resolve(strict=True)
    installer = Path(installer).resolve(strict=True)
    current = run(exe, "--version").stdout.strip().split()[-1]
    report = {"installed": str(exe), "current": current}
    data = installer.read_bytes()
    with tempfile.TemporaryDirectory(prefix="pokersense-update-") as folder:
        root = Path(folder)
        files = root / "cloud"
        files.mkdir()
        shutil.copyfile(installer, files / "PokerSense-AA-Setup.exe")
        server, base = serve(files)
        try:
            url = base + "PokerSense-AA-Setup.exe"
            for name, body in (
                    ("bad.json", manifest(NEWER, url, data, sha256="0" * 64)),
                    ("same.json", manifest(current, url, data)),
                    ("latest.json", manifest(NEWER, url, data))):
                (files / name).write_text(json.dumps(body), "utf-8")

            state = root / "bad-state"
            result = run(exe, "--update-now", "--update-url", base + "bad.json",
                         "--state", str(state))
            assert result.returncode == 4, result.stdout + result.stderr
            assert "sha256" in result.stdout, result.stdout
            assert not list((state / "updates").glob("*")), "a wrong file was kept"
            report["bad_hash"] = "REFUSED_NOTHING_STARTED"

            result = run(exe, "--update-now", "--update-url", base + "same.json",
                         "--state", str(root / "same-state"))
            assert result.returncode == 0 and "最新" in result.stdout, result.stdout
            report["same_version"] = "UP_TO_DATE"

            sidecar = synthetic_recognition(root / "private", files / "recognition")
            zip_url = base + "recognition/PokerSense-AA-recognition.zip"
            listed = {"url": zip_url, "sha256": sidecar["zip_sha256"],
                      "bytes": sidecar["zip_bytes"],
                      "manifest_sha256": sidecar["manifest_sha256"]}
            _write_json(files / "rec.json", manifest(current, url, data,
                                                     recognition=listed))
            _write_json(files / "rec-bad.json", manifest(
                current, url, data, recognition={**listed, "sha256": "0" * 64}))

            state = root / "rec-bad-state"
            state.mkdir()
            status = window_status(exe, state, base + "rec-bad.json")
            assert status["build"]["recognition_bundle"] == "NOT_INSTALLED", status
            assert status["window"]["capture_available"] is False
            assert "sha256" in status["log"], status["log"]
            assert not (state / "recognition" / "current.json").exists()
            report["recognition_bad_hash"] = "REFUSED_NOT_INSTALLED"

            state = root / "rec-state"
            state.mkdir()
            status = window_status(exe, state, base + "rec.json")
            assert status["build"]["recognition_bundle"] == "INSTALLED", status
            assert status["build"]["capture_enabled"] is True
            assert status["window"]["capture_available"] is True
            assert status["window"]["profile"]["ready"] is True, status["window"]
            assert "已下载" in status["log"], status["log"]
            again = window_status(exe, state, base + "rec.json")
            assert "已经是最新的" in again["log"], again["log"]
            assert again["build"]["recognition_bundle"] == "INSTALLED"
            report["recognition_first_start"] = "DOWNLOADED_VALIDATED_CAPTURE_ON"
            report["recognition_next_start"] = "UP_TO_DATE"

            state = root / "rec-console-state"
            result = run(exe, "--update-now", "--update-url", base + "rec.json",
                         "--state", str(state))
            assert result.returncode == 0, result.stdout + result.stderr
            assert "[识别资源] 已下载" in result.stdout, result.stdout
            assert (state / "recognition" / "current.json").is_file()
            report["recognition_check_for_updates"] = "DOWNLOADED"

            window = root / "window-state"
            window.mkdir()
            status = window_status(exe, window, base + "latest.json", screenshot)
            assert status["status"] == "AVAILABLE", status
            assert status["latest"] == NEWER and status["can_install"] is True, status
            report["window"] = {key: status.get(key) for key in
                                ("status", "latest", "can_install", "screenshot")}
            assert status["build"]["recognition_bundle"] == "NOT_INSTALLED"

            # The installer empties _internal before copying (pokersense.iss).
            marker = exe.parent / "_internal" / "update-smoke-marker"
            marker.write_text("old files", "utf-8")
            state = root / "update-state"
            result = run(exe, "--update-now", "--update-url", base + "latest.json",
                         "--state", str(state))
            assert result.returncode == 0, result.stdout + result.stderr
            assert "校验通过" in result.stdout, result.stdout
            name = f"PokerSense-AA-Setup-{NEWER}.exe"
            assert (state / "updates" / name).is_file()
            deadline = time.monotonic() + 240
            time.sleep(3)
            while setup_running(name) or setup_running(name.replace(".exe", ".tmp")):
                assert time.monotonic() < deadline, "installer never finished"
                time.sleep(1)
            assert not marker.exists(), "installer did not replace the files"
            deadline = time.monotonic() + 30
            while not setup_running(exe.name) and time.monotonic() < deadline:
                time.sleep(1)
            report["relaunched"] = setup_running(exe.name)
            if os.name == "nt":
                subprocess.run(["taskkill", "/IM", exe.name, "/F"], capture_output=True)
                time.sleep(2)
            again = run(exe, "--version")
            assert again.returncode == 0 and current in again.stdout, again.stdout
            report["update"] = "DOWNLOADED_VERIFIED_INSTALLED"
        finally:
            server.shutdown()
    report["result"] = "UPDATE_SMOKE_PASS"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True,
                        help="the installed PokerSense-AA.exe")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = smoke(args.exe, args.installer, args.screenshot)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
