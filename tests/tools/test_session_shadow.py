"""分量账本: both strategies replayed offline, divergences booked with a fold
worth 0 (made-up hands only: the repository is public)."""

import json
from decimal import Decimal

from tools import session_package as package
from tools import session_shadow as shadow

from tests.tools.test_session_package import rows


def test_only_the_hands_v33_adds_count_as_loosened():
    assert "K8o" in shadow.LOOSENED["late_limp"]
    assert "K9o" not in shadow.LOOSENED["late_limp"]       # v3.2 had it
    assert "K7o" in shadow.LOOSENED["bb_complete"]
    assert "Q6s" in shadow.LOOSENED["sb_complete"]
    assert "AA" not in set().union(*shadow.LOOSENED.values())


def test_from_here_counts_back_to_the_decision_and_on_to_the_next_posts():
    hand = {"chips": "-38", "start": "200", "big_blind": "2"}
    assert shadow.from_here({"your_stack": "200"}, hand, Decimal(2)) == (-18.0, None)
    assert shadow.from_here({"your_stack": "184"}, hand, Decimal(2)) == (-10.0, None)
    busted = {"chips": "-200", "start": "200", "big_blind": "2"}
    assert shadow.from_here({"your_stack": "150"}, busted, None) == (-75.0, None)
    assert shadow.from_here({"your_stack": "200"}, hand, None)[0] is None
    unfinished = {**hand, "chips": None}
    assert shadow.from_here({"your_stack": "200"}, unfinished, 2)[0] is None


def test_a_line_is_worth_0_folded_what_you_got_played_and_nothing_else():
    assert shadow.worth("fold", "call", -5.0) == 0.0
    assert shadow.worth("call", "call", -5.0) == -5.0
    assert shadow.worth("raise", "call", -5.0) is None
    assert shadow.worth("call", None, None) is None


def side(action, chips=None):
    return {"action": action, "chips": chips, "to": chips, "rule": None}


def test_the_three_groups():
    deep = {"street": "flop", "your_stack": "150", "effective_bb": 75.0}
    assert shadow.group_of(deep, side("raise", "150"), side("fold")) == "c_old_allin"
    shallow = {**deep, "effective_bb": 30.0}
    assert shadow.group_of(shallow, side("raise", "150"), side("fold")) == (
        "b_postflop_plain_fold")
    assert shadow.group_of(deep, side("raise", "60"), side("call")) == "other"
    before = {"street": "preflop", "your_stack": "200", "effective_bb": 100.0}
    assert shadow.group_of(before, side("call"), side("fold")) == "a_preflop_old_in"
    assert shadow.group_of(before, side("fold"), side("call")) == "other"
    assert shadow.entered("c_old_allin", "call") is False
    assert shadow.entered("a_preflop_old_in", "call") is True
    assert shadow.entered("b_postflop_plain_fold", None) is None


def test_the_loosened_spots_by_seat_rule_and_hand():
    late = {"street": "preflop", "position": "late", "seat_name": "BTN",
            "hero": "Kh 8d"}
    assert shadow.loosened(late, {"rule": "T1.limp"}) == "late_limp"
    assert shadow.loosened(late, {"rule": "T1.out"}) == "late_limp"   # v3.2 folds it
    assert shadow.loosened(late, {"rule": "T2.call"}) is None         # facing a raise
    assert shadow.loosened({**late, "hero": "Kh 9d"}, {"rule": "T1.limp"}) is None
    assert shadow.loosened({**late, "street": "flop"}, {"rule": "T1.limp"}) is None
    big = {"street": "preflop", "position": "blind", "seat_name": "BB", "hero": "Kh 7d"}
    assert shadow.loosened(big, {"rule": "T1.a"}) == "bb_complete"
    small = {**big, "seat_name": "SB", "hero": "Qh 6h"}
    assert shadow.loosened(small, {"rule": "T1.a.fold"}) == "sb_complete"
    assert shadow.loosened(small, None) is None


# -- the whole block on made-up hands ---------------------------------------------

def ready(action, chips=None, rule=None):
    report = {"status": "ready", "kind": "plain" if rule else "multiway",
              "advice": [{"action": action, "to": chips, "chips": chips}]}
    if rule:
        report["plain"] = {"rule": rule}
    return report


# (street, your stack, effective bb, cards, position, seat, old, plain, you did)
SPOTS = [
    [("preflop", "200", 100.0, "Ah Td", "early", "UTG", ready("call"),
      ready("fold", rule="T2.out"), "call"),
     ("flop", "180", 90.0, "Ah Td", "early", "UTG", ready("call"),
      ready("fold", rule="R.CE"), "call")],
    [("flop", "150", 75.0, "Qh Qd", "middle", "MP", ready("raise", "150"),
      ready("call", rule="F.C"), "fold")],
    [("preflop", "200", 100.0, "Kh 8d", "late", "BTN", ready("fold"),
      ready("call", rule="T1.limp"), "call")],
    [("turn", "120", 60.0, "9h 9d", "late", "CO", ready("call"),
      ready("fold", rule="R.CE"), "call")],
]
# Each hand's result on the sheet, its start, and the luck after an all-in.
SHEET = [("-38", "200", 0.0), ("-52", "200", 0.0), ("10", "200", 1.5),
         ("-122", "200", None)]


BOARDS = {"preflop": [None] * 5, "flop": ["2c", "7d", "9s", None, None],
          "turn": ["2c", "7d", "9s", "Jh", None]}


def made_block(monkeypatch, spot=lambda *_: None):
    log, hands, old, plain = [], [], [], []
    for spots, (chips, start, runout) in zip(SPOTS, SHEET):
        hand_rows, turns, decisions = [], [], []
        for street, mine, deep, cards, place, seat, one, two, you in spots:
            row = {"fields": {"board": BOARDS[street]}}
            log.append(row)
            hand_rows.append(row)
            old.append(one)
            plain.append(two)
            turns.append([(row, two)])
            decisions.append({"street": street, "your_stack": mine,
                              "effective_bb": deep, "hero": cards, "position": place,
                              "seat_name": seat, "button": "call", "to_call": "4",
                              "you_did": you})
        hands.append({"hand_id": f"h{len(hands)}", "rows": hand_rows, "turns": turns,
                      "decisions": decisions, "stakes": {"big_blind": "2"},
                      "chips": chips, "start": start,
                      "luck": {"runout": runout, "allin": runout is None}})
    tail = {"fields": {}}
    log.append(tail)
    old.append(None)
    plain.append(None)
    hands.append({"hand_id": "h4", "rows": [tail], "turns": [], "decisions": [],
                  "stakes": {"big_blind": "2"}, "chips": None, "start": None,
                  "luck": None})
    monkeypatch.setattr(shadow, "replays", lambda _: {"old": old, "plain": plain})
    monkeypatch.setattr(shadow, "posts", lambda *_: Decimal(2))
    monkeypatch.setattr(shadow, "shown_spot", spot)
    return shadow.block(log, hands, code="abcdef1", page_version="v3.3")


def test_each_hand_books_its_first_divergence_in_its_group(monkeypatch):
    block = made_block(monkeypatch)
    items = block["decisions"]
    assert [item["group"] for item in items] == [
        "a_preflop_old_in", None, "c_old_allin", "other", "b_postflop_plain_fold"]
    assert [item["from_here_bb"] for item in items] == [-18.0, -8.0, 0.0, 6.0, -20.0]
    first, second, allin, limp, turn = items
    assert first["in_minus_fold_bb"] == -18.0 and first["booked"]["diff_bb"] == 18.0
    assert second["agree"] is False and second["booked"] is None   # after the first
    assert allin["entered"] is False and allin["in_minus_fold_bb"] is None
    assert limp["loosened"] == "late_limp" and limp["in_minus_fold_bb"] == 6.0
    assert limp["in_minus_fold_luck_out_bb"] == 4.5                # 1.5 of runout luck
    assert turn["in_minus_fold_bb"] == -20.0
    assert turn["in_minus_fold_luck_out_bb"] is None               # luck not worked out
    top = block["summary"]
    assert top["page_version"] == "v3.3" and top["replay_code"] == "abcdef1"
    assert top["first_divergences"] == 4 and top["diverged"] == 5
    assert top["groups"]["a_preflop_old_in"]["in_minus_fold_bb"] == -18.0
    assert top["groups"]["c_old_allin"]["you_folded"] == 1
    assert top["groups"]["b_postflop_plain_fold"]["luck_out_booked"] == 0
    assert top["loosened"]["late_limp"] == {
        "n": 1, "entered": 1, "booked": 1, "in_minus_fold_bb": 6.0,
        "in_minus_fold_luck_out_bb": 4.5, "luck_out_booked": 1, "plain_enters": 1}
    assert top["fold_check"] == {"n": 1, "off": 0}
    assert top["replay_matches_shown"] == {"n": 5, "same": 5}
    assert top["shown_by"] == {"plain": 5}


def test_p3_counts_the_folds_that_met_a_pair_or_a_bluff(monkeypatch):
    shown = {"h0": {"3": "9h 9c"}, "h3": {"5": "Ah Kd"}}      # a set; nothing
    monkeypatch.setattr(shadow, "chips", lambda *_: 3.0)
    block = made_block(monkeypatch, spot=lambda rows, indexes, hand: (
        None, 0.5, shown[hand]) if hand in shown else None)
    weak = [item["plain_fold_weak_shown"] for item in block["decisions"]]
    assert weak == [None, False, None, None, True]  # only plain's folds after the flop
    assert block["summary"]["plain_fold_shown"] == {
        "n": 2, "weak": 1, "diverged": 2, "diverged_weak": 1}


def test_a_pair_on_the_board_is_not_the_opponents():
    rows = [{"fields": {"board": ["Ks", "Kd", "4c", None, None]}},
            {"fields": {"board": ["Ks", "Kd", "4c", "9h", "2s"]}}]
    assert shadow.weak_shown((None, 0.5, {"3": "Qh 9d"}), rows) is True   # 9s up
    assert shadow.weak_shown((None, 0.5, {"3": "Kh 3d"}), rows) is False  # trips
    assert shadow.weak_shown((None, 0.5, {"3": "Kh 3d", "5": "7c 6c"}), rows) is False
    assert shadow.weak_shown(None, rows) is None
    assert shadow.weak_shown((None, 0.5, {"3": "Qh 9d"}), rows[:0]) is None


# -- in the package -------------------------------------------------------------------

def whole(tmp_path):
    """The made-up session with every hand seen from its start and the post of
    the next hand taken off your stack."""
    log = rows()
    for item in log:
        fields = item["fields"]
        fields["actions_v1"]["complete"] = True
        if fields["actions_v1"]["hand_id"] == "hand_2":
            fields["stacks"]["4"] = "162"
    folder = tmp_path / "20261016-200000-live"
    folder.mkdir()
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in log) + "\n", encoding="utf-8")
    return folder


def test_the_package_keeps_the_ledger_and_folding_comes_to_0(tmp_path):
    found = package.build(whole(tmp_path), settings={"machine": "m", "player": "p"})
    assert "shadow" not in found["nulls"]
    block = found["shadow"]
    assert [item["from_here_bb"] for item in block["decisions"]] == [
        -18.0, -10.0, 0.0, 0.0]
    assert block["summary"]["decisions"] == 4
    assert block["summary"]["old_without_solver"] is True
    assert "弃 = 0" in block["summary"]["convention"]


def test_the_rest_of_the_package_stands_when_the_replay_fails(tmp_path, monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("坏了")
    monkeypatch.setattr(shadow, "block", broken)
    found = package.build(whole(tmp_path), settings={"machine": "m", "player": "p"})
    assert found["shadow"] is None
    assert found["nulls"]["shadow"] == "影子重放没做成：RuntimeError: 坏了"
    assert len(found["decisions"]) == 4
