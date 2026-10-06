"""Thin ROOT conversion for pinned postflop saved solutions; never runs a solver."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from types import MappingProxyType

from poker_engine.core.enums import ActionType, PlayerStatus, Position, Street
from poker_engine.core.errors import InvalidStateError
from poker_engine.core.value_objects import ChipAmount
from poker_engine.strategy.contracts import (
    ActionAmountSemantics, DecisionContext, GameType, RangeDistribution,
)
from poker_engine.strategy.frozen_postflop import (
    ENGINE_PIN, SOLUTION_SHA256, _combo, _fixed_decimal_context, _no_duplicates,
)
from poker_engine.strategy.provider import (
    ActionOption, LookupState, MatchKind, ProviderCapability, ProviderResult,
    StrategyCandidate,
)
from poker_engine.strategy.range_tracker import bayesian_action_update
from .catalog import ASSETS, CATALOG_VERSION, chip_text, decisions, line

MODEL = "hu-root-bet-abstraction-v1"
RANGE_SOURCE = "declared-synthetic-model-root"
RANGE_VERSION = ENGINE_PIN + "/root-range-v1"
MAX_SOLUTION_BYTES = 64 * 1024**2
MASS_TOLERANCE = Decimal("0.000001")  # New multi-size f32 rows only.


class RootError(ValueError):
    """Named refusal; no fallback or synthetic solver result."""


def require(condition, reason):
    if not condition:
        raise RootError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def config_digest(config):
    return digest(json.dumps(config, sort_keys=True, separators=(",", ":"),
                             default=float).encode())


def weighted_range(raw):
    """Already-expanded explicit combos only; no new range parser."""
    result = {}
    for token in raw.split(","):
        cards, weight = token.strip().split(":")
        cards, weight = _combo(cards), Decimal(weight)
        require(cards not in result and weight.is_finite() and 0 < weight <= 1,
                "invalid_explicit_range")
        result[cards] = weight
    return result


def _validate_context(context):
    require(isinstance(context, DecisionContext), "decision_context_required")
    require(context.is_decision_ready, "context_not_ready")
    config = context.game_config
    require(config.variant == "NLHE" and config.game_type is GameType.CASH
            and config.dealt_player_count == 2 and context.active_seats == (0, 1)
            and tuple(s.seat_id for s in context.seats) == (0, 1),
            "synthetic_two_dealt_two_active_only")
    require(config.small_blind.value == 1 and config.big_blind.value == 2
            and config.minimum_chip.value == 1 and config.ante.value == 0
            and config.rake_percent == 0 and config.rake_cap.value == 0,
            "unsupported_units_or_rules")
    require(context.street in (Street.TURN, Street.RIVER)
            and context.hero_seat == context.actor_seat == 0
            and not context.action_history and context.action_line == "hu-root:ROOT",
            "only_OOP_model_start_ROOT")
    require("query_model:" + MODEL in context.assumptions
            and "execution_mode:simulation" in context.assumptions,
            "explicit_synthetic_model_required")
    require(all(s.occupied and s.status is PlayerStatus.ACTIVE
                and s.street_committed.value == 0 for s in context.seats),
            "active_ROOT_seat_conflict")
    stack = context.seats[0].stack.value
    require(stack > 0 and context.seats[1].stack.value == stack,
            "equal_positive_ROOT_stacks_required")
    require(len(context.pots) == 1 and context.pots[0].eligible_seats == (0, 1),
            "single_HU_pot_required")
    require(context.pots[0].amount.value
            == sum(s.hand_committed.value for s in context.seats),
            "ROOT_contribution_pot_conflict")
    require(len(context.effective_stacks) == 1
            and context.effective_stacks[0].opponent_seat == 1
            and context.effective_stacks[0].amount.value == stack
            and context.effective_stack_bb == stack / config.big_blind.value,
            "effective_stack_conflict")
    require(context.hero_range is not None
            and context.hero_range.seat_id == 0
            and len(context.villain_ranges) == 1
            and context.villain_ranges[0].seat_id == 1,
            "range_role_conflict")
    ranges = (context.hero_range,) + context.villain_ranges
    board = {str(c) for c in context.board_cards}
    for distribution in ranges:
        require(distribution.source == RANGE_SOURCE
                and distribution.source_version == RANGE_VERSION
                and bool(distribution.combo_weights), "explicit_ROOT_ranges_required")
        for cards, weight in distribution.combo_weights.items():
            require(cards == _combo(cards) and 0 < weight <= 1
                    and not {cards[:2], cards[2:]} & board,
                    "range_blocker_or_weight_conflict")
    require(any(not {a[:2], a[2:]} & {b[:2], b[2:]}
                for a in ranges[0].combo_weights for b in ranges[1].combo_weights),
            "no_compatible_joint_hands")
    none, total = ActionAmountSemantics.NONE, ActionAmountSemantics.TOTAL_STREET
    menu = tuple((a.action, a.min_amount.value, a.max_amount.value, a.amount_semantics)
                 for a in context.legal_actions)
    require(menu == ((ActionType.FOLD, 0, 0, none), (ActionType.CHECK, 0, 0, none),
                     (ActionType.BET, 2, stack, total)),
            "complete_native_ROOT_menu_conflict")
    return ranges


def request_config(context):
    """Convert explicit current ROOT facts to official SolveConfig, not a tree."""
    with localcontext(_fixed_decimal_context()):
        ranges = _validate_context(context)
        empty = {"percents": [], "allin": False}
        bet = {"percents": [50.0, 100.0], "allin": True}
        raise_ = {"percents": [100.0], "allin": True}
        sizings = {}
        for role in ("oop", "ip"):
            sizings[role] = {}
            for street in ("flop", "turn", "river"):
                used = street != "flop"
                sizings[role][street] = deepcopy({
                    "bet": bet if used else empty,
                    "raise": raise_ if used else empty,
                    "donk": bet if used and role == "oop" else empty,
                })
        return {
            "board": " ".join(str(c) for c in context.board_cards),
            "oop_range": ",".join(
                f"{c}:{w}" for c, w in sorted(ranges[0].combo_weights.items())),
            "ip_range": ",".join(
                f"{c}:{w}" for c, w in sorted(ranges[1].combo_weights.items())),
            "effective_stack": float(context.seats[0].stack.value),
            "starting_pot": float(context.pots[0].amount.value),
            "allin_threshold": 100.0, "raise_cap": 1,
            "target_exploitability": 0.5, "max_iterations": 2000,
            "alpha": 1.5, "beta": 0.0, "gamma": 2.0,
            "turn_chance_sampling": False, "regret_floor": False,
            "rake": {"percent": 0.0, "cap": 0.0}, "sizings": sizings,
        }


def config_toml(config):
    lines = [f"{k} = {json.dumps(v)}" for k, v in config.items()
             if k not in ("rake", "sizings")]
    lines += ["", "[rake]", "percent = 0.0", "cap = 0.0"]
    for role, streets in config["sizings"].items():
        for street, tables in streets.items():
            lines += ["", f"[sizings.{role}.{street}]"]
            for kind, table in tables.items():
                lines.append(f"{kind} = {{ percents = {json.dumps(table['percents'])}, "
                             f"allin = {str(table['allin']).lower()} }}")
    return "\n".join(lines) + "\n"


def expected_root_actions(config):
    """Only ROOT percentage-to-chips conversion, matching the declared abstraction."""
    pot, stack = Decimal(str(config["starting_pot"])), Decimal(
        str(config["effective_stack"]))
    street = "turn" if len(config["board"].split()) == 4 else "river"
    table = config["sizings"]["oop"][street]["bet"]
    actions = [("Check", None)]
    for percent in table["percents"]:
        amount = (pot * Decimal(str(percent)) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        amount = min(stack, max(Decimal("0.01"), amount))
        label = "AllIn" if amount >= stack * Decimal(
            str(config["allin_threshold"])) / 100 else "Bet"
        action = (label, stack if label == "AllIn" else amount)
        if action not in actions:
            actions.append(action)
    if table["allin"] and ("AllIn", stack) not in actions:
        actions.append(("AllIn", stack))
    return tuple(actions)


class RootAssetProvider:
    """Caller-owned ROOT reader. A file/source label never authenticates a solve."""
    provider_id = "research-pinned-postflop-ROOT"

    def __init__(self, context, config, data, *, sha256, origin):
        require(origin in ("REVIEWED_SAVED_FIXTURE", "MOCK_CONVERSION_ONLY",
                           "NATIVE_SAVED_RUN"), "explicit_result_origin_required")
        require(len(data) <= MAX_SOLUTION_BYTES and digest(data) == sha256,
                "solution_size_or_digest_mismatch")
        if origin == "REVIEWED_SAVED_FIXTURE":
            require(sha256 == SOLUTION_SHA256, "not_the_reviewed_saved_fixture")
        self.origin, self.sha256 = origin, sha256
        self.config = deepcopy(config)
        self.source_version = f"{ENGINE_PIN}/{origin}/sha256:{sha256}"
        self.capability = ProviderCapability(
            frozenset({2}), frozenset({context.street}), frozenset({GameType.CASH}),
            (context.effective_stack_bb,), (ChipAmount(0),), (Decimal(0),),
            frozenset({"hu-root:ROOT"}), hero_positions=frozenset({Position.BB}),
        )
        self.solution = json.loads(
            data, parse_float=Decimal, object_pairs_hook=_no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(RootError("nonfinite_json")),
        )
        require(config_digest(self.solution["config"]) == config_digest(config),
                "saved_config_mismatch")
        roots = [n for n in self.solution["nodes"] if n["node"] == 0]
        require(len(roots) == 1 and roots[0]["player"] == 0, "unique_OOP_ROOT_required")
        self.root = roots[0]
        with localcontext(_fixed_decimal_context()):
            self.paths = MappingProxyType(decisions(sha256, config))
            self._nodes = {node["node"]: node for node in self.solution["nodes"]}
            if self.paths:
                _, node_count, decision_count = ASSETS[sha256]
                require(self.solution["node_count"] == node_count
                        and len(self._nodes) == decision_count
                        and len(self._nodes) == len(self.solution["nodes"]),
                        "catalog_asset_structure_mismatch")
                for path in self.paths:
                    self.model_menu(path)  # Exact saved labels/axes, not a tree build.
                stack = Decimal(str(config["effective_stack"]))
                buckets = tuple(sorted({min(stack - Decimal(b) for b in bets) / 2
                                        for _, _, bets in self.paths.values()}))
                self.capability = ProviderCapability(
                    frozenset({2}), frozenset({context.street}),
                    frozenset({GameType.CASH}), buckets, (ChipAmount(0),),
                    (Decimal(0),), frozenset(line(p) for p in self.paths),
                    hero_positions=frozenset({Position.BB, Position.SB}),
                )

    def query(self, context):
        if hasattr(self, "_river_start"):
            from .river_projection import query_projection
            return query_projection(self, context)
        if isinstance(context, DecisionContext) and context.action_line != line(()):
            return self._query_path(context)
        try:
            with localcontext(_fixed_decimal_context()):
                ranges = _validate_context(context)
                require(" ".join(str(c) for c in context.board_cards)
                        == self.config["board"]
                        and context.seats[0].stack.value
                        == Decimal(str(self.config["effective_stack"]))
                        and context.pots[0].amount.value
                        == Decimal(str(self.config["starting_pot"])),
                        "model_ROOT_facts_mismatch")
                for role, distribution in zip(("oop", "ip"), ranges):
                    require(dict(distribution.combo_weights)
                            == weighted_range(self.config[role + "_range"]),
                            "model_ROOT_range_mismatch")
                labels = tuple((a["kind"], context.seats[0].stack.value
                                if a["kind"] == "AllIn" else a.get("amount"))
                               for a in self.root["actions"])
                require(labels == expected_root_actions(self.config),
                        "saved_ROOT_model_menu_mismatch")
                combos = [_combo(row["cards"])
                          for row in self.solution["root_combos"][0]]
                width = self.root["combo_count"]
                require(len(combos) == width and len(set(combos)) == width
                        and set(combos) == set(ranges[0].combo_weights),
                        "ROOT_combo_axis_mismatch")
                hero = _combo("".join(str(c) for c in context.hero_cards))
                require(hero in combos, "hero_not_in_ROOT_range")
                values = self.root["strategy"]
                require(len(values) == width * len(labels), "strategy_shape_mismatch")
                raw = [Decimal(str(values[a * width + combos.index(hero)]))
                       for a in range(len(labels))]
                require(all(p.is_finite() and 0 <= p <= 1 for p in raw)
                        and abs(sum(raw) - 1) <= MASS_TOLERANCE,
                        "probability_row_invalid")
                meta = self.solution["meta"]
                measured = Decimal(str(meta["exploitability_pct_of_pot"]))
                require(meta.get("payoff_unit", "chips") == "chips"
                        and meta["iterations"] > 0 and measured.is_finite()
                        and 0 <= measured <= Decimal(str(
                            self.config["target_exploitability"])), "NOT_CONVERGED")
                options, totals, sizes = [], {}, []
                for (label, amount), probability in zip(labels, raw):
                    action = ActionType.CHECK if label == "Check" else ActionType.BET
                    if amount is not None:
                        require(amount % context.game_config.minimum_chip.value == 0
                                and any(a.action is ActionType.BET
                                        and a.min_amount.value <= amount
                                        <= a.max_amount.value
                                        for a in context.legal_actions),
                                "model_size_outside_native_menu")
                        sizes.append(ChipAmount(amount))
                    probability /= sum(raw)
                    options.append(ActionOption(action, probability,
                                                ChipAmount(amount) if amount else None,
                                                label))
                    totals[action] = totals.get(action, Decimal(0)) + probability
                # Decimal division can leave a final-digit residual; preserve all
                # branches, assigning only that residual to the final branch.
                residual = Decimal(1) - sum(o.probability for o in options)
                if residual:
                    from dataclasses import replace
                    last = options[-1]
                    options[-1] = replace(last, probability=last.probability + residual)
                    totals[last.action] += residual
                candidate = StrategyCandidate(
                    context.hand_id, context.state_version, context.request_id,
                    self.provider_id, self.source_version, MatchKind.EXACT, 1.0,
                    totals, recommended_sizes={ActionType.BET: tuple(sizes)},
                    action_options=tuple(options), action_ev={}, confidence=0,
                    evidence=("source_engine:ucsandman/postflop",
                              "engine_pin:" + ENGINE_PIN,
                              "result_origin:" + self.origin,
                              "solution_sha256:" + self.sha256,
                              "config_sha256:" + config_digest(self.config)),
                    assumptions=context.assumptions + (
                        "restricted_bet_abstraction_not_full_native_strategy",
                        "action_EV_absent", "source_labels_not_authenticated",
                    ), produced_at=datetime.now(timezone.utc),
                    expires_at=context.request.expires_at,
                )
                return ProviderResult(
                    LookupState.HIT_EXACT, self.provider_id, candidate)
        except (RootError, KeyError, TypeError, ValueError) as exc:
            return ProviderResult(LookupState.REJECTED, self.provider_id,
                                  reasons=(str(exc),))

    def _decision(self, path):
        require(type(path) is tuple and path in self.paths, "path_not_catalogued")
        node, actor, bets = self.paths[path]
        return self._nodes[node], actor, tuple(Decimal(b) for b in bets)

    def for_multiway_river(self, start, *, action_order, origin):
        """Opt-in declared river projection; the original provider is unchanged."""
        from .river_projection import bind_projection
        return bind_projection(self, start, action_order, origin)

    def river_ranges(self, path):
        """Saved-policy ranges in original seats and declared source namespace."""
        from .river_projection import projected_ranges
        return projected_ranges(self, path)

    def projected_advice(self, context):
        """Frequency lookup plus the existing mandatory research-only hard gate."""
        from poker_engine.strategy.advice import build_advice
        from poker_engine.strategy.router import StrategyRouter
        from .river_projection import projection_gate
        return build_advice(context, StrategyRouter((self,)).route(context),
                            hard_gates=(projection_gate(self),))

    def model_menu(self, path):
        """Saved abstraction menu, kept separate from the complete native menu."""
        with localcontext(_fixed_decimal_context()):
            node, actor, bets = self._decision(path)
            pot = Decimal(str(self.config["starting_pot"]))
            stack = Decimal(str(self.config["effective_stack"]))
            half = pot / 2
            expected = [("Check", None), ("Bet", half), ("Bet", pot),
                        ("AllIn", None)] if node["node"] in (0, 1) else (
                [("Fold", None), ("Call", None), ("Raise", 5 * half),
                 ("AllIn", None)] if node["node"] in (3, 21) else (
                    [("Fold", None), ("Call", None), ("AllIn", None)]
                    if node["node"] in (12, 30) else
                    [("Fold", None), ("Call", None)]))
            require(node["player"] == actor
                    and node["combo_count"] == len(self.solution["root_combos"][actor])
                    and [(a["kind"], a.get("amount")) for a in node["actions"]]
                    == expected, "catalog_saved_menu_or_axis_mismatch")
            call = min(bets[1 - actor] - bets[actor], stack - bets[actor])
            result = []
            for kind, amount in expected:
                action = ActionType(kind.lower()) if kind != "AllIn" else (
                    ActionType.RAISE if call > 0 else ActionType.BET)
                if kind == "AllIn":
                    # ROOT remaining stack is this street's maximum total.
                    amount = stack
                if action is ActionType.CALL:
                    amount = call
                amount = Decimal(amount or 0)
                semantics = (ActionAmountSemantics.ADDITIONAL
                             if action is ActionType.CALL else (
                                 ActionAmountSemantics.TOTAL_STREET
                                 if action in (ActionType.BET, ActionType.RAISE)
                                 else ActionAmountSemantics.NONE))
                token = kind.upper() if kind not in ("Bet", "Raise") else (
                    kind.upper() + ":" + chip_text(amount))
                result.append({"action": action, "amount": amount,
                               "semantics": semantics, "source_label": kind,
                               "token": token})
            return tuple(result)

    def _row(self, node, combo):
        actor = node["player"]
        combos = [_combo(item["cards"])
                  for item in self.solution["root_combos"][actor]]
        require(len(set(combos)) == len(combos) == node["combo_count"]
                and len(node["strategy"]) == len(node["actions"]) * len(combos),
                "saved_node_strategy_axis_mismatch")
        require(combo in combos, "hero_not_in_saved_axis")
        slot = combos.index(combo)
        raw = [Decimal(str(node["strategy"][a * len(combos) + slot]))
               for a in range(len(node["actions"]))]
        mass = sum(raw)
        require(all(p.is_finite() and 0 <= p <= 1 for p in raw)
                and abs(mass - 1) <= MASS_TOLERANCE, "probability_row_invalid")
        probabilities = [p / mass for p in raw[:-1]]
        return tuple(probabilities + [Decimal(1) - sum(probabilities)])

    def path_ranges(self, path):
        """Reuse the existing tracker to condition priors on saved average policy."""
        with localcontext(_fixed_decimal_context()):
            self._decision(path)
            ranges = [RangeDistribution(i, weighted_range(self.config[role + "_range"]),
                                        RANGE_SOURCE, RANGE_VERSION)
                      for i, role in enumerate(("oop", "ip"))]
            for index, token in enumerate(path):
                prefix = path[:index]
                node, actor, _ = self._decision(prefix)
                tokens = [a["token"] for a in self.model_menu(prefix)]
                require(token in tokens, "path_step_outside_saved_menu")
                column = tokens.index(token)
                likelihoods = {combo: self._row(node, combo)[column]
                               for combo in ranges[actor].combo_weights}
                try:
                    update = bayesian_action_update(
                        ranges[actor], likelihoods,
                        source_version=(RANGE_VERSION + "/" + self.sha256
                                        + "/" + line(path[:index + 1])),
                    )
                except InvalidStateError:
                    raise RootError("zero_saved_policy_reach") from None
                require(not update.missing_likelihood_combos
                        and update.likelihood_coverage == 1,
                        "incomplete_saved_policy_likelihoods")
                ranges[actor] = update.distribution
            require(any(not {a[:2], a[2:]} & {b[:2], b[2:]}
                        for a in ranges[0].combo_weights
                        for b in ranges[1].combo_weights),
                    "zero_compatible_joint_policy_reach")
            return tuple(ranges)

    def context_for_path(self, path, hero, *, request=None, max_seats=2):
        """Owned synthetic fixture using the existing config's street start."""
        from poker_engine.core.request_context import RequestContext
        from .fixtures import Case, native_path
        with localcontext(_fixed_decimal_context()):
            _, actor, _ = self._decision(path)
            identity = ASSETS[self.sha256][0] + "/" + line(path) + "/" + hero
            request = request or RequestContext(identity, 1, identity,
                                                datetime.now(timezone.utc))
            case = Case(identity, self.config["board"],
                        int(self.config["starting_pot"]),
                        int(self.config["effective_stack"]),
                        self.config["oop_range"], self.config["ip_range"], hero)
            return native_path(case, path, actor, self.path_ranges(path), request,
                               max_seats=max_seats)

    def _query_path(self, context):
        try:
            with localcontext(_fixed_decimal_context()):
                require(context.is_decision_ready, "context_not_ready")
                config = context.game_config
                require(config.dealt_player_count == 2
                        and tuple(s.seat_id for s in context.seats) == (0, 1)
                        and context.active_seats == (0, 1),
                        "saved_asset_dealt_and_contender_history_scope")
                require(config.variant == "NLHE" and config.game_type is GameType.CASH
                        and config.small_blind.value == 1
                        and config.big_blind.value == 2
                        and config.minimum_chip.value == 1 and config.ante.value == 0
                        and config.rake_percent == 0 and config.rake_cap.value == 0,
                        "unsupported_units_or_rules")
                require("query_model:" + MODEL in context.assumptions
                        and [a for a in context.assumptions
                             if a.startswith("execution_mode:")]
                        == ["execution_mode:simulation"], "synthetic_model_required")
                require(isinstance(context.action_line, str)
                        and context.action_line.startswith("hu-root:"),
                        "path_not_catalogued")
                path = tuple(context.action_line.removeprefix("hu-root:").split(","))
                node, actor, bets = self._decision(path)
                require(context.hero_seat == context.actor_seat == actor,
                        "actor_mismatch")
                require(context.hero_range is not None
                        and context.hero_range.seat_id == actor
                        and len(context.villain_ranges) == 1
                        and context.villain_ranges[0].seat_id == 1 - actor,
                        "range_role_conflict")
                ranges = self.path_ranges(path)
                supplied = {r.seat_id: r for r in
                            (context.hero_range,) + context.villain_ranges}
                require(all(dict(supplied[i].combo_weights) == dict(r.combo_weights)
                            and supplied[i].source == r.source
                            and supplied[i].source_version == r.source_version
                            for i, r in enumerate(ranges)),
                        "conditional_range_mismatch")
                hero = _combo("".join(str(c) for c in context.hero_cards))
                require(hero in ranges[actor].combo_weights,
                        "hero_not_in_positive_policy_reach")
                require(any(not {hero[:2], hero[2:]} & {c[:2], c[2:]}
                            for c in ranges[1 - actor].combo_weights),
                        "hero_has_no_compatible_opponent")
                replay = self.context_for_path(path, hero, request=context.request,
                                               max_seats=config.max_seats)
                require(context.board_cards == replay.board_cards
                        and context.street is replay.street, "board_or_street_mismatch")
                require(context.seats == replay.seats and context.pots == replay.pots
                        and context.effective_stacks == replay.effective_stacks
                        and context.effective_stack_bb == replay.effective_stack_bb,
                        "native_replay_accounting_or_status_mismatch")
                require(context.legal_actions == replay.legal_actions,
                        "complete_native_menu_or_semantics_mismatch")
                require(len(context.action_history) == len(replay.action_history),
                        "path_history_mismatch")
                for actual, expected in zip(context.action_history,
                                            replay.action_history):
                    require(actual.hand_id == context.hand_id
                            and actual.state_version == context.state_version
                            and actual.source == expected.source
                            and actual.event_type is expected.event_type
                            and type(actual.payload.get("seat")) is int
                            and dict(actual.payload) == dict(expected.payload)
                            and actual.timestamp <= context.request.requested_at,
                            "path_history_mismatch")
                meta = self.solution["meta"]
                measured = Decimal(str(meta["exploitability_pct_of_pot"]))
                require(meta.get("payoff_unit", "chips") == "chips"
                        and meta["iterations"] > 0 and measured.is_finite()
                        and 0 <= measured <= Decimal(str(
                            self.config["target_exploitability"])), "NOT_CONVERGED")
                options, totals, sizes = [], {}, {}
                # Leave ten digits of addition headroom for the existing exact
                # Candidate contracts. Grouping four 40-digit probabilities by
                # action can otherwise differ by a final Decimal rounding digit.
                # This changes only wire precision, far below the f32 tolerance;
                # path-range likelihoods above retain their saved-policy precision.
                probabilities = [p.quantize(Decimal("1e-30"))
                                 for p in self._row(node, hero)]
                largest = max(range(len(probabilities)), key=probabilities.__getitem__)
                probabilities[largest] += Decimal(1) - sum(probabilities)
                for item, probability in zip(
                    self.model_menu(path), probabilities,
                ):
                    action, amount, semantics = (
                        item[k] for k in ("action", "amount", "semantics")
                    )
                    require(amount % config.minimum_chip.value == 0
                            and any(a.action is action
                                    and a.amount_semantics is semantics
                                    and a.min_amount.value <= amount
                                    <= a.max_amount.value
                                    for a in context.legal_actions),
                            "model_action_outside_native_menu")
                    chip = ChipAmount(amount) if action in (
                        ActionType.BET, ActionType.RAISE) else None
                    options.append(ActionOption(action, probability, chip,
                                                item["source_label"]))
                    totals[action] = totals.get(action, Decimal(0)) + probability
                    if chip is not None:
                        sizes.setdefault(action, []).append(chip)
                candidate = StrategyCandidate(
                    context.hand_id, context.state_version, context.request_id,
                    self.provider_id, self.source_version, MatchKind.EXACT, 1.0,
                    totals, action_options=tuple(options),
                    recommended_sizes={a: tuple(v) for a, v in sizes.items()},
                    action_ev={}, confidence=0,
                    evidence=("source_engine:ucsandman/postflop",
                              "engine_pin:" + ENGINE_PIN,
                              "result_origin:" + self.origin,
                              "solution_sha256:" + self.sha256,
                              "config_sha256:" + config_digest(self.config),
                              "path_catalog:" + CATALOG_VERSION,
                              "saved_node:" + str(node["node"]),
                              "path_unit:total_street_chips",
                              "ranges:existing_bayesian_action_update_saved_policy"),
                    assumptions=context.assumptions + (
                        "restricted_bet_abstraction_not_full_native_strategy",
                        "conditional_independent_model_ranges_not_empirical",
                        "saved_f32_candidate_30_digit_wire_mass",
                        "action_EV_absent", "source_labels_not_authenticated"),
                    produced_at=datetime.now(timezone.utc),
                    expires_at=context.request.expires_at,
                )
                return ProviderResult(LookupState.HIT_EXACT, self.provider_id,
                                      candidate)
        except (RootError, KeyError, TypeError, ValueError) as exc:
            return ProviderResult(LookupState.REJECTED, self.provider_id,
                                  reasons=(str(exc),))
