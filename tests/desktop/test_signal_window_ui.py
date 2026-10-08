from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from poker_engine.desktop import aa_server

ROOT = Path(__file__).resolve().parents[2]


class Session:
    def snapshot(self):
        return {"status": "STOPPED", "generation": 0, "payload": None}

    def preview(self):
        return None

    def stop(self):
        pass


def test_the_signal_window_view_covers_each_state():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the signal window's view script")
    completed = subprocess.run(
        [node, str(ROOT / "tests/ui/test_signal_view.js")], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "signal view cases passed" in completed.stdout


def test_the_signal_window_is_the_front_page_and_the_old_page_stays(tmp_path):
    app = aa_server.create_app(tmp_path / "missing.json", session=Session())
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="signal"' in page.text and "/signal.js" in page.text
        assert 'id="device"' in page.text      # the card is not always device 0
        # The grade after you act, this session's list, and the "行动后再看" switch.
        for element in ('id="compare"', 'id="session-rows"', 'id="advice-after"'):
            assert element in page.text
        for path, kind in (("/signal.js", "javascript"),
                           ("/signal_view.js", "javascript"),
                           ("/signal.css", "text/css")):
            response = client.get(path)
            assert response.status_code == 200
            assert kind in response.headers["content-type"]
        classic = client.get("/classic")
        assert classic.status_code == 200 and 'id="watch-view"' in classic.text


def test_the_signal_window_writes_data_as_text_only():
    # Values read from the screen go in with textContent, never as markup.
    for name in ("signal.js", "signal_view.js"):
        script = (ROOT / "ui/aa-live" / name).read_text(encoding="utf-8")
        assert "innerHTML" not in script and "insertAdjacentHTML" not in script
