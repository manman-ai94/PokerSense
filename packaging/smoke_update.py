"""Update path of an installed AA program, end to end, on a Windows runner.

A local HTTP server plays the cloud folder. The installed program must:
refuse an installer whose sha256 does not match (nothing started), say it is
up to date for its own version, show "update available" in the window's
/api/update, and for a newer version download, verify and start the
installer, which waits for the program to exit and installs again.
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
import tempfile
import threading
import time
from urllib.request import urlopen

NEWER = "99.0.0"


def manifest(version, url, data, sha256=None):
    return {"schema": "pokersense-update-v1", "product": "PokerSense-AA",
            "version": version, "published": "2026-01-01T00:00:00Z",
            "commit": "smoke", "notes": "smoke test",
            "installer": {"url": url, "bytes": len(data),
                          "sha256": sha256 or hashlib.sha256(data).hexdigest()}}


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
    """Start the window with the update address and read /api/update."""
    ready = state / "ready.json"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (state / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(exe), "--no-browser", "--port", "0", "--state", str(state),
             "--ready-file", str(ready), "--update-url", url],
            stdout=log, stderr=log, creationflags=flags)
        try:
            deadline = time.monotonic() + 60
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
            if screenshot:
                take_screenshot(base, screenshot)
            return status
        finally:
            process.terminate()
            process.wait(timeout=20)


def take_screenshot(url, path):
    edge = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / (
        "Microsoft/Edge/Application/msedge.exe")
    if not edge.exists():
        return
    subprocess.run([str(edge), "--headless=new", "--disable-gpu",
                    "--hide-scrollbars", "--window-size=1366,800",
                    "--virtual-time-budget=8000", f"--screenshot={path}", url],
                   capture_output=True, timeout=120)


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

            window = root / "window-state"
            window.mkdir()
            status = window_status(exe, window, base + "latest.json", screenshot)
            assert status["status"] == "AVAILABLE", status
            assert status["latest"] == NEWER and status["can_install"] is True, status
            report["window"] = {key: status[key] for key in
                                ("status", "latest", "can_install")}

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
