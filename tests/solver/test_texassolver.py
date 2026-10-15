"""TexasSolver adapter: commands, ranges and reading the strategy back.

The last test runs the real solver and is skipped where it is not installed
(it never is on CI: the solver is built locally, outside the repository).
"""

from pathlib import Path
import sys
import time

import pytest

from poker_engine.solver.texassolver import (
    BINARY_ENV, SMOKE_SPOT, SolverTimeout, Spot, TexasSolver, Tree, all_combos,
    amount_of, combo_key, node_at, range_text, smoke_test, solver_binary, strategy_of)


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
    # Said explicitly, so a running solver drops the previous spot's raises;
    # no trailing comma, which the solver would read as a size and crash on.
    assert "set_bet_sizes oop,river,raise" in lines
    assert "set_bet_sizes ip,river,raise" in lines
    assert not any(line.endswith(",") for line in lines)
    assert "set_bet_sizes ip,river,allin" in lines


def test_every_size_list_of_every_street_is_sent_even_when_empty():
    lines = Tree(bets=(), raises=(), donks=(), allin=False).commands(["turn", "river"])
    sizes = [line for line in lines if line.startswith("set_bet_sizes")]
    kinds = {"oop": ("bet", "raise", "donk"), "ip": ("bet", "raise")}
    assert sorted(sizes) == sorted(
        f"set_bet_sizes {player},{street},{kind}" for street in ("turn", "river")
        for player in kinds for kind in kinds[player])


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


@pytest.mark.skipif(solver_binary() is None, reason="TexasSolver is not installed")
def test_a_spot_without_raises_after_one_with_them_solves_as_on_a_fresh_solver():
    board = ("Qs", "Jh", "2h", "7c", "3d")
    polarized = {"QhQd": 1.0, "QcQd": 1.0, "6s5s": 1.0, "6d5d": 1.0, "9s8s": 1.0}
    catchers = {"KcJc": 1.0, "KdJd": 1.0, "AcJc": 1.0, "AdJd": 1.0}
    spots = [Spot(board=board, pot=100, stack=400, range_ip=catchers,
                  range_oop=polarized,
                  tree=Tree(bets=(50,), raises=raises, donks=(), allin=False))
             for raises in ((100,), ())]
    with TexasSolver(threads=1) as solver:
        alone = solver.solve(spots[1])
    with TexasSolver(threads=1) as solver:
        solver.solve(spots[0])
        after = solver.solve(spots[1])

    def facing_the_bet(tree):
        bet = next(action for action in tree["actions"] if action.startswith("BET"))
        return node_at(tree, [bet])["actions"]

    assert facing_the_bet(alone) == ["CALL", "FOLD"]
    assert after == alone


# ---- the process: a stand-in solver, so these run everywhere ---------------

FAKE = r'''
import json, sys, time
mode = sys.argv[1]
log = open(sys.argv[2], "ab")
settings = {}
for raw in sys.stdin.buffer:
    log.write(raw)
    log.flush()
    words = raw.decode("ascii").rstrip("\n").split(" ")  # as getline, then split
    if words[0] == "start_solve" and mode == "hang":
        time.sleep(600)
    if words[0] == "set_bet_sizes":         # kept until changed, as the solver does
        player, street, kind, *sizes = words[1].split(",")
        setting = settings.setdefault(f"{player},{street}", {
            "bet": [], "raise": [], "donk": [], "allin": False})
        if kind == "allin":
            setting["allin"] = True               # there is no command to undo it
        else:
            setting[kind] = [float(size) for size in sizes]   # "" crashes, as stof
    if words[0] == "dump_result":
        tree = {"strategy": {"actions": ["CHECK"], "strategy": {}},
                "settings": settings}
        open(words[1], "w").write(json.dumps(tree))
    if words[0] not in ("set_pot", "set_effective_stack", "set_board", "set_range_ip",
                        "set_range_oop", "set_bet_sizes", "set_allin_threshold",
                        "build_tree", "set_thread_num", "set_accuracy",
                        "set_max_iteration", "set_print_interval",
                        "set_use_isomorphism", "start_solve", "set_dump_rounds",
                        "dump_result"):
        sys.stdout.write("command not recognized: " + words[0] + "\n")
        sys.stdout.flush()
'''


class FakeSolver(TexasSolver):
    """TexasSolver driving the stand-in above in ``mode`` ("solve" or "hang");
    the stand-in logs the bytes it was sent."""

    def __init__(self, tmp_path, mode="solve", **options):
        (tmp_path / "console_solver").write_text("", "utf-8")
        (tmp_path / "fake.py").write_text(FAKE, "utf-8")
        self.mode, self.log = mode, tmp_path / "sent.log"
        super().__init__(tmp_path / "console_solver", **options)

    def command(self):
        return [sys.executable, str(self.binary.parent / "fake.py"), self.mode,
                str(self.log)]


def test_commands_end_in_a_line_feed_alone(tmp_path):
    with FakeSolver(tmp_path) as solver:
        assert solver.solve(SMOKE_SPOT)["strategy"]["actions"] == ["CHECK"]
    sent = solver.log.read_bytes()
    assert b"\r" not in sent
    assert sent.endswith(b"pokersense_done\n")
    assert b"\nstart_solve\n" in sent


RIVER = dict(board=("Qs", "Jh", "2h", "7c", "3d"), pot=10, stack=40,
             range_ip={"QhQd": 1.0}, range_oop={"KcJc": 1.0})


def test_a_running_solver_does_not_keep_the_previous_spots_sizes(tmp_path):
    raising = Spot(**RIVER, tree=Tree(bets=(50, 100), raises=(100,), donks=(50,)))
    plain = Spot(**RIVER, tree=Tree(bets=(100,), raises=(), donks=()))
    with FakeSolver(tmp_path) as solver:
        solver.solve(raising)
        settings = solver.solve(plain)["settings"]
    for player in ("oop", "ip"):
        assert settings[f"{player},river"]["bet"] == [100.0]
        assert settings[f"{player},river"]["raise"] == []
    assert settings["oop,river"]["donk"] == []


def test_a_tree_without_all_in_gets_a_fresh_solver_once_all_in_was_on(tmp_path):
    shoving = Spot(**RIVER, tree=Tree(bets=(100,), raises=(), donks=()))
    capped = Spot(**RIVER, tree=Tree(bets=(100,), raises=(), donks=(), allin=False))
    with FakeSolver(tmp_path) as solver:
        assert solver.solve(shoving)["settings"]["ip,river"]["allin"] is True
        pid = solver._process.pid
        assert solver.solve(capped)["settings"]["ip,river"]["allin"] is False
        assert solver._process.pid != pid       # the solver cannot turn it off
        pid = solver._process.pid
        solver.solve(capped)
        assert solver._process.pid == pid       # nothing to undo: same process
        assert solver.solve(shoving)["settings"]["ip,river"]["allin"] is True
        assert solver._process.pid == pid


def test_a_solve_past_its_timeout_kills_the_solver_and_the_next_one_starts_anew(
        tmp_path):
    with FakeSolver(tmp_path, mode="hang", timeout=1.0) as solver:
        solver._start()
        hung = solver._process
        started = time.monotonic()
        with pytest.raises(SolverTimeout):
            solver.solve(SMOKE_SPOT)
        assert time.monotonic() - started < 15
        assert hung.poll() is not None           # nothing left running
        assert solver._process is None and solver.timeouts == 1
        assert not list(Path(solver._workdir.name).glob("spot-*.json"))
        solver.mode = "solve"
        assert solver.solve(SMOKE_SPOT)["strategy"]["actions"] == ["CHECK"]


def test_a_per_solve_timeout_overrides_the_solvers_own(tmp_path):
    with FakeSolver(tmp_path, mode="hang", timeout=None) as solver:
        with pytest.raises(SolverTimeout):
            solver.solve(SMOKE_SPOT, timeout=0.5)


def test_the_smoke_test_says_whether_the_solver_works(tmp_path, monkeypatch):
    monkeypatch.setenv(BINARY_ENV, str(tmp_path / "missing.exe"))
    assert smoke_test() == {"ready": False, "seconds": 0.0, "reason": "not_installed",
                            "binary": None}
    fake = FakeSolver(tmp_path)
    fake.close()
    monkeypatch.setattr(TexasSolver, "command", FakeSolver.command)
    monkeypatch.setattr(TexasSolver, "mode", "solve", raising=False)
    monkeypatch.setattr(TexasSolver, "log", tmp_path / "sent.log", raising=False)
    report = smoke_test(tmp_path / "console_solver")
    assert report["ready"] is True and report["reason"] is None
    monkeypatch.setattr(TexasSolver, "mode", "hang", raising=False)
    report = smoke_test(tmp_path / "console_solver", timeout=0.5)
    assert report == {**report, "ready": False, "reason": "timeout"}
