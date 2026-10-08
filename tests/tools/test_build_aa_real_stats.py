"""The AA real-player numbers kept in the package: aggregates, enough decisions."""

from tools.build_aa_real_stats import build


def row(n, grade, **shares):
    return {"n": n, "grade": grade,
            **{key: {"count": 0, "share": value} for key, value in shares.items()}}


def test_keeps_only_rows_with_enough_decisions():
    stats = {"version": "1.1", "hands_counted": 96, "video_minutes": 113.7,
             "groups": {"ALL": {
                 "preflop": {"ALL|rfi": row(171, "usable", **{"raise": 0.15}),
                             "BB|rfi": row(4, "too_few", call=1.0)},
                 "postflop": {"flop|multi|other|facing_bet":
                              row(68, "usable", fold=0.69, call=0.22)},
                 "sizes": {"preflop_open": {"n": 25, "grade": "rough", "median": 0.96},
                           "river_raise": {"n": 2, "grade": "too_few", "median": 1.8}},
                 "player": {"ALL|vpip": {"n": 595, "grade": "usable", "share": 0.42},
                            "ALL|wtsd": {"n": 99, "grade": "usable", "share": 0.3}}}}}
    kept = build(stats)
    assert set(kept["preflop"]) == {"ALL|rfi"}
    assert kept["preflop"]["ALL|rfi"]["raise"] == 0.15
    assert kept["postflop"]["flop|multi|other|facing_bet"]["fold"] == 0.69
    assert set(kept["sizes"]) == {"preflop_open"}
    assert set(kept["player"]) == {"ALL|vpip"}
    assert "1.1" in kept["source"] and "96 hands" in kept["source"]
