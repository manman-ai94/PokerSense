"""What AA's all-in insurance is worth, from the odds table at the table.

After everyone is all in, the player ahead may insure against the cards that
would beat them (``docs/aa-table-rules.zh-CN.md``). The premium comes out of
the pot; when one of the bought outs comes, the table pays premium x odds,
otherwise the premium is gone. That reading matches the one reviewed hand
(``tests/fixtures/aa_reference_hands/insurance_32880_v1.json``: 174 x 1.8 is
the 313 shown). So each chip of premium returns ``outs / unseen x odds`` on
average, and the table's odds are below the fair ``(unseen - outs) / outs``:
insurance gives chips away. With no other cards shown (42 to 45 unseen) it
loses 24% to 54% of the premium; a premium returned on a hit as well would
still lose. The odds are the table's own help page; outs over 16 cannot be
bought.
"""

from __future__ import annotations

ODDS = {1: 30.0, 2: 16.0, 3: 10.0, 4: 8.0, 5: 6.0, 6: 5.0, 7: 4.0, 8: 3.5,
        9: 3.0, 10: 2.5, 11: 2.2, 12: 2.0, 13: 1.8, 14: 1.6, 15: 1.4, 16: 1.3}
MAX_PLAYERS = 3                     # more players in the pot: no insurance


def premium_return(outs, unseen, *, premium_back=False):
    """Chips back on average per chip of premium (below 1 loses)."""
    if outs not in ODDS:
        raise ValueError("insurance is sold for 1 to 16 outs")
    if not outs < unseen <= 52:
        raise ValueError("more unseen cards than outs are needed")
    return outs / unseen * (ODDS[outs] + (1.0 if premium_back else 0.0))


def unseen_cards(board, players, shown=0):
    """Cards not seen by anyone with ``board`` cards out and every hand in
    the pot face up (all in), plus ``shown`` other cards turned over."""
    return 52 - board - 2 * players - shown


def loss_range(players=(2, MAX_PLAYERS), boards=(3, 4), shown=0):
    """The smallest and largest share of the premium lost on average."""
    losses = [1.0 - premium_return(outs, unseen_cards(board, count, shown))
              for outs in ODDS for count in players for board in boards]
    return min(losses), max(losses)


__all__ = ["ODDS", "MAX_PLAYERS", "loss_range", "premium_return", "unseen_cards"]
