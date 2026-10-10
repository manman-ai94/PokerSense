"""The table's stakes told from the chips on the table, and used everywhere."""

from decimal import Decimal

from poker_engine.desktop.aa_grading import AAGrades
from poker_engine.desktop.aa_solver_advice import AASolverAdvice, open_level
from poker_engine.desktop.aa_solver_input import (check_hand, hand_facts, replay_hand,
                                                  solver_observation, starting_stacks)
from poker_engine.desktop.aa_stakes import (default_stakes, detect_stakes,
                                            settle_stakes, stakes_label,
                                            stakes_report)

# A 2/4/8(4) table, six players, dealer 5: small blind 0 (2), big blind 1 (4),
# straddle 2 (8); seat 3 acts first. The hand opens with 6 x 4 + 2 + 4 + 8 = 38.
ACTIONS = [
    (10, "preflop", 3, "fold", "0"), (12, "preflop", 4, "fold", "0"),
    (14, "preflop", 5, "call", "8"), (16, "preflop", 0, "fold", "0"),
    (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "check", "0"),
    (30, "flop", 2, "check", "0"), (32, "flop", 5, "raise", "20"),
    (34, "flop", 2, "call", "20"),
]
BOARD = ["Ah", "Kd", "7c"]


def rows(small=2, ante=4, actions=ACTIONS, ante_frame=True, blinds=True, pot=None):
    """Frame-log rows of one hand: the pot resets, the antes show on every
    seat, then the blinds and straddle, then the actions."""
    history = {"hand_id": "hand_1", "complete": True, "start": "pot_went_down",
               "dealer": 5}
    opening = str(pot if pot is not None else 6 * ante + 7 * small)
    result = []
    for frame in range(40):
        if frame == 3 and ante_frame:
            wagers = {str(seat): str(ante) for seat in range(6)}
        elif 4 <= frame < 10 and blinds:
            wagers = {"0": str(small), "1": str(2 * small), "2": str(4 * small)}
        else:
            wagers = {}
        states = {str(seat): "active" for seat in range(6)}
        states["7"] = "waiting"
        result.append({"processed": frame, "fields": {
            "pot": "0" if frame < 3 else opening, "participants": states,
            "street_wagers": wagers,
            "board": BOARD + [None, None] if frame >= 30 else [None] * 5,
            "stacks": {"5": "400"}, "actions_v1": {**history, "actions": [
                list(a) + ["no_chips"] for a in actions if a[0] <= frame]}}})
    return result


def test_the_blinds_and_antes_on_the_table_give_the_level():
    found = detect_stakes([row["fields"] for row in rows()[:10]], range(6))
    assert found == {"small_blind": 2, "big_blind": 4, "straddle_amount": 8,
                     "ante": 4}
    one_two = detect_stakes([row["fields"] for row in rows(1, 2)[:10]], range(6))
    assert stakes_label({**one_two}) == "1/2/4(2)"


def test_the_blinds_go_round_the_seats_in_the_hand():
    # Dealer 3, seat 5 empty: small blind 6, big blind 7, straddle 0.
    frame = {"street_wagers": {"6": "2", "7": "4", "0": "8", "2": "4"}}
    assert detect_stakes([frame], [0, 1, 2, 3, 4, 6, 7])["small_blind"] == 2
    # Not the AA structure (a misread digit): no level from it.
    assert detect_stakes([{"street_wagers": {"0": "1", "1": "2", "2": "7"}}],
                         range(6)) is None


def test_without_the_ante_frame_the_opening_pot_gives_the_ante():
    fields = [row["fields"] for row in rows(ante_frame=False)[:10]]
    assert detect_stakes(fields, range(6), Decimal(38))["ante"] == 4
    # A pot that does not share out evenly: the ante stays unknown.
    assert detect_stakes(fields, range(6), Decimal(39))["ante"] is None
    assert detect_stakes(fields, range(6))["ante"] is None


def test_a_bomb_pot_shows_no_blinds():
    bomb = [{"street_wagers": {str(seat): "14" for seat in range(8)}}]
    assert detect_stakes(bomb, range(8)) is None


def test_the_hand_settles_on_what_it_showed_or_what_came_before():
    two_four = {"small_blind": Decimal(2), "big_blind": Decimal(4),
                "straddle_amount": Decimal(8), "ante": Decimal(4)}
    seen = settle_stakes(two_four)
    assert seen["source"] == "table" and seen["big_blind"] == 4
    # A bomb pot, or a hand joined midway: the last level seen.
    assert settle_stakes(None, seen) == {**seen, "source": "carried"}
    # Same blinds, ante unread: the last level seen, ante and all.
    assert settle_stakes({**two_four, "ante": None}, seen)["source"] == "carried"
    # Nothing seen yet in this observation: 1/2/4(2), not settled.
    nothing = settle_stakes(None)
    assert nothing == default_stakes() and nothing["source"] == "unsure"
    assert stakes_label(nothing) == "1/2/4(2)"
    # Other blinds with the ante unread: not settled, the ante is not guessed.
    other = settle_stakes({**two_four, "big_blind": Decimal(10), "ante": None}, seen)
    assert other["source"] == "unsure" and other["big_blind"] == 4
    assert stakes_report(seen) == {"small_blind": "2", "big_blind": "4",
                                   "straddle_amount": "8", "ante": "4",
                                   "label": "2/4/8(4)", "source": "table"}


def test_a_two_four_hand_replays_at_its_own_stakes():
    found = rows()
    facts = hand_facts(found)
    assert facts["stakes"]["big_blind"] == 4 and facts["stakes"]["source"] == "table"
    assert facts["blind_dealer"] == 5
    assert facts["opening_wagers"] == {0: Decimal(2), 1: Decimal(4), 2: Decimal(8)}
    result = replay_hand(facts)
    assert (result["status"], result["replayed"]) == ("ok", len(ACTIONS))
    assert result["arena"].rules.big_blind == 4
    report = check_hand(found)
    assert report["opening_pot_matches"] is True and report["stakes"] == "2/4/8(4)"
    # Antes of 4 each; seat 5 put in 8 + 20 and has 400 left.
    assert starting_stacks(facts, result)[5] == Decimal(432)


def test_at_two_four_the_price_and_the_open_level_are_not_halved():
    found = rows(actions=ACTIONS[:2])          # seat 5 (and later you) to act
    facts = hand_facts(found)
    observation, reason = solver_observation({**facts, "price": Decimal(8)}, 5,
                                             ["As", "Ks"])
    assert reason is None
    assert observation["rules"]["big_blind"] == "4"
    assert Decimal(observation["to_call"]) == 8
    assert Decimal(observation["pot"]) == 38
    assert open_level(facts["stakes"]) == 8 and open_level() == 4


def test_the_window_shows_and_carries_the_level():
    advice = AASolverAdvice(executor=object(), warm_executor=None)
    first = None
    for row in rows():
        first = advice.observe_fields(row["fields"], row["processed"])
    assert first["stakes"]["label"] == "2/4/8(4)"
    assert first["stakes"]["source"] == "table"
    # The next hand shows no blinds (a bomb pot): the level carries over.
    bomb = rows(blinds=False, ante_frame=False)
    for row in bomb:
        row["fields"]["actions_v1"] = {**row["fields"]["actions_v1"],
                                       "hand_id": "hand_2", "actions": []}
    report = advice.observe_fields(bomb[5]["fields"], 100)
    assert report["stakes"] == {**first["stakes"], "source": "carried"}
    assert advice.stakes()["big_blind"] == 4


def test_grading_counts_big_blinds_at_the_tables_level():
    class Advice:
        def stakes(self):
            return {"big_blind": Decimal(4)}

    assert AAGrades(Advice())._big_blind() == 4
    assert AAGrades(object())._big_blind() == 2


def preflop_turn(small):
    """Your turn before the flop at a table of blinds ``small``/``2 small``:
    seat 3 folded, you (seat 4) face the straddle, every stack 100 big blinds."""
    found = rows(small, 2 * small, actions=ACTIONS[:1])
    for row in found:
        if row["processed"] >= 20:
            row["fields"].update(
                hero=["As", "Qs"], street="preflop",
                stacks={str(seat): str(200 * small) for seat in range(6)},
                hero_controls={"visible": True, "button": "call",
                               "call_amount": str(4 * small)})
    advice = AASolverAdvice(executor=object(), warm_executor=None)
    for row in found:
        report = advice.observe_fields(row["fields"], row["processed"])
    return report


def test_the_preflop_advice_scales_with_the_stakes():
    one_two, two_four = preflop_turn(1), preflop_turn(2)
    assert one_two["status"] == two_four["status"] == "ready"
    assert two_four["stakes"]["label"] == "2/4/8(4)"
    assert Decimal(two_four["to_call"]) == 2 * Decimal(one_two["to_call"]) == 8
    small = {row["action"]: row for row in one_two["options"]}
    big = {row["action"]: row for row in two_four["options"]}
    assert small.keys() == big.keys()
    for name, row in small.items():
        # The same worth in big blinds; a raise to twice as many chips (to the chip).
        assert abs(row["big_blinds"] - big[name]["big_blinds"]) < 0.05
        if name == "raise":
            assert abs(Decimal(big[name]["to"]) - 2 * Decimal(row["to"])) <= 1
