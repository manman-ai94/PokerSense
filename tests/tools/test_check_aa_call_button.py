"""Call-button check summaries from synthetic reads (no recording needed)."""

from tools.check_aa_call_button import compare

TURNS = [{"from": 1.0, "to": 2.0, "button": "38"},
         {"from": 5.0, "to": 5.5, "button": "check"},
         {"from": 9.0, "to": 9.0, "button": "all_in"}]


def test_compare_separates_amounts_checks_and_all_in():
    results = [(0, 1.0, "38"), (0, 1.5, None), (0, 2.0, "36"),
               (1, 5.0, "check"), (1, 5.5, "check"), (2, 9.0, "check")]
    report = compare(results, TURNS)
    assert report["counts"] == {"amount:correct": 1, "amount:unknown": 1,
                                "amount:wrong": 1, "check:correct": 2,
                                "all_in:wrong": 1}
    assert report["wrong"] == [{"seconds": 2.0, "expected": "38", "got": "36"},
                               {"seconds": 9.0, "expected": "all_in", "got": "check"}]
