"""Exact AA 5-8 player forced-bet and rake rules for shadow strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

from poker_engine.core.enums import Position
from poker_engine.core.value_objects import ChipAmount

from .contracts import GameConfig, GameType


_POSITIONS = {
    5: (Position.BTN, Position.SB, Position.BB, Position.UTG, Position.CO),
    6: (Position.BTN, Position.SB, Position.BB, Position.UTG, Position.HJ,
        Position.CO),
    7: (Position.BTN, Position.SB, Position.BB, Position.UTG, Position.LJ,
        Position.HJ, Position.CO),
    8: (Position.BTN, Position.SB, Position.BB, Position.UTG, Position.UTG1,
        Position.LJ, Position.HJ, Position.CO),
}
_STRADDLE_MODES = {"none", "mandatory_utg", "optional_explicit_utg"}
_ANTE_MODES = {"none", "per_dealt_player"}
_RAKE_APPLICATIONS = {"unverified", "all_pots", "postflop_only"}
_RAKE_ROUNDING = {"unverified", "exact", "floor_to_chip", "ceil_to_chip"}
_RAKE_DISTRIBUTIONS = {"unverified", "proportional_all_pots", "main_pot_first"}
_VERIFICATION = {"simulation", "live_verified"}


def _decimal(value, name, *, positive=False):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an exact decimal string")
    number = Decimal(value)
    if not number.is_finite() or number < 0 or positive and number <= 0:
        raise ValueError(f"invalid {name}")
    return number


@dataclass(frozen=True)
class AARuleProfileV2:
    table_size: int
    small_blind: Decimal
    big_blind: Decimal
    ante: Decimal
    ante_mode: str
    straddle_mode: str
    straddle_amount: Decimal
    rake_percent: Decimal
    rake_cap_bb: Decimal
    rake_application: str
    rake_rounding: str
    rake_distribution: str
    minimum_chip: Decimal
    verification_status: str
    source: str

    def __post_init__(self):
        if type(self.table_size) is not int or self.table_size not in _POSITIONS:
            raise ValueError("table_size must be 5, 6, 7 or 8")
        for name in (
            "small_blind", "big_blind", "ante", "straddle_amount",
            "rake_percent", "rake_cap_bb", "minimum_chip",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite non-negative Decimal")
        if self.small_blind <= 0 or self.big_blind <= self.small_blind:
            raise ValueError("blinds must satisfy 0 < small < big")
        if self.minimum_chip <= 0:
            raise ValueError("minimum_chip must be > 0")
        chip_amounts = (
            self.small_blind, self.big_blind, self.ante, self.straddle_amount,
            self.rake_cap_bb * self.big_blind,
        )
        if any(amount % self.minimum_chip != 0 for amount in chip_amounts):
            raise ValueError("configured chip amounts must align to minimum_chip")
        if self.rake_percent > 1:
            raise ValueError("rake_percent must be <= 1")
        if self.ante_mode not in _ANTE_MODES:
            raise ValueError("invalid ante_mode")
        if self.ante_mode == "none" and self.ante != 0:
            raise ValueError("ante must be zero when ante_mode is none")
        if self.straddle_mode not in _STRADDLE_MODES:
            raise ValueError("invalid straddle_mode")
        if self.straddle_mode == "none" and self.straddle_amount != 0:
            raise ValueError("straddle_amount must be zero without straddle")
        if (self.straddle_mode != "none"
                and self.straddle_amount <= self.big_blind):
            raise ValueError("straddle must exceed big blind")
        if self.rake_application not in _RAKE_APPLICATIONS:
            raise ValueError("invalid rake_application")
        if self.rake_rounding not in _RAKE_ROUNDING:
            raise ValueError("invalid rake_rounding")
        if self.rake_distribution not in _RAKE_DISTRIBUTIONS:
            raise ValueError("invalid rake_distribution")
        if self.verification_status not in _VERIFICATION:
            raise ValueError("invalid verification_status")
        if (self.verification_status == "live_verified"
                and (self.rake_application == "unverified"
                     or self.rake_rounding == "unverified"
                     or self.rake_distribution == "unverified")):
            raise ValueError("live_verified rules cannot contain unknown rake policy")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be non-empty")

    @classmethod
    def from_dict(cls, value):
        required = {
            "schema_version", "table_size", "small_blind", "big_blind", "ante",
            "ante_mode", "straddle_mode", "straddle_amount", "rake_percent",
            "rake_cap_bb", "rake_application", "rake_rounding", "minimum_chip",
            "rake_distribution", "verification_status", "source",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("AA rule profile requires exact schema fields")
        if value["schema_version"] != 2:
            raise ValueError("unsupported AA rule profile schema")
        return cls(
            table_size=value["table_size"],
            small_blind=_decimal(value["small_blind"], "small_blind", positive=True),
            big_blind=_decimal(value["big_blind"], "big_blind", positive=True),
            ante=_decimal(value["ante"], "ante"),
            ante_mode=value["ante_mode"],
            straddle_mode=value["straddle_mode"],
            straddle_amount=_decimal(value["straddle_amount"], "straddle_amount"),
            rake_percent=_decimal(value["rake_percent"], "rake_percent"),
            rake_cap_bb=_decimal(value["rake_cap_bb"], "rake_cap_bb"),
            rake_application=value["rake_application"],
            rake_rounding=value["rake_rounding"],
            rake_distribution=value["rake_distribution"],
            minimum_chip=_decimal(value["minimum_chip"], "minimum_chip", positive=True),
            verification_status=value["verification_status"],
            source=value["source"],
        )

    def to_dict(self):
        return {
            "schema_version": 2,
            "table_size": self.table_size,
            "small_blind": str(self.small_blind),
            "big_blind": str(self.big_blind),
            "ante": str(self.ante),
            "ante_mode": self.ante_mode,
            "straddle_mode": self.straddle_mode,
            "straddle_amount": str(self.straddle_amount),
            "rake_percent": str(self.rake_percent),
            "rake_cap_bb": str(self.rake_cap_bb),
            "rake_application": self.rake_application,
            "rake_rounding": self.rake_rounding,
            "rake_distribution": self.rake_distribution,
            "minimum_chip": str(self.minimum_chip),
            "verification_status": self.verification_status,
            "source": self.source,
        }

    @property
    def fingerprint(self):
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def live_strategy_blockers(self):
        blockers = []
        if self.verification_status != "live_verified":
            blockers.append("aa_rules_not_live_verified")
        if self.rake_application == "unverified":
            blockers.append("rake_application_unverified")
        if self.rake_rounding == "unverified":
            blockers.append("rake_rounding_unverified")
        if self.rake_distribution == "unverified":
            blockers.append("rake_distribution_unverified")
        return tuple(blockers)

    def game_config(self):
        return GameConfig(
            variant="NLHE", game_type=GameType.CASH, max_seats=8,
            dealt_player_count=self.table_size,
            small_blind=ChipAmount(self.small_blind),
            big_blind=ChipAmount(self.big_blind),
            ante=ChipAmount(self.ante),
            rake_percent=self.rake_percent,
            rake_cap=ChipAmount(self.rake_cap_bb * self.big_blind),
            minimum_chip=ChipAmount(self.minimum_chip),
        )


@dataclass(frozen=True)
class ForcedBetPlan:
    rules_fingerprint: str
    occupied_seats: tuple[int, ...]
    dealer_seat: int
    positions: Mapping[int, Position]
    contributions: Mapping[int, Decimal]
    components: Mapping[int, tuple[tuple[str, Decimal], ...]]
    straddler_seat: int | None
    first_actor_seat: int
    current_bet: Decimal
    minimum_raise_to: Decimal
    expected_total: Decimal

    def __post_init__(self):
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))
        object.__setattr__(
            self, "contributions", MappingProxyType(dict(self.contributions))
        )
        object.__setattr__(self, "components", MappingProxyType({
            seat: tuple(values) for seat, values in self.components.items()
        }))


@dataclass(frozen=True)
class OpeningReconciliation:
    status: str
    expected: Mapping[int, Decimal]
    observed: Mapping[int, Decimal]
    differences: Mapping[int, Decimal]
    total_difference: Decimal
    automatic_fee_attribution: bool = False
    strategy_eligible: bool = False

    def __post_init__(self):
        for name in ("expected", "observed", "differences"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def build_forced_bet_plan(
    rules: AARuleProfileV2,
    occupied_seats: tuple[int, ...],
    dealer_seat: int,
    *,
    observed_optional_straddler: int | None = None,
):
    if not isinstance(rules, AARuleProfileV2):
        raise TypeError("rules must be AARuleProfileV2")
    occupied = tuple(sorted(occupied_seats))
    if (len(occupied) != rules.table_size or len(set(occupied)) != len(occupied)
            or any(type(seat) is not int or not 0 <= seat < 8 for seat in occupied)
            or dealer_seat not in occupied):
        raise ValueError("occupied seats/dealer do not match AA table size")
    start = occupied.index(dealer_seat)
    clockwise = occupied[start:] + occupied[:start]
    positions = dict(zip(clockwise, _POSITIONS[rules.table_size]))
    by_position = {position: seat for seat, position in positions.items()}
    contributions = {seat: Decimal("0") for seat in range(8)}
    components = {seat: [] for seat in range(8)}

    def add(seat, kind, amount):
        contributions[seat] += amount
        components[seat].append((kind, amount))

    if rules.ante_mode == "per_dealt_player":
        for seat in occupied:
            add(seat, "ante", rules.ante)
    add(by_position[Position.SB], "small_blind", rules.small_blind)
    add(by_position[Position.BB], "big_blind", rules.big_blind)
    straddler = None
    if rules.straddle_mode == "mandatory_utg":
        straddler = by_position[Position.UTG]
    elif rules.straddle_mode == "optional_explicit_utg":
        if observed_optional_straddler is not None:
            if observed_optional_straddler != by_position[Position.UTG]:
                raise ValueError("optional straddler must be explicit UTG seat")
            straddler = observed_optional_straddler
    elif observed_optional_straddler is not None:
        raise ValueError("observed straddler conflicts with straddle_mode none")
    if straddler is not None:
        add(straddler, "straddle", rules.straddle_amount)
    first_position = Position.UTG
    first_actor = by_position[first_position]
    current_bet = rules.big_blind
    if straddler is not None:
        index = clockwise.index(straddler)
        first_actor = clockwise[(index + 1) % len(clockwise)]
        current_bet = rules.straddle_amount
    return ForcedBetPlan(
        rules.fingerprint, occupied, dealer_seat, positions, contributions,
        {seat: tuple(values) for seat, values in components.items()},
        straddler, first_actor, current_bet, current_bet * 2,
        sum(contributions.values(), Decimal("0")),
    )


def reconcile_opening_debits(
    rules: AARuleProfileV2, plan: ForcedBetPlan, observed: Mapping[str, str],
):
    if plan.rules_fingerprint != rules.fingerprint:
        raise ValueError("forced-bet plan/rules fingerprint mismatch")
    if not isinstance(observed, Mapping) or set(observed) != set(map(str, range(8))):
        raise ValueError("observed opening requires all eight physical seats")
    actual = {
        seat: _decimal(observed[str(seat)], f"observed_seat_{seat}")
        for seat in range(8)
    }
    differences = {
        seat: actual[seat] - plan.contributions[seat] for seat in range(8)
    }
    total = sum(differences.values(), Decimal("0"))
    exact = all(value == 0 for value in differences.values())
    return OpeningReconciliation(
        "EXACT_FORCED_BETS" if exact else "UNALLOCATED_OPENING_DIFFERENCE",
        plan.contributions, actual, differences, total,
        automatic_fee_attribution=False,
        strategy_eligible=exact and not rules.live_strategy_blockers,
    )


@dataclass(frozen=True)
class RakeEstimate:
    status: str
    amount: Decimal | None
    uncapped: Decimal | None
    cap: Decimal
    reason: str
    strategy_eligible: bool = False


def estimate_rake(rules: AARuleProfileV2, pot: str, *, saw_flop: bool | None):
    amount = _decimal(pot, "pot")
    cap = rules.rake_cap_bb * rules.big_blind
    if rules.rake_application == "unverified" or rules.rake_rounding == "unverified":
        return RakeEstimate(
            "UNKNOWN", None, None, cap, "rake_application_or_rounding_unverified"
        )
    if rules.rake_application == "postflop_only" and saw_flop is None:
        return RakeEstimate("UNKNOWN", None, None, cap, "saw_flop_unknown")
    if rules.rake_application == "postflop_only" and saw_flop is False:
        return RakeEstimate(
            "EXACT_CONFIGURED", Decimal("0"), Decimal("0"), cap,
            "configured_no_flop_no_drop",
            strategy_eligible=not rules.live_strategy_blockers,
        )
    uncapped = amount * rules.rake_percent
    value = min(uncapped, cap)
    if rules.rake_rounding != "exact":
        units = value / rules.minimum_chip
        rounding = (
            ROUND_FLOOR if rules.rake_rounding == "floor_to_chip"
            else ROUND_CEILING
        )
        value = units.to_integral_value(rounding=rounding) * rules.minimum_chip
        value = min(value, cap)
    return RakeEstimate(
        "EXACT_CONFIGURED", value, uncapped, cap,
        "configured_policy_not_platform_observation",
        strategy_eligible=not rules.live_strategy_blockers,
    )


__all__ = [
    "AARuleProfileV2", "ForcedBetPlan", "OpeningReconciliation", "RakeEstimate",
    "build_forced_bet_plan", "estimate_rake", "reconcile_opening_debits",
]
