"""A bot that plays like the real player population in the PHH dataset.

Before the flop it uses the measured frequencies directly: in a spot where
players raise r and call c of the time, it raises its strongest r of hands,
calls the next c and folds the rest, cutting by single combinations so the
shares come out exact. Its hand is random at a first decision, so a share of
hands is a share of decisions. At a later decision (opened and now re-raised,
limped and now raised ...) the same shares apply within the range it got
there with, which its own earlier decisions define.

After the flop the measured frequency of each decision is turned into an
equity threshold. The thresholds come from a calibration run of this bot
(``tools/calibrate_population_bot.py``): the equity it had at each kind of
decision is recorded, and "bet 71% of the time" becomes "bet with the top
71% of the equities seen there".

The 2009 games had no antes or straddles. On the AA table the forced
straddler acts last before the flop with the full blind in, like a big
blind, so it uses the big blind's frequencies; the big blind has half of it
in and one player behind, like a small blind, so it uses the small blind's.
Other seats use the position with the same number of seats to the button.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json

from poker_engine.core.enums import Position

from .bots import (MAX_EQUITY_OPPONENTS, POSTFLOP_TRIALS, _Policy, opponents_in_hand,
                   passive, position, raise_toward)
from .spots import KINDS, postflop_spot, preflop_spot
from .strength import combo_percentile, equity

STATS_FILE = "phh_population_stats_v1.json"
CALIBRATION_FILE = "population_bot_v1.json"
GROUP = "7-9"

NAMES = {Position.BTN: "BTN", Position.CO: "CO", Position.HJ: "HJ",
         Position.LJ: "LJ", Position.UTG1: "EP", Position.UTG: "EP",
         Position.SB: "SB", Position.BB: "BB"}


def _data(name):
    return resources.files("poker_engine.scoreboard").joinpath(name)


@lru_cache(maxsize=1)
def population_stats():
    report = json.loads(_data(STATS_FILE).read_text(encoding="utf-8"))
    return report["frequencies"][GROUP]


@lru_cache(maxsize=1)
def calibration():
    data = _data(CALIBRATION_FILE)
    if not data.is_file():
        return {}
    return json.loads(data.read_text(encoding="utf-8"))["quantiles"]


def stats_position(observation):
    """Position whose real-player frequencies this seat uses before the flop."""
    seat_position = position(observation)
    if observation.get("straddler_seat") is not None:
        if observation["observing_seat"] == observation["straddler_seat"]:
            return "BB"
        if seat_position == Position.BB:
            return "SB"
    return NAMES[seat_position]


def actions(observation, street):
    return [(row["actor"], KINDS[row["kind"]]) for row in observation["public_history"]
            if row["street"] == street]


def preflop_shares(name, spot):
    """(raise, call) shares of real players at this position and spot."""
    stats = population_stats()
    row = stats.get(f"{name}|{spot}") or stats.get(f"ALL|{spot}") or {}
    return row.get("raise", 0.0), row.get("call", 0.0)


def preflop_band(observation, name):
    """The range the seat's own earlier preflop decisions leave it with.

    A range is a band of hand percentiles (0 = strongest). Each decision splits
    the band in raise, call and fold parts; the action taken keeps one part.
    """
    me = observation["observing_seat"]
    history = actions(observation, "preflop")
    low, high = 0.0, 1.0
    for index, (player, kind) in enumerate(history):
        if player != me:
            continue
        spot = preflop_spot(history[:index], me)
        raise_share, call_share = preflop_shares(name, spot)
        width = high - low
        if kind == "r":
            high = low + raise_share * width
        else:
            low, high = (low + raise_share * width,
                         low + (raise_share + call_share) * width)
    return low, high


def postflop_situation(observation):
    me, street = observation["observing_seat"], observation["street"]
    aggressor = None
    for player, kind in actions(observation, "preflop"):
        if kind == "r":
            aggressor = player
    return postflop_spot(street, actions(observation, street), me,
                         opponents_in_hand(observation), aggressor)


def fallbacks(spot):
    """Pooled spots to use when a spot is too rare to calibrate, nearest first.

    The same street and facing with both roles pooled, then both widths
    (equity against more players runs lower, so width is kept first), then
    the whole street at that width.
    """
    street, width, _, facing = spot.split("|")
    return (f"{street}|{width}|{facing}", f"{street}|{facing}", f"{street}|{width}")


def threshold(spot, share):
    """Equity above which a decision taken ``share`` of the time is taken."""
    table = calibration()
    quantiles = next((table[key] for key in (spot, *fallbacks(spot)) if key in table),
                     None)
    if not quantiles:
        return None
    share = min(max(share, 0.0), 1.0)
    return quantiles[round((len(quantiles) - 1) * (1 - share))]


class PopulationBot(_Policy):
    name = "population"

    def __init__(self, recorder=None):
        self.recorder = recorder      # calibration: collects (spot, equity, action)

    def decide(self, observation, rng):
        if observation["street"] == "preflop":
            return self.preflop(observation)
        return self.postflop(observation, rng)

    def preflop(self, observation):
        name = stats_position(observation)
        me = observation["observing_seat"]
        spot = preflop_spot(actions(observation, "preflop"), me)
        raise_share, call_share = preflop_shares(name, spot)
        low, high = preflop_band(observation, name)
        share = combo_percentile(observation["own_hole"])
        place = (share - low) / (high - low) if high > low else 1.0
        if place <= raise_share:
            size = 0.5 if spot in ("rfi", "vs_limp") else 1.0
            return raise_toward(observation, size) or "check_call"
        if place <= raise_share + call_share:
            return "check_call"
        return passive(observation)

    def postflop(self, observation, rng):
        spot = postflop_situation(observation)
        row = population_stats().get(spot) or {}
        win = equity(observation["own_hole"], observation["board"],
                     min(opponents_in_hand(observation), MAX_EQUITY_OPPONENTS),
                     POSTFLOP_TRIALS, rng)
        if spot.endswith("checked_to"):
            bet = threshold(spot, row.get("bet", 0.35))
            action = "bet" if bet is not None and win >= bet else "check"
        else:
            raise_share = row.get("raise", 0.1)
            raise_at = threshold(spot, raise_share)
            call_at = threshold(spot, raise_share + row.get("call", 0.4))
            action = ("raise" if raise_at is not None and win >= raise_at else
                      "call" if call_at is not None and win >= call_at else "fold")
        if self.recorder is not None:
            self.recorder.append((spot, win, action))
        if action in ("bet", "raise"):
            size = 0.66 if action == "bet" else 1.0
            return raise_toward(observation, size) or "check_call"
        return passive(observation) if action == "fold" else "check_call"


__all__ = ["PopulationBot", "fallbacks", "population_stats", "preflop_band",
           "stats_position", "threshold"]
