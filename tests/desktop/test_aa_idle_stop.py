"""A closed or forgotten window does not keep the capture card open."""

import threading

from fastapi.testclient import TestClient

from poker_engine.desktop import aa_server
from poker_engine.desktop.aa_server import IdleStop


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Session:
    def __init__(self, status="RUNNING"):
        self.status, self.stops = status, 0

    def snapshot(self):
        return {"status": self.status, "generation": 0, "payload": None}

    def preview(self):
        return None

    def stop(self):
        self.stops += 1
        self.status = "STOPPED"


def test_the_source_stops_when_no_page_has_been_in_touch():
    clock, session = Clock(), Session()
    idle = IdleStop(session, 180, threading.RLock(), clock)
    clock.now += 179
    assert idle.check() is False and session.stops == 0
    idle.touch()                       # a poll or a heartbeat
    clock.now += 179
    assert idle.check() is False
    clock.now += 2
    assert idle.check() is True and session.stops == 1 and idle.stops == 1
    # Nothing open: nothing to stop.
    clock.now += 500
    assert idle.check() is False and session.stops == 1


def test_pages_keep_the_source_running_by_polling_or_heartbeat(tmp_path):
    session = Session()
    app = aa_server.create_app(tmp_path / "missing.json", session=session,
                               idle_stop_seconds=180)
    idle = app.state.idle_stop
    with TestClient(app) as client:
        idle.seen = -1e9
        assert client.get("/api/heartbeat").json() == {"ok": True}
        assert idle.check() is False
        idle.seen = -1e9
        client.get("/api/status")
        assert idle.check() is False and session.stops == 0
    assert aa_server.create_app(tmp_path / "missing.json",
                                session=Session()).state.idle_stop is None
