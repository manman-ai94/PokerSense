"""The window's switch to 《一页纸打法 v3.2》 (``plain``): classic stays the
default; with the switch on, every frame goes to the live page
(``aa_plain_advice``, tested in ``test_aa_plain_live``) and nothing of the
old path runs; the switch is kept across restarts."""

import json

from fastapi.testclient import TestClient
import pytest

from poker_engine.desktop import aa_server
from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from tests.desktop.test_aa_solver_advice import Bot, Inline, run

HEADERS = {"X-AA-Live": "1"}


def test_plain_runs_no_solver_and_no_background_job():
    bot, executor = Bot({"CALL": 1.0}), Inline()
    advice = AASolverAdvice(bot, executor, strategy="plain")
    results = run(advice, range(50))
    assert not bot.seen and executor.submitted == 0
    assert all(result.get("kind") in (None, "plain") for result in results)


def test_classic_stays_the_default_and_the_switch_takes_only_the_two_names():
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline())
    assert advice.strategy == "classic"
    report = run(advice, range(50))[-1]
    assert report["kind"] == "multiway" and "contract" in report    # no solver
    assert not bot.seen
    with pytest.raises(ValueError):
        advice.set_strategy("solver")
    with pytest.raises(ValueError):
        AASolverAdvice(strategy="other")


def test_the_settings_switch_is_kept(tmp_path):
    path = tmp_path / "advice-strategy.json"
    app = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path,
                               strategy_path=path)
    with TestClient(app) as client:
        state = client.get("/api/strategy").json()
        assert state == {"strategy": "classic", "choices": ["classic", "plain"],
                         "default": "classic", "saved": True}
        plain = {"strategy": "plain"}
        assert client.post("/api/strategy", json=plain).status_code == 403
        assert client.post("/api/strategy", json={"strategy": "solver"},
                           headers=HEADERS).status_code == 400
        answer = client.post("/api/strategy", json=plain, headers=HEADERS)
        assert answer.status_code == 200 and answer.json()["strategy"] == "plain"
        assert app.state.aa_session._solver_advice.strategy == "plain"
        assert client.get("/strategy.js").status_code == 200
        page = client.get("/classic").text
        assert 'id="strategy-plain"' in page and "/strategy.js" in page
    assert json.loads(path.read_text(encoding="utf-8")) == {"strategy": "plain"}
    again = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path,
                                 strategy_path=path)
    assert again.state.aa_session._solver_advice.strategy == "plain"
    unsaved = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path)
    with TestClient(unsaved) as client:
        assert client.get("/api/strategy").json()["saved"] is False
    path.write_text("not json", encoding="utf-8")
    assert aa_server.load_strategy(path) == "classic"
