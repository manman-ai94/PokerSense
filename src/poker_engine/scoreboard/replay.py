"""Replay a hand's public actions to see what each player saw when acting.

An observation carries the rules, seats, dealer, board and public history of
the hand, which is everything that decided how the betting went. Dealing the
same board from an explicit deck and repeating the actions rebuilds, for every
past action, the observation its actor had then (with someone else's hole
cards, which callers replace). Ranges come from asking a policy, for every
possible hand, whether it would have acted the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .spots import KINDS
from .strength import DECK


@dataclass(frozen=True)
class Decision:
    seat: int
    street: str
    observation: dict
    action: dict

    @property
    def kind(self):
        return KINDS[self.action["kind"]]


def replay_deck(board_history, seats):
    """A deck that deals these board cards; the hole cards are placeholders."""
    board = [card for row in board_history for card in row["cards"]]
    rest = [card for card in DECK if card not in board]
    deck, rest = rest[:2 * seats], rest[2 * seats:]
    for row in board_history:
        deck += [rest.pop(0), *row["cards"]]          # burn, then the street
    return deck + rest


def public_replay(observation):
    """Every past action of the hand with the observation its actor had."""
    rules = AARuleProfileV2.from_dict(observation["rules"])
    stacks = {int(seat): Decimal(value)
              for seat, value in observation["starting_stacks"].items()}
    arena = AAFullHandArena(rules, starting_stacks=stacks,
                            occupied_seats=observation["occupied_seats"],
                            dealer_seat=observation["dealer_seat"])
    arena.reset(0, deck=replay_deck(observation["board_history"],
                                    len(observation["occupied_seats"])))
    decisions = []
    for row in observation["public_history"]:
        seat = arena.actor
        if seat != row["actor"]:
            raise ValueError(f"replay expected seat {row['actor']}, arena has {seat}")
        decisions.append(Decision(seat, row["street"], arena.observe(seat), row))
        arena.step(row["id"])
    return decisions


def with_hole(observation, cards):
    """The same observation as if its owner held ``cards``."""
    return {**observation, "own_hole": list(cards)}


def kind_of(action_id):
    if action_id == "fold":
        return "f"
    return "r" if action_id.startswith("raise_to") else "c"


__all__ = ["Decision", "kind_of", "public_replay", "replay_deck", "with_hole"]
