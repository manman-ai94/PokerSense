"""定生死的那一条“至今的命中数和战绩”（``aa_rule_record``）：规则键和场次包同一个
哈希；之前各场从账本加起来，本场每个决策只算一次；建议本身不变。"""

import json

from poker_engine.desktop.aa_rule_record import RuleRecord, rule_keys, totals
from poker_engine.desktop.aa_session import frame_summary
from poker_engine.scoreboard import plain_policy
from tools import session_package as package

KEYS = {"T2.call": "T2.call#aaaa", "I5": "I5#bbbb"}


def advice(rule="T2.call", decision=3, hand="hand_0", **extra):
    return {"status": "ready", "kind": "plain", "hand_id": hand, "decision": decision,
            "advice": [{"action": "call"}], "plain": {"rule": rule, "hits": [rule]},
            **extra}


def ledger(tmp_path, *sessions):
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps({"label": f"s{i}", "rules": rules}) + "\n"
                            for i, rules in enumerate(sessions)) + "not json\n",
                    encoding="utf-8")
    return path


def test_a_rule_key_is_the_session_package_s_hash():
    page = package.versions(plain_policy, None)["page"]
    keys = rule_keys()
    assert set(keys) == set(plain_policy.RULES)
    for rule, item in page["rules"].items():
        assert keys[rule] == f"{rule}#{item['sha256']}"


def test_the_record_adds_the_ledger_and_this_session(tmp_path):
    path = ledger(tmp_path,
                  {"T2.call#aaaa": {"hits": 4, "hands": 3, "bb": -6.5}},
                  {"T2.call#aaaa": {"hits": 2, "hands": 2, "bb": 9.0},
                   "T2.call#old0": {"hits": 50, "hands": 40, "bb": 99.0}},
                  {})
    record = RuleRecord(path, keys=KEYS)
    shown = record(advice())
    assert shown["plain"]["rule_key"] == "T2.call#aaaa"
    assert shown["plain"]["record"] == {"hits": 7, "session": 1, "sessions": 2,
                                        "hands": 5, "bb": 2.5}
    # The same decision, frame after frame: counted once.
    assert record(advice())["plain"]["record"]["hits"] == 7
    # The next decision the same rule decides: once more.
    assert record(advice(decision=5))["plain"]["record"] == {
        "hits": 8, "session": 2, "sessions": 2, "hands": 5, "bb": 2.5}
    # A rule nobody had before: this session only.
    assert record(advice("I5", decision=6))["plain"]["record"] == {
        "hits": 1, "session": 1, "sessions": 0, "hands": 0, "bb": 0.0}


def test_the_advice_itself_does_not_change(tmp_path):
    record = RuleRecord(tmp_path / "none.jsonl", keys=KEYS)
    before = advice()
    after = record(before)
    assert after["advice"] == before["advice"] and "record" not in before["plain"]
    assert {key: value for key, value in after["plain"].items()
            if key not in ("rule_key", "record")} == before["plain"]
    for other in (None, {"status": "reading", "kind": "plain"},
                  {"status": "ready", "kind": "multiway", "advice": []},
                  advice("X9"), {"status": "ready", "kind": "plain"}):
        assert record(other) is other


def test_a_new_observation_counts_from_zero_and_reads_the_ledger_again(tmp_path):
    path = ledger(tmp_path, {"T2.call#aaaa": {"hits": 1, "hands": 1, "bb": 1.0}})
    record = RuleRecord(path, keys=KEYS)
    assert record(advice())["plain"]["record"]["hits"] == 2
    # This session's sheet goes into the ledger after the recording stops:
    # it counts from the next start, not twice now.
    now = {"label": "now", "rules": {"T2.call#aaaa": {"hits": 1, "hands": 1,
                                                      "bb": -3.0}}}
    path.write_text(path.read_text(encoding="utf-8") + json.dumps(now) + "\n",
                    encoding="utf-8")
    assert record(advice(decision=4))["plain"]["record"]["hits"] == 3
    record.reset()
    assert record(advice())["plain"]["record"] == {
        "hits": 3, "session": 1, "sessions": 2, "hands": 2, "bb": -2.0}


def test_totals_skip_what_does_not_read():
    assert totals([{"rules": None}, {"rules": {"A#1": "x"}}, {},
                   {"rules": {"A#1": {"hits": 2}}}]) == {
        "A#1": {"hits": 2, "hands": 0, "bb": 0.0, "sessions": 1}}


def test_the_frame_log_keeps_the_key_not_the_record(tmp_path):
    shown = RuleRecord(tmp_path / "none.jsonl", keys=KEYS)(advice())
    logged = frame_summary({"solver_advice_v1": shown})["solver_advice"]
    assert logged["plain"]["rule_key"] == "T2.call#aaaa"
    assert "record" not in logged["plain"] and "record" in shown["plain"]
