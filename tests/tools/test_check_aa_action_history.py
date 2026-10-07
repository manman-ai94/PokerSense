"""Betting-history checks on a synthetic measurement log."""

from tools.check_aa_action_history import compare, pot_step, rebuild, rebuilt, summarize


def row(processed, source, pot, street, actions=()):
    return {"processed": processed, "source_frame": source,
            "pts_seconds": processed / 10,
            "fields": {"pot": pot, "street": street, "actions_tail": list(actions)}}


CALL = {"frame": 5, "slot": 3, "kind": "call", "amount": None, "street": "preflop",
        "epoch": "deal_1", "status": "OBSERVED_GLYPH"}
RAISE = {"frame": 12, "slot": 4, "kind": "aggressive", "amount": "30",
         "street": "river", "epoch": "deal_1",
         "status": "OBSERVED_GLYPH_CASH_CANDIDATE"}


def log():
    rows = []
    for frame in range(20):
        pot = "23" if frame < 4 else "27" if frame < 11 else "57"
        street = "preflop" if frame < 10 else "flop"
        seen = [CALL] if frame >= 5 else []
        seen += [RAISE] if frame >= 12 else []
        rows.append(row(frame, frame * 3, pot, street, seen[-3:]))
    return rows


def test_actions_are_rebuilt_once_in_order():
    actions = rebuild(log())
    assert [(a["slot"], a["kind"]) for a in actions] == [(3, "call"), (4, "aggressive")]


def test_amounts_come_from_the_pot_rise_next_to_the_action():
    by_frame = {r["processed"]: r for r in log()}
    assert str(pot_step(by_frame, 5)) == "4"        # the pot rose just before the badge
    assert str(pot_step(by_frame, 12)) == "30"


def test_summary_and_rebuild_report_streets_and_amounts():
    summary = summarize(log())
    assert summary["priced_actions"] == 2 and summary["priced_with_amount"] == 1
    assert summary["street_disagreement_pairs"] == {"river->flop": 1}
    assert rebuilt(log()) == {"hands": 1, "actions": 2, "priced_actions": 2,
                              "priced_with_amount": 2}


def test_a_labelled_hand_is_compared_action_by_action():
    label = {"streets": [
        {"street": "preflop", "actions": [
            {"slot": 3, "kind": "call", "debit": "4", "window": [9, 15]}]},
        {"street": "river", "actions": [
            {"slot": 4, "kind": "raise", "debit": "30", "window": [33, 36]}]}]}
    report = compare(log(), label)
    assert report["matched_in_order"] == 2 and report["differences"] == []
    assert report["amounts"] == {"missing": 1, "correct": 1}


def v1_log():
    """A rebuilt hand: the blinds go in (pot 0 -> 23), seat 3 calls 4 (23 -> 27),
    then the pot rises by 30 with no action, and seat 6 shows folded without a
    fold action."""
    rows = []
    for frame in range(30):
        pot = ("0" if frame < 2 else "23" if frame < 4 else "27" if frame < 25
               else "57")
        actions = [[5, "preflop", 3, "call", "4", "pot_rise"]] if frame >= 5 else []
        states = {"3": "active", "6": "active" if frame < 10 else "folded"}
        rows.append({"processed": frame, "source_frame": frame * 3,
                     "pts_seconds": frame / 10,
                     "fields": {"pot": pot, "street": "preflop", "participants": states,
                                "actions_v1": {"hand_id": "hand_0", "complete": True,
                                               "start": "after_hand_over", "dealer": 7,
                                               "actions": actions}}})
    return rows


def test_rebuilt_hands_report_unexplained_rises_and_folds():
    from tools.check_aa_action_history import (hands_v1, summarize_v1,
                                               unexplained_rises, unrecorded_folds)
    hand = hands_v1(v1_log())["hand_0"]
    assert [a["kind"] for a in hand["actions"]] == ["call"]
    assert unexplained_rises(hand) == [{"frame": 25, "chips": "30"}]
    assert unrecorded_folds(hand) == [6]
    summary = summarize_v1(v1_log())
    assert summary["priced_with_amount"] == 1 and summary["unexplained_pot_rises"] == 1


def test_labelled_hands_are_matched_by_time_and_compared():
    from tools.check_aa_action_history import compare_hands
    labelled = [{"from": 0.0, "to": 3.0, "actions": [["preflop", 3, "call", "4"],
                                                     ["preflop", 6, "fold", "0"]]}]
    report = compare_hands(v1_log(), labelled)
    assert report["totals"] == {"labelled_actions": 2, "matched": 1, "missing": 1,
                                "extra": 0, "amount_correct": 1}


def test_all_ins_compare_with_labels_as_raises_or_calls():
    from tools.check_aa_action_history import labelled_kinds
    actions = [{"street": "flop", "slot": 3, "kind": "raise", "amount": "23"},
               {"street": "flop", "slot": 1, "kind": "all_in", "amount": "448"},
               {"street": "flop", "slot": 3, "kind": "all_in", "amount": "200"},
               {"street": "turn", "slot": 5, "kind": "all_in", "amount": None}]
    assert labelled_kinds(actions) == ["raise", "raise", "call", "raise"]
