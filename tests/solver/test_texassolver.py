"""TexasSolver adapter: commands, ranges and reading the strategy back.

The last test runs the real solver and is skipped where it is not installed
(it never is on CI: the solver is built locally, outside the repository).
"""

import pytest

from poker_engine.solver.texassolver import (Spot, TexasSolver, Tree, all_combos,
                                             amount_of, combo_key, node_at, range_text,
                                             solver_binary, strategy_of)


def test_combo_keys_put_the_higher_card_first():
    assert combo_key(["Kd", "Ah"]) == "AhKd"
    assert combo_key(["9c", "9h"]) == "9h9c"
    assert combo_key(["5c", "6c"]) == "6c5c"
    assert len(all_combos()) == 1326
    assert len(all_combos(("Ah", "Kd", "2c"))) == 1176


def test_symmetric_classes_are_written_once_and_others_by_combination():
    aces = {key: 1.0 for key in all_combos() if key[0] == key[2] == "A"}
    suited = {key: 0.5 for key in all_combos() if key[0] == "A" and key[2] == "K"
              and key[1] == key[3]}
    assert range_text({**aces, **suited}) == "AA,AKs:0.5"
    assert range_text({"AhKh": 1.0, "AsKs": 0.25}) == "AhKh,AsKs:0.25"


def test_the_board_leaves_classes_symmetric_and_drops_blocked_combinations():
    board = ("Ah", "7c", "2d")
    aces = {key: 1.0 for key in all_combos() if key[0] == key[2] == "A"}
    assert range_text(aces, board) == "AA"
    assert range_text({"AhAs": 1.0, "KdKs": 1.0}, board) == "KsKd"


def test_spot_commands_cover_the_street_and_later_ones():
    spot = Spot(board=("Qs", "Jh", "2h", "7c"), pot=58, stack=171,
                range_ip={"AhAd": 1.0}, range_oop={"KhKd": 1.0}, tree=Tree())
    lines = spot.commands("out.json", threads=4, accuracy=0.3, max_iterations=150)
    assert lines[:3] == ["set_pot 58", "set_effective_stack 171",
                         "set_board Qs,Jh,2h,7c"]
    assert "set_bet_sizes oop,turn,bet,50,100" in lines
    assert "set_bet_sizes ip,river,raise,100" in lines
    assert "set_bet_sizes oop,river,donk,50" in lines
    assert not any(",flop," in line for line in lines)
    assert lines[-3:] == ["start_solve", "set_dump_rounds 1", "dump_result out.json"]
    assert "set_thread_num 4" in lines and "set_accuracy 0.3" in lines


def test_a_tree_without_raise_sizes_only_raises_all_in():
    lines = Tree(bets=(50,), raises=(), donks=(50,)).commands(["river"])
    assert not any(",raise" in line for line in lines)
    assert "set_bet_sizes ip,river,allin" in lines


TREE = {"player": 1, "node_type": "action_node", "actions": ["CHECK", "BET 29.000000"],
        "strategy": {"actions": ["CHECK", "BET 29.000000"],
                     "strategy": {"AhKd": [0.25, 0.75]}},
        "childrens": {"CHECK": {"player": 0, "node_type": "action_node",
                                "actions": ["CHECK", "BET 29.000000"],
                                "strategy": {"actions": ["CHECK", "BET 29.000000"],
                                             "strategy": {"QsQd": [1.0, 0.0]}}}}}


def test_reading_a_node_and_a_strategy():
    assert strategy_of(TREE, ["Kd", "Ah"]) == {"CHECK": 0.25, "BET 29.000000": 0.75}
    assert strategy_of(node_at(TREE, ["CHECK"]), ["Qd", "Qs"]) == {
        "CHECK": 1.0, "BET 29.000000": 0.0}
    assert amount_of("BET 29.000000") == 29.0 and amount_of("CALL") == 0.0
    with pytest.raises(KeyError):
        node_at(TREE, ["BET 50.000000"])


@pytest.mark.skipif(solver_binary() is None, reason="TexasSolver is not installed")
def test_a_polarized_river_bets_the_nuts_against_bluff_catchers():
    board = ("Qs", "Jh", "2h", "7c", "3d")
    # Sets of queens (the nuts here) and missed hands against pairs of jacks.
    polarized = {"QhQd": 1.0, "QcQd": 1.0, "6s5s": 1.0, "6d5d": 1.0, "9s8s": 1.0}
    catchers = {"KcJc": 1.0, "KdJd": 1.0, "AcJc": 1.0, "AdJd": 1.0}
    spot = Spot(board=board, pot=100, stack=100, range_ip=catchers, range_oop=polarized)
    with TexasSolver(threads=2) as solver:
        tree = solver.solve(spot)
        again = solver.solve(spot)
    assert tree == again
    assert tree["player"] == 1                      # out of position acts first
    betting = sum(p for action, p in strategy_of(tree, ["Qh", "Qd"]).items()
                  if action.startswith("BET"))
    assert betting > 0.9


@pytest.mark.skipif(solver_binary() is None, reason="TexasSolver is not installed")
def test_the_solver_restarts_after_its_load_budget():
    spot = Spot(board=("Qs", "Jh", "2h", "7c", "3d"), pot=100, stack=100,
                range_ip={"KcJc": 1.0}, range_oop={"QhQd": 1.0, "6s5s": 1.0})
    with TexasSolver(threads=1) as solver:
        solver.LOAD = {5: 0.5}                     # restart after every two rivers
        first = solver.solve(spot)
        pid = solver._process.pid
        solver.solve(spot)
        assert solver._process is None and solver.restarts == 1
        assert solver.solve(spot) == first          # a new process, same answer
        assert solver._process.pid != pid
