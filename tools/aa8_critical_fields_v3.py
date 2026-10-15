"""Critical-field evaluation projection; frozen V2 evaluation remains historical."""

from poker_engine.desktop.aa_critical_perception import checked_view
from tools.aa8_holdout_predict_v2 import normalize_fields as legacy_fields


def normalize_fields(row, derived=None):
    """Use precisely the same qualified candidates as snapshot prefill.
    ``derived``: see ``checked_view``."""
    result = legacy_fields(row)
    view = checked_view(row, derived)
    for target, name in (("board_cards", "board"), ("participation", "participation")):
        field = (view["fields"][name] if view else {"status": "UNKNOWN", "value": None})
        known = field["status"] == "KNOWN"
        result[target] = {"status": "KNOWN" if known else "UNKNOWN",
                          "value": field["value"] if known else None,
                          "origin": "automatic",
                          "semantics": "source_bound_machine_candidate_not_truth"}
        if target == "participation" and result[target]["value"] is not None:
            result[target]["value"] = {
                k: v.lower() for k, v in result[target]["value"].items()}
    return result
