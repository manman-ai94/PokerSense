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
