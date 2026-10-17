"""The ledger's "from here" (``session_shadow.from_here``) with each hand
paying its own posts (``aa_session_report.chips`` since #132): it does not
depend on the next hand's position, and a bust is booked (nightly code check
2026-10-17). Made-up hands only."""

import json

from tools import session_package as package

# Six players at 1/2/4(2), dealer 5: small blind 0, big blind 1, straddle 2;
# seat 3 raises to 16, you (seat 4, ante only) call; flop bet 20 called;
# checked down; seat 3 shows queens. Next hand the dealer is seat 1, so you
# are the straddle: you post 4 + ante 2 = 6 (this hand you posted the ante 2).
ACTIONS = [
    (10, "preflop", 3, "raise", "16", "wager"),
    (13, "preflop", 4, "call", "16", "wager"),
    (14, "preflop", 5, "fold", "0", "wager"),
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
BOARD = ["Qh", "8d", "3c", "2s", "Jd"]
SHOWN = {"3": {"cards": ["Qs", "Qc"], "frame": 55}}
CODE = {"version": "0.1.0", "commit": "abcdef1234", "dirty": False}


def plain(rule, action):
    return {"status": "ready", "kind": "plain", "advice": [{"action": action}],
            "plain": {"action": action, "rule": rule, "hits": [rule],
                      "tag": "就绪 0.4s", "waited": 0.4, "defaults": []}}


TURNS = [(11, 13, "preflop", "12", "call", plain("T2.call", "call")),
         (31, 33, "flop", "20", "call", plain("F.C", "call")),
         (41, 43, "turn", None, "check", plain("N.C", "check")),
         (51, 53, "river", None, "check", plain("N.C", "check"))]


def street_at(frame):
    return ("river" if frame >= 50 else "turn" if frame >= 40
            else "flop" if frame >= 30 else "preflop")


def next_hand(frame, dealer):
    # Your stack after this hand: 200 - 16 - 20 = 164, less what you post now.
    stacks = {str(seat): "200" for seat in range(6)} | {"3": "255", "4": str(164 - 6)}
    return {"processed": frame, "pts_seconds": frame / 10,
            "video_seconds": 100.0 + frame / 10,
            "fields": {"scene_supported": True, "hero": ["7c", "2d"],
                       "street": "preflop", "pot": "19", "dealer": dealer,
                       "participants": {str(seat): "active" for seat in range(6)},
                       "board": [None] * 5, "stacks": stacks,
                       "hero_controls": {"visible": False}, "actions_tail": [],
                       "actions_v1": {"hand_id": "hand_2", "complete": True,
                                      "start": "pot_went_down", "dealer": dealer,
                                      "actions": []},
                       "solver_advice": {"status": "idle"}}}


def rows(next_dealer):
    result = []
    pots = {"preflop": "19", "flop": "51", "turn": "91", "river": "91"}
    for frame in range(66):
        if frame >= 62:
            result.append(next_hand(frame, next_dealer))
            continue
        done = [list(a) for a in ACTIONS if a[0] <= frame]
        street = street_at(frame)
        board = BOARD[:{"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]]
        paid = {seat: sum(int(a[4]) for a in ACTIONS if a[0] <= frame and a[2] == seat)
                for seat in range(6)}
        folded = {a[2] for a in ACTIONS if a[0] <= frame and a[3] == "fold"}
        turn = next((t for t in TURNS if t[0] <= frame <= t[1]), None)
        advice = turn[5] if turn else {"status": "idle", "reason": "not_your_turn"}
        fields = {
            "scene_supported": True, "hero": ["Ah", "Kd"], "street": street,
            "pot": pots[street], "dealer": 5,
            "participants": {str(seat): "folded" if seat in folded else "active"
                             for seat in range(6)},
            "board": board + [None] * (5 - len(board)),
            "stacks": {str(seat): str(200 - paid[seat]) for seat in range(6)},
            "hero_controls": ({"visible": True, "button": turn[4],
                               "call_amount": turn[3]} if turn
                              else {"visible": False}),
            "actions_tail": [{"frame": a[0], "slot": a[2], "kind": a[3]}
                             for a in ACTIONS if a[0] <= frame],
            "actions_v1": {"hand_id": "hand_1", "complete": True,
                           "start": "pot_went_down", "dealer": 5, "actions": done},
            "solver_advice": advice}
        if frame >= 55:
            fields["shown_cards"] = {"hand_id": "hand_1", "seats": SHOWN, "unknown": []}
        item = {"processed": frame, "pts_seconds": frame / 10,
                "video_seconds": 100.0 + frame / 10, "fields": fields}
        if frame == 0:
            item["code"] = CODE
        result.append(item)
    return result


def built(tmp_path, next_dealer):
    folder = tmp_path / f"20261016-20000{next_dealer}-live"
    folder.mkdir()
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows(next_dealer)) + "\n",
        encoding="utf-8")
    return package.build(folder, settings={"machine": "m", "player": "p"})


def test_from_here_does_not_depend_on_next_hands_position(tmp_path):
    found = built(tmp_path, next_dealer=1)          # next hand: you straddle
    hand = found["hands"][0]
    # The sheet (aa_session_report.chips, since #132) counts this hand with its
    # own posts: 164 + 6 - (200 + 2) = -38, the ante included. Same as when
    # the next hand's posts equal this one's.
    assert hand["result"]["your_chips"] in (-38, -38.0)
    assert "shadow" not in found["nulls"]
    block = found["shadow"]
    # From each decision on: what your stack became (164 before next posts)
    # less your stack at the decision (200, 184, 164, 164), in bb of 2.
    # Checked the turn and river with nothing more put in: those come to 0.
    got = [item["from_here_bb"] for item in block["decisions"]]
    assert got == [-18.0, -10.0, 0.0, 0.0], got


def test_a_bust_is_booked_not_dropped():
    # The sheet's own result for a hand you lost every chip in (all in and
    # lost; the next hand goes by without you): aa_session_report.chips now
    # makes it -(start + this hand's posts) = -(200 + ante 2).
    from tools.aa_session_report import chips
    from tools import session_shadow as shadow
    hands = [
        {"hand_id": "h1", "your_cards": "Ah Kd", "start_stack": 200.0, "posted": 2.0,
         "most_pot": 410.0, "you_in": True, "end_stack": 0.0, "complete": True,
         "first_stack": 200.0, "your_actions": ["call", "all_in"]},
        {"hand_id": "h2", "your_cards": None, "start_stack": None, "posted": 0.0,
         "most_pot": 19.0, "you_in": False, "end_stack": None, "complete": True,
         "first_stack": None, "your_actions": []}]
    chips(hands)
    assert hands[0]["your_chips"] == -202.0
    # build() hands the shadow this result, the start read (200) and this
    # hand's posts (2). Shoving your 200 from the decision on lost 200 = 100 bb.
    hand = {"chips": hands[0]["your_chips"], "start": "200", "posted": 2.0,
            "big_blind": "2"}
    assert shadow.from_here({"your_stack": "200"}, hand) == (-100.0, None)
