"""Exercise a built AA EXE offline from an empty cwd; never open a device."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def smoke(executable):
    executable = Path(executable).resolve(strict=True)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME"}}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    report = {"executable": str(executable),
              "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "capture_started": False, "endpoints": {}}
    with tempfile.TemporaryDirectory(prefix="pokersense-aa-offline-") as folder:
        root = Path(folder)
        for argument in ("--help", "--version", "--self-check"):
            result = subprocess.run(
                [str(executable), argument], cwd=root, env=environment,
                capture_output=True, text=True, timeout=30, creationflags=flags)
            if result.returncode:
                raise RuntimeError(f"{argument}: {result.stderr}")
            if argument == "--self-check":
                report["self_check"] = json.loads(result.stdout)
                assert not report["self_check"]["missing_resources"]
                assert report["self_check"]["capture_enabled"] is False
            elif argument == "--version":
                report["version"] = result.stdout.strip()
        ready_file = root / "ready.json"
        with (root / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(executable), "--no-browser", "--port", "0",
                 "--state", str(root / "state"), "--ready-file", str(ready_file)],
                cwd=root, env=environment, stdout=log, stderr=log,
                creationflags=flags)
            try:
                deadline = time.monotonic() + 30
                while not ready_file.exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.flush()
                        raise RuntimeError((root / "server.log").read_text("utf-8"))
                    time.sleep(0.05)
                ready = json.loads(ready_file.read_text("utf-8"))
                base = ready["base"]
                endpoints = ("", "app.js", "style.css", "controls.js",
                             "analysis.js", "review.js", "study.js",
                             "hand_input.js", "analysis_records.js", "api/build",
                             "api/status", "api/analysis/example/terminal",
                             "api/analysis/example/threeway")
                for endpoint in endpoints:
                    with urlopen(base + endpoint, timeout=5) as response:
                        content = response.read()
                        assert content
                        report["endpoints"]["/" + endpoint] = response.status
                        if endpoint == "api/analysis/example/terminal":
                            terminal_example = json.loads(content)["document"]
                        if endpoint == "api/build":
                            identity = json.loads(content)
                            assert identity["product"] == "PokerSense-AA"
                            assert identity["version"] == (
                                report["self_check"]["version"])
                        if endpoint == "api/status":
                            status = json.loads(content)
                            assert status["capture_available"] is False
                            assert status["profile"]["ready"] is False
                            assert status["replay_available"] is False
                # Exercise an actual frozen spawned analysis worker, not just
                # imports or resource existence. This uses public manual data.
                analysis_request = Request(
                    base + "api/analysis", data=json.dumps({
                        "kind": "terminal", "document": terminal_example,
                        "rules_source": "document",
                        "rules_revision": status["table_rules"]["revision"],
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-AA-Live": "1"})
                with urlopen(analysis_request, timeout=5) as response:
                    assert response.status == 200
                analysis_deadline = time.monotonic() + 15
                while True:
                    with urlopen(base + "api/status", timeout=5) as response:
                        analysis = json.load(response)["analysis"]
                    if analysis["status"] != "RUNNING":
                        break
                    if time.monotonic() >= analysis_deadline:
                        raise AssertionError("frozen analysis never completed")
                    time.sleep(0.05)
                assert analysis["status"] == "COMPLETE", analysis
                assert analysis["result"]["strategy_eligible"] is False
                assert analysis["result"]["advice_emitted"] is False
                report["manual_analysis"] = "COMPLETE_CONDITIONAL_NOT_LIVE"
                request = Request(
                    base + "api/start", data=b'{"mode":"capture-card"}',
                    headers={"Content-Type": "application/json", "X-AA-Live": "1"})
                try:
                    urlopen(request, timeout=5).close()
                except HTTPError as error:
                    assert error.code == 403
                    report["capture_request_status"] = error.code
                else:
                    raise AssertionError("offline package enabled capture")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    report["result"] = "OFFLINE_PACKAGE_SMOKE_PASS"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = smoke(args.executable)
    text = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
