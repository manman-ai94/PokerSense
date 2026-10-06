"""Declared synthetic ROOT inputs. Uses installed PokerKit; no solver execution."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from importlib.metadata import version

from poker_engine.core.enums import (
    ActionType, PlayerStatus, Position, Rank, Street, Suit,
)
from poker_engine.core.request_context import RequestContext
from poker_engine.core.value_objects import Card, ChipAmount
from poker_engine.strategy.contracts import (
    ContextQuality, DecisionContext, DecisionSeat, EffectiveStack, GameConfig,
    GameType, InputProvenance, InputSource, LegalAction, PotState, QualityStatus,
    RangeDistribution,
)
from poker_engine.strategy.frozen_postflop import _combo, _fixed_decimal_context

from .adapter import MODEL, RANGE_SOURCE, RANGE_VERSION, require

A = "AA,KK,QQ,JJ,AKs,AQs,AJs:0.5,KQs:0.5"
B = "QQ,JJ,TT,99,AQs,AJs,ATs:0.5,KQs:0.5,QJs:0.5,JTs:0.5"


@dataclass(frozen=True)
class Case:
    name: str
    board: str
    pot: int
    stack: int
    oop: str
    ip: str
    hero: str


CASES = (
    Case("river-a", "Qh 9h 6c 2d As", 20, 80, A, B, "AcAd"),
    Case("river-b", "Ks Td 7c 4h 2s", 24, 72, B, A, "QhQd"),
    Case("turn-c", "Jh 8h 4c 2d", 20, 80, A, B, "AsAd"),
)


def expand_range(raw, board):
    """Expand hand classes with existing PokerKit, retaining declared weights."""
    from pokerkit import parse_range
    result = {}
    board = set(board.split())
    for token in raw.split(","):
        name, colon, weight = token.partition(":")
        weight = Decimal(weight if colon else "1")
        for cards in parse_range(name):
            cards = _combo("".join(sorted(repr(c) for c in cards)))
            if {cards[:2], cards[2:]} & board:
                continue
            require(cards not in result and 0 < weight <= 1,
                    "declared_range_overlap_or_weight")
            result[cards] = weight
    return result


# Reuse the accepted 30b85ebd PokerKit adapter helper, with identical AST.
def _native_menu(state):
    menu = []
    if state.can_fold():
        menu.append(LegalAction(ActionType.FOLD, ChipAmount(0), ChipAmount(0)))
    if state.can_check_or_call():
        amount = state.checking_or_calling_amount
        menu.append(LegalAction(ActionType.CALL if amount else ActionType.CHECK,
                                ChipAmount(amount), ChipAmount(amount)))
    if state.can_complete_bet_or_raise_to():
        # The entire interval includes the maximum all-in size, not sample sizes.
        action = ActionType.RAISE if max(state.bets) else ActionType.BET
        menu.append(LegalAction(
            action, ChipAmount(state.min_completion_betting_or_raising_to_amount),
            ChipAmount(state.max_completion_betting_or_raising_to_amount),
        ))
    return tuple(menu)


def native_state(case, *, hero_seat=0, opponent="????"):
    """Existing synthetic street-start construction with an explicit hero seat."""
    from pokerkit import Automation, Mode, NoLimitTexasHoldem
    require(version("pokerkit") == "0.7.5", "pinned_PokerKit_required")
    require(type(hero_seat) is int and hero_seat in (0, 1), "native_hero_seat")
    initial = case.stack + case.pot // 2
    state = NoLimitTexasHoldem.create_state(
        (Automation.ANTE_POSTING, Automation.BLIND_OR_STRADDLE_POSTING,
         Automation.BET_COLLECTION), True, 0, (1, 2), 2, (initial, initial), 2,
        mode=Mode.CASH_GAME,
    )
    state.deal_hole(case.hero, hero_seat)
    state.deal_hole(opponent, 1 - hero_seat)
    state.complete_bet_or_raise_to(case.pot // 2)
    state.check_or_call()
    board = case.board.split()
    streets = ["".join(board[:3]), board[3]] + (board[4:] if len(board) == 5 else [])
    for i, cards in enumerate(streets):
        state.burn_card("??")
        state.deal_board(cards)
        if i != len(streets) - 1:
            state.check_or_call()
            state.check_or_call()
    return state


def native_root(case, *, selected=True, opponent="????"):
    """Construct a local synthetic ROOT; never reads a private real hand."""
    state = native_state(case, opponent=opponent)
    with localcontext(_fixed_decimal_context()):
        ranges = tuple(RangeDistribution(
            seat, expand_range(raw, case.board), RANGE_SOURCE, RANGE_VERSION,
        ) for seat, raw in enumerate((case.oop, case.ip)))
    return state, context_from_native(state, ranges, case.name, selected=selected)


def native_path(case, path, actor, ranges, request, *, max_seats=2):
    """Replay a finite model path in PokerKit from its existing street start.

    This creates an owned synthetic state. It does not filter caller history
    or read/backfill another player's hole cards.
    """
    from pokerkit import CompletionBettingOrRaisingTo
    from poker_engine.core.events import EventType, StateEvent
    from .catalog import line

    state = native_state(case, hero_seat=actor)
    street = Street.TURN if len(case.board.split()) == 4 else Street.RIVER
    history = []
    for token in path:
        seat = state.actor_index
        facing = max(state.bets) > state.bets[seat]
        if token == "CHECK":
            require(state.checking_or_calling_amount == 0, "CHECK_faces_bet")
            state.check_or_call()
            kind, amount = EventType.CHECK, 0
        else:
            amount = (state.bets[seat] + state.stacks[seat]
                      if token == "ALLIN" else int(token.split(":")[1]))
            operation = state.complete_bet_or_raise_to(amount)
            require(isinstance(operation, CompletionBettingOrRaisingTo),
                    "native_path_operation_conflict")
            kind = EventType.RAISE if facing else EventType.BET
        semantics = "none" if kind is EventType.CHECK else "total_street"
        history.append(StateEvent(
            kind, request.hand_id, request.state_version,
            {"seat": seat, "street": street.value,
             "amount_total_street": str(amount), "amount_semantics": semantics},
            request.requested_at, "PokerKit/0.7.5/synthetic-hu-path",
        ))
    require(state.status and state.actor_index == actor and all(state.statuses),
            "native_path_not_a_matching_decision")
    require(state.stacks[actor] > 0, "actor_cannot_act")
    with localcontext(_fixed_decimal_context()):
        seats = tuple(DecisionSeat(
            i, f"synthetic-{i}", Position.BB if i == 0 else Position.SB,
            ChipAmount(state.stacks[i]), ChipAmount(state.bets[i]),
            ChipAmount(state.starting_stacks[i] - state.stacks[i]),
            PlayerStatus.ACTIVE if state.stacks[i] else PlayerStatus.ALL_IN,
            is_hero=i == actor, is_dealer=i == 1,
        ) for i in (0, 1))

        def cards(values):
            return tuple(Card(Rank(repr(c)[0]), Suit(repr(c)[1])) for c in values)

        return DecisionContext(
            request, GameConfig("NLHE", GameType.CASH, max_seats, 2,
                                ChipAmount(1), ChipAmount(2)),
            seats, actor, actor, (0, 1), cards(state.hole_cards[actor]),
            cards(c for row in state.board_cards for c in row), street,
            (PotState("main", ChipAmount(state.total_pot_amount), (0, 1)),),
            _native_menu(state), tuple(history),
            (EffectiveStack(1 - actor, ChipAmount(min(state.stacks))),),
            ranges[actor], (ranges[1 - actor],), ContextQuality(1.0),
            tuple(InputProvenance(
                name, InputSource.DERIVED, QualityStatus.VALID, 1.0,
                "PokerKit/0.7.5/synthetic-hu-path",
            ) for name in ("seats", "board", "hero", "pots", "legal_actions",
                           "ranges", "action_history")),
            assumptions=("execution_mode:simulation", "query_model:" + MODEL,
                         "declared_synthetic_ROOT_and_path_not_authenticated"),
            action_line=line(path),
            effective_stack_bb=Decimal(min(state.stacks)) / 2,
        )


def context_from_native(state, ranges, identity, *, selected):
    """Read complete native ROOT facts. Does not act or expose opponent hole cards."""
    from pokerkit import BettingStructure, BoardDealing, Mode, State, rake
    require(version("pokerkit") == "0.7.5" and isinstance(state, State),
            "pinned_PokerKit_required")
    require(state.player_count == 2 and all(state.statuses) and state.status
            and state.actor_index == 0 and state.street_index in (2, 3)
            and isinstance(state.operations[-1], BoardDealing)
            and state.bets == [0, 0], "two_active_native_ROOT_required")
    require(state.betting_structure is BettingStructure.NO_LIMIT
            and state.blinds_or_straddles == (1, 2) and state.antes == (0, 0)
            and state.rake is rake and state.mode is Mode.CASH_GAME,
            "native_rules_mismatch")
    with localcontext(_fixed_decimal_context()):
        request = RequestContext(identity, 1, identity + "-ROOT",
                                 datetime.now(timezone.utc))
        config = GameConfig("NLHE", GameType.CASH, 2, 2, ChipAmount(1), ChipAmount(2))
        seats = tuple(DecisionSeat(
            i, f"synthetic-{i}", Position.BB if i == 0 else Position.SB,
            ChipAmount(state.stacks[i]), ChipAmount(state.bets[i]),
            ChipAmount(state.starting_stacks[i] - state.stacks[i]),
            PlayerStatus.ACTIVE, is_hero=i == 0, is_dealer=i == 1,
        ) for i in (0, 1))
        require(state.checking_or_calling_amount == 0, "ROOT_must_not_face_bet")
        menu = _native_menu(state)

        def cards(values):
            return tuple(Card(Rank(repr(c)[0]), Suit(repr(c)[1])) for c in values)

        assumptions = ("execution_mode:simulation",
                       "declared_synthetic_ROOT_facts_not_authenticated")
        if selected:
            assumptions += ("query_model:" + MODEL,)
        return DecisionContext(
            request, config, seats, 0, 0, (0, 1), cards(state.hole_cards[0]),
            cards(c for row in state.board_cards for c in row),
            Street.TURN if state.street_index == 2 else Street.RIVER,
            (PotState("main", ChipAmount(state.total_pot_amount), (0, 1)),),
            tuple(menu), (), (EffectiveStack(1, ChipAmount(min(state.stacks))),),
            ranges[0], (ranges[1],), ContextQuality(1.0),
            tuple(InputProvenance(
                name, InputSource.DERIVED, QualityStatus.VALID, 1.0,
                "PokerKit/0.7.5/declared-synthetic-ROOT",
            ) for name in (
                "seats", "board", "hero", "pots", "legal_actions", "ranges")),
            assumptions=assumptions, action_line="hu-root:ROOT",
            effective_stack_bb=Decimal(min(state.stacks)) / 2,
        )
