from fastapi.testclient import TestClient

from poker_engine.desktop import aa_server


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
        assert client.post("/api/stop", json={}, headers=HEADERS).status_code == 200
        assert session.stops == 1


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
