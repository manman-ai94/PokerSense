"""Seat-state check summaries from synthetic rows (no recording needed)."""

from tools.check_aa_seat_states import agreement, coverage


def row(states, *, supported=True, hero=False, actor=None):
    return {"supported": supported, "hero_cards": hero, "actor": actor,
            "states": dict(zip("01234567", states))}


ALL = ["active"] * 4 + ["folded"] * 2 + ["empty", "waiting"]


def test_coverage_counts_all_eight_known_by_frame_kind():
    rows = [(0.0, row(ALL, hero=True, actor=4)),
            (0.1, row(ALL[:7] + ["unknown"], hero=True)),
            (0.2, row(ALL, actor=2)),
            (0.3, row(["unknown"] * 8, supported=False))]
    result = coverage(rows)
    assert result["supported_frames"] == 3
    assert result["all_known_supported"] == round(2 / 3, 4)
    assert result["all_known_while_acting"] == 1.0
    assert result["all_known_hero_cards"] == 0.5
    assert result["all_known_hero_cards_while_acting"] == 1.0


def test_agreement_uses_the_nearest_frame_and_skips_unscored_seats():
    rows = [(10.0, row(ALL)), (10.3, row(["unknown"] + ALL[1:]))]
    labels = {"10.05": "AAAAFFEW", "10.28": "?AAFFFEW", "50": "AAAAAAAA"}
    result = agreement(rows, labels)
    assert result["counts"] == {"correct": 14, "wrong": 1, "no_frame": 1}
    assert result["wrong"] == [{"seconds": 10.28, "seat": 3,
                                "expected": "folded", "got": "active"}]
