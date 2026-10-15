"""The chips you can win at a decision after the flop: main pot, side pots, rake.

The range rule (``multiway_bot``) weighed your share of beating every
opponent against the whole pot, and called when that share beat
``to_call / (pot + to_call)``. With stacks of different depths that is wrong
in two ways, and rake makes it a third (audit 2026-10-14, S1 and S5):

* chips you cannot match are not yours to win: facing a bet above your stack
  you call all in for less, and the rest goes back to the bettor or into a
  side pot between the others. Counting them made a call look cheap: 50 to
  call into 600 is a price of 8%, against the 200 you can win it is 25%;
* an opponent all in for less can win only the pots up to its chips: above
  them your share is against the others only;
* the table takes rake (AA: 5%, at most 5 big blinds a hand), so a call wins
  back less than the pot.

``pots`` splits the chips you can win if you call (or check) the way the
table settles them (``AAFullHandArena._settle``): each level where an
opponent's chips run out starts a new pot, and an opponent can win the chips
up to what it has in plus its stack. The live window leaves a stack it has
not read deep, so an opponent not read covers every pot, as before. Money in
the pot no seat's chips account for (the window's pot read above the
replay's) is in the main pot. Rake comes off every pot in proportion
(``rake_distribution`` "proportional_all_pots"); chips nobody else matched go
back to their owner unraked.

Without a side pot and without rake, ``pots`` is the whole pot against every
opponent and ``price`` is ``to_call / (pot + to_call)``: what the rule used.
"""

from __future__ import annotations

from .preflop_policy import rake

EPSILON = 1e-9


def _chips(values):
    return {int(seat): float(value) for seat, value in (values or {}).items()}


def opponents(observation):
    me = observation["observing_seat"]
    folded = set(observation["folded"])
    return [seat for seat in observation["occupied_seats"]
            if seat != me and seat not in folded]


def _put(observation):
    """{seat: chips in this hand} once you call, and the money the seats'
    chips do not account for; None without the seats' chips."""
    put = _chips(observation.get("contributions"))
    if not put:
        return None
    me = observation["observing_seat"]
    extra = max(0.0, float(observation["pot"]) - sum(put.values()))
    put[me] = put.get(me, 0.0) + float(observation["to_call"] or 0)
    return put, extra


def pots(observation):
    """[(chips, opponents who can win them too)] of the chips you can win if
    you call or check, main pot first, before rake."""
    rivals = opponents(observation)
    found = _put(observation)
    if found is None:
        pot = float(observation["pot"]) + float(observation["to_call"] or 0)
        return [(pot, tuple(rivals))]
    put, extra = found
    stacks = _chips(observation.get("stacks"))
    mine = put[observation["observing_seat"]]
    reach = {seat: put.get(seat, 0.0) + stacks.get(seat, float("inf"))
             for seat in rivals}
    levels = sorted({value for value in reach.values() if value < mine} | {mine})
    layers, low = [], 0.0
    for level in levels:
        chips = sum(min(value, level) - min(value, low) for value in put.values())
        if not layers:
            chips += extra
        if chips > EPSILON:
            layers.append((chips, tuple(seat for seat in rivals
                                        if reach[seat] >= level - EPSILON)))
        low = level
    return layers


def kept(observation):
    """The share of the pot the winners keep after rake, once you call."""
    found = _put(observation)
    rules = observation.get("rules") or {}
    if found is None or not float(rules.get("rake_percent") or 0):
        return 1.0
    put, extra = found
    values = sorted(put.values(), reverse=True) + [0.0]
    # Chips above what anyone else put in go back to their owner, unraked.
    contested = sum(min(value, values[1]) for value in put.values()) + extra
    if contested <= EPSILON:
        return 1.0
    return 1.0 - rake(observation, contested) / contested


def matched(observation):
    """The chips you can win if you call or check, before rake: what every
    seat has in, up to what you will have in, and the money no seat's chips
    account for."""
    found = _put(observation)
    if found is None:
        return float(observation["pot"]) + float(observation["to_call"] or 0)
    put, extra = found
    mine = put[observation["observing_seat"]]
    return sum(min(value, mine) for value in put.values()) + extra


def winnable(observation):
    """The chips you can win if you call or check, after rake."""
    return matched(observation) * kept(observation)


def price(observation):
    """The share of what you can win that a call costs (0 with nothing to call)."""
    to_call = float(observation["to_call"] or 0)
    if to_call <= 0:
        return 0.0
    return to_call / winnable(observation)


__all__ = ["kept", "matched", "opponents", "pots", "price", "winnable"]
