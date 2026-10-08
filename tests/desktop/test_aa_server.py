from types import SimpleNamespace

from fastapi.testclient import TestClient

from poker_engine.desktop import aa_recorder, aa_server


class Session:
    def __init__(self):
        self.starts = []
        self.stops = 0

    def snapshot(self):
        return {"status": "STOPPED", "generation": self.stops, "payload": None}

    def preview(self):
        return None

    def start(self, options):
        self.starts.append(options)

    def stop(self):
        self.stops += 1


HEADERS = {"X-AA-Live": "1"}


def test_page_status_do_not_start_and_missing_profile_is_visible(tmp_path):
    session = Session()
    app = aa_server.create_app(tmp_path / "missing.json", session=session)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        status = client.get("/api/status").json()
        assert status["profile"]["ready"] is False
        assert status["capture_available"] is False
        assert status["realtime"]["mode"] == "OBSERVATION_ONLY"
        assert status["realtime"]["advice"] is None
        assert status["realtime"]["action_deadline"] is None
        assert not status["realtime"]["strategy_eligible"]
        assert status["realtime"]["rules_revision"] == status["table_rules"]["revision"]
        assert client.get("/api/preview.jpg").status_code == 404
        assert session.starts == []
    assert session.stops == 1


def test_controls_are_same_origin_and_explicit(tmp_path, monkeypatch):
    session = Session()
    monkeypatch.setattr(aa_server, "preflight_profile",
                        lambda _: {"ready": True, "errors": []})
    app = aa_server.create_app(tmp_path / "profile.json", replay_pool=tmp_path,
                               session=session)
    with TestClient(app) as client:
        body = {"mode": "development-replay"}
        assert client.post("/api/start", json=body).status_code == 403
        cross = {**HEADERS, "Origin": "https://example.com"}
        assert client.post("/api/start", json=body, headers=cross).status_code == 403
        assert client.post("/api/start", json=body,
                           headers=HEADERS).status_code == 200
        assert session.starts == [body]
        assert client.post("/api/start", json={"mode": "capture-card"},
                           headers=HEADERS).status_code == 403
        assert client.post("/api/start", json={**body, "path": "other"},
                           headers=HEADERS).status_code == 400
        assert client.post("/api/start", json={**body, "find_phone": "yes"},
                           headers=HEADERS).status_code == 400
        assert client.post("/api/start", json={**body, "find_phone": True},
                           headers=HEADERS).status_code == 200
        assert client.post("/api/stop", json={}, headers=HEADERS).status_code == 200
        assert session.stops == 1


def test_the_status_lists_the_cameras_only_with_the_capture_card(tmp_path):
    cameras = SimpleNamespace(names=lambda: ["FaceTime HD Camera"])
    app = aa_server.create_app(tmp_path / "missing.json", session=Session(),
                               allow_capture=True, camera_list=cameras)
    with TestClient(app) as client:
        assert client.get("/api/status").json()["capture_devices"] == [
            "FaceTime HD Camera"]
    app = aa_server.create_app(tmp_path / "missing.json", session=Session(),
                               camera_list=cameras)
    with TestClient(app) as client:
        assert client.get("/api/status").json()["capture_devices"] is None


def test_missing_models_prevents_any_start(tmp_path):
    session = Session()
    app = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path,
                               session=session)
    with TestClient(app) as client:
        response = client.post("/api/start", json={"mode": "development-replay"},
                               headers=HEADERS)
        assert response.status_code == 409
        assert session.starts == []


def test_frozen_ui_path(monkeypatch, tmp_path):
    monkeypatch.setattr(aa_server.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert aa_server.ui_root() == tmp_path / "ui" / "aa-live"


def test_rules_save_stops_old_session_and_cannot_claim_verified(tmp_path):
    from poker_engine.desktop.aa_table_config import empty_config

    session = Session()
    rules_path = tmp_path / "rules.json"
    app = aa_server.create_app(tmp_path / "missing", session=session,
                               rules_path=rules_path)
    with TestClient(app) as client:
        prior = client.get("/api/rules").json()
        document = {**empty_config(), "small_blind": "2", "big_blind": "4"}
        result = client.post("/api/rules", headers=HEADERS,
                             json={"document": document,
                                   "revision": prior["revision"]})
        assert result.status_code == 200
        assert session.stops == 1 and rules_path.exists()
        assert not result.json()["visual_verified"]
        assert not result.json()["conditional_analysis_ready"]
        again = client.post("/api/rules", headers=HEADERS,
                            json={"document": empty_config(),
                                  "revision": prior["revision"]})
        assert again.status_code == 400


def test_issue_recording_disabled_without_explicit_directory(tmp_path):
    app = aa_server.create_app(tmp_path / "missing", session=Session())
    with TestClient(app) as client:
        assert not client.get("/api/status").json()["issue_recording_available"]
        assert client.post("/api/issues", headers=HEADERS,
                           json={"note": "", "category": "cards"}).status_code == 403


class Analysis:
    def __init__(self):
        self.report = {"status": "IDLE", "binding": {}}
        self.calls = []

    def start(self, kind, document, *, binding):
        self.calls.append((kind, document, binding))
        self.report = {"status": "COMPLETE", "binding": binding,
                       "result": {"strategy_eligible": False}}
        return self.report

    def cancel(self):
        self.report = {"status": "CANCELLED", "binding": {}}
        return self.report

    def status(self):
        return self.report


def test_analysis_binds_rules_and_invalidates_on_generation_change(tmp_path):
    session, analysis = Session(), Analysis()
    app = aa_server.create_app(tmp_path / "missing", session=session,
                               analysis_service=analysis)
    with TestClient(app) as client:
        rules = client.get("/api/rules").json()
        sample = client.get("/api/analysis/example/terminal").json()["document"]
        body = {"kind": "terminal", "document": sample,
                "rules_source": "table", "rules_revision": rules["revision"]}
        assert client.post("/api/analysis", headers=HEADERS,
                           json=body).status_code == 400
        body["rules_source"] = "document"
        response = client.post("/api/analysis", headers=HEADERS, json=body)
        assert response.status_code == 200
        assert analysis.calls[0][2]["table_rules_revision"] == rules["revision"]
        assert analysis.calls[0][2]["effective_rules"] == sample["rules"]
        assert analysis.calls[0][2]["input_source"].startswith("MANUAL_HYPOTHESIS")
        session.stops += 1
        assert client.get("/api/status").json()["analysis"]["status"] == "CANCELLED"
        body["rules_revision"] = "stale"
        assert client.post("/api/analysis", headers=HEADERS,
                           json=body).status_code == 400


def test_rules_metadata_legacy_post_cancel_and_clear_lifecycle(tmp_path):
    from poker_engine.desktop.aa_table_config import STACK_RANGE, empty_config

    session, analysis = Session(), Analysis()
    rules_path = tmp_path / "rules.json"
    app = aa_server.create_app(tmp_path / "missing", session=session,
                               analysis_service=analysis, rules_path=rules_path)
    with TestClient(app) as client:
        first = client.get("/api/rules").json()
        document = {**empty_config(), "small_blind": "1", "big_blind": "2",
                    STACK_RANGE[0]: "50", STACK_RANGE[1]: "200"}
        analysis.report = {"status": "COMPLETE", "binding": {}}
        saved = client.post("/api/rules", headers=HEADERS,
                            json={"document": document,
                                  "revision": first["revision"]}).json()
        assert analysis.status()["status"] == "CANCELLED"
        assert session.stops == 1 and session.starts == []
        # Old callers omit both metadata fields, but may still edit table rules.
        old_document = {key: value for key, value in document.items()
                        if key not in STACK_RANGE}
        old_document["table_label"] = "changed by other page"
        latest = client.post("/api/rules", headers=HEADERS,
                             json={"document": old_document,
                                   "revision": saved["revision"]}).json()
        assert latest["document"][STACK_RANGE[0]] == "50"
        assert latest["document"][STACK_RANGE[1]] == "200"
        assert session.stops == 2
        # A stale page or invalid range never saves, cancels, or stops again.
        analysis.report = {"status": "COMPLETE", "binding": {}}
        disk = rules_path.read_bytes()
        stale = client.post("/api/rules", headers=HEADERS,
                            json={"document": empty_config(),
                                  "revision": saved["revision"]})
        assert stale.status_code == 400
        invalid = client.post("/api/rules", headers=HEADERS,
                              json={"document": {**document, STACK_RANGE[0]: "300"},
                                    "revision": latest["revision"]})
        assert invalid.status_code == 400
        assert session.stops == 2 and analysis.status()["status"] == "COMPLETE"
        assert rules_path.read_bytes() == disk
        # Cancel edits is a fresh GET, so another page's current values win.
        assert client.get("/api/rules").json() == latest
        assert session.stops == 2
        cleared = client.post("/api/rules", headers=HEADERS,
                              json={"document": empty_config(),
                                    "revision": latest["revision"]})
        assert cleared.status_code == 200
        assert cleared.json()["document"] == empty_config()
        assert analysis.status()["status"] == "CANCELLED"
        assert session.stops == 3 and session.starts == []
    # Restart reads the saved clear; no actual source or capture was opened.
    restarted = aa_server.create_app(tmp_path / "missing", session=Session(),
                                     rules_path=rules_path)
    with TestClient(restarted) as client:
        assert client.get("/api/rules").json() == cleared.json()


def test_analysis_rejects_duplicate_keys_and_large_body(tmp_path):
    app = aa_server.create_app(tmp_path / "missing", session=Session(),
                               analysis_service=Analysis())
    with TestClient(app) as client:
        headers = {**HEADERS, "Content-Type": "application/json"}
        response = client.post("/api/analysis", headers=headers,
                               content='{"kind":"terminal","kind":"threeway"}')
        assert response.status_code == 400
        assert client.post("/api/analysis", headers=headers,
                           content=' ' * 220001).status_code == 413


def test_video_replay_is_offered_only_when_a_recording_is_configured(
        tmp_path, monkeypatch):
    monkeypatch.setattr(aa_server, "preflight_profile",
                        lambda _: {"ready": True, "errors": []})
    body = {"mode": "video-replay"}
    session = Session()
    app = aa_server.create_app(tmp_path / "profile.json", session=session)
    with TestClient(app) as client:
        assert client.get("/api/status").json()["video_available"] is False
        assert client.post("/api/start", json=body,
                           headers=HEADERS).status_code == 400
    recording = tmp_path / "rec.mkv"
    recording.write_bytes(b"x")
    session = Session()
    app = aa_server.create_app(tmp_path / "profile.json", session=session,
                               replay_video=recording,
                               replay_video_exclude=["300-820"])
    with TestClient(app) as client:
        assert client.get("/api/status").json()["video_available"] is True
        assert client.post("/api/start", json=body,
                           headers=HEADERS).status_code == 200
        assert session.starts == [body]


def test_the_service_grades_your_decisions_against_its_own_advice(tmp_path):
    from poker_engine.desktop.aa_grading import AAGrades

    app = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path)
    service = app.state.aa_session
    assert isinstance(service._grades, AAGrades)
    assert service._grades._advice is service._solver_advice


def test_recording_is_asked_for_by_the_page_and_only_from_the_capture_card(
        tmp_path, monkeypatch):
    monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 100 * aa_recorder.GB)

    class Recording(Session):
        kind = "capture-card"

        def __init__(self):
            super().__init__()
            self.calls = []

        def snapshot(self):
            return {**super().snapshot(), "source_kind": self.kind}

        def record(self, on, out=None):
            self.calls.append((on, out))

    session = Recording()
    app = aa_server.create_app(tmp_path / "missing.json", session=session,
                               recordings_dir=tmp_path / "recordings")
    with TestClient(app) as client:
        assert client.post("/api/recording", json={"on": True}).status_code == 403
        assert client.post("/api/recording", json={"on": "yes"},
                           headers=HEADERS).status_code == 400
        assert client.post("/api/recording", json={"on": True},
                           headers=HEADERS).status_code == 200
        on, out = session.calls[-1]
        assert on is True and out.parent == tmp_path / "recordings"
        assert out.name.endswith("-live")
        assert client.post("/api/recording", json={"on": False},
                           headers=HEADERS).status_code == 200
        assert session.calls[-1] == (False, None)
        session.kind = "video-replay"
        refused = client.post("/api/recording", json={"on": True}, headers=HEADERS)
        assert refused.status_code == 409 and len(session.calls) == 2


def test_recording_starts_only_once_the_window_has_seen_the_table(
        tmp_path, monkeypatch):
    # A computer camera also gives a 1920x1080 picture: the window records
    # only when its recognition has seen the AA table lately.
    monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 100 * aa_recorder.GB)

    class Recording(Session):
        seen = None

        def __init__(self):
            super().__init__()
            self.calls = []

        def snapshot(self):
            return {**super().snapshot(), "source_kind": "capture-card"}

        def table_seen(self):
            return self.seen

        def record(self, on, out=None):
            self.calls.append((on, out))

    session = Recording()
    app = aa_server.create_app(tmp_path / "missing.json", session=session,
                               recordings_dir=tmp_path / "recordings")
    with TestClient(app) as client:
        for seen in (None, aa_server.TABLE_SECONDS + 1):
            session.seen = seen
            refused = client.post("/api/recording", json={"on": True}, headers=HEADERS)
            assert refused.status_code == 409 and session.calls == []
            assert refused.json()["detail"].startswith("没找到采集卡画面，录像没有开始。")
        session.seen = 2.0
        assert client.post("/api/recording", json={"on": True},
                           headers=HEADERS).status_code == 200
        assert session.calls[-1][0] is True


def test_recording_does_not_start_with_little_room_left(tmp_path, monkeypatch):
    class Recording(Session):
        def __init__(self):
            super().__init__()
            self.calls = []

        def snapshot(self):
            return {**super().snapshot(), "source_kind": "capture-card"}

        def record(self, on, out=None):
            self.calls.append((on, out))

    session = Recording()
    app = aa_server.create_app(tmp_path / "missing.json", session=session,
                               recordings_dir=tmp_path / "recordings")
    monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 12 * aa_recorder.GB)
    with TestClient(app) as client:
        refused = client.post("/api/recording", json={"on": True}, headers=HEADERS)
        assert refused.status_code == 409 and session.calls == []
        assert "磁盘只剩 12 GB" in refused.json()["detail"]
        # Stopping always works.
        assert client.post("/api/recording", json={"on": False},
                           headers=HEADERS).status_code == 200
        monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 30 * aa_recorder.GB)
        assert client.post("/api/recording", json={"on": True},
                           headers=HEADERS).status_code == 200
