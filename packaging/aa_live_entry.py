"""AA engineering desktop entry. No capture or model loading on startup."""

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser


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


REQUIRED_RESOURCES = (
    "ui/aa-live/index.html", "ui/aa-live/app.js", "ui/aa-live/style.css",
    "ui/aa-live/hand_input.js", "ui/aa-live/analysis_records.js",
    "configs/strategy/examples/terminal-multiway-river-manual.json",
    "configs/strategy/examples/threeway-river-response-manual.json",
)


def default_state():
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".local" / "share") / (
        "PokerSense-AA") / __version__


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
    result.add_argument("--allow-capture", action="store_true",
                        help="Explicitly enable UI capture controls; no auto-start")
    result.add_argument("--port", type=int, default=8771)
    result.add_argument("--no-browser", action="store_true")
    result.add_argument("--open-browser", action="store_true",
                        help="Compatibility flag; browser opens by default")
    result.add_argument("--ready-file", type=Path)
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
    }


def create_app(args):
    from poker_engine.desktop.aa_server import create_app as aa_app

    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    # Missing external resources are expected in a public offline package.
    # No synthetic profile is created or represented as an accepted model.
    profile = args.profile or state / "external-aa-profile-not-configured.json"
    app = aa_app(
        profile, replay_pool=args.replay_pool, replay_first=args.replay_first,
        replay_last=args.replay_last, replay_playlist=args.replay_playlist,
        allow_capture=args.allow_capture, bundle_sha256=args.bundle_sha256,
        rules_path=args.rules_path or state / "table-rules.json",
        records_dir=args.records_dir or state / "records")

    @app.get("/api/build")
    def build_identity():
        return package_report(args)

    return app


def open_listener(preferred):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", preferred))
    except OSError:
        listener.close()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    return listener


def serve(args):
    import uvicorn

    app = create_app(args)
    with open_listener(args.port) as listener:
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
        print("AA offline preview. Close this console to stop. "
              "Private recognition models and live strategy are not included.",
              flush=True)
        if not args.no_browser:
            webbrowser.open(base)
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join(timeout=10)
    return 0


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if not 0 <= args.port <= 65535:
        cli.error("--port must be between 0 and 65535")
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
