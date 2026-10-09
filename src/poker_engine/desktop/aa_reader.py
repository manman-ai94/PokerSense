"""Explicit AA8 candidate reader for a source-checkout desktop session.

Preflight reads configuration and file metadata only. Constructing AA8Reader
loads the configured development model references; it never opens a device.
Candidates remain distinct from complete legal state and live strategy.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from types import ModuleType
import uuid

import numpy as np

from ..data_paths import resolve_legacy_path
from .aa_seat_states import AASeatStates, SeatCueRecorder, icon_template
from .aa_action_history import AAActionHistory
from .aa_street import AAStreet
from .aa_semantics import AAObservationSemantics


_POOLS = ("source", "context_source", "late_source", "bomb_pool")
_FILES = ("bank_path", "profile_path", "heads_path", "reservations")
_REQUIRED = set(_POOLS + _FILES + ("audit",))
_HASH = re.compile(r"[0-9a-f]{64}")
GAP_SECONDS = 1.0               # a longer gap starts the frame reading over
HAND_GAP_SECONDS = 3.0          # and a longer one the street and the hand too


def _path(value, root):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty_path_required")
    legacy = resolve_legacy_path(value)
    if legacy is not None:
        return legacy.resolve()
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _profile(path):
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(raw, dict) or not _REQUIRED <= set(raw)
            or set(raw) - _REQUIRED - {"glyph_supplement", "bundle_manifest"}):
        raise ValueError("explicit_aa8_factory_fields_required")
    if not isinstance(raw["audit"], str) or not _HASH.fullmatch(raw["audit"]):
        raise ValueError("training_audit_sha256_required")
    spec = {key: str(_path(raw[key], path.parent)) for key in _POOLS + _FILES}
    spec["audit"] = raw["audit"]
    refs = raw.get("glyph_supplement", [])
    if not isinstance(refs, list):
        raise ValueError("glyph_supplement_list_required")
    if refs and (len(refs) != 3 or any(not isinstance(r, dict) for r in refs)):
        raise ValueError("three_competing_glyph_references_required")
    supplements = []
    for row in refs:
        if (set(row) != {"label", "path", "slot", "sha256"}
                or row["label"] not in ("fold", "muck", "all_in")
                or type(row["slot"]) is not int or not 0 <= row["slot"] < 8
                or not isinstance(row["sha256"], str)
                or not _HASH.fullmatch(row["sha256"])):
            raise ValueError("invalid_glyph_reference")
        supplements.append({**row, "path": str(_path(row["path"], path.parent))})
    if supplements and len({r["label"] for r in supplements}) != 3:
        raise ValueError("three_competing_glyph_references_required")
    return path, spec, supplements


def preflight_profile(path, *, bundle_sha256=None):
    """Describe readiness without decoding models/images or opening devices.

    Portable bundles additionally hash all model bytes against a trusted digest.
    """
    result = {"ready": False, "errors": [], "paths": {},
              "strategy_eligible": False, "profile_path": str(path)}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if (isinstance(raw, dict) and "bundle_manifest" in raw
                or bundle_sha256 is not None):
            from .aa_bundle import validate_bundle
            result["bundle"] = validate_bundle(path, bundle_sha256)
        resolved, spec, supplements = _profile(path)
        result["profile_path"] = str(resolved)
        result["paths"] = {k: spec[k] for k in _POOLS + _FILES}
        for key in _POOLS:
            if not Path(spec[key]).is_dir():
                result["errors"].append("missing_directory:" + key)
            elif not (Path(spec[key]) / "samples.json").is_file():
                result["errors"].append("missing_manifest:" + key)
        for key in _FILES:
            if not Path(spec[key]).is_file():
                result["errors"].append("missing_file:" + key)
        for row in supplements:
            if not Path(row["path"]).is_file():
                result["errors"].append("missing_glyph:" + row["label"])
        if Path(spec["profile_path"]).is_file():
            layout = json.loads(Path(spec["profile_path"]).read_text(encoding="utf-8"))
            if (not isinstance(layout, dict) or layout.get("canvas") != [498, 1080]
                    or layout.get("hero_slot") != 4
                    or not isinstance(layout.get("slots"), list)
                    or len(layout["slots"]) != 8
                    or any(not isinstance(r, dict) for r in layout["slots"])
                    or [r.get("slot") for r in layout["slots"]] != list(range(8))):
                result["errors"].append("aa8_hero4_layout_required")
        result["glyph_supplement_configured"] = bool(supplements)
        result["ready"] = not result["errors"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["errors"].append(str(exc))
    return result


class _GlyphReader:
    def __init__(self, base, modes, supplement):
        self.base, self.modes, self.supplement = base, modes, supplement
        self.scene = base.scene
        self.suspended = True

    def recognize(self, image):
        special = self.modes.recognize(image)
        self.suspended = bool(
            self.scene.recognize(image).get("scene") != "AA_TABLE_CANDIDATE"
            or special.get("block_state_updates")
            or special.get("insurance") == "VISIBLE")
        if self.suspended:
            return {str(slot): None for slot in range(8)}
        base = self.base.recognize(image)
        return self.supplement.recognize(image, base, supported=True) if (
            self.supplement is not None) else base


class _Tracker:
    def __init__(self, reader):
        from tools.aa8_glyph_transitions_v2 import GlyphTransitionsV2
        self.reader = reader
        self.tracker = GlyphTransitionsV2()

    def observe(self, frame, glyphs):
        return self.tracker.observe(frame, glyphs, suspended=self.reader.suspended)


POT_LABEL_MATCH = .80      # the "底池:" label match the window reads the pot at


def _live_pipeline(pipeline):
    """The frozen pipeline module with the pot read at ``POT_LABEL_MATCH``.

    The label is matched at .90 against reviewed rasterizations; with the
    label drawn a pixel off, a third to a half of the turn and river frames
    of 10/09 went without a pot (a turn all-in's pot of 273 for 13 s). At .80
    the same frames read, and only one placement of the colon still has to
    match; the digits are read as strictly as before. 10/09 recording, read
    again frame by frame (another decoder than the window's, so .90 already
    read some): of 1445 flop-to-river frames the re-measure had no pot for,
    1081 read at .80 against 669 at .90; 400 frames that had one read the
    same, and every one looked at by eye (18 that differed from a nearby
    reading, 12 more at random) was right.
    The module object is replaced, not changed: the frozen offline tools keep
    .90."""
    from tools.aa8_unmarked_money import pot_patch
    live = ModuleType(pipeline.__name__ + "_live")
    live.__dict__.update(vars(pipeline))

    def unique_pot_patch(image, prefixes):
        candidates = {}
        for prefix in prefixes:
            patch = pot_patch(image, prefix, threshold=POT_LABEL_MATCH)
            if patch is not None:
                key = (patch.shape, hashlib.sha256(patch.tobytes()).hexdigest())
                candidates[key] = patch
        return next(iter(candidates.values())) if len(candidates) == 1 else None

    live.unique_pot_patch = unique_pot_patch
    return live


def _create_candidate(spec):
    # Explicit module, imported only after user starts a configured session.
    from tools.aa8_candidate_v2 import create_candidate
    from .aa_live_context import (
        LiveFrameEvidence, LiveHandLedger, LiveCausalWagers,
    )
    from .aa_live_context_v3 import LiveStateAdapterV3
    from tools.aa8_cards_v2 import AA8CardReaderV2
    state = create_candidate(spec)
    state.p = _live_pipeline(state.p)
    state.cards = AA8CardReaderV2(spec["heads_path"], preprocessing="gaussian_050")
    state.frame_enricher = LiveFrameEvidence(
        state.cache.bank, state.profile, state.seats.empty)
    state.adapter = LiveStateAdapterV3()
    state.hand_ledger = LiveHandLedger()
    state.causal_wagers = LiveCausalWagers()
    from tools.aa8_action_transfer import inventory, load
    source = Path(spec["source"])
    pool = inventory(source, spec["audit"])
    icon = icon_template([load(source, pool[frame]) for frame in (1320, 1500)],
                         state.profile)
    state.seats = SeatCueRecorder(state.seats, icon)
    return state


def _copy_candidate(state):
    """Copy temporal/model state while retaining its imported implementation.

    FrozenPredictionState stores the pipeline module in ``p``. Modules cannot
    be pickled, and must remain shared implementation references, not copies.
    A per-call memo avoids changing deepcopy behavior anywhere else.
    """
    memo = {id(value): value for value in vars(state).values()
            if isinstance(value, ModuleType)}
    return deepcopy(state, memo)


class AA8Reader:
    """Read sampled AA8 observations, never promoting model candidates.

    ``frame`` is the caller's observation sequence, not an invented raw-device
    frame ID. The caller must retain raw capture counters separately. Skips,
    source changes and time gaps reset all temporal state without reloading
    training images. Source elapsed seconds must increase; sampling does not
    establish complete action coverage.

    A gap of up to ``HAND_GAP_SECONDS`` between consecutive frames of one
    source (a stall: on 10/07 and 10/08 a frame took 1.1 to 1.5 s four
    times, each while the advice was being worked out on your turn) starts
    the frame reading over but keeps the street and the hand's history, with
    the gap left out of the street's clock. Before, the hand then counted as
    joined in the middle and got no advice to its end; the cards and badges
    are read again within a few frames, and a badge read again is left out
    (``aa_action_history``).
    """

    def __init__(self, profile_path, *, factory=None, bundle_sha256=None,
                 analysis_enabled=True):
        if type(analysis_enabled) is not bool:
            raise ValueError("analysis_enabled_must_be_boolean")
        self._analysis_enabled = analysis_enabled
        self.preflight = preflight_profile(profile_path, bundle_sha256=bundle_sha256)
        if not self.preflight["ready"]:
            raise ValueError("; ".join(self.preflight["errors"]))
        self._profile_sha256 = hashlib.sha256(
            Path(profile_path).read_bytes()).hexdigest()
        self._bundle_sha256 = bundle_sha256
        _, spec, references = _profile(profile_path)
        state = (factory or _create_candidate)(spec)
        supplement = None
        if references:
            from tools.aa8_glyph_supplement_v3 import GlyphSupplementV3
            from tools.wpk_video_dataset import read_image
            images = {}
            for ref in references:
                path = Path(ref["path"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
                    raise ValueError("glyph_reference_hash_mismatch:" + ref["label"])
                images[ref["label"]] = (read_image(path), ref["slot"])
            supplement = GlyphSupplementV3(state.profile, images)
        state.reader = _GlyphReader(state.reader, state.modes, supplement)
        state.tracker = _Tracker(state.reader)
        self._initial = _copy_candidate(state)
        self._state = state
        self._source = "aa8-session-" + uuid.uuid4().hex
        self._last = None
        self._invalidated = False
        self._semantics = AAObservationSemantics()
        self._seat_states = AASeatStates()
        self._street = AAStreet()
        self._actions = AAActionHistory()
        self._gaps = 0.0            # seconds of stalls left out of the street
        from .aa_critical_perception import CriticalPerceptionBoundary
        self._critical = CriticalPerceptionBoundary()

    def read(self, image, frame, sample):
        try:
            if (not isinstance(image, np.ndarray)
                    or image.shape != (1080, 498, 3) or image.dtype != np.uint8):
                raise ValueError("aa8_uint8_bgr_498x1080_required")
            if type(frame) is not int or frame < 0 or not isinstance(sample, dict):
                raise ValueError("valid_observation_sequence_and_sample_required")
            pts = sample.get("pts_seconds")
            if (isinstance(pts, bool) or not isinstance(pts, (int, float))
                    or not math.isfinite(pts) or pts < 0):
                raise ValueError("finite_nonnegative_source_elapsed_seconds_required")
            source = sample.get("source_id", sample.get("session_id", self._source))
            if not isinstance(source, str) or not source:
                raise ValueError("nonempty_source_identity_required")
            previous = self._last
            if previous and source == previous[2] and (
                    frame <= previous[0] or pts <= previous[1]):
                raise ValueError("duplicate_or_backwards_observation")
            reset = bool(self._invalidated or previous and (
                source != previous[2] or frame != previous[0] + 1
                or pts - previous[1] > GAP_SECONDS))
            stall = bool(reset and not self._invalidated
                         and source == previous[2] and frame == previous[0] + 1
                         and pts - previous[1] <= HAND_GAP_SECONDS)
            if reset:
                self._state = _copy_candidate(self._initial)
                self._semantics.reset()
                self._critical.reset()
                self._seat_states.reset()
            if stall:
                self._gaps += pts - previous[1]
            elif reset:
                self._street.reset()
                self._actions.reset()
                self._gaps = 0.0
            self._state.audit = source
            current_hash = hashlib.sha256(image.tobytes()).hexdigest()
            seats = getattr(self._state, "seats", None)
            if isinstance(seats, SeatCueRecorder):
                seats.last = None
            row = self._state.read(image, frame, {
                "pts_seconds": pts, "sha256": current_hash})
            row["seat_cues_v1"] = (seats.last if isinstance(seats, SeatCueRecorder)
                                   else None)
            row["seat_states_v1"] = self._seat_states.observe(row, pts)
            row["street_v1"] = self._street.observe(row, pts - self._gaps)
            row.update(
                source_id=source, training_audit_sha256=self._initial.audit,
                observation_sequence=frame, reader_gap_reset=reset,
                pixel_hash_encoding="raw BGR uint8 498x1080",
                candidate_only=True, strategy_eligible=False, advice_emitted=False,
                runtime_profile_sha256=self._profile_sha256,
                runtime_bundle_sha256=self._bundle_sha256,
                complete_legal_state=False,
                actions_complete_and_canonical_verified=False)
            row["source_frame"] = sample.get("source_frame")
            row["context_only"] = sample.get("context_only", False)
            row["source_provenance"] = {
                key: sample[key] for key in (
                    "source_kind", "source_pts_exact", "source_manifest_sha256",
                    "source_png_sha256", "source_playlist_sha256",
                    "source_pool", "source_file")
                if key in sample}
            row["action_history_candidate"] = list(
                getattr(self._state.adapter, "actions", [])[-256:]) if hasattr(
                    self._state, "adapter") else []
            row["action_history_v1"] = self._actions.observe(row, frame)
            row.update(self._semantics.observe(row))
            row["critical_perception_v1"] = self._critical.observe(row)
            from .aa_critical_perception import target_s_candidate_screen
            row["target_s_candidate_screen"] = target_s_candidate_screen(row)
            from tools.aa8_critical_fields_v3 import normalize_fields
            row["evaluation_fields"] = normalize_fields(row)
            if self._analysis_enabled:
                from .aa_river_strategy import current_river_study
                row["river_strategy_v1"] = current_river_study(row)
            else:
                row["river_strategy_v1"] = {
                    "status": "ANALYSIS_DISABLED", "strategy_eligible": False,
                    "advice_emitted": False}
            self._last = (frame, pts, source)
            self._invalidated = False
            return row
        except Exception:
            # A rejected/read-failed frame must never bridge temporal evidence.
            self._invalidated = True
            raise
