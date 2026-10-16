"""The window's switch to 《一页纸打法 v3.1》 (``plain``): every decision by the
one page, no solver, no range rule, no rough rule; iron law 5 when the hand
cannot be read or the answer does not come in time."""

import json

from fastapi.testclient import TestClient
import pytest

from poker_engine.desktop import aa_server
from poker_engine.desktop.aa_session import frame_summary
from poker_engine.desktop.aa_solver_advice import (
    HOLD_FRAMES, AASolverAdvice, plain_advice_row, plain_unread)
from poker_engine.scoreboard import plain_policy
from tests.desktop.test_aa_solver_advice import Bot, Inline, run, still

HEADERS = {"X-AA-Live": "1"}


def test_plain_advises_the_turn_by_the_page_without_the_solver():
    # You limped, the straddle checked, the flop went check-check; on the turn
    # (Ah Kd 7c 2s) the straddle bets 10. Your queens are a pair under the top
    # card: C, and C folds to a turn bet.
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline(), strategy="plain")
    ready = run(advice, range(50))[-1]
    assert (ready["status"], ready["kind"]) == ("ready", "plain")
    assert ready["street"] == "turn"
    assert ready["advice"] == [{"action": "fold", "frequency": 1.0}]
    page = ready["plain"]
    assert (page["rule"], page["tier"], page["hand"]) == ("F.C", "C", "中对")
    assert page["reason"].endswith("面对下注·C 档——弃。")
    assert page["range"] and page["need"] is not None and page["flip"]
    assert ready["acts_on_client"] is False and not bot.seen      # no solver
    assert frame_summary({"solver_advice_v1": ready})["solver_advice"]["plain"] == page


def test_plain_is_the_same_page_on_the_scoreboard(monkeypatch):
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), strategy="plain")
    run(advice, range(50))
    observations = []
    original = plain_policy.decide

    def spy(observation, **kwargs):
        observations.append(observation)
        return original(observation, **kwargs)

    monkeypatch.setattr(plain_policy, "decide", spy)
    advice.set_strategy("classic")                  # switching works the step out again
    advice.set_strategy("plain")
    live = run(advice, range(50, 52))[-1]["plain"]
    assert observations and original(observations[-1]).row() == live


def test_a_hand_that_does_not_replay_gets_iron_law_5_at_once():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still, strategy="plain")
    results = run(advice, range(50), drop=(0,))         # seat 3's fold was missed
    first = results[42]
    assert (first["status"], first["kind"]) == ("ready", "plain")
    assert first["advice"] == [{"action": "fold", "frequency": 1.0}]
    assert first["plain"]["rule"] == "S1" and first["plain"]["unread"]
    assert first["plain"]["reason"].startswith("看不清：")


def test_an_answer_that_does_not_come_in_time_is_iron_law_5_until_it_does():
    executor = Inline(finish=False)
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor, clock=still, strategy="plain")
    results = run(advice, range(42 + HOLD_FRAMES + 2))
    assert results[42]["status"] == "computing"
    late = results[42 + HOLD_FRAMES]
    assert (late["status"], late["kind"]) == ("ready", "plain") and late["provisional"]
    assert late["plain"]["rule"] == "I5" and late["advice"][0]["action"] == "fold"
    assert "rough_for" not in late and executor.submitted == 1   # no rough rule


def test_classic_stays_the_default_and_the_switch_takes_only_the_two_names():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    assert advice.strategy == "classic"
    assert run(advice, range(50))[-1].get("kind") is None       # the solver's
    with pytest.raises(ValueError):
        advice.set_strategy("solver")
    with pytest.raises(ValueError):
        AASolverAdvice(strategy="other")


def test_rows_for_the_window_and_the_grades():
    row = plain_advice_row(plain_policy.Advice("raise", to=69.0),
                           {"bets": {"4": "4"}, "observing_seat": 4})
    assert row == {"action": "raise", "frequency": 1.0, "chips": "65", "to": "69"}
    assert plain_advice_row(plain_policy.Advice("call"), {}) == {
        "action": "call", "frequency": 1.0}
    check = plain_unread({"hero_controls": {"button": "check"}}, "hand_incomplete")
    assert check["advice"] == [{"action": "check", "frequency": 1.0}]
    assert check["plain"]["reason"] == (
        "看不清：这手的动作接不上（hand_incomplete）；第 1 步·看不清 → 铁律 5——过牌。")


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
