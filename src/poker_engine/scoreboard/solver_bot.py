"""Heads-up postflop play from TexasSolver; everything else from rfi_table.

At a heads-up decision on a street it covers, the bot

1. replays the hand's public actions and works out both players' ranges at
   the start of the street: its own by asking its own policy what it would
   have done with every possible hand (exact: it knows its own randomness),
   the opponent's by asking the population model the same (an estimate, the
   same one a live table would use);
2. solves the street from its first action, follows this street's actions so
   far in the solution and plays its own hand's strategy there;
3. turns the solver's bet into the nearest bet the table allows.

Preflop, multiway pots and anything it cannot handle (solver not installed,
an opponent action the population model never takes, ...) are played by
rfi_table; ``counts`` records how often each happened.
"""

from __future__ import annotations

from collections import Counter, OrderedDict

from poker_engine.solver.texassolver import (Spot, TexasSolver, Tree, all_combos,
                                             amount_of, combo_key, node_at,
                                             solver_binary, strategy_of)

from .bots import RfiTablePolicy, _Policy, _rng, opponents_in_hand
from .population import PopulationBot
from .replay import kind_of, public_replay, with_hole
from .strength import hand_class

# Which heads-up streets each solver strategy plays.
STREET_SETS = {"solver_river": ("river",), "solver_turn": ("turn", "river"),
               "solver_flop": ("flop", "turn", "river")}
# Tree, target accuracy (exploitability, % of the pot) and iteration cap per
# street. A river takes milliseconds and a turn about 4 s on one thread. A
# flop solve also covers every turn and river card, so the flop gets a smaller
# tree (half pot or all in, raises all in only), a looser target and a cap:
# one to two minutes instead of six.
STREET_SOLVES = {"flop": (Tree(bets=(50,), raises=(), donks=(50,)), 2.0, 30),
                 "turn": (Tree(), 0.5, 200), "river": (Tree(), 0.5, 200)}
# A flop solve's time and memory grow with the ranges: a raised pot (about
# 400 hands in both ranges) takes 45 s and 0.9 GB, a limped pot checked
# through by the big blind (1300 hands) 3.5 minutes and 4.6 GB. Wider flops
# are left to the base policy.
MAX_FLOP_HANDS = 600
ORDER = ("preflop", "flop", "turn", "river")
MODEL_SALT = "population-range"


class Fallback(Exception):
    """The solver cannot play this decision; the reason is counted."""


class SolverBot(_Policy):
    def __init__(self, name="solver_river", solves=None, threads=1, cache_size=16):
        self.name = name
        self.streets = STREET_SETS[name]
        self.base = RfiTablePolicy()
        self.model = PopulationBot()
        self.solves = dict(STREET_SOLVES if solves is None else solves)
        self.threads = threads
        self.max_flop_hands = MAX_FLOP_HANDS
        self.counts = Counter()
        self._solutions = OrderedDict()
        self._cache_size = cache_size

    # -- arena contract -------------------------------------------------------

    def for_game(self, salt):
        def policy(observation):
            return self.decide(observation, _rng(salt, observation), salt)
        return policy

    def decide(self, observation, rng, salt=None):
        if (salt is None or observation["street"] not in self.streets
                or opponents_in_hand(observation) != 1):
            return self.base.decide(observation, rng)
        try:
            action = self.solved_action(observation, rng, salt)
        except Fallback as reason:
            self.counts[str(reason)] += 1
            return self.base.decide(observation, rng)
        self.counts["solved"] += 1
        return action

    # -- solving --------------------------------------------------------------

    def solved_action(self, observation, rng, salt):
        me, street = observation["observing_seat"], observation["street"]
        decisions = public_replay(observation)
        live = [seat for seat in observation["occupied_seats"]
                if seat not in observation["folded"]]
        villain = next(seat for seat in live if seat != me)
        board = tuple(observation["board"])
        hero = {key: 1.0 for key in all_combos(board)}
        other = dict(hero)
        own = combo_key(observation["own_hole"])
        for past in ORDER[:ORDER.index(street)]:
            hero, other = self.street_ranges(past, decisions, me, villain, hero, other,
                                             salt, board, own)
        now = [d for d in decisions if d.street == street]
        tree, first = self.street_solution(now, observation, me, villain, hero, other,
                                           board)
        node = tree
        for decision in now:
            node = node_at(node, [self.label(node, decision)])
        try:
            strategy = strategy_of(node, observation["own_hole"])
        except KeyError:
            raise Fallback("own_hand_not_in_range") from None
        return self.to_arena(sample(strategy, rng), observation)

    def street_solution(self, decisions, observation, me, villain, hero, other, board):
        start = decisions[0].observation if decisions else observation
        first = decisions[0].seat if decisions else me
        live = [seat for seat in start["occupied_seats"] if seat not in start["folded"]]
        if len(live) != 2:
            raise Fallback("multiway_at_street_start")
        stacks = start["stacks"]
        stack = min(float(stacks[str(me)]), float(stacks[str(villain)]))
        if stack <= 0:
            raise Fallback("all_in")
        if start["street"] == "flop":
            hero, other = by_class(hero, board[:3]), by_class(other, board[:3])
            if len(hero) + len(other) > self.max_flop_hands:
                raise Fallback("flop_ranges_too_wide")
        ranges = {me: hero, villain: other}
        oop, ip = first, (villain if first == me else me)
        shown = {"flop": 3, "turn": 4, "river": 5}[start["street"]]
        street_board = tuple(board[:shown])
        tree, accuracy, iterations = self.solves[start["street"]]
        spot = Spot(board=street_board, pot=float(start["pot"]), stack=stack,
                    range_ip=ranges[ip], range_oop=ranges[oop], tree=tree)
        return self.solve(spot, accuracy, iterations), first

    def street_ranges(self, street, decisions, me, villain, hero, other, salt, board,
                      own=None):
        """Both ranges after ``street``'s actions, from the ranges before it.

        ``own`` is the hand the bot actually holds; it stays in its own range
        (see ``keep_own``).
        """
        now = [d for d in decisions if d.street == street]
        if not now:
            return hero, other
        solved = (street in self.streets and street != "preflop"
                  and len([s for s in now[0].observation["occupied_seats"]
                           if s not in now[0].observation["folded"]]) == 2)
        node = None
        if solved:
            try:
                node, _ = self.street_solution(now, now[0].observation, me, villain,
                                               hero, other, board)
            except Fallback:          # the street was played by the base policy
                node = None
        for decision in now:
            if decision.seat == me:
                if node is not None:
                    hero = keep_own(weighted(hero, node, self.label(node, decision)),
                                    hero, own)
                else:
                    hero = kept(hero, decision,
                                lambda obs: self.base.decide(obs, _rng(salt, obs)),
                                both_orders=True)
            elif decision.seat == villain:
                before = other
                other = kept(other, decision, lambda obs: self.model.decide(
                    obs, _rng(MODEL_SALT, obs)))
                if not other:
                    self.counts["villain_range_kept"] += 1
                    other = before
            if node is not None:
                node = node_at(node, [self.label(node, decision)])
        return hero, other

    def solve(self, spot, accuracy, iterations):
        key = "\n".join(spot.commands("x", self.threads, accuracy, iterations))
        if key in self._solutions:
            self._solutions.move_to_end(key)
            return self._solutions[key]
        tree = shared_solver(self.threads).solve(spot, accuracy, iterations)
        self._solutions[key] = tree
        if len(self._solutions) > self._cache_size:
            self._solutions.popitem(last=False)
        return tree

    # -- actions --------------------------------------------------------------

    @staticmethod
    def label(node, decision):
        """The solution's branch for an action taken at the table."""
        actions = node.get("actions") or []
        kind = decision.kind
        if kind == "f":
            label = "FOLD"
        elif kind == "c":
            label = "CALL" if float(decision.observation["to_call"] or 0) else "CHECK"
        else:
            bets = decision.observation["bets"]
            added = float(decision.action["raise_to"]) - float(bets[str(decision.seat)])
            sized = [action for action in actions
                     if action.startswith(("BET", "RAISE"))]
            if not sized:
                raise Fallback("raise_not_in_solution")
            label = min(sized, key=lambda action: abs(amount_of(action) - added))
        if label not in actions:
            raise Fallback("action_not_in_solution")
        return label

    @staticmethod
    def to_arena(choice, observation):
        to_call = float(observation["to_call"] or 0)
        if choice in ("CHECK", "CALL"):
            return "check_call"
        if choice == "FOLD":
            return "fold" if to_call else "check_call"
        raises = [action for action in observation["legal_actions"]
                  if action["kind"] == "raise_to"]
        if not raises:
            return "check_call"
        mine = float(observation["bets"][str(observation["observing_seat"])])
        target = mine + amount_of(choice)
        return min(raises,
                   key=lambda action: abs(float(action["raise_to"]) - target))["id"]


_SOLVERS = {}


def shared_solver(threads):
    """One running solver per process and thread count (starting one takes 3.5 s)."""
    if threads not in _SOLVERS:
        if solver_binary() is None:
            raise Fallback("solver_not_installed")
        _SOLVERS[threads] = TexasSolver(threads=threads)
    return _SOLVERS[threads]


def kept(weights, decision, decide, both_orders=False):
    """Weights times how often ``decide`` takes the action that was taken.

    A bot's randomness depends on the order its two cards were dealt in, so
    with ``both_orders`` each hand is asked both ways and kept with weight
    0.5 or 1 (exact for a player replaying its own policy); otherwise once.
    """
    result = {}
    for key, weight in weights.items():
        orders = ((key[:2], key[2:]), (key[2:], key[:2])) if both_orders else \
            ((key[:2], key[2:]),)
        share = sum(kind_of(decide(with_hole(decision.observation, cards)))
                    == decision.kind for cards in orders) / len(orders)
        if share:
            result[key] = weight * share
    return result


def weighted(weights, node, label):
    """Weights times each hand's probability of taking ``label`` at ``node``."""
    strategy = node["strategy"]
    column = strategy["actions"].index(label)
    table = strategy["strategy"]
    result = {}
    for key, weight in weights.items():
        row = table.get(key)
        if row and row[column] * weight > 0:
            result[key] = weight * row[column]
    return result


def by_class(weights, board):
    """Every hand class at its average weight over the combinations left.

    The population model cuts its ranges by single combinations, so a class at
    the edge of a range is split by suit; one such class makes the solver drop
    its suit-symmetry speed-up for the whole solve. Before any postflop action
    the suits of a class carry no information, so the flop gets class weights.
    """
    groups = {}
    for key in all_combos(board):
        groups.setdefault(hand_class((key[:2], key[2:])), []).append(key)
    result = {}
    for keys in groups.values():
        average = sum(weights.get(key, 0.0) for key in keys) / len(keys)
        if average > 0:
            result.update(dict.fromkeys(keys, average))
    return result


def keep_own(weights, before, own, floor=0.01):
    """Keep the hand actually held in a range reweighted by solver frequencies.

    The bot took the action it took, so its own hand stays in: if the solver
    gave that action no weight for this hand (the decision was played by the
    base policy), the hand keeps its earlier weight. Weights are then scaled
    so the largest is 1, which does not change a solve, and the own hand gets
    at least ``floor``: the solver ignores weights of 0.5% or less.
    """
    if own is None or own not in before:
        return weights
    weights = dict(weights)
    weights[own] = weights.get(own) or before[own]
    top = max(weights.values())
    weights = {key: value / top for key, value in weights.items()}
    weights[own] = max(weights[own], floor)
    return weights


def sample(strategy, rng):
    """One action drawn from {action: probability} (in a fixed order)."""
    actions = sorted(strategy)
    total = sum(strategy[action] for action in actions)
    point = rng.random() * total
    for action in actions:
        point -= strategy[action]
        if point <= 0:
            return action
    return actions[-1]


__all__ = ["Fallback", "STREET_SETS", "STREET_SOLVES", "SolverBot", "by_class",
           "keep_own", "kept", "sample", "shared_solver", "weighted"]
