"""The window's switch to 《一页纸打法 v3.3c》 (``plain``): the window's
default since 2026-10-17; with it on, every frame goes to the live page
(``aa_plain_advice``, tested in ``test_aa_plain_live``) and nothing of the
old path runs; the switch is kept across restarts, and a choice saved
while classic was the default gives way to plain once."""

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


def test_tools_still_replay_classic_and_the_switch_takes_only_the_two_names():
    # The window passes its switch (plain by default); a tool that replays
    # the older advice passes none.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    assert advice.strategy == "classic"
    assert run(advice, range(50))[-1].get("kind") is None       # the solver's
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
        assert state == {"strategy": "plain", "choices": ["plain", "classic"],
                         "default": "plain", "saved": True}
        assert app.state.aa_session._solver_advice.strategy == "plain"
        classic = {"strategy": "classic"}
        assert client.post("/api/strategy", json=classic).status_code == 403
        assert client.post("/api/strategy", json={"strategy": "solver"},
                           headers=HEADERS).status_code == 400
        answer = client.post("/api/strategy", json=classic, headers=HEADERS)
        assert answer.status_code == 200 and answer.json()["strategy"] == "classic"
        assert app.state.aa_session._solver_advice.strategy == "classic"
        assert client.get("/strategy.js").status_code == 200
        page = client.get("/classic").text
        assert 'id="strategy-plain"' in page and "/strategy.js" in page
    assert json.loads(path.read_text(encoding="utf-8")) == {"strategy": "classic",
                                                            "default": "plain"}
    again = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path,
                                 strategy_path=path)
    assert again.state.aa_session._solver_advice.strategy == "classic"
    unsaved = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path)
    with TestClient(unsaved) as client:
        assert client.get("/api/strategy").json()["saved"] is False
    path.write_text("not json", encoding="utf-8")
    assert aa_server.load_strategy(path) == "plain"


def test_a_choice_saved_under_the_old_default_gives_way_once(tmp_path):
    # Saved before 10-17 (no "default": classic was it): plain from now on.
    path = tmp_path / "advice-strategy.json"
    for old in ({"strategy": "classic"}, {"strategy": "plain"},
                {"strategy": "classic", "default": "classic"}):
        path.write_text(json.dumps(old), encoding="utf-8")
        assert aa_server.load_strategy(path) == "plain"
    # Chosen under the new default: kept.
    aa_server.save_strategy(path, "classic")
    assert aa_server.load_strategy(path) == "classic"
    assert aa_server.load_strategy(None) == "plain"
