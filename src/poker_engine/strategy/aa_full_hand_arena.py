"""Deterministic offline AA full-hand lab; never a live strategy provider.

PokerKit 0.7.5 controls betting. Bets are integer minimum-chip units; terminal
splits and configured rake use Fraction (synthetic fractional odd-chip model).
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from importlib.metadata import version
import random
from typing import Mapping

from .aa_rules_v2 import AARuleProfileV2, build_forced_bet_plan, estimate_rake


ARENA_VERSION = "aa-full-hand-arena-v1"
SETTLEMENT_MODEL = "EXACT_FRACTIONAL_SPLIT_SIMULATION_NOT_PLATFORM_ODD_CHIPS"
_STREETS = ("preflop", "flop", "turn", "river")


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("money requires an exact decimal string/int/Decimal")
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise ValueError("money must be finite and non-negative")
    return result


def _money(value):
    if isinstance(value, Fraction):
        return str(value)
    return format(value.normalize(), "f") if value else "0"


def _ratio(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fractional_divmod(amount, divisor):
    return Fraction(amount, divisor), 0


@dataclass(frozen=True)
class ArenaAction:
    kind: str
    raise_to: Decimal | None = None

    def __post_init__(self):
        if self.kind not in ("fold", "check_call", "raise_to"):
            raise ValueError("unsupported action kind")
        if self.kind == "raise_to":
            object.__setattr__(self, "raise_to", _decimal(self.raise_to))
        elif self.raise_to is not None:
            raise ValueError("only raise_to actions have an amount")

    @property
    def id(self):
        if self.kind == "raise_to":
            return "raise_to:" + _money(self.raise_to)
        return self.kind

    def to_dict(self):
        return {"id": self.id, "kind": self.kind,
                "raise_to": (_money(self.raise_to)
                             if self.raise_to is not None else None)}

    @classmethod
    def from_id(cls, value):
        if not isinstance(value, str):
            raise ValueError("action must be ArenaAction or string id")
        if value.startswith("raise_to:"):
            return cls("raise_to", _decimal(value.split(":", 1)[1]))
        return cls(value)


class AAFullHandArena:
    """Physical eight-seat table with explicitly occupied 6/7/8 seats.

    The observing API never includes seed, future cards or other hole cards.
    Host code owns simulator internals; untrusted policies must receive only
    the returned observation, not this object. clone() is for offline trainers.
    """

    def __init__(self, rules: AARuleProfileV2, starting_stacks=None,
                 occupied_seats=None, dealer_seat=None, optional_straddler=None):
        if not isinstance(rules, AARuleProfileV2):
            raise TypeError("rules must be AARuleProfileV2")
        if "unverified" in (rules.rake_application, rules.rake_rounding,
                            rules.rake_distribution):
            raise ValueError("unverified rake is not a usable simulation rule")
        if version("pokerkit") != "0.7.5":
            raise RuntimeError("arena requires audited PokerKit 0.7.5")
        self.rules = rules
        self.occupied_seats = tuple(sorted(
            range(rules.table_size) if occupied_seats is None else occupied_seats))
        self.dealer_seat = (self.occupied_seats[-1] if dealer_seat is None
                            else dealer_seat)
        plan = build_forced_bet_plan(
            rules, self.occupied_seats, self.dealer_seat,
            observed_optional_straddler=optional_straddler)
        dealer_index = self.occupied_seats.index(self.dealer_seat)
        # PokerKit index 0 is SB, with BTN last (for >=3 players).
        self._seats = (self.occupied_seats[dealer_index + 1:]
                       + self.occupied_seats[:dealer_index + 1])
        self._straddler = plan.straddler_seat
        if starting_stacks is None:
            starting_stacks = {seat: rules.big_blind * 100
                               for seat in self.occupied_seats}
        elif not isinstance(starting_stacks, Mapping):
            starting_stacks = tuple(starting_stacks)
            if len(starting_stacks) != len(self.occupied_seats):
                raise ValueError("starting stacks require exactly the occupied seats")
            starting_stacks = dict(zip(self.occupied_seats, starting_stacks))
        if set(starting_stacks) != set(self.occupied_seats):
            raise ValueError("starting stacks require exactly the occupied seats")
        self.starting_stacks = {seat: _decimal(starting_stacks[seat])
                                for seat in self.occupied_seats}
        for seat, amount in self.starting_stacks.items():
            if amount <= rules.ante or amount % rules.minimum_chip:
                raise ValueError("stack must cover ante and align to minimum chip")
            if amount < plan.contributions[seat]:
                raise ValueError("short forced blind/straddle is not supported")
        self._state = None
        self._history = []
        self._board_history = []
        self._settlement = None

    def _units(self, amount):
        amount = _decimal(amount)
        if amount % self.rules.minimum_chip:
            raise ValueError("amount is not minimum-chip aligned")
        return int(amount / self.rules.minimum_chip)

    def _chips(self, units):
        return Decimal(units) * self.rules.minimum_chip

    def reset(self, seed, *, deck=None):
        """Reset with local RNG. Explicit 52-card deck is a synthetic test hook."""
        from pokerkit import Automation, Card, Deck, NoLimitTexasHoldem
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        if deck is None:
            cards = list(Deck.STANDARD)
            random.Random(seed).shuffle(cards)
        else:
            cards = list(Card.parse(" ".join(deck)))
            if len(cards) != 52 or set(cards) != set(Deck.STANDARD):
                raise ValueError("explicit deck must contain all 52 unique cards")
        self._deck = cards
        self._deck_cursor = 0
        self._history = []
        self._board_history = []
        self._folded = set()
        self._settlement = None
        antes = self._units(self.rules.ante)
        blinds = [self._units(self.rules.small_blind),
                  self._units(self.rules.big_blind)] + [0] * (len(self._seats) - 2)
        if self._straddler is not None:
            blinds[self._seats.index(self._straddler)] = self._units(
                self.rules.straddle_amount)
        automations = (
            Automation.ANTE_POSTING, Automation.BET_COLLECTION,
            Automation.BLIND_OR_STRADDLE_POSTING,
            Automation.RUNOUT_COUNT_SELECTION,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING, Automation.HAND_KILLING,
        )
        self._state = NoLimitTexasHoldem.create_state(
            automations, True, antes, blinds, self._units(self.rules.big_blind),
            tuple(self._units(self.starting_stacks[s]) for s in self._seats),
            len(self._seats), divmod=_fractional_divmod)
        if self._straddler is not None:
            # PokerKit's default min_bet applies to every street. A live UTG
            # straddle changes only the preflop minimum full raise increment.
            streets = self._state.streets
            self._state.streets = (replace(
                streets[0], min_completion_betting_or_raising_amount=self._units(
                    self.rules.straddle_amount)), *streets[1:])
        self._contributions = [-Fraction(p) for p in self._state.payoffs]
        self._holes = []
        for index in range(len(self._seats)):
            hole = self._take(2)
            self._holes.append(tuple(hole))
            self._state.deal_hole(hole, index)
        self._advance()
        return self

    def _take(self, count):
        result = self._deck[self._deck_cursor:self._deck_cursor + count]
        if len(result) != count:
            raise RuntimeError("private deck exhausted")
        self._deck_cursor += count
        return result

    def _require_reset(self):
        if self._state is None:
            raise RuntimeError("arena must be reset first")

    @property
    def actor(self):
        self._require_reset()
        index = self._state.actor_index
        return None if index is None else self._seats[index]

    @property
    def terminal(self):
        self._require_reset()
        return not self._state.status

    @property
    def street(self):
        self._require_reset()
        index = self._state.street_index
        return _STREETS[index] if index is not None else "terminal"

    def _advance(self):
        state = self._state
        while state.status and state.actor_index is None:
            if state.can_burn_card():
                state.burn_card(self._take(1)[0])
            elif state.can_deal_board():
                cards = self._take(state.board_dealing_count)
                street = self.street
                state.deal_board(cards)
                self._board_history.append({
                    "street": street, "cards": [repr(card) for card in cards],
                })
            elif state.can_push_chips():
                state.push_chips()
            elif state.can_pull_chips():
                state.pull_chips()
            else:
                raise RuntimeError("unsupported non-actor PokerKit phase")
        if not state.status:
            self._settle()

    def legal_actions(self):
        self._require_reset()
        if self.terminal:
            return ()
        state = self._state
        result = []
        if state.can_fold():
            result.append(ArenaAction("fold"))
        if state.can_check_or_call():
            result.append(ArenaAction("check_call"))
        low = state.min_completion_betting_or_raising_to_amount
        high = state.max_completion_betting_or_raising_to_amount
        if low is not None and high is not None:
            call = state.checking_or_calling_amount
            pot = sum(-p for p in state.payoffs)
            current_bet = max(state.bets)
            candidates = (low, current_bet + (pot + call) // 2,
                          current_bet + pot + call, high)
            amounts = sorted({int(min(high, max(low, amount)))
                              for amount in candidates})
            result.extend(ArenaAction("raise_to", self._chips(amount))
                          for amount in amounts
                          if state.can_complete_bet_or_raise_to(amount))
        return tuple(result)

    def step(self, action):
        self._require_reset()
        if not isinstance(action, ArenaAction):
            action = ArenaAction.from_id(action)
        if self.terminal:
            raise ValueError("cannot act after terminal")
        state = self._state
        index, street = state.actor_index, self.street
        actor = self._seats[index]
        paid = 0
        # Verify completely before mutating state (including off-grid raises).
        if action.kind == "raise_to":
            units = self._units(action.raise_to)
            state.verify_completion_betting_or_raising_to(units)
            paid = units - state.bets[index]
            state.complete_bet_or_raise_to(units)
        elif action.kind == "fold":
            state.verify_folding()
            state.fold()
            self._folded.add(actor)
        else:
            state.verify_checking_or_calling()
            paid = state.checking_or_calling_amount
            state.check_or_call()
        self._contributions[index] += paid
        self._history.append({"index": len(self._history), "actor": actor,
                              "street": street, **action.to_dict(),
                              "paid": _money(self._chips(paid))})
        self._advance()
        return self

    def observe(self, seat):
        self._require_reset()
        if seat not in self.occupied_seats:
            raise ValueError("observer must occupy a dealt seat")
        state = self._state
        index = self._seats.index(seat)
        is_actor = seat == self.actor
        return {
            "schema_version": 1, "arena_version": ARENA_VERSION,
            "settlement_model": SETTLEMENT_MODEL,
            "strategy_eligible": False, "simulation_only": True,
            "rules_fingerprint": self.rules.fingerprint,
            "rules": self.rules.to_dict(), "table_size": self.rules.table_size,
            "big_blind": _money(self.rules.big_blind),
            "observing_seat": seat, "actor": self.actor,
            "occupied_seats": list(self.occupied_seats),
            "dealer_seat": self.dealer_seat, "straddler_seat": self._straddler,
            "street": self.street,
            "terminal": self.terminal,
            "own_hole": [repr(card) for card in self._holes[index]],
            "board": [repr(card) for row in state.board_cards for card in row],
            # Recorded when dealt, never reconstructed from a final board.
            "board_history": deepcopy(self._board_history),
            "stacks": {str(s): _money(Fraction(self.starting_stacks[s])
                                      + self._settlement["returns"][s])
                       if self.terminal else _money(self._chips(state.stacks[i]))
                       for i, s in enumerate(self._seats)},
            "starting_stacks": {str(s): _money(v)
                                for s, v in self.starting_stacks.items()},
            "bets": {str(s): _money(self._chips(state.bets[i]))
                     for i, s in enumerate(self._seats)},
            "folded": sorted(self._folded),
            "all_in": sorted(s for i, s in enumerate(self._seats)
                             if state.stacks[i] == 0 and s not in self._folded),
            "contributions": {
                str(s): _money(self._chips(int(self._contributions[i])))
                for i, s in enumerate(self._seats)
            },
            "betting": {
                "can_raise": bool(is_actor and state.can_complete_bet_or_raise_to()),
                "min_raise_to": _money(self._chips(
                    state.min_completion_betting_or_raising_to_amount))
                if is_actor and state.min_completion_betting_or_raising_to_amount
                is not None else None,
                "max_raise_to": _money(self._chips(
                    state.max_completion_betting_or_raising_to_amount))
                if is_actor and state.max_completion_betting_or_raising_to_amount
                is not None else None,
                "last_full_raise_increment": _money(self._chips(
                    state.completion_betting_or_raising_amount)),
                "acted_since_full_raise": sorted(
                    self._seats[i] for i in state.acted_player_indices),
                "pending_actors": [self._seats[i] for i in state.actor_indices],
                "consecutive_short_raise_increments": [
                    _money(self._chips(value)) for value in
                    state.consecutive_all_in_completion_betting_or_raising_amounts
                ],
            },
            "pot": _money(self._chips(sum(-p for p in state.payoffs)))
            if not self.terminal else "0",
            "to_call": _money(self._chips(state.checking_or_calling_amount))
            if is_actor else None,
            "public_history": deepcopy(self._history),
            "legal_actions": [a.to_dict() for a in self.legal_actions()]
            if is_actor else [],
        }

    def _settle(self):
        from pokerkit import StandardHighHand
        contributions = self._contributions
        unit = Fraction(self.rules.minimum_chip)
        credits = [Fraction(0)] * len(self._seats)
        refunds = [Fraction(0)] * len(self._seats)
        layers = []
        prior = Fraction(0)
        board = [card for row in self._state.board_cards for card in row]
        for threshold in sorted(set(contributions)):
            contributors = [i for i, value in enumerate(contributions)
                            if value >= threshold]
            amount = (threshold - prior) * len(contributors)
            prior = threshold
            if not amount:
                continue
            if len(contributors) == 1:
                refunds[contributors[0]] += amount
                continue
            eligible = [i for i in contributors
                        if self._seats[i] not in self._folded]
            if not eligible:
                raise RuntimeError("pot has no eligible player")
            if len(eligible) == 1:
                winners = eligible
            else:
                hands = {i: StandardHighHand.from_game(self._holes[i], board)
                         for i in eligible}
                best = max(hands.values())
                winners = [i for i in eligible if hands[i] == best]
            layers.append((amount, winners))
            for i in winners:
                credits[i] += amount / len(winners)
        gross = [credits[i] + refunds[i] - contributions[i]
                 for i in range(len(self._seats))]
        if gross != list(self._state.payoffs):
            raise RuntimeError("settlement ledger disagrees with PokerKit gross")
        total_pot = sum((amount for amount, _ in layers), Fraction(0)) * unit
        pot_decimal = (Decimal(total_pot.numerator)
                       / Decimal(total_pot.denominator))
        estimate = estimate_rake(self.rules, str(pot_decimal),
                                 saw_flop=len(board) >= 3)
        if estimate.amount is None:
            raise RuntimeError("rake unavailable")
        total_rake = Fraction(estimate.amount)
        remaining = total_rake
        deductions = [Fraction(0)] * len(self._seats)
        pot_rows = []
        for amount, winners in layers:
            chips = amount * unit
            if self.rules.rake_distribution == "proportional_all_pots":
                rake = total_rake * chips / total_pot if total_pot else Fraction(0)
            else:
                rake = min(chips, remaining)
                remaining -= rake
            for i in winners:
                deductions[i] += rake / len(winners)
            pot_rows.append({"amount": _ratio(chips), "rake": _ratio(rake),
                             "winners": [self._seats[i] for i in winners]})
        returns = {seat: gross[i] * unit - deductions[i]
                   for i, seat in enumerate(self._seats)}
        if sum(returns.values()) + total_rake != 0:
            raise RuntimeError("settlement does not conserve chips")
        self._settlement = {"returns": returns, "rake": total_rake,
                            "pots": pot_rows,
                            "refunds": {seat: refunds[i] * unit
                                        for i, seat in enumerate(self._seats)}}

    def terminal_returns(self):
        if not self.terminal:
            raise ValueError("terminal returns are unavailable before settlement")
        return dict(self._settlement["returns"])

    def terminal_result(self):
        returns = self.terminal_returns()
        return {"schema_version": 1, "settlement_model": SETTLEMENT_MODEL,
                "rules_fingerprint": self.rules.fingerprint,
                "strategy_eligible": False, "empirical_status": "NOT_ASSESSED",
                "returns": {str(k): _ratio(v) for k, v in returns.items()},
                "rake": _ratio(self._settlement["rake"]),
                "refunds": {str(k): _ratio(v) for k, v in
                            self._settlement["refunds"].items()},
                "pots": deepcopy(self._settlement["pots"])}

    def clone(self):
        self._require_reset()
        return deepcopy(self)
