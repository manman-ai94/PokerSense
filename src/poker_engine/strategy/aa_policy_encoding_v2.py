"""Auditable synthetic-only state identity and lossy card features.

Exact identity removes only hole/flop ordering, exact-decimal spelling and a
globally consistent suit permutation. Physical seats remain physical seats.
The learning representation is intentionally lossy, NOT poker-state equivalence,
calibrated equity, a range estimate, or evidence of strategy strength.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from itertools import combinations, permutations
import re

from .aa_frozen_policy import FORBIDDEN, canonical_hash


ENCODER_VERSION_V2 = "aa_public_features_v2"
ABSTRACTION_DISCLOSURE = (
    "Physical seats and exact public action/amount history are retained. "
    "Preflop uses 169 rank/suitedness classes. Postflop replaces exact hole "
    "ranks/suits by rank-pair bins, made category, private/board contribution, "
    "public suit-count and private blocker/draw relations, and geometric "
    "straight completions. This is a lossy research abstraction; collisions "
    "are not proven strategic equivalence. No inferred past board or equity."
)
_RANKS = "23456789TJQKA"
_SUITS = "cdhs"
_STREETS = ("preflop", "flop", "turn", "river")
_FORBIDDEN = FORBIDDEN | {
    "hole_cards", "opponent_cards", "rng_state", "deal_seed", "deck_seed",
    "next_board", "private_state", "all_holes", "unrevealed_cards",
}


def exact_money(value):
    """Canonical, lossless Decimal spelling; never normalize under a context."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("invalid_exact_money")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid_exact_money") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_exact_money")
    if not amount:
        return "0"
    text = format(amount, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _reject_hidden(value):
    if isinstance(value, dict):
        if _FORBIDDEN.intersection(value):
            raise ValueError("private_or_future_policy_input")
        for item in value.values():
            _reject_hidden(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_hidden(item)


def _card(card):
    if (not isinstance(card, str) or len(card) != 2
            or card[0] not in _RANKS or card[1] not in _SUITS):
        raise ValueError("invalid_public_card")
    return card


def _seat(value, occupied):
    if type(value) is not int or value not in occupied:
        raise ValueError("invalid_public_seat")
    return value


def _seats(values, occupied, *, ordered=False):
    if not isinstance(values, (list, tuple)):
        raise ValueError("invalid_public_seats")
    result = [_seat(value, occupied) for value in values]
    if len(set(result)) != len(result):
        raise ValueError("duplicate_public_seat")
    return result if ordered else sorted(result)


def _seat_money(values, occupied):
    if not isinstance(values, dict) or set(values) != {str(s) for s in occupied}:
        raise ValueError("invalid_seat_money_map")
    return {str(s): exact_money(values[str(s)]) for s in occupied}


def _action(row):
    if not isinstance(row, dict):
        raise ValueError("invalid_legal_menu")
    kind = row.get("kind")
    if kind not in ("fold", "check_call", "raise_to"):
        raise ValueError("invalid_legal_menu")
    amount = exact_money(row.get("raise_to")) if kind == "raise_to" else None
    action_id = "raise_to:" + amount if kind == "raise_to" else kind
    if (row.get("id") != action_id
            or (kind != "raise_to" and row.get("raise_to") is not None)):
        raise ValueError("invalid_legal_menu")
    return {"id": action_id, "kind": kind, "raise_to": amount}


def validated_menu_v2(observation):
    menu = observation.get("legal_actions")
    if not isinstance(menu, (list, tuple)) or not menu:
        raise ValueError("invalid_legal_menu")
    result = [_action(row) for row in menu]
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("invalid_legal_menu")
    return sorted(result, key=lambda row: row["id"])


def _visible_cards(obs):
    hole = [_card(card) for card in obs["own_hole"]]
    board = [_card(card) for card in obs["board"]]
    street = obs["street"]
    expected_count = dict(zip(_STREETS, (0, 3, 4, 5))).get(street)
    if len(hole) != 2 or len(board) != expected_count:
        raise ValueError("invalid_street_card_count")
    if len(set(hole + board)) != len(hole + board):
        raise ValueError("duplicate_cards")
    history = obs["board_history"]
    if not isinstance(history, (list, tuple)):
        raise ValueError("explicit_board_history_required")
    expected = list(_STREETS[1:_STREETS.index(street) + 1])
    if len(history) != len(expected):
        raise ValueError("incomplete_board_history")
    normalized = []
    for row, expected_street in zip(history, expected):
        if not isinstance(row, dict) or row.get("street") != expected_street:
            raise ValueError("invalid_board_history_order")
        cards = [_card(card) for card in row.get("cards", ())]
        if len(cards) != (3 if expected_street == "flop" else 1):
            raise ValueError("invalid_board_history_card_count")
        normalized.append({"street": expected_street, "cards": cards})
    flattened = [card for row in normalized for card in row["cards"]]
    if flattened != board:
        raise ValueError("board_history_current_board_mismatch")
    return hole, normalized


def _canonical_cards(hole, history):
    """Joint private/public suit orbit, retaining chronological street groups."""
    candidates = []
    for target in permutations(_SUITS):
        suit_map = dict(zip(_SUITS, target))

        def remap(card):
            return card[0] + suit_map[card[1]]

        mapped_hole = sorted(remap(card) for card in hole)
        mapped_history = [
            {"street": row["street"],
             "cards": sorted(remap(card) for card in row["cards"])}
            for row in history
        ]
        flat = [card for row in mapped_history for card in row["cards"]]
        candidates.append((tuple(mapped_hole + flat), mapped_hole, mapped_history))
    _, canonical_hole, canonical_history = min(candidates, key=lambda row: row[0])
    return canonical_hole, canonical_history


def _five_rank(cards):
    ranks = [_RANKS.index(card[0]) + 2 for card in cards]
    groups = sorted(((count, rank) for rank, count in Counter(ranks).items()),
                    reverse=True)
    unique = set(ranks)
    if 14 in unique:
        unique.add(1)
    straight = max((low + 4 for low in range(1, 11)
                    if set(range(low, low + 5)) <= unique), default=0)
    flush = len({card[1] for card in cards}) == 1
    counts = [count for count, _ in groups]
    if straight and flush:
        return (8, straight)
    if counts[0] == 4:
        return (7, *(rank for _, rank in groups))
    if counts == [3, 2]:
        return (6, *(rank for _, rank in groups))
    if flush:
        return (5, *sorted(ranks, reverse=True))
    if straight:
        return (4, straight)
    if counts[0] == 3:
        return (3, *(rank for _, rank in groups))
    if counts[:2] == [2, 2]:
        return (2, *(rank for _, rank in groups))
    if counts[0] == 2:
        return (1, *(rank for _, rank in groups))
    return (0, *sorted(ranks, reverse=True))


def _best_rank(cards):
    return max((_five_rank(hand) for hand in combinations(cards, 5)), default=None)


def _straight_features(hole, board):
    private = {_RANKS.index(card[0]) + 2 for card in hole}
    public = {_RANKS.index(card[0]) + 2 for card in board}
    if 14 in private:
        private.add(1)
    if 14 in public:
        public.add(1)
    visible = private | public
    completions = []
    for low in range(1, 11):
        window = set(range(low, low + 5))
        missing = window - visible
        if len(missing) == 1:
            rank = missing.pop()
            completions.append({
                "high_rank": low + 4, "missing_rank": 14 if rank == 1 else rank,
                "private_required_ranks": sorted((window & private) - public),
                "public_alone_missing_count": len(window - public),
            })
    return completions


def _card_features(hole, history):
    board = [card for row in history for card in row["cards"]]
    own_ranks = sorted((_RANKS.index(card[0]) + 2 for card in hole), reverse=True)
    if not board:
        return {"preflop_class": "".join(_RANKS[r - 2] for r in own_ranks)
                + ("pair" if own_ranks[0] == own_ranks[1]
                   else "suited" if hole[0][1] == hole[1][1] else "offsuit")}
    best = _best_rank(hole + board)
    board_best = _best_rank(board)
    suited_relations = []
    for suit in _SUITS:
        public_ranks = sorted((_RANKS.index(card[0]) + 2 for card in board
                               if card[1] == suit), reverse=True)
        private_ranks = sorted((_RANKS.index(card[0]) + 2 for card in hole
                                if card[1] == suit), reverse=True)
        # Suit labels themselves never enter learning features. Relations are
        # sorted as a multiset and preserve private/board association.
        if public_ranks or private_ranks:
            highest_absent = max(set(range(2, 15)) - set(public_ranks))
            suited_relations.append({
                "board_ranks": public_ranks, "private_count": len(private_ranks),
                "board_rank_path": [
                    {"street": row["street"],
                     "ranks": sorted(_RANKS.index(card[0]) + 2 for card in row["cards"]
                                     if card[1] == suit)}
                    for row in history
                ],
                "private_high_rank": max(private_ranks, default=0),
                "holds_highest_rank_absent_from_board": highest_absent in private_ranks,
                "combined_count": len(public_ranks) + len(private_ranks),
                "one_card_flush_draw": len(board) < 5
                and len(public_ranks) + len(private_ranks) == 4,
                "flush_draw_uses_private": len(board) < 5 and bool(private_ranks)
                and len(public_ranks) + len(private_ranks) == 4,
            })
    suited_relations.sort(key=lambda row: (
        row["board_ranks"], row["private_count"], row["private_high_rank"],
        tuple(tuple(item["ranks"]) for item in row["board_rank_path"])))
    return {
        "own_rank_pair_bins": [(rank - 2) // 2 for rank in own_ranks],
        "private_pair": own_ranks[0] == own_ranks[1],
        "private_suited": hole[0][1] == hole[1][1],
        "made_category": best[0], "board_only_category": (
            board_best[0] if board_best is not None else None),
        "private_improves_board_five": best > board_best
        if board_best is not None else None,
        "private_ranks_matching_board": sorted(set(own_ranks) & {
            _RANKS.index(card[0]) + 2 for card in board}),
        "board_rank_path": [{"street": row["street"],
                             "ranks": sorted(_RANKS.index(card[0]) + 2
                                             for card in row["cards"])}
                            for row in history],
        "suit_relations": suited_relations,
        "one_card_straight_completions": _straight_features(hole, board)
        if len(board) < 5 else [],
    }


def encode_decision_v2(observation):
    """Return source-free exact identity, abstract identity and inspectable views.

    Unknown additional fields are never copied into the model. Known hidden
    labels are rejected recursively, including inside provenance dictionaries.
    Source receipts are intentionally separate from these decision features.
    """
    if not isinstance(observation, dict):
        raise ValueError("invalid_policy_observation")
    _reject_hidden(observation)
    obs = observation
    if (obs.get("simulation_only") is not True
            or obs.get("strategy_eligible") is not False
            or obs.get("terminal") is not False):
        raise ValueError("v2_encoder_requires_synthetic_decision")
    if obs.get("actor") != obs.get("observing_seat"):
        raise ValueError("policy_must_observe_current_actor")
    try:
        occupied = obs["occupied_seats"]
        count = obs["table_size"]
        if (type(count) is not int or count not in (6, 7, 8)
                or len(occupied) != count or len(set(occupied)) != count
                or any(type(s) is not int or s not in range(8) for s in occupied)):
            raise ValueError("invalid_occupied_seats")
        occupied = sorted(occupied)
        fingerprint = obs["rules_fingerprint"]
        if (not isinstance(fingerprint, str)
                or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None):
            raise ValueError("invalid_rule_fingerprint")
        hole, history = _visible_cards(obs)
        hole, history = _canonical_cards(hole, history)
        actor = _seat(obs["actor"], occupied)
        betting = obs["betting"]
        if type(betting["can_raise"]) is not bool:
            raise ValueError("invalid_public_betting_state")
        view = {
            "rules_fingerprint": obs["rules_fingerprint"], "table_size": count,
            "street": obs["street"], "actor": actor, "observing_seat": actor,
            "occupied_seats": occupied,
            "dealer_seat": _seat(obs["dealer_seat"], occupied),
            "straddler_seat": _seat(obs["straddler_seat"], occupied)
            if obs["straddler_seat"] is not None else None,
            "big_blind": exact_money(obs["big_blind"]),
            "pot": exact_money(obs["pot"]), "to_call": exact_money(obs["to_call"]),
            "folded": _seats(obs["folded"], occupied),
            "all_in": _seats(obs["all_in"], occupied),
            "own_hole": hole, "board_history": history,
            "legal_actions": validated_menu_v2(obs),
            "betting": {
                "can_raise": betting["can_raise"],
                "min_raise_to": exact_money(betting["min_raise_to"])
                if betting["min_raise_to"] is not None else None,
                "max_raise_to": exact_money(betting["max_raise_to"])
                if betting["max_raise_to"] is not None else None,
                "last_full_raise_increment": exact_money(
                    betting["last_full_raise_increment"]),
                "acted_since_full_raise": _seats(
                    betting["acted_since_full_raise"], occupied),
                "pending_actors": _seats(
                    betting["pending_actors"], occupied, ordered=True),
                "consecutive_short_raise_increments": [
                    exact_money(value)
                    for value in betting["consecutive_short_raise_increments"]
                ],
            },
        }
        for field in ("stacks", "starting_stacks", "bets", "contributions"):
            view[field] = _seat_money(obs[field], occupied)
        public_history = []
        previous_street_index = 0
        for index, row in enumerate(obs["public_history"]):
            if (type(row["index"]) is not int or row["index"] != index
                    or row["street"] not in _STREETS
                    or _STREETS.index(row["street"]) < previous_street_index
                    or _STREETS.index(row["street"]) > _STREETS.index(obs["street"])):
                raise ValueError("invalid_public_history_order")
            previous_street_index = _STREETS.index(row["street"])
            public_history.append({"index": index,
                                   "actor": _seat(row["actor"], occupied),
                                   "street": row["street"], **_action(row),
                                   "paid": exact_money(row["paid"])})
        view["public_history"] = public_history
    except (KeyError, TypeError) as exc:
        raise ValueError("missing_or_invalid_v2_observation_field") from exc
    features = {key: deepcopy(value) for key, value in view.items()
                if key not in ("own_hole", "board_history")}
    features["cards"] = _card_features(hole, history)
    return {
        "encoder": ENCODER_VERSION_V2,
        "exact_key": canonical_hash({"encoder": ENCODER_VERSION_V2,
                                     "exact_view": view}),
        "abstract_key": canonical_hash({"encoder": ENCODER_VERSION_V2,
                                        "features": features}),
        "exact_view": view, "features": features,
        "abstraction_disclosure": ABSTRACTION_DISCLOSURE,
    }


def information_key_v2(observation):
    return encode_decision_v2(observation)["abstract_key"]
