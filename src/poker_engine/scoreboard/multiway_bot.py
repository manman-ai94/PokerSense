"""After the flop with two or more opponents: play by equity against their ranges.

``range_multiway+aa_preflop`` plays like its base policy everywhere except
postflop decisions with more than one opponent. There every opponent's range
is read from their actions with the population model and your share of the
pot against those ranges is worked out (``ranges``); then

- facing a bet: raise about the pot when the share is at least ``raise``,
  call when it beats the price by ``margin``, otherwise fold;
- with nothing to call: bet when the share is at least ``bet``, otherwise
  check; about two thirds of the pot (``size``) against two opponents, the
  pot (``size3``) against three or more.

The share and the price are of the chips you can win (``side_pots``, since
2026-10-15): with an opponent all in for less, your share of each side pot
is against the players in it; facing a bet above your stack, the chips you
cannot match are not in the price; and the price is of the pot after rake.
Before, the share was of beating everyone and the price
``to_call / (pot + to_call)``, which is what this still is with stacks of one
depth and no rake.

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

``implied`` (off at 0): a draw's implied odds. On the flop or the turn,
holding at least ``outs`` cards that make you a straight or a flush, a call
is priced as if that share of the chips still behind were in the pot too
(yours after calling, at most the most an opponent still in has behind): a
draw hit wins more on the later streets than the pot now; without it a
draw just short of the price folds however deep the stacks are. A candidate
for the scoreboard league; the live rough rule counts it the same way.

Parameters can follow the name, for example
``range_multiway@bet=0.55:raise=0.7:margin=0.05+aa_preflop`` (":" between
them: "," separates strategies on the command line).
"""

from __future__ import annotations

from collections import Counter

from phevaluator import evaluate_cards

from .bots import _Policy, _rng, opponents_in_hand, raise_toward
from .preflop_reading import reading_model, reading_of
from .ranges import opponent_ranges, ranges_equity
from .side_pots import pots, price

DEFAULTS = {"bet": 0.3, "raise": 0.6, "margin": 0.0, "trials": 600,
            "hu": 0.0, "hu_bet": 0.55, "hu_raise": 0.7,
            "size": 0.66, "size3": 1.0, "raise_size": 1.0, "guard": 30.0,
            "implied": 0.0, "outs": 8}
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
                                 seed=rng.randrange(2 ** 31), pots=pots(observation))
        if share is None:
            self.counts["no_equity"] += 1
            return self.base.decide(observation, rng)
        self.counts["decided"] += 1
        return choose(observation, share, self.params)


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
    return {"call": implied_price(observation, params) + params["margin"],
            "raise": params["raise"]}


def implied_price(observation, params=DEFAULTS):
    """``side_pots.price`` with a draw's implied odds: on the flop or the turn,
    holding at least ``outs`` cards that make you a straight or a flush, a
    call is priced as if ``implied`` of the chips still behind (yours after
    calling, at most the most an opponent still in has behind) were in the
    pot too. Off (0) by default."""
    base = price(observation)
    extra = implied_chips(observation, params)
    if not base or not extra:
        return base
    to_call = float(observation["to_call"])
    return to_call / (to_call / base + extra)


def implied_chips(observation, params=DEFAULTS):
    """The chips ``implied_price`` adds to the pot: 0 when it does not apply."""
    share = float(params.get("implied", 0) or 0)
    if share <= 0 or observation["street"] not in ("flop", "turn"):
        return 0.0
    if draw_outs(observation["own_hole"], observation["board"]) < params["outs"]:
        return 0.0
    stacks = {str(seat): float(value)
              for seat, value in (observation.get("stacks") or {}).items()}
    me = str(observation["observing_seat"])
    mine = stacks.get(me, 0.0) - float(observation["to_call"] or 0)
    theirs = [stacks.get(str(seat), 0.0) for seat in observation["occupied_seats"]
              if str(seat) != me and seat not in observation["folded"]]
    return share * max(0.0, min(mine, max(theirs, default=0.0)))


DRAWN = ("straight", "flush", "straight_flush")


def draw_outs(hole, board):
    """The cards still unseen that would make you a straight or a flush with
    one of your own cards, where you do not have one yet and the board would
    not make it by itself."""
    hole, board = list(hole), [card for card in board if card]
    if len(board) not in (3, 4) or ORDER.index(hand_kind(hole + board)) >= ORDER.index(
            "straight"):
        return 0
    seen = set(hole) | set(board)
    count = 0
    for card in (rank + suit for rank in "23456789TJQKA" for suit in "cdhs"):
        if card in seen or hand_kind(hole + board + [card]) not in DRAWN:
            continue
        if len(board) == 4 and hand_kind(board + [card]) in DRAWN:
            continue
        count += 1
    return count


def choose(observation, share, params=DEFAULTS):
    """The action id for your share of the pot against the field, with the
    big-pot guard (``guard_action``)."""
    action = unguarded(observation, share, params)
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
        enough = share >= price(observation) + params["margin"]
        return "check_call" if enough else "fold"
    if observation["street"] == "river":
        return "check_call"
    current = max(float(value) for value in observation["bets"].values())
    put = float(action.partition(":")[2]) - current
    if put <= GUARD_SIZE * float(observation["pot"]) + 1e-9:
        return action
    return raise_toward(observation, GUARD_SIZE) or "check_call"


def unguarded(observation, share, params=DEFAULTS):
    """``choose`` without the big-pot guard."""
    params = street_params(observation, params)
    line = cuts(observation, params)
    if "bet" in line:
        if share >= line["bet"]:
            return raise_toward(observation, params["size"]) or "check_call"
        return "check_call"
    if share >= line["raise"]:
        return raise_toward(observation, params["raise_size"]) or "check_call"
    return "check_call" if share >= line["call"] else "fold"


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


__all__ = ["DEFAULTS", "RangeMultiwayBot", "big_pot", "choose", "covered", "cuts",
           "from_name", "guard_action", "guarded", "hand_kind", "street_params",
           "unguarded", "weak_hand"]
