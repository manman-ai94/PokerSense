from copy import deepcopy

import pytest

from tools.aa8_unmarked_money import infer_call


def inputs():
    before = {"stacks": {"0": "104", "3": "15"}, "pot": "474"}
    after = {"stacks": {"0": "0", "3": "15"}, "pot": "578"}
    context = {"actor": 0, "street_price": "221", "actor_street_wager": "63",
               "reviewed_single_action_interval": True}
    return before, after, context


def test_short_call_only_conditional_on_context():
    result = infer_call(*inputs())
    assert result["action"] == "call" and result["all_in"]
    assert result["debit"] == "104"
    assert not result["context_automated"]
    assert not result["strategy_eligible"]
    assert not result["visual_action_glyph_inferred"]


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-1", 578, "577"])
def test_unknown_invalid_or_inconsistent_pot_abstains(value):
    before, after, context = inputs()
    after["pot"] = value
    assert infer_call(before, after, context)["status"] == "UNKNOWN"


def test_multiple_cash_changes_or_missing_context_abstain():
    before, after, context = inputs()
    after["stacks"]["3"] = "14"
    assert infer_call(before, after, context)["action"] is None
    before, after, context = inputs()
    context["reviewed_single_action_interval"] = False
    assert infer_call(before, after, context)["action"] is None


def test_cannot_explain_raise_as_call_or_add_missing_roster():
    before, after, context = inputs()
    context["street_price"] = "100"
    assert infer_call(before, after, context)["action"] is None
    before, after, context = inputs()
    changed = deepcopy(after)
    changed["stacks"]["6"] = "100"
    assert infer_call(before, changed, context)["action"] is None


def test_the_pot_label_matches_at_the_threshold_given(monkeypatch):
    import numpy as np
    import tools.aa8_unmarked_money as money
    binary = np.zeros((21, 104), np.uint8)
    binary[5:15, 45:60] = 255                       # the digits after the colon
    monkeypatch.setattr(money, "region", lambda image: np.zeros((21, 104, 3), np.uint8))
    monkeypatch.setattr(money, "pot_mask", lambda patch: binary)
    monkeypatch.setattr(money, "colon_x", lambda binary: None)
    monkeypatch.setattr(money, "colon_candidates", lambda binary: [40])
    monkeypatch.setattr(money, "prefix_score", lambda candidate, prefix: .85)
    assert money.pot_patch(None, "label") is None              # .90 by default
    assert money.pot_patch(None, "label", threshold=.80) is not None


def test_ink_detached_below_the_label_is_not_part_of_the_pot(monkeypatch):
    import numpy as np
    import tools.aa8_unmarked_money as money
    binary = np.zeros((21, 104), np.uint8)
    binary[1:17, 24:55] = 255                       # the "底池" label
    binary[[7, 8, 13, 14], 57:59] = 255             # the colon's dots
    binary[4:15, 62:80] = 255                       # the digits
    binary[20, 20:90] = 255                         # a chip icon's top, below a gap
    monkeypatch.setattr(money, "region", lambda image: np.zeros((21, 104, 3), np.uint8))
    monkeypatch.setattr(money, "pot_mask", lambda patch: binary)
    monkeypatch.setattr(money, "colon_candidates", lambda binary: [57])
    monkeypatch.setattr(money, "prefix_score", lambda candidate, prefix: .95)
    assert money.pot_patch(None, "label").shape[0] == 17 + 4     # rows 4..20, padded
    assert money.pot_patch(None, "label", label_rows_only=True).shape[0] == 11 + 4
    clean = binary.copy()
    clean[20] = 0
    assert (money.label_line(clean, 57) == clean).all()        # nothing to drop
