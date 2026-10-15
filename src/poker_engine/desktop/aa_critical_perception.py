"""Source-bound critical AA8 candidates. This module grants no truth authority.

KNOWN means an internally consistent machine candidate, never a confirmed fact
or measured visual accuracy. Historical observations are retained in the row.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re


FIELDS = ("board", "hero_participation", "participation", "all_in_seats",
          "river_first_actor")
SEMANTICS = "SOURCE_BOUND_MACHINE_CANDIDATES_NOT_TRUTH"
CAUSAL_EVIDENCE_KEY = "critical_perception_evidence_v1"
MAX_BOARD_WITNESSES = 4
MAX_TRANSITION_ROWS = 256
_CARD = re.compile(r"[2-9TJQKA][cdhs]")
_HASH = re.compile(r"[0-9a-f]{64}")
_STATES = {"active": "ACTIVE", "folded": "FOLDED", "all_in": "ALL_IN",
           "waiting": "WAITING", "empty": "EMPTY"}


def _binding(row):
    state = row.get("observed_state_v2") or {}
    return {"source_id": row.get("source_id"), "epoch": state.get("observed_epoch"),
            "frame": row.get("frame"), "source_frame": row.get("source_frame"),
            "pts_seconds": row.get("pts_seconds"),
            "source_sha256": row.get("source_sha256")}


def _valid_binding(binding):
    return (isinstance(binding["source_id"], str) and bool(binding["source_id"])
            and isinstance(binding["epoch"], str) and bool(binding["epoch"])
            and all(type(binding[k]) is int and binding[k] >= 0
                    for k in ("frame", "source_frame"))
            and type(binding["pts_seconds"]) in (int, float)
            and math.isfinite(binding["pts_seconds"]) and binding["pts_seconds"] >= 0
            and isinstance(binding["source_sha256"], str)
            and _HASH.fullmatch(binding["source_sha256"]) is not None)


RAW_KEYS = ("source_id", "source_frame", "frame", "pts_seconds", "source_sha256",
            "scene_supported", "reader_gap_reset", "special_modes", "cards",
            "board_count",
            "observed_state_v2", "participation", "current_actor", "actor_evidence",
            "stacks", "dealer_seat", "dealer_evidence_v2", "dealer_observation_v2",
            "glyphs",
            "observed_actions_v2", "glyph_transitions", "action_history_candidate",
            "causal_street_wagers_v2", "street_wagers", "wager_visibility_v2",
            "observed_center_v2", "pot")


def _raw_input(row):
    return deepcopy({key: row.get(key) for key in RAW_KEYS})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(row):
    raw = {key: row.get(key) for key in RAW_KEYS}
    raw[CAUSAL_EVIDENCE_KEY] = row.get(CAUSAL_EVIDENCE_KEY)
    encoded = _canonical(raw)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _field(value=None, reason="not_supported", *, conflict=False):
    status = "CONFLICT" if conflict else "UNKNOWN" if value is None else "KNOWN"
    return {"status": status,
            "value": deepcopy(value), "reasons": [] if value is not None else [reason]}


def _blocked(row):
    modes = row.get("special_modes") or {}
    return (row.get("scene_supported") is not True
            or modes.get("block_state_updates") is True
            or modes.get("insurance") == "VISIBLE")


def _board(row):
    state, cards = row.get("observed_state_v2") or {}, row.get("cards") or {}
    stage = state.get("street_candidate")
    size = {"flop": 3, "turn": 4, "river": 5}.get(stage)
    values = cards.get("board_slots")
    geometry = state.get("positive_board_geometry") or {}
    if (size is None or row.get("board_count") != size
            or not isinstance(values, list) or len(values) != 5
            or not all(isinstance(c, str) and _CARD.fullmatch(c) for c in values[:size])
            or any(c is not None for c in values[size:])
            or len(set(values[:size])) != size
            or state.get("board_candidate") != values[:size]
            or geometry.get("last_frame") != row.get("frame")
            or type(geometry.get("streak")) is not int or geometry["streak"] < 2):
        return None
    hero = cards.get("hero") or []
    if not isinstance(hero, list) or set(hero) & set(values[:size]):
        return None
    return values[:size]


def _participation(row):
    state = row.get("observed_state_v2") or {}
    epoch, frame = state.get("observed_epoch"), row.get("frame")
    participants, cues = state.get("participants") or {}, (
        row.get("participation") or {}).get("slots") or {}
    conflicts = set(state.get("critical_status_conflicts") or [])
    result, unknown = {}, []
    for seat in map(str, range(8)):
        item, cue = participants.get(seat) or {}, cues.get(seat) or {}
        value = item.get("state")
        if cue.get("conflict") or seat in conflicts:
            return None, "participation_conflict:" + seat, True
        evidence_frame = item.get("evidence_frame")
        if (item.get("epoch") != epoch or value not in _STATES
                or type(evidence_frame) is not int or evidence_frame > frame):
            unknown.append(seat)
            continue
        # Terminal events persist within a hand. Active/occupancy observations
        # require current positive support; historical ACTIVE is not currentness.
        if value not in ("folded", "all_in") and evidence_frame != frame:
            unknown.append(seat)
            continue
        if value in ("active", "all_in"):
            stack = (row.get("stacks") or {}).get(seat) or {}
            try:
                text = stack.get("value")
                number = (Decimal(text) if isinstance(text, str) and len(text) <= 64
                          else None)
            except (InvalidOperation, TypeError, ValueError):
                number = None
            if (number is None or not number.is_finite()
                    or (number <= 0 if value == "active" else number != 0)):
                unknown.append(seat)
                continue
        result[seat] = _STATES[value]
    return result, "current_participation_missing:" + ",".join(unknown), False


def _empty_wagers(row):
    wagers = row.get("causal_street_wagers_v2") or {}
    vector = wagers.get("wagers")
    return (wagers.get("status") == "OBSERVED_STREET_WAGERS_CANDIDATE"
            and wagers.get("title_center_ledger_reconciled") is True
            and isinstance(vector, dict) and set(vector) == set(map(str, range(8)))
            and all(v in ("0", "0.0", "0.00") if isinstance(v, str)
                    else v == {"status": "NOT_APPLICABLE"} for v in vector.values()))


def _provisional_empty_wagers(row):
    """Only retain the first initializer frame; never publish UNKNOWN as zero."""
    causal = row.get("causal_street_wagers_v2") or {}
    raw, visibility = row.get("street_wagers"), row.get("wager_visibility_v2")
    if (causal.get("status") != "WAGERS_UNKNOWN"
            or causal.get("reason") != "two_stable_frames_required"
            or not isinstance(raw, dict) or set(raw) != set(map(str, range(8)))
            or not isinstance(visibility, dict)
            or set(visibility) != set(map(str, range(8)))
            or any(value is not None for value in raw.values())
            or any(v.get("status") != "VISIBLE_EMPTY_CANDIDATE"
                   for v in visibility.values())):
        return False
    try:
        values = [(row.get(key) or {}).get("value") for key in (
            "pot", "observed_center_v2")]
        if any(not isinstance(v, str) or len(v) > 64 for v in values):
            return False
        title, center = map(Decimal, values)
        return title.is_finite() and center.is_finite() and title == center >= 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _actor_supported(row):
    evidence = row.get("actor_evidence") or {}
    actor = row.get("current_actor")
    if actor == 4 and evidence.get("reason") == "hero_buttons":
        return evidence.get("hero_turn") is True
    return (type(actor) is int and evidence.get("actor") == actor
            and evidence.get("timer_suffix_verified") is True
            and evidence.get("reason") in (
                "unique_bright_ring_candidate",
                "unique_ring_and_suffix_union_candidate"))


def _no_river_actions(row, start):
    state = row.get("observed_state_v2") or {}
    lists = ("observed_actions_v2", "glyph_transitions", "action_history_candidate")
    if (state.get("pending_actions") != 0
            or any(not isinstance(row.get(key), list) for key in lists)
            or row["observed_actions_v2"] or row["glyph_transitions"]):
        return False
    # Old, still-visible fold badges are not new river actions. Both the event
    # onset and semantic street are checked, including zero-cost CHECK/FOLD.
    return not any(a.get("epoch") == state.get("observed_epoch")
                   and (a.get("street") == "river" or
                        type(a.get("frame")) is int and a["frame"] >= start)
                   for a in row["action_history_candidate"])


class _ProjectionReducer:
    """Causal qualification, with no image models, labels, or solver access."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.last = None
        self.board = None
        self.board_conflict = False
        self.river = None

    def observe(self, row):
        binding = _binding(row)
        fields = {key: _field(reason="source_or_current_context_missing")
                  for key in FIELDS}
        result = {"schema_version": 1, "semantics": SEMANTICS,
                  "candidate_only": True, "strategy_eligible": False,
                  "advice_emitted": False, "binding": binding,
                  "raw_evidence_digest": _digest(row), "window": [], "fields": fields}
        previous = self.last
        valid = _valid_binding(binding) and not _blocked(row)
        contiguous = (valid and previous is not None
                      and previous["binding"]["source_id"] == binding["source_id"]
                      and previous["binding"]["epoch"] == binding["epoch"]
                      and previous["binding"]["frame"] + 1 == binding["frame"]
                      and previous["binding"]["source_frame"] + 1 == (
                          binding["source_frame"])
                      and 0 < binding["pts_seconds"] - previous["binding"][
                          "pts_seconds"] <= 1
                      and row.get("reader_gap_reset") is not True)
        if not contiguous:
            self.reset()
        if not valid:
            return result
        board = _board(row)
        if board is not None:
            if self.board is not None and (len(board) < len(self.board)
                                           or board[:len(self.board)] != self.board):
                self.board_conflict = True
            if not self.board_conflict:
                self.board = list(board)
        fields["board"] = (_field(reason="board_changed_within_hand", conflict=True)
                           if self.board_conflict else _field(
                               board if board is not None and len(board) == 5 else None,
                               "current_complete_river_board_missing"))
        states, reason, conflict = _participation(row)
        fields["participation"] = _field(
            states if states is not None and len(states) == 8 else None,
            reason, conflict=conflict)
        hero = (states or {}).get("4")
        fields["hero_participation"] = _field(
            hero if hero in ("ACTIVE", "FOLDED", "ALL_IN") else None,
            reason, conflict=conflict)
        fields["all_in_seats"] = _field(
            sorted(int(s) for s, v in states.items() if v == "ALL_IN")
            if states is not None and len(states) == 8 else None,
            reason, conflict=conflict)
        state = row.get("observed_state_v2") or {}
        active = sorted(int(s) for s, v in (states or {}).items() if v == "ACTIVE")
        dealer, actor = row.get("dealer_seat"), row.get("current_actor")
        # Seat numbering is the fixed AA8 clockwise layout. The dealer evidence
        # must be current, and two actor observations must corroborate that order.
        dealer_evidence = row.get("dealer_evidence_v2") or {}
        first = (min(active, key=lambda s: (s - dealer) % 8 or 8)
                 if type(dealer) is int and 0 <= dealer < 8 and active else None)
        start = self.river["start"] if self.river else binding["frame"]
        no_actions = _no_river_actions(row, start)
        geometry = state.get("positive_board_geometry") or {}
        river_geometry = (state.get("street_candidate") in (None, "river")
                          and row.get("board_count") == 5
                          and geometry.get("last_frame") == binding["frame"]
                          and type(geometry.get("streak")) is int
                          and geometry["streak"] >= 1)
        wagers_ready = _empty_wagers(row)
        provisional = _provisional_empty_wagers(row)
        supported = (not self.board_conflict and len(states or {}) == 8
                     and river_geometry and no_actions
                     and (wagers_ready or provisional)
                     and _actor_supported(row) and actor == first
                     and dealer_evidence.get("dealer_seat") == dealer
                     and dealer_evidence.get("epoch") == binding["epoch"]
                     and dealer_evidence.get("frame") == binding["frame"]
                     and (row.get("dealer_observation_v2") or {}).get(
                         "dealer_seat") == dealer)
        if (contiguous and previous["stage"] == "turn" and previous["board"] is not None
                and len(previous["board"]) == 4 and supported):
            self.river = {"actor": actor, "start": binding["frame"],
                          "window": [previous["binding"], binding], "states": states,
                          "dealer": dealer, "turn_board": previous["board"],
                          "requires_initial_baseline": not wagers_ready}
        elif self.river is not None:
            if (not contiguous or not supported
                    or states != self.river["states"] or dealer != self.river["dealer"]
                    or actor != self.river["actor"]
                    or len(self.river["window"]) >= 256):
                self.river = None
            else:
                self.river["window"].append(binding)
                baseline = (row.get("causal_street_wagers_v2") or {}).get(
                    "baseline_evidence_frames")
                initial_baseline = (not self.river["requires_initial_baseline"] or
                                    baseline == [self.river["start"],
                                                 self.river["start"] + 1])
                if (wagers_ready and initial_baseline
                        and fields["board"]["status"] == "KNOWN"
                        and board[:4] == self.river["turn_board"]):
                    fields["river_first_actor"] = _field(actor)
                    result["window"] = deepcopy(self.river["window"])
        self.last = {"binding": binding, "stage": state.get("street_candidate"),
                     "board": board}
        return result


def _same_context(left, right):
    return (left["source_id"] == right["source_id"] and left["epoch"] == right["epoch"])


def _ordered(left, right, *, adjacent=False):
    if not (_valid_binding(left) and _valid_binding(right)
            and _same_context(left, right)):
        return False
    if adjacent:
        return (right["frame"] == left["frame"] + 1
                and right["source_frame"] == left["source_frame"] + 1
                and 0 < right["pts_seconds"] - left["pts_seconds"] <= 1)
    return (right["frame"] > left["frame"]
            and right["source_frame"] > left["source_frame"]
            and right["pts_seconds"] > left["pts_seconds"])


def _board_progression(rows):
    """Reproduce board changes from raw witnesses, never from a stored flag."""
    previous = None
    for index, row in enumerate(rows):
        board = _board(row)
        if board is None or board == previous:
            raise ValueError("invalid_or_redundant_board_witness")
        if previous is not None and (
                len(board) < len(previous) or board[:len(previous)] != previous):
            if index != len(rows) - 1:
                raise ValueError("board_witnesses_must_stop_after_first_conflict")
            return True
        previous = board
    return False


def _reconstruct(row):
    """Pure semantic replay of separately retained raw candidate evidence."""
    evidence = row.get(CAUSAL_EVIDENCE_KEY)
    if (not isinstance(evidence, dict)
            or set(evidence) != {"schema_version", "board_witnesses", "transition_rows"}
            or type(evidence["schema_version"]) is not int
            or evidence["schema_version"] != 1):
        raise ValueError("causal_evidence_required")
    boards, temporal = evidence["board_witnesses"], evidence["transition_rows"]
    if (not isinstance(boards, list) or len(boards) > MAX_BOARD_WITNESSES
            or not isinstance(temporal, list)
            or not 1 <= len(temporal) <= MAX_TRANSITION_ROWS
            or any(not isinstance(item, dict) or set(item) != set(RAW_KEYS)
                   for item in boards + temporal)):
        raise ValueError("invalid_or_overflowed_causal_evidence")
    current = _raw_input(row)
    if _canonical(temporal[-1]) != _canonical(current):
        raise ValueError("causal_evidence_current_end_mismatch")
    binding = _binding(current)
    if not _valid_binding(binding) or _blocked(current):
        if boards or len(temporal) != 1:
            raise ValueError("invalid_context_cannot_retain_temporal_evidence")
    else:
        seen = {}
        bindings = {}
        for item in boards + temporal:
            ref = _binding(item)
            if (not _valid_binding(ref) or not _same_context(ref, binding)
                    or _blocked(item) or ref["frame"] > binding["frame"]
                    or ref["frame"] < binding["frame"] and not _ordered(ref, binding)):
                raise ValueError("causal_witness_context_mismatch")
            encoded = _canonical(item)
            if ref["frame"] in seen and seen[ref["frame"]] != encoded:
                raise ValueError("conflicting_raw_witness_at_same_frame")
            seen[ref["frame"]] = encoded
            bindings[ref["frame"]] = ref
        merged = [bindings[frame] for frame in sorted(bindings)]
        for previous, following in zip(merged, merged[1:]):
            gap = following["frame"] - previous["frame"]
            if (not _ordered(previous, following)
                    or following["source_frame"] - previous["source_frame"] != gap
                    or following["pts_seconds"] - previous["pts_seconds"] > gap):
                raise ValueError("merged_causal_witness_chronology_mismatch")
        for previous, following in zip(boards, boards[1:]):
            if (not _ordered(_binding(previous), _binding(following))
                    or following.get("reader_gap_reset") is True):
                raise ValueError("board_witness_order_or_reset")
        for previous, following in zip(temporal, temporal[1:]):
            if (not _ordered(_binding(previous), _binding(following), adjacent=True)
                    or following.get("reader_gap_reset") is True):
                raise ValueError("transition_witness_gap_or_reset")
    board_conflict = _board_progression(boards)
    for item in temporal:
        board = _board(item)
        if board is None or _blocked(item) or not _valid_binding(_binding(item)):
            continue
        prior = [w for w in boards if w["frame"] <= item["frame"]]
        if not prior or (not _board_progression(prior) and _board(prior[-1]) != board):
            raise ValueError("board_progression_witness_missing")
    reducer = _ProjectionReducer()
    for item in temporal:
        result = reducer.observe(item)
    if board_conflict:
        result["fields"]["board"] = _field(
            reason="board_changed_within_hand", conflict=True)
        result["fields"]["river_first_actor"] = _field(
            reason="board_changed_within_hand", conflict=True)
        result["window"] = []
    result["raw_evidence_digest"] = _digest(row)
    return result


class CriticalPerceptionBoundary:
    """Retain bounded raw evidence separately; derive every cached conclusion.

    observe appends only CAUSAL_EVIDENCE_KEY to its row. Original raw fields are
    unchanged. Sparse board witnesses preserve every legal progression and the
    first contradiction; action evidence is always a contiguous raw window.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.last = None
        self.boards = []
        self.temporal = []
        self.has_turn_anchor = False

    def observe(self, row):
        raw = _raw_input(row)
        binding = _binding(raw)
        valid = _valid_binding(binding) and not _blocked(raw)
        if (not valid or self.last is None
                or not _ordered(self.last, binding, adjacent=True)
                or raw.get("reader_gap_reset") is True):
            self.reset()
        if valid:
            board = _board(raw)
            conflict = _board_progression(self.boards)
            if (board is not None and not conflict
                    and (not self.boards or _board(self.boards[-1]) != board)):
                self.boards.append(raw)
                conflict = _board_progression(self.boards)
            if board is not None and len(board) == 4 and not conflict:
                self.temporal = [raw]
                self.has_turn_anchor = True
            elif self.has_turn_anchor and len(self.temporal) < MAX_TRANSITION_ROWS:
                self.temporal.append(raw)
            else:
                self.temporal = [raw]
                self.has_turn_anchor = False
            self.last = binding
        else:
            self.temporal = [raw]
        row[CAUSAL_EVIDENCE_KEY] = deepcopy({
            "schema_version": 1, "board_witnesses": self.boards,
            "transition_rows": self.temporal})
        return _reconstruct(row)


def checked_view(row, derived=None):
    """Re-derive the entire view; cached statuses and windows own no authority.

    ``derived`` is ``_reconstruct(row)`` when the caller has just worked it
    out on this very row (the live reader, right after
    ``CriticalPerceptionBoundary.observe``); it is compared with the stored
    view the same way.

    Raw witness authenticity still belongs to external source verification.
    This check does not create a real-hand confirmation or a signed receipt.
    """
    try:
        view = row.get("critical_perception_v1")
        if not isinstance(view, dict):
            return None
        if derived is None:
            derived = _reconstruct(row)
        return derived if _canonical(view) == _canonical(derived) else None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def target_s_candidate_screen(row, derived=None):
    """Screen shape only. Never substitutes for human factual confirmation."""
    view = checked_view(row, derived)
    reasons = []
    if view is None:
        reasons.append("critical_candidate_view_missing_or_invalid")
    else:
        fields = view["fields"]
        reasons.extend("critical_field_not_known:" + name for name in FIELDS
                       if fields[name]["status"] != "KNOWN")
        if not reasons:
            states = fields["participation"]["value"]
            if fields["hero_participation"]["value"] != "ACTIVE":
                reasons.append("hero_not_active")
            if sum(value == "ACTIVE" for value in states.values()) != 3:
                reasons.append("not_exactly_three_active")
            if fields["all_in_seats"]["value"]:
                reasons.append("all_in_at_river_start")
            if fields["river_first_actor"]["value"] != 4:
                reasons.append("hero_not_river_first_actor")
    return {"status": "SCREEN_BLOCKED" if reasons else "SCREEN_ELIGIBLE",
            "reasons": reasons, "candidate_only": True,
            "semantics": "TARGET_S_STRUCTURAL_CANDIDATE_NOT_ACCEPTANCE",
            "binding": deepcopy(view["binding"]) if view else None,
            "strategy_eligible": False, "advice_emitted": False,
            "real_hand_confirmed": False}
