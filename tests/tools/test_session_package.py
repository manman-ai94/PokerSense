"""场次包: one session as evidence an AI can read, from a made-up frame log
(no real hands: the repository is public)."""

import json
import re

import pytest

from poker_engine.scoreboard import plain_policy
from tools import session_package as package

PAGE = re.search(r"v\d+(?:\.\d+)*", plain_policy.__doc__).group(0)   # 一页纸现在的版本

# Six players at 1/2/4, dealer 5: small blind 0, big blind 1, straddle 2;
# seat 3 acts first. You (seat 4) hold Ah Kd. Seat 3 raises to 16, you
# call; seat 3 bets the flop, you call; both check the turn and the river
# and seat 3 shows queens. Seat 5's fold was put in from the chips (no badge
# was read for it).
ACTIONS = [
    (10, "preflop", 3, "raise", "16", "wager"),
    (13, "preflop", 4, "call", "16", "wager"),
    (14, "preflop", 5, "fold", "0", "street_logic"),
    (16, "preflop", 0, "fold", "0", "wager"),
    (18, "preflop", 1, "fold", "0", "wager"),
    (20, "preflop", 2, "fold", "0", "wager"),
    (30, "flop", 3, "bet", "20", "wager"),
    (33, "flop", 4, "call", "20", "wager"),
    (40, "turn", 3, "check", "0", "wager"),
    (43, "turn", 4, "check", "0", "wager"),
    (50, "river", 3, "check", "0", "wager"),
    (53, "river", 4, "check", "0", "wager"),
]
BADGE = {14}                      # frames whose action no badge was read for
BOARD = ["Qh", "8d", "3c", "2s", "Jd"]
SHOWN = {"3": {"cards": ["Qs", "Qc"], "frame": 55}}
CODE = {"version": "0.1.0", "commit": "abcdef1234", "dirty": False}


def plain(rule, action, **extra):
    row = {"action": action, "rule": rule, "rule_label": plain_policy.RULES[rule],
           "hits": [rule], "reason": f"理由 {rule}", "flip": "翻转条件",
           "range": "前 12%", "equity": 0.41, "need": 0.29, "tier": "C",
           "tag": "就绪 0.4s", "waited": 0.4, "defaults": []}
    row.update(extra)
    return {"status": "ready", "kind": "plain", "advice": [{"action": action}],
            "plain": row}


# Your turns: (first frame, last frame, street, price, button, advice).
TURNS = [(11, 13, "preflop", "12", "call", plain("T2.call", "call")),
         (31, 33, "flop", "20", "call", plain("F.C", "call")),
         (41, 43, "turn", None, "check", plain("N.C", "check")),
         (51, 53, "river", None, "check",
          {"status": "ready", "kind": "plain", "advice": [{"action": "check"}],
           "plain": {"action": "check", "rule": "I5", "hits": ["I5"],
                     "unread": "pot", "missing": ["pot"], "tag": "铁律 5：缺底池",
                     "waited": 1.2, "unspecified": None}})]


def street_at(frame):
    return ("river" if frame >= 50 else "turn" if frame >= 40
            else "flop" if frame >= 30 else "preflop")


def rows(hand="hand_1"):
    """The hand frame by frame, then the first frames of the next one (the
    hand is over: its result is read from your stack)."""
    result = []
    pots = {"preflop": "19", "flop": "51", "turn": "91", "river": "91"}
    for frame in range(66):
        if frame >= 62:
            result.append(next_hand(frame))
            continue
        done = [list(a) for a in ACTIONS if a[0] <= frame]
        street = street_at(frame)
        board = BOARD[:{"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]]
        paid = {seat: sum(int(a[4]) for a in ACTIONS if a[0] <= frame and a[2] == seat)
                for seat in range(6)}
        folded = {a[2] for a in ACTIONS if a[0] <= frame and a[3] == "fold"}
        turn = next((t for t in TURNS if t[0] <= frame <= t[1]), None)
        advice = turn[5] if turn else {"status": "idle", "reason": "not_your_turn"}
        if turn and frame == turn[0] and turn[2] == "preflop":
            advice = {"status": "reading", "kind": "plain", "reason": "steady"}
        fields = {
            "scene_supported": True, "hero": ["Ah", "Kd"], "street": street,
            "pot": None if street == "river" else pots[street],
            "dealer": 5,
            "participants": {str(seat): "folded" if seat in folded else "active"
                             for seat in range(6)},
            "board": board + [None] * (5 - len(board)),
            "stacks": {str(seat): str(200 - paid[seat]) for seat in range(6)},
            "hero_controls": ({"visible": True, "button": turn[4],
                               "call_amount": turn[3]} if turn
                              else {"visible": False}),
            "actions_tail": [{"frame": a[0], "slot": a[2], "kind": a[3]}
                             for a in ACTIONS if a[0] <= frame and a[0] not in BADGE],
            "actions_v1": {"hand_id": hand, "complete": frame >= 55,
                           "start": "pot_went_down", "dealer": 5, "actions": done},
            "solver_advice": advice}
        if frame >= 55:
            fields["shown_cards"] = {"hand_id": hand, "seats": SHOWN, "unknown": []}
        item = {"processed": frame, "pts_seconds": frame / 10,
                "video_seconds": 100.0 + frame / 10, "fields": fields}
        if frame == 0:
            item["code"] = CODE
        result.append(item)
    return result


def next_hand(frame):
    """Seat 3 took the pot; a new hand is dealt to you."""
    stacks = {str(seat): "200" for seat in range(6)} | {"3": "255", "4": "164"}
    return {"processed": frame, "pts_seconds": frame / 10,
            "video_seconds": 100.0 + frame / 10,
            "fields": {"scene_supported": True, "hero": ["7c", "2d"],
                       "street": "preflop", "pot": "19", "dealer": 0,
                       "participants": {str(seat): "active" for seat in range(6)},
                       "board": [None] * 5, "stacks": stacks,
                       "hero_controls": {"visible": False}, "actions_tail": [],
                       "actions_v1": {"hand_id": "hand_2", "complete": False,
                                      "start": "pot_went_down", "dealer": 0,
                                      "actions": []},
                       "solver_advice": {"status": "idle"}}}


@pytest.fixture
def built(tmp_path):
    folder = tmp_path / "20261016-200000-live"
    folder.mkdir()
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows()) + "\n", encoding="utf-8")
    (folder / "recording.json").write_text(json.dumps(
        {"started": "2026-10-16T20:00:00-0700", "recorded_seconds": 600.0}),
        encoding="utf-8")
    settings = {"machine": "peng-mac", "player": "peng"}
    return folder, package.build(folder, settings=settings)


def test_the_session_says_who_played_where_and_with_what_code(built):
    folder, found = built
    assert found["schema"] == "pokersense.session_package" and found["format"] == 1
    session = found["session"]
    assert session["label"] == folder.name and session["machine"] == "peng-mac"
    assert session["code"] == CODE and session["spectate"] is False
    assert session["started"] == "2026-10-16T20:00:00-0700"
    assert session["decisions"] == 4
    identity = found["identity"]
    assert identity["player"] == "peng" and identity["machine"] == "peng-mac"
    assert identity["opponents"] is None and "昵称" in found["nulls"][
        "identity.opponents"]


def test_one_line_a_decision_with_the_advice_and_what_you_did(built):
    _, found = built
    first, flop, turn, river = found["decisions"]
    assert [d["street"] for d in found["decisions"]] == [
        "preflop", "flop", "turn", "river"]
    assert first["advice"]["rule"] == "T2.call" and first["advice"]["action"] == "call"
    assert first["advice"]["reason"] == "理由 T2.call"
    assert (first["advice"]["equity"], first["advice"]["need"]) == (0.41, 0.29)
    assert first["advice"]["flip"] == "翻转条件"
    assert first["you_did"] == "call" and first["followed"] is True
    assert first["ready_waited"] == 0.4 and first["iron5"] is False
    assert first["advice_before_action"] is True
    assert first["deviation_reason"] is None
    assert river["iron5"] is True and river["missing"] == ["pot"]
    assert river["pot_missing"] is True
    assert flop["opponents"] == 1


def test_shown_cards_carry_the_range_and_where_the_hand_sits_in_it(built):
    _, found = built
    (shown,) = found["shown"]
    assert shown["seat"] == 3 and shown["cards"] == ["Qs", "Qc"]
    assert shown["how"] == "showdown" and shown["calibrates"] is True
    reading = shown["range"]
    assert reading["class"] == "raise"
    assert 0.0 <= reading["percentile"] <= 1.0
    # Checks keep the range as it is (section 4 cuts at a call, bet or raise).
    assert [(step["street"], step["action"]) for step in reading["steps"]] == [
        ("flop", "bet")]
    assert reading["in"] is True
    assert shown["actions"] == {"preflop": ["raise"], "flop": ["bet"],
                                "turn": ["check"], "river": ["check"]}


def test_the_denominators_count_the_seats_that_never_showed(built):
    _, found = built
    counts = found["shown_denominators"]
    assert counts["raise"] == {"seats": 1, "showdown": 1}
    # Hand 1: seats 0, 1, 2 and 5 folded before putting chips in; hand 2 is
    # not seen from its start (and the log ends in it).
    assert counts["none"] == {"seats": 9, "folded": 4, "late": 5}


def test_misreads_count_the_inferred_actions_and_missing_numbers(built):
    _, found = built
    misreads = found["misreads"]
    assert misreads["counts"]["actions_inferred_from_chips"] == 1
    assert misreads["counts"]["pot_missing"] == 1


def test_rule_hits_and_timing(built):
    _, found = built
    assert found["rule_hits"]["rules"]["T2.call"]["hits"] == 1
    timing = found["timing"]
    assert timing["decisions"] == 4 and timing["no_advice"] == 0
    assert timing["changes_of_mind"] == 0


def test_versions_hash_each_rule_with_the_pages_numbers(built, monkeypatch):
    _, found = built
    page = found["versions"]["page"]
    assert page["version"] == PAGE
    before = page["rules"]["T2.call"]
    assert before["text"] == plain_policy.RULES["T2.call"]
    monkeypatch.setattr(plain_policy, "PRICE_SHARE", 0.2)
    after = package.versions(plain_policy, CODE)["page"]["rules"]["T2.call"]
    assert after["label_sha256"] == before["label_sha256"]
    assert after["sha256"] != before["sha256"]       # another number: another rule
    assert set(found["versions"]["opponent_models"]) == set(package.MODELS)


def test_each_hand_is_one_replayable_record(built):
    _, found = built
    hand = found["hands"][0]
    assert hand["your_cards"] == ["Ah", "Kd"] and hand["board"] == BOARD
    assert hand["dealer"] == 5
    inferred = [a for a in hand["actions"] if a["inferred"]]
    assert [(a["seat"], a["kind"]) for a in inferred] == [(5, "fold")]
    assert hand["shown"] == {"3": ["Qs", "Qc"]}


def test_written_whole_into_the_flywheel_folder(built):
    folder, found = built
    path = package.write(folder, found)
    assert path == folder / "flywheel" / "package.json"
    assert json.loads(path.read_text(encoding="utf-8"))["session"]["decisions"] == 4
    assert not list((folder / "flywheel").glob("*.part"))


def test_a_watched_table_is_marked_spectating(tmp_path):
    folder = tmp_path / "20261016-210000-live"
    folder.mkdir()
    watched = []
    for item in rows():
        fields = item["fields"]
        fields["hero"] = [None, None]
        fields["hero_controls"] = {"visible": False}
        fields["solver_advice"] = {"status": "idle"}
        fields["stacks"].pop("4", None)
        watched.append(item)
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in watched) + "\n", encoding="utf-8")
    found = package.build(folder, settings={"machine": "du", "player": ""})
    assert found["session"]["spectate"] is True and found["decisions"] == []
    assert found["identity"]["player"] == "du"         # the machine's name
    assert found["shown"][0]["cards"] == ["Qs", "Qc"]


def test_the_window_writes_the_sheet_then_the_package(built, capsys, monkeypatch):
    folder, _ = built
    monkeypatch.setattr(package.os, "nice", lambda step: 0, raising=False)
    assert package.main(["--recording", str(folder), "--with-sheet",
                         "--no-ledger"]) == 0
    assert (folder / "flywheel" / "体检单.txt").exists()
    found = json.loads((folder / "flywheel" / "package.json").read_text(
        encoding="utf-8"))
    assert found["rule_hits"]["from"].startswith("flywheel/summary.json")
    assert "package.json" in capsys.readouterr().out


def test_the_hand_the_log_ends_in_counts_as_unfinished(tmp_path):
    folder = tmp_path / "20261016-220000-live"
    folder.mkdir()
    cut = rows()
    for item in cut:
        history = item["fields"]["actions_v1"]
        if history["hand_id"] == "hand_2":
            history["complete"] = True          # seen from its start
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in cut) + "\n", encoding="utf-8")
    found = package.build(folder, settings={"machine": "du", "player": ""})
    assert found["shown_denominators"]["none"] == {"seats": 9, "folded": 4,
                                                   "unfinished": 5}
