"""Bomb pots (暴击) on the scoreboard.

AA tables can turn bomb pots on for a while ("暴击:7BB"): every player puts in
the set amount, there is no preflop betting and the hand starts on the flop
(on a 2026-09-09 recording a bomb pot opened with 98 = 7 players x 7 big
blinds; about 7% of peng's hands on 2026-10-07 were bomb pots). The arena
deals one with ``reset(seed, bomb=chips)``; observations then carry
``bomb_pot`` (chips each player put in), no preflop history and no
straddler.

With ``Bomb`` the scoreboard makes a share of its deals bomb pots, the same
deals for every strategy and seat, and splits each result into normal hands
and bomb pots (``by_kind``). ``share=1`` scores bomb pots alone.
"""

from __future__ import annotations

from dataclasses import dataclass
import random

KINDS = ("normal", "bomb")
SHARE = 0.07                # of peng's hands on 2026-10-07


@dataclass(frozen=True)
class Bomb:
    post: float = 7.0       # big blinds every player puts in
    share: float = SHARE    # share of deals that are bomb pots

    def __post_init__(self):
        if self.post <= 0 or not 0 < self.share <= 1:
            raise ValueError("a bomb pot needs a positive post and 0 < share <= 1")

    def chips(self, seed, big_blind):
        """Each player's post in chips (a string, as the arena takes money) when
        deal ``seed`` is a bomb pot, else None."""
        if random.Random(seed * 6_271 + 5).random() < self.share:
            return f"{self.post * big_blind:g}"
        return None

    def to_dict(self):
        return {"post_big_blinds": self.post, "share": self.share}


__all__ = ["Bomb", "KINDS", "SHARE"]
