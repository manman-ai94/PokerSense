"""After the flop with two or more opponents: play by equity against their ranges.

``range_multiway+aa_preflop`` plays like its base policy everywhere except
postflop decisions with more than one opponent. There every opponent's range
is read from their actions with the population model and your share of the
pot against those ranges is worked out (``ranges``); then

- facing a bet: raise about the pot when the share is at least ``raise``,
  call when it beats the price (``to_call / (pot + to_call)``) by ``margin``,
  otherwise fold;
- with nothing to call: bet when the share is at least ``bet``, otherwise
  check; about two thirds of the pot (``size``) against two opponents, the
  pot (``size3``) against three or more.

With ``hu=1`` the heads-up flop is played the same way, with its own cuts
``hu_bet`` and ``hu_raise`` (one opponent's fair share is a half, not a
third or less): the live window has no solver for that street (a flop solve
takes about a minute) and plays it so. 0.55 and 0.7 won the most of the cuts
tried on the scoreboard (2026-10-08, AA pool with the mushroom pool).
With ``hu=2`` the heads-up turn and river are played the same way too: what
the live window shows there until the solver answers.

``bet`` was 0.4 until 2026-10-09: with seven opponents that bet only with
twice a fair share, and the 10/09 session showed checks with strong hands in
big multiway pots. 0.3 beat 0.4 on the AA real-player table (mushroom pool,
bomb pots, reads) on two batches of deals.

``size3`` was two thirds until 2026-10-09 too. The scoreboard table offers
the minimum, half the pot, the pot and all in, so two thirds plays as half
the pot there; betting the pot into three or more opponents won +9.2 and
+5.5 bb/100 on the AA real-player table on two batches of deals, while the
pot against two opponents lost 4.0.

The big-pot guard (``guard``, in big blinds; 0 turns it off): with one pair
or less of your own (top pair included: a pair on the board does not count
as yours, nor a hand the board alone makes) in a pot of at least ``guard``
big blinds, there is no raise (facing a bet: call or fold by the price), a
bet is at most half the pot, and on the river there is no bet at all. The
ranges are read narrower than people play (a shown hand was ruled out on the
river 84% of the time, 2026-10-13), so the share comes out at 0.9-1.0 with a
pair and the rule bet big: of 6 river bets at 0.85 or more on the recordings
3 won. A stop-gap until the ranges are read better and bets are sized
against the hands that call. 30 big blinds from the 10/08-10/10 recordings
(lines from 20 to 30 change the same decisions there, a higher one lets
lost hands through; see the pull request).

Parameters can follow the name, for example
``range_multiway@bet=0.55:raise=0.7:margin=0.05+aa_preflop`` (":" between
them: "," separates strategies on the command line).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from functools import lru_cache
import random

from phevaluator import evaluate_cards

from poker_engine.solver.texassolver import all_combos

from .bots import MAX_EQUITY_OPPONENTS, _Policy, _rng, opponents_in_hand, raise_toward
from .population import actions, population_stats, threshold
from .preflop_reading import reading_model, reading_of
from .ranges import _Range, opponent_ranges, ranges_equity
from .spots import postflop_spot
from .strength import CARD_ID, DECK, _EVALUATE_7

DEFAULTS = {"bet": 0.3, "raise": 0.6, "margin": 0.0, "trials": 600,
            "hu": 0.0, "hu_bet": 0.55, "hu_raise": 0.7,
            "size": 0.66, "size3": 1.0, "raise_size": 1.0, "guard": 30.0,
            "sizing": 1.0, "elastic": 0.5, "sticky": 1.0}
# The model's own bet and raise (of the pot), the sizes its continue shares
# were seen at.
REFERENCE = {"facing_bet": 0.66, "facing_raise": 1.0}
MIN_SIZE = 0.25                 # smaller bets (the minimum) are not offered
RUNOUTS = 30                    # boards dealt to rank every hand's strength
GUARD_SIZE = 0.5                # the most a guarded bet puts in, of the pot
# phevaluator's ranks (lower is stronger) where each kind of hand ends.
KINDS = ((10, "straight_flush"), (166, "four_of_a_kind"), (322, "full_house"),
         (1599, "flush"), (1609, "straight"), (2467, "three_of_a_kind"),
         (3325, "two_pair"), (6185, "one_pair"), (7462, "high_card"))
ORDER = [name for _, name in reversed(KINDS)]       # high card first


class RangeMultiwayBot(_Policy):
    def __init__(self, base, name="range_multiway", **params):
        unknown = set(params) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown parameters {sorted(unknown)}")
        self.base, self.name = base, name
        self.params = {**DEFAULTS, **params}
        self.adjusted = getattr(base, "adjusted", False)
        self.model = reading_model(self.adjusted, reading_of(base))
        self.counts = Counter()

    def for_game(self, salt):
        # The base plays through its own game policy: a solver base needs the
        # game's salt, which ``decide`` does not carry.
        base = self.base.for_game(salt)

        def policy(observation):
            if not covered(observation, self.params):
                return base(observation)
            return self.decide(observation, _rng(salt, observation))
        return policy

    def decide(self, observation, rng):
        if not covered(observation, self.params):
            return self.base.decide(observation, rng)
        ranges = opponent_ranges(observation, self.model)
        share, _ = ranges_equity(observation["own_hole"], observation["board"], ranges,
                                 trials=int(self.params["trials"]),
                                 seed=rng.randrange(2 ** 31))
        if share is None:
            self.counts["no_equity"] += 1
            return self.base.decide(observation, rng)
        self.counts["decided"] += 1
        return choose(observation, share, self.params, ranges=ranges,
                      seed=rng.randrange(2 ** 31))


def covered(observation, params=DEFAULTS):
    """Whether the rule plays this decision: after the flop with two or more
    opponents, and on the heads-up flop with ``hu``."""
    if observation["street"] == "preflop":
        return False
    opponents = opponents_in_hand(observation)
    if opponents == 1 and params["hu"] >= 2:      # every heads-up street
        return True
    return opponents >= 2 or (opponents == 1 and observation["street"] == "flop"
                              and bool(params["hu"]))


def street_params(observation, params=DEFAULTS):
    """The cuts for this decision: heads-up ones against one opponent."""
    opponents = opponents_in_hand(observation)
    if opponents >= 3:
        return {**params, "size": params["size3"]}
    if opponents == 2:
        return params
    return {**params, "bet": params["hu_bet"], "raise": params["hu_raise"],
            "size": DEFAULTS["size"]}


def cuts(observation, params=DEFAULTS):
    """The shares of the pot where the action changes: with nothing to call,
    ``bet``; facing a bet, ``call`` (the price plus the margin) and ``raise``."""
    to_call = float(observation["to_call"] or 0)
    if to_call == 0:
        return {"bet": params["bet"]}
    price = to_call / (float(observation["pot"]) + to_call)
    return {"call": price + params["margin"], "raise": params["raise"]}


def choose(observation, share, params=DEFAULTS, *, ranges=None, model=None, seed=0):
    """The action id for your share of the pot against the field, with the
    big-pot guard (``guard_action``)."""
    action = unguarded(observation, share, params, ranges=ranges, model=model,
                       seed=seed)
    return guard_action(observation, action, share, params)


def hand_kind(cards):
    """"one_pair", "flush", ... for five to seven cards."""
    rank = evaluate_cards(*cards)
    return next(name for top, name in KINDS if rank <= top)


def _board_kind(board):
    """The kind the board's cards make by themselves, counting only repeated
    ranks (a pair, two pair, trips, ...): what every player in has."""
    counts = sorted(Counter(card[0] for card in board).values(), reverse=True) + [0, 0]
    if counts[0] >= 4:
        return "four_of_a_kind"
    if counts[0] == 3:
        return "full_house" if counts[1] >= 2 else "three_of_a_kind"
    if counts[0] == 2:
        return "two_pair" if counts[1] == 2 else "one_pair"
    return "high_card"


def weak_hand(hole, board):
    """Whether you hold one pair or less of your own after the flop: top
    pair included; a pair on the board is not yours (two pair with one pair
    on the board is one pair of yours), nor a hand the board alone makes."""
    hole, board = list(hole), [card for card in board if card]
    if len(board) < 3:
        return False
    kind = hand_kind(hole + board)
    board_kind = _board_kind(board)
    if ORDER.index(kind) <= ORDER.index("one_pair"):
        return True
    if kind == "two_pair" and board_kind != "high_card":
        return True
    if kind == board_kind:
        return True
    return len(board) == 5 and evaluate_cards(*board) == evaluate_cards(*hole, *board)


def big_pot(pot, big_blind, params=DEFAULTS):
    """The pot in big blinds when it is at least the guard's line, else None."""
    line, big_blind = float(params.get("guard", 0) or 0), float(big_blind or 0)
    if line <= 0 or big_blind <= 0:
        return None
    size = float(pot) / big_blind
    return size if size >= line else None


def guarded(observation, params=DEFAULTS):
    """The pot in big blinds when the guard is on for this decision, else None."""
    if observation["street"] == "preflop":
        return None
    size = big_pot(observation["pot"], observation["rules"]["big_blind"], params)
    if size is None or not weak_hand(observation["own_hole"], observation["board"]):
        return None
    return size


def guard_action(observation, action, share, params=DEFAULTS):
    """``action`` under the big-pot guard: in a guarded spot a raise becomes a
    call when the share beats the price (else a fold), a bet over half the
    pot becomes a half-pot bet, and a river bet becomes a check."""
    if not action.startswith("raise_to") or guarded(observation, params) is None:
        return action
    to_call = float(observation["to_call"] or 0)
    if to_call > 0:
        price = to_call / (float(observation["pot"]) + to_call)
        return "check_call" if share >= price + params["margin"] else "fold"
    if observation["street"] == "river":
        return "check_call"
    current = max(float(value) for value in observation["bets"].values())
    put = float(action.partition(":")[2]) - current
    if put <= GUARD_SIZE * float(observation["pot"]) + 1e-9:
        return action
    return raise_toward(observation, GUARD_SIZE) or "check_call"


def unguarded(observation, share, params=DEFAULTS, *, ranges=None, model=None, seed=0):
    """``choose`` without the big-pot guard: with ``sizing`` (the default)
    the most valuable action against the hands that would call it
    (``sized``), else by the share of the pot and the lines (``lines``).
    ``ranges``: the opponents' ranges when already read (read here with
    ``model``, by default the window's reader, otherwise; a decision without
    its hand's history is played by the lines)."""
    if params.get("sizing"):
        if ranges is None and "public_history" in observation:
            ranges = opponent_ranges(observation, model or window_reader())
        action = sized(observation, share, ranges, params, seed) if ranges else None
        if action is not None:
            return action
    return lines(observation, share, params)


def lines(observation, share, params=DEFAULTS):
    """The rule until 2026-10-13: bet or raise when the share of the pot is
    over a line, about two thirds or the whole pot."""
    params = street_params(observation, params)
    line = cuts(observation, params)
    if "bet" in line:
        if share >= line["bet"]:
            return raise_toward(observation, params["size"]) or "check_call"
        return "check_call"
    if share >= line["raise"]:
        return raise_toward(observation, params["raise_size"]) or "check_call"
    return "check_call" if share >= line["call"] else "fold"


@lru_cache(maxsize=1)
def window_reader():
    """The model the live window reads ranges with (``aa_preflop``'s reader),
    so a reading it has done is found in the ranges' cache."""
    return reading_model(True)


def candidates(observation):
    """{action id: chips it puts in} of the bets or raises worth weighing:
    every legal one of at least ``MIN_SIZE`` of the pot after calling, and
    all in."""
    raises = [action for action in observation["legal_actions"]
              if action["kind"] == "raise_to"]
    if not raises:
        return {}
    me = str(observation["observing_seat"])
    mine, to_call = float(observation["bets"][me]), float(observation["to_call"] or 0)
    current = mine + to_call
    base = float(observation["pot"]) + to_call
    top = max(float(action["raise_to"]) for action in raises)
    return {action["id"]: float(action["raise_to"]) - mine for action in raises
            if float(action["raise_to"]) - current >= MIN_SIZE * base - 1e-9
            or float(action["raise_to"]) == top}


@lru_cache(maxsize=256)
def strengths(board, opponents):
    """{(card id, card id), lower first: share of the pot the hand wins against
    ``opponents`` random hands} for every hand the board leaves: the model's
    own measure (``PopulationBot.postflop``), for all hands at once. Each of
    ``RUNOUTS`` boards (the river as it is) ranks every hand; a hand's share
    against one random hand is the share of the other hands it beats, and
    against several that share to their number."""
    rng = random.Random("".join(board) + str(opponents))
    known = [CARD_ID[card] for card in board]
    deck = [CARD_ID[card] for card in DECK if card not in board]
    hands = [tuple(sorted((CARD_ID[key[:2]], CARD_ID[key[2:]]))) for key in all_combos()
             if key[:2] not in board and key[2:] not in board]
    need = 5 - len(board)
    runouts = ([()] if not need else
               [tuple(rng.sample(deck, need)) for _ in range(RUNOUTS)])
    totals, counts = Counter(), Counter()
    for runout in runouts:
        full = (*known, *runout)
        ranked = [(hand, _EVALUATE_7(*hand, *full)) for hand in hands
                  if hand[0] not in runout and hand[1] not in runout]
        order = sorted(rank for _, rank in ranked)
        others = len(order) - 1
        for hand, rank in ranked:
            low, high = bisect_left(order, rank), bisect_right(order, rank)
            beaten = (len(order) - high + (high - low - 1) / 2) / others
            totals[hand] += beaten ** opponents
            counts[hand] += 1
    return {hand: totals[hand] / counts[hand] for hand in totals}


def continue_line(observation, seat, put, after, params=DEFAULTS):
    """The strength (``strengths``) from which ``seat`` goes on (calls or
    raises) when you put ``put`` in, the pot then ``after``; None when it
    goes on with every hand.

    The share of hands that go on is the population's (``population_stats``,
    as the model plays) at the model's size, scaled by
    (1 + that size) / (1 + this size) to the power ``elastic``: a bigger bet
    is called less often; ``sticky`` scales it for players who call more."""
    street, me = observation["street"], observation["observing_seat"]
    history = actions(observation, street) + [(me, "r")]
    aggressor = None
    for player, kind in actions(observation, "preflop"):
        if kind == "r":
            aggressor = player
    spot = postflop_spot(street, history, seat, opponents_in_hand(observation),
                         aggressor)
    row = population_stats().get(spot) or {}
    share = row.get("raise", 0.1) + row.get("call", 0.4)
    call = min(float(observation["bets"][str(me)]) + put
               - float(observation["bets"][str(seat)]),
               float(observation["stacks"][str(seat)]))
    size = call / max(after - call, 1e-9)
    facing = spot.rpartition("|")[2]
    share *= ((1 + REFERENCE[facing]) / (1 + size)) ** params["elastic"]
    return threshold(spot, min(share * params["sticky"], 1.0)), call


def values(observation, ranges, params=DEFAULTS, seed=0):
    """{action id: chips} of checking or calling ("check_call") and of each
    bet or raise (``candidates``), each counted as what comes back to you
    from the pot at the end less what it puts in, or None.

    The opponents' hands are dealt from their ranges (``ranges_equity``) and
    the board run out. A check or call goes to a showdown with everyone. A
    bet or raise is called by the opponents whose hand is strong enough for
    its size (``continue_line``; a raise of theirs is taken as a call); with
    no caller the pot is yours, else the showdown with the callers is for the
    pot and the calls (what you put over the biggest call comes back). An
    opponent all in is in every showdown and puts nothing more in."""
    if not ranges:
        return None
    options = candidates(observation)
    if not options:
        return None
    me = str(observation["observing_seat"])
    board = tuple(observation["board"])
    hero = observation["own_hole"]
    dead = set(hero) | set(board)
    parts = {seat: _Range(weights, dead) for seat, weights in ranges.items()}
    if not all(part.hands for part in parts.values()):
        return None
    pot, to_call = float(observation["pot"]), float(observation["to_call"] or 0)
    mine_in = float(observation["bets"][me])
    strength = strengths(board, min(len(parts), MAX_EQUITY_OPPONENTS))
    lines_of, out = {}, [seat for seat in parts
                         if float(observation["stacks"][str(seat)]) <= 0]
    for action, put in options.items():
        lines_of[action] = {
            seat: continue_line(observation, seat, put, pot + put, params)
            for seat in parts if seat not in out}
    rng = random.Random(seed)
    first, second = (CARD_ID[card] for card in hero)
    known = [CARD_ID[card] for card in board]
    deck = [CARD_ID[card] for card in DECK if card not in dead]
    need = 5 - len(board)
    totals = Counter()
    dealt = 0
    trials = int(params["trials"])
    seats = list(parts)
    for _ in range(trials):
        for _ in range(50):
            hands = [parts[seat].draw(rng) for seat in seats]
            used = {card for hand in hands for card in hand}
            if len(used) == 2 * len(hands):
                break
        else:
            continue
        rest = rng.sample([card for card in deck if card not in used], need)
        full = (*known, *rest)
        mine = _EVALUATE_7(first, second, *full)
        ranks = dict(zip(seats, (_EVALUATE_7(*hand, *full) for hand in hands)))
        held = {seat: tuple(sorted(hand)) for seat, hand in zip(seats, hands)}
        totals["check_call"] += (_won(mine, list(ranks.values())) * (pot + to_call)
                                 - to_call)
        for action, put in options.items():
            callers = [seat for seat, (line, _) in lines_of[action].items()
                       if line is None or strength.get(held[seat], 0.0) >= line]
            calls = [lines_of[action][seat][1] for seat in callers]
            if not callers:
                totals[action] += (pot if not out else
                                   _won(mine, [ranks[seat] for seat in out]) * pot)
                continue
            matched = min(put, max(float(observation["bets"][str(seat)]) + call
                                   for seat, call in zip(callers, calls)) - mine_in)
            totals[action] += (_won(mine, [ranks[seat] for seat in callers + out])
                               * (pot + matched + sum(calls)) - matched)
        dealt += 1
    if dealt < trials / 2:
        return None
    return {action: total / dealt for action, total in totals.items()}


def _won(mine, ranks):
    """Your share of a pot against hands of these ranks (lower is stronger)."""
    if not ranks:
        return 1.0
    best = min(ranks)
    if mine < best:
        return 1.0
    return 1.0 / (1 + ranks.count(mine)) if mine == best else 0.0


def sized(observation, share, ranges, params=DEFAULTS, seed=0):
    """The most valuable action against the hands that would call it
    (``values``), or None when it cannot be worked out. Facing a bet you fold
    when your share of the pot does not pay the price (as ``lines``);
    otherwise a bet or raise is made only when it is worth more than checking
    or calling."""
    worth = values(observation, ranges, params, seed)
    if worth is None:
        return None
    to_call = float(observation["to_call"] or 0)
    if to_call > 0:
        price = to_call / (float(observation["pot"]) + to_call)
        if share < price + params["margin"]:
            return "fold"
    return max(worth, key=lambda action: (worth[action], action == "check_call"))


def from_name(name, make_policy):
    """``range_multiway[@k=v:...]+base`` as a policy."""
    head, _, base = name.partition("+")
    _, _, text = head.partition("@")
    params = {}
    for item in filter(None, text.split(":")):
        key, _, value = item.partition("=")
        params[key] = float(value)
    bot = RangeMultiwayBot(make_policy(base), **params)
    bot.name = name
    return bot


__all__ = ["DEFAULTS", "RangeMultiwayBot", "big_pot", "candidates", "choose",
           "continue_line", "covered", "cuts", "from_name", "guard_action", "guarded",
           "hand_kind", "lines", "sized", "street_params", "strengths", "unguarded",
           "values", "weak_hand", "window_reader"]
