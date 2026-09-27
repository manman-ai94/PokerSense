"""Nine fixed, synthetic terminal decisions with public-only exact oracles.

These are necessary strategic sanity checks, not a representative poker test or
a profitability estimate.  Each observation comes from a complete legal arena
trajectory.  Only ``observation`` may be passed to a policy; the remaining case
fields are evaluation-side labels, proofs and terminal evidence.
"""
from __future__ import annotations

from fractions import Fraction

from .aa_full_hand_arena import AAFullHandArena
from .aa_rules_v2 import AARuleProfileV2


SANITY_VERSION = "aa-local-terminal-sanity-v1"
SOURCE = "SIMULATION_HAND_AUTHORED_SANITY"
FEE_STRESS = "UNREALISTIC_FEE_STRESS_NOT_AA_RULE"
CASE_KINDS = ("board_royal_no_rake", "board_royal_fee_stress", "private_royal")
_EXPECTED = dict(zip(CASE_KINDS, ("check_call", "fold", "check_call")))
_BOARD_ROYAL = ("Ts", "Js", "Qs", "Ks", "As")
_PRIVATE_BOARD = ("Qs", "Js", "Ts", "2d", "3c")


def _ratio(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _validate_case(players, kind):
    if type(players) is not int or players not in (6, 7, 8):
        raise ValueError("sanity_players_must_be_6_7_or_8")
    if kind not in CASE_KINDS:
        raise ValueError("unknown_sanity_case_kind")


def _rules(players, kind):
    """Explicit fixed assumptions, never inferred from a real AA table."""
    stress = kind == "board_royal_fee_stress"
    return AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": players,
        "small_blind": "1", "big_blind": "2", "ante": "2",
        "ante_mode": "per_dealt_player", "straddle_mode": "mandatory_utg",
        "straddle_amount": "4", "rake_percent": (
            "0.5" if stress else "0" if kind == "board_royal_no_rake" else "0.03"),
        "rake_cap_bb": "1000" if stress else "2",
        "rake_application": "all_pots", "rake_rounding": "floor_to_chip",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "1",
        "verification_status": "simulation",
        "source": SOURCE + (":" + FEE_STRESS if stress else ""),
    })


def sanity_deck(players, kind):
    """Return a full explicit deck; reserve public path and Hero before filling.

    The arena deals two consecutive cards to each physical seat, followed by
    burn/flop/burn/turn/burn/river. Opponent cards are arbitrary unused cards;
    none are inputs to the action label or the closed-form comparison.
    """
    from pokerkit import Deck

    _validate_case(players, kind)
    private = kind == "private_royal"
    board = _PRIVATE_BOARD if private else _BOARD_ROYAL
    hole = ("As", "Ks") if private else ("2c", "3d")
    reserved = {2 * (players - 1): hole[0], 2 * (players - 1) + 1: hole[1]}
    reserved.update(zip((2 * players + i for i in (1, 2, 3, 5, 7)), board))
    unused = iter(repr(card) for card in Deck.STANDARD
                  if repr(card) not in reserved.values())
    return [reserved[index] if index in reserved else next(unused)
            for index in range(52)]


def build_sanity_arena(players, kind, *, deck=None):
    """Replay to the last river decision; optional full deck aids audit probes.

    A changed deck must preserve this case's Hero cards and public board. It may
    freely change opponent cards, burns and undealt cards. No policy receives
    this simulator, its explicit deck or either successor terminal result.
    """
    _validate_case(players, kind)
    arena = AAFullHandArena(_rules(players, kind)).reset(
        0, deck=sanity_deck(players, kind) if deck is None else deck)
    hero = players - 1
    while arena.street != "river":
        if arena.terminal or len(arena.observe(arena.actor)["public_history"]) > 32:
            raise RuntimeError("sanity_trajectory_did_not_reach_river")
        arena.step("check_call")
    # The first opponent shoves; all subsequent opponents call all-in. Hero
    # acts last, so both legal branches terminate without future decisions.
    while arena.actor != hero:
        if arena.terminal:
            raise RuntimeError("sanity_trajectory_ended_before_hero")
        raises = [action for action in arena.legal_actions()
                  if action.kind == "raise_to"]
        arena.step(raises[-1] if raises else "check_call")
    observation = arena.observe(hero)
    expected_board = _PRIVATE_BOARD if kind == "private_royal" else _BOARD_ROYAL
    expected_hole = ("As", "Ks") if kind == "private_royal" else ("2c", "3d")
    if (tuple(observation["board"]) != expected_board
            or set(observation["own_hole"]) != set(expected_hole)):
        raise ValueError("sanity_deck_changed_public_or_hero_cards")
    if (observation["street"] != "river"
            or observation["all_in"] != list(range(players - 1))
            or observation["folded"]
            or [a["id"] for a in observation["legal_actions"]]
            != ["fold", "check_call"]):
        raise RuntimeError("sanity_terminal_menu_or_allin_contract_failed")
    return arena


def _public_oracle(observation, kind):
    """Independent closed form, with no hand evaluator or simulator internals."""
    hero = str(observation["observing_seat"])
    players = observation["table_size"]
    rules = observation["rules"]
    contribution = Fraction(observation["contributions"][hero])
    owed = Fraction(observation["to_call"])
    final_contributions = {seat: Fraction(amount) + (owed if seat == hero else 0)
                           for seat, amount in observation["contributions"].items()}
    if len(set(final_contributions.values())) != 1:
        raise RuntimeError("sanity_oracle_requires_equal_final_contributions")
    pot = sum(final_contributions.values(), Fraction())
    unit = Fraction(rules["minimum_chip"])
    cap = Fraction(rules["rake_cap_bb"]) * Fraction(rules["big_blind"])
    # Exact rational implementation is deliberately separate from estimate_rake.
    unrounded = min(pot * Fraction(rules["rake_percent"]), cap)
    rake = min((unrounded // unit) * unit, cap)
    private = kind == "private_royal"
    share = pot - rake if private else (pot - rake) / players
    fold_return = -contribution
    call_return = share - contribution - owed
    return {
        "proof": ("HERO_PRIVATE_ROYAL_IS_UNBEATABLE_FOR_ALL_OPPONENT_HOLDINGS"
                  if private else "BOARD_ROYAL_TIES_ALL_REMAINING_PLAYERS"),
        "hidden_information_used": False, "future_decisions": 0,
        "formula": ("(pot_after_call - rake) - to_call" if private else
                    "(pot_after_call - rake) / players - to_call"),
        "pot_after_call": _ratio(pot), "rake_after_call": _ratio(rake),
        "hero_call_share_after_rake": _ratio(share), "to_call": _ratio(owed),
        "hero_sunk_contribution": _ratio(contribution),
        "terminal_hero_returns": {
            "fold": _ratio(fold_return), "check_call": _ratio(call_return)},
        "incremental_returns_vs_fold": {
            "fold": _ratio(0), "check_call": _ratio(call_return - fold_return)},
        "strict_margin": _ratio(abs(call_return - fold_return)),
    }


def build_sanity_cases():
    """Nine serializable cases; expected actions are fixed before model scores.

    The oracle uses only the observation. Independent engine clones verify both
    exact branch returns; evidence and expected labels remain outside the model
    observation. This set includes an intentionally unrealistic fee stress case.
    """
    cases = []
    for players in (6, 7, 8):
        for kind in CASE_KINDS:
            arena = build_sanity_arena(players, kind)
            observation = arena.observe(arena.actor)
            oracle = _public_oracle(observation, kind)
            branch_evidence = {}
            for action in ("fold", "check_call"):
                terminal = arena.clone().step(action)
                if not terminal.terminal:
                    raise RuntimeError("sanity_branch_requires_future_decision")
                measured = _ratio(terminal.terminal_returns()[arena.actor])
                if measured != oracle["terminal_hero_returns"][action]:
                    raise RuntimeError("sanity_engine_closed_form_disagreement")
                branch_evidence[action] = terminal.terminal_result()
            delta = oracle["incremental_returns_vs_fold"]["check_call"]
            if (delta["numerator"] == 0
                    or (delta["numerator"] > 0) != (_EXPECTED[kind] == "check_call")):
                raise RuntimeError("sanity_declared_action_not_strictly_optimal")
            cases.append({
                "id": f"n{players}-{kind}", "sanity_version": SANITY_VERSION,
                "kind": kind, "source_kind": SOURCE,
                "scope": FEE_STRESS if kind == "board_royal_fee_stress" else SOURCE,
                "simulation_only": True, "strategy_eligible": False,
                "advice_emitted": False, "empirical_strength": "NOT_ASSESSED",
                "observation": observation, "expected_action": _EXPECTED[kind],
                "oracle": oracle, "branch_evidence": branch_evidence,
            })
    return cases
