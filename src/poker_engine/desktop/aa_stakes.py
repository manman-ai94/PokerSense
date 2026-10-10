"""The table's stakes (盲注级别), told from the chips on the table each hand.

AA tables come in levels written "1/2/4(2)": small blind 1, big blind 2, a
forced straddle of 4 from the seat after the big blind, and an ante of 2 from
every player. The advice, the grading and every big-blind figure used to take
1/2/4(2) from ``configs/game/aa-scoreboard-rules-v2.json`` (the scoreboard's
rule set, which stays as it is); at a 2/4 table each of them was off by two.

Every hand shows its forced bets on the table before the first action (the
frame logs of 10/07 to 10/09): first the antes, the same amount in front of
every seat for a moment, then the small blind, the big blind and the straddle
in front of three seats in a row (1, 2 and 4). ``detect_stakes`` reads them:

- **blinds**: three seats in a row (in the hand's seat order) with x, 2x and
  4x in front, the AA structure; the amount seen in the most frames wins.
  Another structure is not taken (a misread digit does not make a level);
- **ante**: the same amount in front of every one of three or more seats in a
  frame before the blinds show; when no such frame was read, the opening pot
  less the blinds and straddle, shared out evenly among the players (whole
  chips only). Neither: the ante is unknown.

``settle_stakes`` decides the hand's stakes from that and the stakes the
earlier hands settled on: seen in full this hand, those ("table"); the same
blinds with the ante unread, or nothing seen (a bomb pot shows no blinds, a
hand joined midway shows none either), the earlier ones ("carried"); blinds
of another level with the ante unread, or nothing seen yet in this
observation, the earlier ones or 1/2/4(2), marked "unsure" so the window says
the level is not settled. The ante is never guessed from the blinds.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys

# The packaged app keeps its configs next to its code, under _MEIPASS.
RULES_PATH = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
              / "configs/game/aa-scoreboard-rules-v2.json")
AMOUNTS = ("small_blind", "big_blind", "straddle_amount", "ante")
ANTE_SEATS = 3                      # seats with the same bet for an ante frame


def default_stakes():
    """The 1/2/4(2) of the shared rule set, "unsure": nothing read yet."""
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return {**{key: Decimal(raw[key]) for key in AMOUNTS}, "source": "unsure"}


def _wagers(fields):
    return {int(seat): Decimal(value)
            for seat, value in (fields.get("street_wagers") or {}).items()
            if value not in (None, "")}


def _blinds(wagers, seats):
    """The small blind of the x, 2x, 4x on three seats in a row, or None."""
    ring = seats if len(seats) >= 3 else sorted(wagers)
    for at, seat in enumerate(ring):
        small = wagers.get(seat)
        if not small or small <= 0:
            continue
        big = wagers.get(ring[(at + 1) % len(ring)])
        straddle = wagers.get(ring[(at + 2) % len(ring)])
        if big == 2 * small and straddle == 4 * small:
            return small
    return None


def detect_stakes(fields, seats, opening_pot=None):
    """{small_blind, big_blind, straddle_amount, ante} from the frames of one
    hand before its first action (``fields``, oldest first), ``ante`` None
    when unread; None when no blinds of the AA structure are seen.
    ``seats``: the seats in the hand, in order."""
    seats = sorted(seats)
    smalls, antes, first_blind = Counter(), Counter(), None
    for index, f in enumerate(fields):
        wagers = _wagers(f)
        if not wagers:
            continue
        small = _blinds(wagers, seats)
        if small is not None:
            smalls[small] += 1
            first_blind = index if first_blind is None else first_blind
            continue
        values = set(wagers.values())
        if (first_blind is None and len(wagers) >= ANTE_SEATS and len(values) == 1
                and next(iter(values)) > 0):
            antes[next(iter(values))] += 1
    if not smalls:
        return None
    small = max(smalls, key=lambda value: (smalls[value], -value))
    found = {"small_blind": small, "big_blind": 2 * small,
             "straddle_amount": 4 * small, "ante": None}
    if antes:
        found["ante"] = max(antes, key=lambda value: (antes[value], -value))
    elif opening_pot is not None and seats:
        rest = Decimal(opening_pot) - 7 * small
        if rest > 0 and rest % len(seats) == 0:
            found["ante"] = rest / len(seats)
    return found


def settle_stakes(found, earlier=None):
    """The hand's stakes from what it showed (``detect_stakes``) and the
    stakes earlier hands settled on (None: nothing seen yet); see the module
    notes. A dict of ``AMOUNTS`` plus "source": table, carried or unsure."""
    earlier = earlier or default_stakes()
    if found is not None and found["ante"] is not None:
        return {**found, "source": "table"}
    seen = earlier["source"] != "unsure"
    if found is None or found["big_blind"] == earlier["big_blind"]:
        return {**earlier, "source": "carried" if seen else "unsure"}
    return {**earlier, "source": "unsure"}


def stakes_label(stakes):
    """The level as AA writes it: "1/2/4(2)"."""
    def text(value):
        return format(Decimal(value).normalize(), "f")
    return (f"{text(stakes['small_blind'])}/{text(stakes['big_blind'])}/"
            f"{text(stakes['straddle_amount'])}({text(stakes['ante'])})")


def stakes_report(stakes):
    """The stakes for the window: chips as text, the label and the source."""
    return {**{key: format(Decimal(stakes[key]).normalize(), "f") for key in AMOUNTS},
            "label": stakes_label(stakes), "source": stakes["source"]}


__all__ = ["AMOUNTS", "RULES_PATH", "default_stakes", "detect_stakes",
           "settle_stakes", "stakes_label", "stakes_report"]
