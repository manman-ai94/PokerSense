"""AA engineering desktop entry. No capture or model loading on startup."""

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


CHROME = Path("/Applications/Google Chrome.app")


def open_page(url, *, platform=sys.platform, chrome=CHROME, run=subprocess.run,
              fallback=webbrowser.open):
    """Chrome on a Mac that has it: the always-on-top small window of the
    signal page (Document Picture-in-Picture) exists in Chrome, not Safari."""
    if platform == "darwin" and chrome.exists():
        try:
            run(["open", "-a", str(chrome), url], check=True, timeout=15)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    fallback(url)


def resource_root():
    frozen = getattr(sys, "_MEIPASS", None)
    return Path(frozen) if frozen else Path(__file__).resolve().parents[1]


def configure_source_path():
    if not getattr(sys, "frozen", False):
        root = resource_root()
        for path in (root, root / "src"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))


configure_source_path()
from poker_engine import __version__  # noqa: E402
from poker_engine.data_paths import DATA_ROOT_ENV  # noqa: E402
from poker_engine.desktop import app_update  # noqa: E402


REQUIRED_RESOURCES = (
    "ui/aa-live/index.html", "ui/aa-live/app.js", "ui/aa-live/style.css",
    "ui/aa-live/hand_input.js", "ui/aa-live/analysis_records.js",
    "ui/aa-live/signal.html", "ui/aa-live/signal.js", "ui/aa-live/signal_view.js",
    "ui/aa-live/signal.css", "ui/aa-live/update_banner.js",
    "configs/strategy/examples/terminal-multiway-river-manual.json",
    "configs/strategy/examples/threeway-river-response-manual.json",
)


# A closed browser window releases the capture card after this long. Pages
# hidden in the background send a heartbeat; Chrome may slow a hidden page's
# timers to once a minute, hence the margin.
IDLE_STOP_SECONDS = 180


# Imported by the frozen self-test: the reader's lazily imported modules
# (aa_reader) must be inside the package for live recognition to start.
RECOGNITION_MODULES = (
    "poker_engine.desktop.aa_reader", "poker_engine.desktop.aa_live_context",
    "poker_engine.desktop.aa_live_context_v3",
    "poker_engine.desktop.aa_critical_perception",
    "tools.aa8_candidate_v2", "tools.aa8_cards_v2", "tools.aa8_action_transfer",
    "tools.aa8_action_reader", "tools.aa8_special_modes",
    "tools.aa8_glyph_transitions_v2", "tools.aa8_glyph_supplement_v3",
    "tools.aa8_unmarked_money", "tools.aa_data_separation",
    "tools.wpk_video_dataset",
)


def default_state():
    """Installed builds keep one data folder across updates; a source
    checkout keeps one per version."""
    base = os.environ.get("LOCALAPPDATA")
    root = (Path(base) if base else Path.home() / ".local" / "share") / (
        "PokerSense-AA")
    return root / ("data" if getattr(sys, "frozen", False) else __version__)


def progress_printer(label, out):
    shown = [-10]

    def progress(received, total):
        percent = received * 100 // total
        if percent >= shown[0] + 10 or received == total:
            shown[0] = percent
            out(f"{label} 已下载 {percent}%")
    return progress


def sync_recognition(args, url, out):
    """Fetch the recognition bundle the latest release lists, when it is not
    the one in the data folder yet (first start, or a release with a new one)."""
    out("[识别资源] 正在检查识别资源包……")
    result = app_update.sync_recognition(
        url, args.state, progress=progress_printer("[识别资源]", out))
    have = app_update.installed_recognition(args.state) is not None
    status = result["status"]
    if status == "INSTALLED":
        out("[识别资源] 已下载，sha256 和校验都通过：可以接采集卡实时读牌。")
    elif status == "UP_TO_DATE":
        out("[识别资源] 已经是最新的。")
    elif status == "NOT_PUBLISHED" and not have:
        out("[识别资源] 还没有发布识别资源包：暂时不能实时读牌，其余功能照常。")
    elif status == "ERROR":
        out(f"[识别资源] 这次没下载成功：{result['error']}")
        out("[识别资源] 继续用已经有的那份。" if have else
            "[识别资源] 暂时不能实时读牌；下次打开程序会再试。")
    return result


def use_recognition(args, out=print):
    """Before the window opens: bring the recognition bundle up to date (when
    an update address is configured) and use it for the capture card."""
    if args.no_recognition or args.profile:
        return None
    url = app_update.configured_url(args.update_url)
    if url and not args.self_check and not args.no_update_check:
        sync_recognition(args, url, out)
    bundle = app_update.installed_recognition(args.state)
    if bundle is not None:
        args.profile, args.bundle_sha256 = bundle
        args.allow_capture = True
    return bundle


def parser():
    result = argparse.ArgumentParser(
        description=f"PokerSense AA {__version__}: offline engineering preview")
    result.add_argument("--version", action="version",
                        version=f"PokerSense-AA {__version__}")
    result.add_argument("--self-check", action="store_true",
                        help="Read-only package/resource check; no server")
    result.add_argument("--state", type=Path, default=default_state())
    result.add_argument("--profile", type=Path,
                        help="External private AA model profile, never bundled")
    result.add_argument("--bundle-sha256")
    result.add_argument("--rules-path", type=Path)
    result.add_argument("--records-dir", type=Path)
    result.add_argument("--replay-pool", type=Path)
    result.add_argument("--replay-first", type=int)
    result.add_argument("--replay-last", type=int)
    result.add_argument("--replay-playlist", type=Path)
    result.add_argument("--replay-video", type=Path,
                        help="Recording file, or a segment folder with segments.csv")
    result.add_argument("--replay-video-start", type=float, default=0.0)
    result.add_argument("--replay-video-exclude", action="append", default=[],
                        metavar="START-END",
                        help="Recording window in seconds to skip; repeatable")
    result.add_argument("--replay-video-speed", type=float, default=1.0)
    result.add_argument("--frame-log", type=Path,
                        help="Append one JSON line per processed frame")
    result.add_argument("--allow-capture", action="store_true",
                        help="Explicitly enable UI capture controls; no auto-start")
    result.add_argument("--idle-stop", type=float, default=IDLE_STOP_SECONDS,
                        metavar="SECONDS",
                        help="Stop the source when no page is open this long; 0 never")
    result.add_argument("--port", type=int, default=8771)
    result.add_argument("--no-browser", action="store_true")
    result.add_argument("--open-browser", action="store_true",
                        help="Compatibility flag; browser opens by default")
    result.add_argument("--ready-file", type=Path)
    result.add_argument("--update-url",
                        help="Version manifest address (overrides update-config.json)")
    result.add_argument("--update-now", action="store_true",
                        help="Check, download, verify and install an update, then exit")
    result.add_argument("--no-update-check", action="store_true",
                        help="Do not check for updates at startup")
    result.add_argument("--no-recognition", action="store_true",
                        help="Do not fetch or use the recognition bundle")
    result.add_argument("--self-test", action="store_true",
                        help="Run the core calculations and recognition imports; "
                             "no server")
    return result


def package_report(args):
    root = resource_root()
    missing = [name for name in REQUIRED_RESOURCES
               if not (root / name).is_file()]
    return {
        "product": "PokerSense-AA", "version": __version__,
        "entrypoint": "poker_engine.desktop.aa_server",
        "release_status": "ENGINEERING_PREVIEW_NOT_ACCEPTED",
        "resource_root": str(root), "missing_resources": missing,
        "capture_enabled": args.allow_capture,
        "external_model": "CONFIGURED_NOT_VALIDATED" if args.profile else (
            "NOT_CONFIGURED_OFFLINE_AVAILABLE"),
        "strategy_eligible": False, "real_hand_acceptance": "PENDING",
        "empirical_strategy": "NOT_ASSESSED",
        "recognition_bundle": "INSTALLED" if args.bundle_sha256 else "NOT_INSTALLED",
        "update_configured": bool(app_update.configured_url(args.update_url)),
    }


def self_test():
    """The calculations the window gives advice with, and the recognition
    code, run inside this (possibly frozen) program."""
    import importlib
    from poker_engine.desktop.aa_solver_advice import rough_advice
    from poker_engine.desktop.aa_stakes import RULES_PATH
    from poker_engine.scoreboard.runner import run_scoreboard
    from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

    rules = AARuleProfileV2.from_dict(json.loads(RULES_PATH.read_text("utf-8")))
    board = run_scoreboard(rules, ["aa_preflop"], deals=2, pool=("aa_population",))
    fields = {"board": ["Ah", "Kd", "7c", "2s", None],
              "participants": {"2": "active", "3": "folded", "4": "active"},
              "pot": "35", "street_wagers": {"2": "10"},
              "hero_controls": {"visible": True, "button": "call",
                                "call_amount": "10"}, "stacks": {"4": "200"}}
    rough = rough_advice(fields, ["Qs", "Qh"], "turn")
    if board["hands_per_strategy"] <= 0 or rough is None:
        raise RuntimeError("core calculations returned nothing")
    missing = []
    for name in RECOGNITION_MODULES:
        try:
            importlib.import_module(name)
        except ImportError as error:
            missing.append(f"{name}: {error}")
    return {"product": "PokerSense-AA", "version": __version__,
            "scoreboard_hands": board["hands_per_strategy"],
            "rough_advice": rough["advice"][0]["action"],
            "rough_equity": rough["range_equity"]["value"],
            "recognition_modules": len(RECOGNITION_MODULES) - len(missing),
            "missing_modules": missing,
            "result": "SELF_TEST_PASS" if not missing else "SELF_TEST_FAIL"}


def create_app(args):
    from fastapi import HTTPException
    from poker_engine.desktop.aa_server import create_app as aa_app, video_options

    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    # Missing external resources are expected in a public offline package.
    # No synthetic profile is created or represented as an accepted model.
    profile = args.profile or state / "external-aa-profile-not-configured.json"
    app = aa_app(
        profile, replay_pool=args.replay_pool, replay_first=args.replay_first,
        replay_last=args.replay_last, replay_playlist=args.replay_playlist,
        **video_options(args), allow_capture=args.allow_capture,
        bundle_sha256=args.bundle_sha256, idle_stop_seconds=args.idle_stop or None,
        rules_path=args.rules_path or state / "table-rules.json",
        records_dir=args.records_dir or state / "records")

    @app.get("/api/build")
    def build_identity():
        return package_report(args)

    service = app.state.aa_session

    def exit_soon():
        def finish():
            time.sleep(1.0)
            try:
                service.stop()          # finishes a recording first
            finally:
                os._exit(0)
        threading.Thread(target=finish, daemon=True).start()

    updater = app_update.Updater(
        app_update.configured_url(args.update_url), __version__,
        state / "updates", exit_soon=exit_soon)
    app.state.updater = updater

    @app.get("/api/update")
    def update_status():
        return updater.snapshot()

    @app.post("/api/update/check")
    def update_check():
        return updater.refresh()

    @app.post("/api/update/install")
    def update_install():
        try:
            return updater.install()
        except app_update.UpdateError as error:
            raise HTTPException(409, str(error)) from error

    return app


def announce_update(updater):
    """One line on the console when the startup check finds a new version."""
    def run():
        result = updater.refresh()
        if result["status"] == "AVAILABLE":
            print(f"[更新] 有新版 {result['latest']}（现在 {result['current']}）："
                  "在窗口右下角点“立即更新”，或在开始菜单里点“检查更新”。",
                  flush=True)
        elif result["status"] == "ERROR":
            print(f"[更新] 没查到新版：{result['error']}", flush=True)
    threading.Thread(target=run, daemon=True, name="pokersense-update-check").start()


def stop_source(port):
    """Ask the window on ``port`` to stop its source; a recording it makes is
    finished before it answers. Best effort."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/stop", data=b"{}", method="POST",
        headers={"X-AA-Live": "1", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=15).read()
    except (OSError, ValueError):
        pass


def take_over(port, *, run=subprocess.run, kill=os.kill, stop=stop_source,
              me=None, seconds=10, clock=time.monotonic, sleep=time.sleep):
    """Close an older window of this program that listens on ``port``, so a
    new launch keeps the page's address (and what the page remembers there)
    and only one window owns the capture card. Its source is stopped first,
    then the process gets a normal kill. Anything else on the port is left
    alone (``open_listener`` then picks another port). Returns the process
    ids closed; nothing where ``lsof`` is missing (Windows)."""
    me = os.getpid() if me is None else me
    try:
        listed = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                     capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    closed = []
    for pid in sorted({int(item) for item in listed if item.isdigit()} - {me}):
        try:
            command = run(["ps", "-ww", "-o", "command=", "-p", str(pid)],
                          capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if "aa_live_entry.py" not in command:
            continue
        stop(port)
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            continue
        deadline = clock() + seconds
        while clock() < deadline:
            try:
                kill(pid, 0)
            except OSError:
                break
            sleep(0.2)
        print(f"[AA] 关掉了之前开着的窗口（进程 {pid}）", flush=True)
        closed.append(pid)
    return closed


def open_listener(preferred, *, wait=0.0):
    """A listening socket on ``preferred``, tried for ``wait`` seconds (the
    connections of a window just closed may hold it up to half a minute on a
    Mac), else on a free port."""
    deadline, said = time.monotonic() + wait, False
    while True:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # A window just closed leaves its connections waiting a while;
            # this still refuses a port another program listens on.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", preferred))
            break
        except OSError:
            listener.close()
        if time.monotonic() >= deadline:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            break
        if not said:
            print(f"[AA] 等之前的窗口放开端口 {preferred}……", flush=True)
            said = True
        time.sleep(0.25)
    listener.listen(128)
    return listener


def serve(args):
    import uvicorn

    app = create_app(args)
    if not args.no_update_check:
        announce_update(app.state.updater)
    closed = take_over(args.port) if args.port else []
    with open_listener(args.port, wait=40 if closed else 0) as listener:
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started and thread.is_alive():
            if time.monotonic() >= deadline:
                server.should_exit = True
                raise RuntimeError("AA server startup timed out")
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("AA server failed before readiness")
        base = f"http://127.0.0.1:{port}/"
        ready = {**package_report(args), "base": base,
                 "state": str(args.state.resolve())}
        if args.ready_file:
            args.ready_file.write_text(json.dumps(ready), encoding="utf-8")
        print(json.dumps(ready, ensure_ascii=True), flush=True)
        print("PokerSense AA 已打开。关掉这个黑色窗口就是退出程序。"
              if args.bundle_sha256 else
              "AA offline preview. Close this console to stop. "
              "Private recognition models and live strategy are not included.",
              flush=True)
        if not args.no_browser:
            open_page(base)
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join(timeout=10)
    return 0


def console_update(args, *, keep_open=None):
    """The Start-menu "check for updates" shortcut: the recognition bundle,
    then the program."""
    url = app_update.configured_url(args.update_url)

    def out(line):
        print(line, flush=True)
    if url and not args.no_recognition:
        sync_recognition(args, url, out)
    code, started = app_update.run_console_update(
        url, __version__, args.state / "updates", out=out)
    if keep_open is None:
        keep_open = sys.stdin is not None and sys.stdin.isatty()
    if started:
        time.sleep(2)
    elif keep_open:
        try:
            input("按回车键关闭这个窗口……")
        except EOFError:
            pass
    return code


def utf8_output(streams=None):
    """Chinese messages must not crash the program when its output goes to a
    pipe or file: Windows then encodes with the ANSI code page (cp1252)."""
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    if os.name == "nt":
        utf8_output()
    cli = parser()
    args = cli.parse_args(argv)
    if not 0 <= args.port <= 65535:
        cli.error("--port must be between 0 and 65535")
    root = app_update.install_root()
    if args.update_now:
        return console_update(args)
    if args.self_test:
        report = self_test()
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["result"] == "SELF_TEST_PASS" else 1
    use_recognition(args, out=lambda line: print(line, flush=True))
    if root is not None and not os.environ.get(DATA_ROOT_ENV):
        # Recordings and other private data stay in the user's data folder
        # (the source default on Windows is the old G: drive).
        os.environ[DATA_ROOT_ENV] = str(args.state)
    if args.allow_capture and args.profile is None:
        cli.error("--allow-capture requires an explicit external --profile")
    report = package_report(args)
    if args.self_check or report["missing_resources"]:
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 2 if report["missing_resources"] else 0
    return serve(args)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
