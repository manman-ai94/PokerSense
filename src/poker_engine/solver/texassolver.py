"""Run TexasSolver's command-line solver for one heads-up postflop street.

TexasSolver (https://github.com/bupticybee/TexasSolver, AGPL-3.0) is built on
this machine by ``tools/setup_texassolver.sh`` and only ever called as a
separate program; nothing of it is part of this repository. Its location is
``$POKERSENSE_TEXASSOLVER`` or the data directory's
``third_party/TexasSolver-console/install/console_solver``.

The solver loads a 2.6-million-line hand table when it starts (about 3.5 s),
so one process is kept running and fed one spot after another on its
standard input; each spot is solved from the start of the current street
and only that street's strategy is read back. A running solver never frees
the trees it built (about 10 MB per turn, far more per flop), so it is
restarted once the solves it has done add up to roughly a few hundred MB.

Solver conventions used here:

- ``set_pot`` is the pot at the start of the street (dead money included) and
  ``set_effective_stack`` what each player has behind.
- Bet sizes are percentages of the pot; a raise of x is a call plus x% of the
  pot after the call, the same as the arena's half-pot and pot raises.
- Player 1 is out of position and acts first, player 0 is in position.
- Actions read back are "CHECK", "CALL", "FOLD", "BET <chips>" and
  "RAISE <chips>", chips being what that action adds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from poker_engine.data_paths import data_root

BINARY_ENV = "POKERSENSE_TEXASSOLVER"
RANKS = "23456789TJQKA"
SUITS = "cdhs"
DONE = "pokersense_done"
STREETS = {3: "flop", 4: "turn", 5: "river"}


def solver_binary():
    """Path of the console solver, or None when it is not installed."""
    value = os.environ.get(BINARY_ENV, "").strip()
    name = "console_solver.exe" if os.name == "nt" else "console_solver"
    path = (Path(value) if value
            else data_root() / "third_party/TexasSolver-console/install" / name)
    return path if path.is_file() else None


def combo_key(cards):
    """The solver's name for two hole cards: higher card first, e.g. "AhKd"."""
    first, second = sorted(cards, key=lambda c: (RANKS.index(c[0]), SUITS.index(c[1])),
                           reverse=True)
    return first + second


def _class_of(key):
    high, low = key[0], key[2]
    if high == low:
        return high + low
    return high + low + ("s" if key[1] == key[3] else "o")


def all_combos(board=()):
    """Every two-card combination not using a board card, as solver keys."""
    deck = [rank + suit for rank in RANKS for suit in SUITS if rank + suit not in board]
    return [combo_key(pair) for pair in combinations(deck, 2)]


def range_text(weights, board=()):
    """Range in the solver's syntax from {combo key: weight}.

    When every combination of a hand class that the board leaves possible has
    the same weight, the class is written once ("AKs:0.5"), which keeps the
    solver's suit symmetry speed-up; otherwise single combinations are written
    ("AhKh:0.5"). Combinations using a board card are left out.
    """
    weights = {combo_key((key[:2], key[2:])): float(w) for key, w in weights.items()
               if w > 0 and key[:2] not in board and key[2:] not in board}
    possible = {}
    for key in all_combos(board):
        possible.setdefault(_class_of(key), []).append(key)
    parts = []
    for name, keys in possible.items():
        values = {weights.get(key, 0.0) for key in keys}
        if len(values) == 1:
            parts += [(name, values.pop())]
        else:
            parts += [(key, weights.get(key, 0.0)) for key in keys]
    return ",".join(name if weight >= 1 else f"{name}:{weight:.4g}"
                    for name, weight in sorted(parts) if weight > 0)


@dataclass(frozen=True)
class Tree:
    """Bet and raise sizes (percent of pot) for every street and both players."""
    bets: tuple = (50, 100)
    raises: tuple = (100,)
    donks: tuple = (50,)
    allin: bool = True
    allin_threshold: float = 1.0

    def commands(self, streets):
        lines = []
        for street in streets:
            for player in ("oop", "ip"):
                kinds = [("bet", self.bets), ("raise", self.raises)]
                if player == "oop" and street != "flop":
                    kinds.append(("donk", self.donks))
                for kind, sizes in kinds:
                    if sizes:            # an empty list means none of that kind
                        lines.append(f"set_bet_sizes {player},{street},{kind},"
                                     + ",".join(f"{s:g}" for s in sizes))
                if self.allin:
                    lines.append(f"set_bet_sizes {player},{street},allin")
        lines.append(f"set_allin_threshold {self.allin_threshold:g}")
        return lines


@dataclass(frozen=True)
class Spot:
    """One heads-up street to solve, from its first action."""
    board: tuple
    pot: float
    stack: float
    range_ip: dict = field(hash=False)
    range_oop: dict = field(hash=False)
    tree: Tree = Tree()

    def commands(self, output, threads=8, accuracy=0.5, max_iterations=200):
        street = STREETS[len(self.board)]
        later = list(STREETS.values())[list(STREETS.values()).index(street):]
        return [f"set_pot {self.pot:g}", f"set_effective_stack {self.stack:g}",
                "set_board " + ",".join(self.board),
                "set_range_ip " + range_text(self.range_ip, self.board),
                "set_range_oop " + range_text(self.range_oop, self.board),
                *self.tree.commands(later), "build_tree",
                f"set_thread_num {threads}", f"set_accuracy {accuracy:g}",
                f"set_max_iteration {max_iterations}",
                f"set_print_interval {max_iterations}",
                "set_use_isomorphism 1", "start_solve", "set_dump_rounds 1",
                f"dump_result {output}"]


def node_at(tree, actions):
    """The decision node reached by following ``actions`` from the street start."""
    node = tree
    for action in actions:
        children = node.get("childrens") or {}
        if action not in children:
            raise KeyError(f"action {action!r} not in {sorted(children)}")
        node = children[action]
    return node


def strategy_of(node, cards):
    """{action: probability} for these hole cards at a decision node."""
    strategy = node["strategy"]
    probabilities = strategy["strategy"][combo_key(cards)]
    return dict(zip(strategy["actions"], probabilities))


def amount_of(action):
    """Chips added by "BET x" or "RAISE x"; 0 for the others."""
    parts = action.split()
    return float(parts[1]) if len(parts) == 2 else 0.0


class TexasSolver:
    """A running console solver; ``solve`` returns the street's strategy tree."""

    # Share of a restart budget each solve uses, by board size: a flop solve
    # leaves up to several hundred MB behind, a turn about 10 MB, a river little.
    LOAD = {3: 1.0, 4: 0.04, 5: 0.005}

    def __init__(self, binary=None, threads=8, accuracy=0.5, max_iterations=200):
        self.binary = Path(binary) if binary else solver_binary()
        if self.binary is None:
            raise FileNotFoundError("TexasSolver is not installed; run "
                                    "tools/setup_texassolver.sh")
        self.threads, self.accuracy = threads, accuracy
        self.max_iterations = max_iterations
        self._workdir = tempfile.TemporaryDirectory(prefix="texassolver-")
        self._process = None
        self._lock = threading.Lock()
        self._count = 0
        self._load = 0.0
        self.restarts = 0

    def _start(self):
        resources = self.binary.parent / "resources"
        self._process = subprocess.Popen(
            [str(self.binary), "-r", str(resources)], cwd=self._workdir.name,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)

    def solve(self, spot, accuracy=None, max_iterations=None):
        """The street's strategy tree; accuracy and iterations default to the
        solver's own settings."""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            self._count += 1
            output = Path(self._workdir.name) / f"spot-{self._count}.json"
            lines = spot.commands(output.name, self.threads,
                                  self.accuracy if accuracy is None else accuracy,
                                  self.max_iterations if max_iterations is None
                                  else max_iterations)
            self._process.stdin.write("\n".join(lines + [DONE]) + "\n")
            self._process.stdin.flush()
            for line in self._process.stdout:
                if line.strip() == f"command not recognized: {DONE}":
                    break
            else:
                raise RuntimeError("TexasSolver stopped before finishing the spot")
            if not output.is_file():
                raise RuntimeError("TexasSolver did not write a strategy")
            tree = json.loads(output.read_text(encoding="utf-8"))
            output.unlink()
            self._load += self.LOAD[len(spot.board)]
            if self._load >= 1.0:
                self._stop()
                self.restarts += 1
            return tree

    def _stop(self):
        if self._process is not None and self._process.poll() is None:
            self._process.stdin.close()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._load = 0.0

    def close(self):
        self._stop()
        self._workdir.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = ["Spot", "TexasSolver", "Tree", "all_combos", "amount_of", "combo_key",
           "node_at", "range_text", "solver_binary", "strategy_of"]
