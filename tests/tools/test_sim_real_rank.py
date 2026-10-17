"""The simulation's order of strategy variants against the shown cards' order,
and its level against what the window's strategy really made."""

from decimal import Decimal
import json

import pytest

from tests.tools.test_aa_compare_advice import rows
from tools import sim_real_rank
from tools.aa_compare_advice import chips


def shown_rows(cards=("Kc", "Kd")):
    """The limp, raise, re-raise hand; seat 0 shows ``cards`` at the end."""
    found = rows()
    found[-1]["fields"]["shown_cards"] = {"seats": {"0": {"cards": list(cards)}}}
    return found


class Serial:
    def __init__(self, workers=1):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, items, chunksize=1):
        return map(function, items)


def test_your_turn_is_priced_against_the_cards_shown():
    assert sim_real_rank.spots("log", rows()) == []          # nobody showed
    ((where, observation, share),) = sim_real_rank.spots("log", shown_rows())
    assert where == {"log": "log", "hand_id": "hand_1", "row": 20}
    assert observation["actor"] == 4 and Decimal(observation["to_call"]) == 130
    assert 0.25 < share < 0.35                                 # A♦Q♦ against K♣K♦
    ((call, worth),) = sim_real_rank.decide(("always_call", [(where, observation,
                                                              share)]))
    assert call == {"action": "call"}
    assert worth == pytest.approx(chips(call, observation, share) / 4)
    assert worth < 0


def reported(cards=("Kc", "Kd"), yours="Ad Qd", start=0.0, end=2.9, log="log"):
    """A session report (``aa_session_report``) whose one hand shows ``cards``."""
    hand = {"hand_id": "hand_7", "start_pts": start, "end_pts": end,
            "your_cards": yours,
            "shown_cards": [{"seat": 0, "cards": list(cards), "actions": {}}]}
    return {"summary": {}, "hands": [{"log": log, **hand} if log else hand]}


def from_reports(tmp_path, *reports):
    paths = []
    for index, report in enumerate(reports):
        path = tmp_path / f"rec{index}.report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(path)
    return sim_real_rank.report_shown(paths)


def test_cards_read_in_another_reading_price_a_hand_that_read_none(
        tmp_path, monkeypatch):
    monkeypatch.setattr(sim_real_rank, "MIN_ALIGNED", 1)      # one deal here
    # The other reading's clock starts 500 seconds later.
    reports = from_reports(tmp_path, reported(start=500.0, end=502.9))
    ((where, observation, share),) = sim_real_rank.spots("log", rows(),
                                                         reports["log"])
    assert where == {"log": "log", "hand_id": "hand_1", "row": 20, "shown": "report"}
    ((_, _, own),) = sim_real_rank.spots("log", shown_rows())
    assert share == pytest.approx(own, abs=0.02)               # A♦Q♦ against K♣K♦
    # Other cards for you there, or nobody showed: nothing to line up or take.
    for other in (reported(yours="Ac Kc"), reported(cards=("Kc", None))):
        assert sim_real_rank.spots("log", rows(),
                                   from_reports(tmp_path, other)["log"]) == []
    # Two reported hands that both fit: neither is taken.
    assert sim_real_rank.spots("log", rows(), from_reports(
        tmp_path, reported(), reported(cards=("2c", "3d")))["log"]) == []
    monkeypatch.setattr(sim_real_rank, "MIN_ALIGNED", 2)      # too few deals
    assert sim_real_rank.spots("log", rows(), reports["log"]) == []


def test_the_clocks_line_up_on_the_usual_gap_between_deals():
    deal = [{"pts_seconds": when, "fields": {"hero": cards}} for when, cards in
            [(10.0, ["Ad", "Qd"]), (11.0, ["Ad", "Qd"]), (40.0, ["2c", "2d"]),
             (70.5, ["Kh", "Js"]), (95.0, [None, "Js"]), (99.0, ["7c", "7d"])]]
    assert [when for when, _ in sim_real_rank.deals(deal)] == [10.0, 40.0, 70.5, 99.0]
    hands = [(start, start + 20, frozenset(cards), {}) for start, cards in
             [(517.0, ("Ad", "Qd")), (548.0, ("2c", "2d")), (577.0, ("Kh", "Js")),
              (900.0, ("7c", "7d"))]]                # the last deal: a stray
    assert sim_real_rank.offset(deal, hands) == pytest.approx(-507.0)
    assert sim_real_rank.offset(deal, hands[:2]) is None      # two deals agree
    shown = {0: ["Kc", "Kd"]}
    span = [(500.0, 530.0, frozenset({"Ad", "Qd"}), shown)]
    assert sim_real_rank.shown_elsewhere(span, 528.0, ["Qd", "Ad"]) == shown
    assert sim_real_rank.shown_elsewhere(span, 534.0, ["Ad", "Qd"]) == shown
    assert sim_real_rank.shown_elsewhere(span, 536.0, ["Ad", "Qd"]) is None
    assert sim_real_rank.shown_elsewhere(span, 520.0, []) is None


def test_the_hands_own_cards_come_before_a_report(tmp_path, monkeypatch):
    monkeypatch.setattr(sim_real_rank, "MIN_ALIGNED", 1)
    reports = from_reports(tmp_path, reported(cards=("2c", "3d")))
    ((where, _, share),) = sim_real_rank.spots("log", shown_rows(), reports["log"])
    assert "shown" not in where and share < 0.35               # still K♣K♦


def test_reports_are_filed_by_their_log_and_their_file_name(tmp_path):
    unread = reported(log=None)
    unread["hands"][0]["your_cards"] = None
    reports = from_reports(tmp_path, reported(log=None), reported(log="other"),
                           reported(cards=("Ac", None), log=None), unread)
    assert set(reports) == {"rec0", "rec1", "other", "rec2"}
    ((start, end, yours, seats),) = reports["rec0"]
    assert (start, end, yours, seats) == (0.0, 2.9, frozenset({"Ad", "Qd"}),
                                          {0: ["Kc", "Kd"]})
    assert reports["rec2"][0][3] == {}               # kept to line the clocks up


def test_the_order_from_the_command_line_takes_cards_from_reports(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sim_real_rank, "ProcessPoolExecutor", Serial)
    monkeypatch.setattr(sim_real_rank, "replay", lambda found: found)
    monkeypatch.setattr(sim_real_rank, "MIN_ALIGNED", 1)
    frames = tmp_path / "rec0.frames.jsonl"
    frames.write_text("".join(json.dumps(row) + "\n" for row in rows()),
                      encoding="utf-8")
    from_reports(tmp_path, reported(log=None))                 # rec0.report.json
    sim = {"pool": ["aa_cal"], "reference": "always_call",
           "strategies": {"always_call": {}, "rfi_table": {}},
           "versus_reference": {"rfi_table": {"delta_bb_per_100": 1.0}}}
    (tmp_path / "sim.json").write_text(json.dumps(sim), encoding="utf-8")
    command = ["--sim", str(tmp_path / "sim.json"), "--frames", str(frames),
               "--out", str(tmp_path / "out")]
    sim_real_rank.main(command)
    found = json.loads((tmp_path / "out" / "rank.json").read_text(encoding="utf-8"))
    assert (found["turns"], found["turns_from_reports"]) == (0, 0)
    sim_real_rank.main([*command, "--shown", str(tmp_path / "rec0.report.json")])
    found = json.loads((tmp_path / "out" / "rank.json").read_text(encoding="utf-8"))
    assert (found["turns"], found["turns_from_reports"]) == (1, 1)
    assert "1 priced from reports" in capsys.readouterr().out


def test_table_actions_read_as_answers():
    observation = sim_real_rank.spots("log", shown_rows())[0][1]
    raises = [item for item in observation["legal_actions"]
              if item["kind"] == "raise_to"]
    assert sim_real_rank.answer(observation, "fold") == {"action": "fold"}
    assert sim_real_rank.answer(observation, "check_call") == {"action": "call"}
    assert sim_real_rank.answer(observation, raises[0]["id"]) == {
        "action": "raise", "to": raises[0]["raise_to"]}
    # A size of the strategy's own, not among the listed ones.
    assert "raise_to:333" not in {item["id"] for item in observation["legal_actions"]}
    picked = sim_real_rank.answer(observation, "raise_to:333")
    assert picked == {"action": "raise", "to": "333"}
    assert chips(picked, observation, 0.3) is not None


def test_kendall_counts_pairs_in_the_same_and_the_other_order():
    assert sim_real_rank.kendall([(1, 1), (2, 2), (3, 3)]) == (1.0, 3, 0)
    assert sim_real_rank.kendall([(1, 3), (2, 2), (3, 1)]) == (-1.0, 0, 3)
    assert sim_real_rank.kendall([(1, 1), (2, 1)]) == (0.0, 0, 0)
    assert sim_real_rank.kendall([(1, 1)]) == (None, 0, 0)


def ranked(monkeypatch, variants, shown, turns=40, differ=40):
    """``rank`` with each variant worth ``shown[name]`` more than the reference
    on each of ``differ`` turns (and answering otherwise there)."""
    def decide(job):
        name, found = job
        return [({"action": name if index < differ and name != "ref" else "ref"},
                 shown.get(name, 0.0) / differ if index < differ else 0.0)
                for index in range(len(found))]

    monkeypatch.setattr(sim_real_rank, "ProcessPoolExecutor", Serial)
    monkeypatch.setattr(sim_real_rank, "decide", decide)
    sim = {"reference": "ref", "pool": ["aa_cal"],
           "strategies": {name: {} for name in ["ref", *variants]},
           "versus_reference": {name: {"delta_bb_per_100": gain}
                                for name, gain in variants.items()}}
    return sim_real_rank.rank(sim, [({}, None, None)] * turns)


def test_the_same_order_agrees(monkeypatch):
    variants = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, variants, {name: gain * 2 for name, gain
                                            in variants.items()})
    assert result["verdict"] == "agree" and result["tau"] == 1.0
    assert result["variants"]["v3"] == {"sim": 3.0, "shown": 6.0, "differ": 40}
    assert result["turns_differ"] == 40
    assert "agree (tau +1.00" in sim_real_rank.summary(result)


def test_the_other_order_disagrees(monkeypatch):
    variants = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, variants, {name: -gain for name, gain
                                            in variants.items()})
    assert result["verdict"] == "disagree" and result["tau"] == -1.0


def test_too_few_variants_or_turns_are_not_enough(monkeypatch):
    few = {f"v{index}": float(index) for index in range(1, 4)}
    assert ranked(monkeypatch, few, few)["verdict"] == "not enough data"
    many = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, many, many, differ=10)
    assert result["verdict"] == "not enough data" and result["tau"] == 1.0


def hand(log, hand_id, adjusted, followed="yes", machine=None):
    line = {"log": log, "hand_id": hand_id, "adjusted": adjusted, "followed": followed}
    return {**line, "machine": machine} if machine else line


def test_only_hands_played_as_advised_without_a_rough_advice_count():
    hands = [hand("a", "h1", 1.0), hand("a", "h2", 2.0, followed="no"),
             hand("a", "h3", 3.0, followed="no_advice"), hand("a", "h4", 4.0),
             hand("b", "h4", 5.0, machine="du")]
    decisions = [{"log": "a", "hand_id": "h4", "kind": "multiway"},
                 {"log": "a", "hand_id": "h4", "kind": "rough"},
                 {"log": "b", "hand_id": "h4", "kind": "preflop", "machine": "du"}]
    assert sim_real_rank.advised(hands, decisions) == [1.0, 5.0]


def leveled(sim_value, values):
    sim = {"pool": ["aa_cal"],
           "strategies": {sim_real_rank.LIVE: {"bb_per_100": sim_value,
                                               "ci95": [sim_value - 30,
                                                        sim_value + 30]}}}
    return sim_real_rank.level(sim, values)


def test_a_simulation_above_the_real_interval_is_too_optimistic():
    values = [-30.0, 25.0] * 200                  # -2.5 bb a hand, spread 27.5
    result = leveled(173.2, values)
    assert result["hands"] == 400 and result["real"] == -250.0
    low, high = result["real_ci95"]
    assert low < -250 < high < 173.2
    assert result["verdict"] == "sim too optimistic"
    wide = result["always_valid_ci95"]
    assert wide[0] < low and wide[1] > high       # the lasting one is wider
    assert result["outside_always_valid"] is (173.2 > wide[1])
    line = sim_real_rank.level_summary(result)
    assert line.startswith("sim vs real level: sim too optimistic (sim +173.2")
    assert "400 hands played as advised" in line


def test_inside_below_and_too_few_hands():
    values = [-30.0, 25.0] * 200
    assert leveled(-250.0, values)["verdict"] == "inside"
    assert leveled(-900.0, values)["verdict"] == "sim too pessimistic"
    few = leveled(173.2, values[:150])
    assert few["verdict"] == "not enough data" and few["real_ci95"] is None
    assert "not enough data" in sim_real_rank.level_summary(few)
    with pytest.raises(SystemExit):
        sim_real_rank.level({"strategies": {}}, values)


def test_the_level_alone_from_the_command_line(tmp_path, capsys):
    sim = {"pool": ["aa_cal"], "reference": "aa_preflop",
           "strategies": {sim_real_rank.LIVE: {"bb_per_100": 173.2,
                                               "ci95": [142.5, 203.8]}}}
    (tmp_path / "sim.json").write_text(json.dumps(sim), encoding="utf-8")
    lines = [hand("a", f"h{index}", value)
             for index, value in enumerate([-30.0, 25.0] * 150)]
    (tmp_path / "hands.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    (tmp_path / "decisions.jsonl").write_text("", encoding="utf-8")
    sim_real_rank.main(["--sim", str(tmp_path / "sim.json"),
                        "--real-hands", str(tmp_path / "hands.jsonl"),
                        "--real-decisions", str(tmp_path / "decisions.jsonl"),
                        "--out", str(tmp_path / "out")])
    assert "sim too optimistic" in capsys.readouterr().out
    found = json.loads((tmp_path / "out" / "level.json").read_text(encoding="utf-8"))
    assert found["hands"] == 300 and not (tmp_path / "out" / "rank.json").exists()
    with pytest.raises(SystemExit):
        sim_real_rank.main(["--sim", str(tmp_path / "sim.json")])
