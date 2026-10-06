"""Public decision diagnostics, not a policy fallback or acceptance grant."""

STREETS = ("preflop", "flop", "turn", "river")


def failure_category(error, phase):
    message = str(error)
    if phase == "BIND":
        return "ADAPTER_ERROR"
    if "unknown_policy_information_set" in message:
        return "UNKNOWN_INFORMATION_SET"
    if "scope_mismatch" in message or "encoder_mismatch" in message:
        return "SCOPE_MISMATCH"
    if "menu" in message or "probabilit" in message:
        return "INVALID_MENU"
    if "budget" in message or "max_actions" in message or "deadline" in message:
        return "BUDGET_EXHAUSTED"
    if phase == "STEP":
        return "ILLEGAL_ACTION"
    return "ADAPTER_ERROR"


def summarize_opportunities(branches):
    """Prefixes actually observed; suffix opportunity counts stay unknown."""
    counts = {street: {"observed": 0, "hit": 0, "miss": 0, "other": 0}
              for street in STREETS}
    first_observed = first_hit = 0
    failures = {}
    for branch in branches:
        rows = branch.get("hero_opportunities", [])
        if rows:
            first_observed += 1
            first_hit += rows[0]["lookup_status"] == "HIT"
        for row in rows:
            street = counts[row["street"]]
            street["observed"] += 1
            status = row["lookup_status"]
            key = ("hit" if status == "HIT" else "miss"
                   if status == "UNKNOWN_INFORMATION_SET" else "other")
            street[key] += 1
        failure = branch.get("first_failure")
        if failure:
            key = failure["category"]
            failures[key] = failures.get(key, 0) + 1
    return {"coverage_scope": "OBSERVED_PREFIX_ONLY_SUFFIX_UNKNOWN_AFTER_FAILURE",
            "streets": counts, "first_hero_observed": first_observed,
            "first_hero_hit": first_hit, "failure_counts": failures}
