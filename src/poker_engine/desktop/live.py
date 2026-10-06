"""Live capture from WePoker Android running in LDPlayer.

Assembles the whole chain the engine was built for —

    ADB CaptureService -> VisionEngine -> ChangeDetector -> Orchestrator
        -> StateEngine -> Equity -> RealtimeAnalysis

— against the emulator's raw portrait framebuffer, using calibration measured
from real 1440x2560 LDPlayer ADB captures.

Scope, stated plainly: **hero cards, board cards, street, pot, seat occupancy,
visual-slot stacks, the Dealer marker, and completed action labels** are
calibrated for Android. The versioned physical-slot mapping promotes those
fields to canonical seats and derives completed-action chip amounts from stack
deltas. The next player to act remains unavailable, so strategy advice still
fails closed while visible-card equity remains available.

Recoverable problems (ADB unavailable, emulator stopped, ambiguous devices,
or a resolution outside the calibrated aspect tolerance) are surfaced as
:class:`LiveCaptureError` so the UI can show what is wrong instead of the
process dying.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from poker_engine.confidence.gate import ConfidenceGate
from poker_engine.core.enums import ActionType, PlayerStatus, Position, Street
from poker_engine.core.state import PlayerState, PokerState
from poker_engine.core.value_objects import ChipAmount
from poker_engine.memory.hand_memory import InMemoryHandMemory
from poker_engine.orchestrator import ApplicationOrchestrator
from poker_engine.perceptual.capture.base import (
    CaptureError,
    CaptureService,
    CaptureTarget,
    Frame,
)
from poker_engine.perceptual.vision.action_recognizer import (
    ActionTemplateSet,
    TemplateActionGlyphRecognizer,
    TemplateActionRecognizer,
)
from poker_engine.perceptual.vision.amount_recognizer import (
    DigitTemplateSet,
    TemplateAmountRecognizer,
)
from poker_engine.perceptual.vision.asset_manifest import VisionAssetManifest
from poker_engine.perceptual.vision.board_slot_detector import (
    TemplateBoardSlotDetector,
)
from poker_engine.perceptual.vision.calibration import (
    CalibrationBins,
    ConfidenceCalibrator,
    MeasuredCalibration,
)
from poker_engine.perceptual.vision.card_layout import (
    BoardSlotLayout,
    CardSubROI,
    board_layout_from_dict,
    hero_layout_from_dict,
)
from poker_engine.perceptual.vision.corner_glyph_recognizer import (
    CornerGlyphCardRecognizer,
    CornerGlyphTemplateSet,
)
from poker_engine.perceptual.vision.engine import VisionEngine
from poker_engine.perceptual.vision.errors import TableMapError
from poker_engine.perceptual.vision.fused_card_adapter import FusedCardRecognizerAdapter
from poker_engine.perceptual.vision.fused_card_recognizer import (
    FusedCardRecognizer,
    load_card_heads,
)
from poker_engine.perceptual.vision.hero_turn_recognizer import (
    AndroidHeroTurnRecognizer,
)
from poker_engine.perceptual.vision.street_detector import TemplateStreetDetector
from poker_engine.perceptual.vision.slot_marker_recognizer import (
    TemplatePerSlotMarkerRecognizer,
    TemplateSlotMarkerRecognizer,
    slot_marker_layout_from_dict,
)
from poker_engine.perceptual.vision.table_map import TableMap
from poker_engine.realtime.pipeline import RealtimePipeline
from poker_engine.state_engine.platform_mapping import (
    PlatformMappedStateEngine,
    PlatformSeatMapping,
)
from poker_engine.strategy.action_line import build_action_line_resolver
from poker_engine.strategy.orchestration import StrategyOrchestrator
from poker_engine.strategy.registry import build_strategy_router

from .errors import LiveCaptureError
from .equity_guard import build_equity_input_guard
from .serialize import DesktopFrame
from .strategy_live import LiveStrategySession
from .table_rules import (
    TableRulesResult, load_user_table_rules, validate_table_rules, table_rules_revision,
)


def _resource_root() -> Path:
    """Return the checkout root or PyInstaller's bundled resource directory."""
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base is not None:
        return Path(frozen_base)
    return Path(__file__).resolve().parents[3]


_REPO_ROOT = _resource_root()
DEFAULT_PLATFORM = "wepoker_android"
DEFAULT_LAYOUT = "ldplayer_portrait_1440x2560"
DEFAULT_DEVICE_SERIAL = os.environ.get("POKERSENSE_ADB_SERIAL", "auto")
CAPTURE_CARD_PLATFORM = "wepoker_android_capture_card"
CAPTURE_CARD_LAYOUT = (
    "phone_samsung_galaxy_s25_ultra__card_ugreen__"
    "uvc_1920x1080_30__canvas_498x1080__v1"
)


def build_capture_backend(
    source: str = "adb",
    *,
    device_index: int = 0,
    api: str = "MSMF",
    normalization=None,
) -> CaptureService:
    """Return a production capture backend.

    ``source`` selects the capture path:

    - ``"adb"`` (default): the LDPlayer ADB backend, for the calibrated
      ``wepoker_android`` platform. Kept as the default so existing callers
      keep working unchanged.
    - ``"capture-card"``: the UVC capture-card backend
      (:class:`CaptureCardBackend`), for ``wepoker_android_capture_card``.
      This backend is wired here but its platform is NOT calibrated yet — the
      production loader fails closed on the missing recognition calibration, so
      a capture-card pipeline will raise rather than read fabricated values.

    ``normalization`` is a :class:`NormalizationConfig` applied inside the
    capture-card backend (portrait phone streamed letterboxed into a landscape
    UVC frame must be rotated/cropped before recognition). It is ignored for the
    ADB source, whose frames are already the calibrated portrait layout.
    """
    if source == "adb":
        from poker_engine.perceptual.capture.adb_backend import AdbBackend

        try:
            return AdbBackend()
        except RuntimeError as exc:
            raise LiveCaptureError(str(exc)) from exc

    if source == "capture-card":
        from poker_engine.perceptual.capture.capture_card_backend import (
            CaptureCardBackend,
        )

        try:
            return CaptureCardBackend(
                device_index=device_index,
                api=api,
                normalization=normalization,
            )
        except RuntimeError as exc:
            raise LiveCaptureError(str(exc)) from exc

    raise LiveCaptureError(f"unknown capture source: {source!r}")


def load_platform_seat_mapping(
    platform: str = DEFAULT_PLATFORM,
    layout: str = DEFAULT_LAYOUT,
) -> PlatformSeatMapping:
    """Load the versioned Android visual-slot to canonical-seat contract."""
    path = (
        _REPO_ROOT / "configs" / "platform"
        / f"{platform}__{layout}_seat_mapping.json"
    )
    if not path.is_file():
        raise LiveCaptureError(f"seat mapping missing at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise LiveCaptureError("unsupported seat mapping schema")

    def slot_map(name: str) -> dict[int, int]:
        return {int(slot): seat for slot, seat in data[name].items()}

    if data.get("platform_id") != platform or data.get("layout_id") != layout:
        raise LiveCaptureError("seat mapping platform/layout mismatch")
    return PlatformSeatMapping(
        platform_id=platform,
        layout_id=layout,
        version=data["version"],
        stack_slot_to_seat=slot_map("stack_slot_to_seat"),
        action_slot_to_seat=slot_map("action_slot_to_seat"),
        actor_slot_to_seat=slot_map("actor_slot_to_seat"),
        dealer_slot_to_seat=slot_map("dealer_slot_to_seat"),
        occupancy_slot_to_seat=slot_map("occupancy_slot_to_seat"),
        actor_observation_is_current=data["actor_observation_is_current"],
    )


def _uncalibrated(name: str) -> ConfidenceCalibrator:
    """A calibrator for a field nothing has been measured about.

    It reports zero confidence at every raw score, so the field is always
    gated to UNKNOWN. This is deliberate: an uncalibrated field must not
    inherit a calibrated field's confidence just because they share a frame.
    """
    return ConfidenceCalibrator(
        name=name,
        version=1,
        bins=CalibrationBins(edges=(0.0, 1.0), confidence=(0.0,)),
        abstain_floor=1.0,
    )


def load_measured_calibration(vision_dir: Path) -> MeasuredCalibration:
    """Load the committed accuracy measurement for a platform's cards."""
    path = vision_dir / "calibration.json"
    if not path.is_file():
        raise LiveCaptureError(f"no calibration measurement at {path}")
    data = json.loads(path.read_text())["card"]
    return MeasuredCalibration(
        samples=data["samples"],
        correct=data["correct"],
        readable_score_floor=data["readable_score_floor"],
        unreadable_score_ceiling=data["unreadable_score_ceiling"],
        source=data["source"],
    )


def load_measured_calibrations(
    vision_dir: Path,
) -> dict[str, MeasuredCalibration]:
    """Load every independently measured field calibration in a profile.

    The capture-card platform calibrates cards with the temporal-fusion
    pipeline under ``card_fused`` (the legacy single-frame ``card`` block is
    kept at floor=1.0 as a deliberate fail-closed guard). When ``card_fused``
    is present it takes precedence as the platform's ``card`` measurement.
    """
    path = vision_dir / "calibration.json"
    if not path.is_file():
        raise LiveCaptureError(f"no calibration measurement at {path}")
    data = json.loads(path.read_text())
    measured = {}
    for name in (
        "card", "board", "street", "amount", "stack", "dealer", "action",
        "occupancy", "actor",
    ):
        field = data.get(name)
        if field is None:
            continue
        if name == "card" and "card_fused" in data:
            # The fused pipeline is the platform's real card measurement; the
            # legacy single-frame ``card`` block is a fail-closed placeholder
            # (floor == ceiling == 1.0) that ``MeasuredCalibration`` would
            # reject. Skip it and take the fused block below.
            continue
        measured[name] = MeasuredCalibration(
            samples=field["samples"],
            correct=field["correct"],
            readable_score_floor=field["readable_score_floor"],
            unreadable_score_ceiling=field["unreadable_score_ceiling"],
            source=field["source"],
        )
    fused = data.get("card_fused")
    if fused is not None:
        measured["card"] = MeasuredCalibration(
            samples=fused["samples"],
            correct=fused["correct"],
            readable_score_floor=fused["suit_floor"],
            unreadable_score_ceiling=0.0,
            source=fused["source"],
        )
    if "card" not in measured:
        raise LiveCaptureError(f"card calibration missing at {path}")
    return measured


def build_confidence_gate(
    measured: MeasuredCalibration | dict[str, MeasuredCalibration],
) -> ConfidenceGate:
    """Gate thresholds set to what the measurement actually supports.

    The threshold is not a wish about how good recognition ought to be; it
    is the accuracy the evidence demonstrates. Collecting more samples
    raises what can be claimed, and the threshold rises with it — see
    ``configs/vision/<platform>/calibration.json``.

    Fields with no measurement keep a threshold of 1.0, which nothing can
    clear, so they stay UNKNOWN until they are calibrated too.
    """
    if isinstance(measured, MeasuredCalibration):
        fields = {"card": measured}
    else:
        fields = dict(measured)
    card_confidence = fields["card"].justified_confidence
    thresholds = {
        "hero_cards": card_confidence,
        "board_cards": (
            fields["board"].justified_confidence if "board" in fields else 1.0
        ),
        "street": (
            fields["street"].justified_confidence if "street" in fields else 1.0
        ),
        "pot": (
            fields["amount"].justified_confidence if "amount" in fields else 1.0
        ),
        "stacks": (
            fields["stack"].justified_confidence if "stack" in fields else 1.0
        ),
        "bet_size": 1.0,
        "action": (
            fields["action"].justified_confidence
            if "action" in fields else 1.0
        ),
    }
    occupancy = (
        fields["occupancy"].justified_confidence
        if "occupancy" in fields else 1.0
    )
    return ConfidenceGate(
        thresholds=thresholds,
        slot_thresholds={"occupancy": occupancy},
    )


def _imread_unicode(path: Path):
    """Read an image via ``imdecode`` so non-ASCII paths work.

    ``cv2.imread`` silently returns ``None`` on Windows for an absolute path
    containing non-ASCII characters (for example a checkout under a Chinese
    directory name). Reading the bytes first and decoding them via
    ``cv2.imdecode`` avoids the filesystem-encoding path that breaks.
    """
    try:
        with open(path, "rb") as handle:
            data = np.frombuffer(handle.read(), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _load_templates(directory: Path) -> dict:
    if not directory.is_dir():
        raise LiveCaptureError(f"template directory missing: {directory}")
    templates = {
        path.stem: _imread_unicode(path) for path in sorted(directory.glob("*.png"))
    }
    if not templates:
        raise LiveCaptureError(f"no templates found in {directory}")
    return templates


def load_calibration(
    platform: str = DEFAULT_PLATFORM, layout: str = DEFAULT_LAYOUT
) -> tuple[TableMap, VisionEngine]:
    """Load a platform's committed calibration into a ready VisionEngine."""
    table_map_path = _REPO_ROOT / "configs" / "platform" / f"{platform}__{layout}.json"
    vision_dir = _REPO_ROOT / "configs" / "vision" / platform
    if not table_map_path.is_file():
        raise LiveCaptureError(
            f"no calibration for {platform}/{layout}: {table_map_path}"
        )

    table_map = TableMap.from_json(table_map_path.read_text())
    calibration_path = vision_dir / "calibration.json"
    if not calibration_path.is_file():
        raise LiveCaptureError(f"no calibration measurement at {calibration_path}")
    calibration_data = json.loads(calibration_path.read_text())
    if calibration_data.get("status") == "uncalibrated":
        raise LiveCaptureError(
            f"recognition profile {platform}/{layout} is explicitly uncalibrated"
        )
    template_source = calibration_data.get("template_source", platform)
    template_dir = _REPO_ROOT / "configs" / "vision" / template_source
    hero_layout = hero_layout_from_dict(
        json.loads((vision_dir / "hero_slot_layout.json").read_text())
    )

    card_recognizer = CornerGlyphCardRecognizer(
        CornerGlyphTemplateSet(
            rank_templates=_load_templates(template_dir / "rank"),
            suit_templates=_load_templates(template_dir / "suit"),
            version=f"{platform}-{layout}-v1",
        )
    )

    # Capture-card platform: the temporal-fusion recognizer supersedes the
    # single-frame matcher whenever its measured ``card_fused`` calibration
    # and exported heads are present. Failure to load the heads keeps the
    # legacy (fail-closed, floor=1.0) path rather than half-wiring the fused
    # pipeline — a missing model file must never silently downgrade to a
    # loosened single-frame gate.
    fused_meta = vision_dir / "card_heads.json"
    fused_card_pipeline = False
    if fused_meta.is_file():
        fused_data = json.loads((vision_dir / "calibration.json").read_text())
        if "card_fused" in fused_data:
            try:
                heads = load_card_heads(vision_dir / "card_heads.npz")
                calibrated = fused_data["card_fused"]
                card_recognizer = FusedCardRecognizerAdapter(
                    FusedCardRecognizer(
                        heads,
                        rank_floor=calibrated.get("rank_floor", 0.0),
                        suit_floor=calibrated.get("suit_floor", 0.3),
                    ),
                    max_frame_gap_seconds=calibrated.get("max_frame_gap_seconds", 1.0),
                    accept_candidates=not calibrated.get(
                        "requires_revalidation", False),
                )
                fused_card_pipeline = True
            except (FileNotFoundError, ValueError, OSError):
                # Keep the legacy fail-closed recognizer; the platform stays
                # UNKNOWN on cards rather than guessing.
                pass

    board_layout_path = vision_dir / "board_slot_layout.json"
    # 阈值默认保持 ADB 标定值；布局 JSON 可选携带平台实测阈值
    # （采集卡绿呢偏亮，empty 阈值需按测量下调，见
    #  docs/adr/DECISION-2026-09-06-pot-stack0-geometry.zh-CN.md）
    board_card_min_presence = 0.50
    board_empty_min_evidence = 0.55
    if board_layout_path.is_file():
        board_layout_dict = json.loads(board_layout_path.read_text())
        board_layout = board_layout_from_dict(board_layout_dict)
        board_card_min_presence = float(
            board_layout_dict.get("card_min_presence", 0.50)
        )
        board_empty_min_evidence = float(
            board_layout_dict.get("empty_min_evidence", 0.55)
        )
    else:
        board_layout = BoardSlotLayout(
            layout_id=f"{layout}_board_uncalibrated",
            version=1,
            slots=tuple(
                CardSubROI(x=i * 0.2, y=0.0, width=0.19, height=1.0)
                for i in range(5)
            ),
        )
    _placeholder_rank = _imread_unicode(next((template_dir / "rank").glob("*.png")))
    digit_dir = vision_dir / "digit"
    digit_templates = (
        _load_templates(digit_dir)
        if digit_dir.is_dir()
        else {"0": _placeholder_rank}
    )
    amount_recognizer = TemplateAmountRecognizer(
        DigitTemplateSet(
            templates=digit_templates,
            version=(f"{platform}-amount-v2" if digit_dir.is_dir() else "uncalibrated"),
        ),
        min_score=0.8,
    )
    stack_digit_dir = vision_dir / "stack_digit"
    stack_recognizer = TemplateAmountRecognizer(
        DigitTemplateSet(
            templates=(
                _load_templates(stack_digit_dir)
                if stack_digit_dir.is_dir()
                else {"0": _placeholder_rank}
            ),
            version=(
                f"{platform}-stack-v1"
                if stack_digit_dir.is_dir()
                else "uncalibrated"
            ),
        ),
        min_score=0.8,
    )
    action_glyph_dir = vision_dir / "action_glyph"
    if action_glyph_dir.is_dir():
        action_files = _load_templates(action_glyph_dir)
        action_recognizer = TemplateActionGlyphRecognizer(
            ActionTemplateSet(
                templates={ActionType(name): image
                           for name, image in action_files.items()},
                version=f"{platform}-action-v1",
            ),
            min_score=0.8,
        )
    else:
        action_recognizer = TemplateActionRecognizer(
            ActionTemplateSet(
                templates={ActionType.FOLD: _imread_unicode(
                    next((template_dir / "suit").glob("*.png"))
                )},
                version="uncalibrated",
            )
        )
    dealer_layout_path = vision_dir / "dealer_slot_layout.json"
    dealer_template_path = vision_dir / "dealer" / "marker.png"
    dealer_recognizer = None
    if dealer_layout_path.is_file() and dealer_template_path.is_file():
        dealer_recognizer = TemplateSlotMarkerRecognizer(
            _imread_unicode(dealer_template_path),
            slot_marker_layout_from_dict(
                json.loads(dealer_layout_path.read_text())
            ),
            version=f"{platform}-dealer-v1",
        )
    empty_layout_path = vision_dir / "empty_slot_layout.json"
    empty_template_path = vision_dir / "empty_slot" / "plus.png"
    empty_slot_recognizer = None
    if empty_layout_path.is_file() and empty_template_path.is_file():
        empty_slot_recognizer = TemplatePerSlotMarkerRecognizer(
            _imread_unicode(empty_template_path),
            slot_marker_layout_from_dict(
                json.loads(empty_layout_path.read_text())
            ),
            version=f"{platform}-occupancy-v1",
        )

    measured = load_measured_calibrations(vision_dir)
    card_calibrator = measured["card"].to_calibrator("card")
    # Fields with no calibration measurement of their own get a calibrator
    # that can never clear a gate: nothing has been measured about them, so
    # they must read UNKNOWN rather than borrow the card measurement's
    # credibility.
    calibrators = {"card": card_calibrator}
    for name in (
        "amount", "stack", "dealer", "action", "occupancy", "actor", "street",
        "board",
    ):
        field_measurement = measured.get(name)
        calibrators[name] = (
            field_measurement.to_calibrator(name)
            if field_measurement is not None
            else _uncalibrated(name)
        )
    manifest = VisionAssetManifest(
        platform_id=platform,
        layout_id=layout,
        card_layout_version=board_layout.version,
        template_set_version=f"{platform}-v1",
        calibration_version=3,
        recognizer_versions={
            "card": "gray-fused-v4" if fused_card_pipeline else "1",
            "amount": "2", "stack": "1", "dealer": "1",
            "action": "2", "occupancy": "1", "actor": "1",
            "street": "2", "board": "2",
        },
    )

    engine = VisionEngine(
        board_layout=board_layout,
        hero_layout=hero_layout,
        card_recognizer=card_recognizer,
        board_slot_detector=TemplateBoardSlotDetector(
            board_layout,
            empty_min_evidence=board_empty_min_evidence,
            card_min_presence=board_card_min_presence,
        ),
        street_detector=TemplateStreetDetector(),
        amount_recognizer=amount_recognizer,
        stack_recognizer=stack_recognizer,
        action_recognizer=action_recognizer,
        calibrators=calibrators,
        manifest=manifest,
        bet_size_semantics=None,
        dealer_recognizer=dealer_recognizer,
        empty_slot_recognizer=empty_slot_recognizer,
        actor_recognizer=AndroidHeroTurnRecognizer(),
        disable_hero_dynamic_fallback=fused_card_pipeline,
    )
    return table_map, engine


class DeviceFrameSource:
    """FrameSource that captures one explicit ADB device on every pull."""

    def __init__(
        self,
        backend: CaptureService,
        device_serial: str,
    ) -> None:
        self._backend = backend
        self._target = CaptureTarget(window_id=device_serial)

    def next_frame(self) -> Frame | None:
        try:
            return self._backend.capture(self._target)
        except CaptureError as exc:
            raise LiveCaptureError(str(exc)) from exc


def _seed_player(seat: int, hero: bool) -> PlayerState:
    return PlayerState(
        player_id=f"p{seat}",
        seat=seat,
        position=Position.UNKNOWN,
        stack=ChipAmount("0"),
        committed_this_street=ChipAmount("0"),
        committed_this_hand=ChipAmount("0"),
        status=PlayerStatus.SITTING_OUT,
        has_cards=False,
        is_hero=hero,
        is_dealer=False,
    )


def _seed_state(hand_id: str = "live-1") -> PokerState:
    """An empty preflop state; recognition drives every field from here."""
    return PokerState(
        state_version=0,
        hand_id=hand_id,
        street=Street.PREFLOP,
        hero_cards=(),
        board_cards=(),
        players=tuple(_seed_player(seat, hero=seat == 0) for seat in range(8)),
        pot=ChipAmount("0"),
        current_bet=ChipAmount("0"),
        to_call=ChipAmount("0"),
        actor=None,
    )


def build_pipeline(
    device_serial: str = DEFAULT_DEVICE_SERIAL,
    platform: str = DEFAULT_PLATFORM,
    layout: str = DEFAULT_LAYOUT,
    source: str = "adb",
    *,
    device_index: int = 0,
    api: str = "MSMF",
    normalization=None,
    frame_source=None,
) -> RealtimePipeline:
    """Assemble a pipeline reading raw portrait frames from the capture source.

    The default ``source="adb"`` keeps the existing calibrated
    ``wepoker_android`` / LDPlayer behaviour unchanged. Passing
    ``source="capture-card"`` reads from a UVC capture card; the capture-card
    platform is wired but NOT calibrated, so its loader fails closed (see
    :func:`load_calibration`) until Stage I measurement lands.
    """
    if source == "capture-card":
        if platform == DEFAULT_PLATFORM and layout == DEFAULT_LAYOUT:
            platform = CAPTURE_CARD_PLATFORM
            layout = CAPTURE_CARD_LAYOUT
        elif platform != CAPTURE_CARD_PLATFORM:
            raise LiveCaptureError(
                "capture-card source requires the independent "
                f"{CAPTURE_CARD_PLATFORM!r} recognition profile"
            )
    elif source == "adb" and platform == CAPTURE_CARD_PLATFORM:
        raise LiveCaptureError(
            "ADB source cannot use the capture-card recognition profile"
        )

    table_map, vision = load_calibration(platform, layout)
    if source == "capture-card":
        from poker_engine.perceptual.capture.normalization import NormalizationConfig
        if normalization is None:
            path = _REPO_ROOT / "configs/vision" / platform / "normalization.json"
            normalization = NormalizationConfig.from_json(
                path.read_text(encoding="utf-8")
            )
        if normalization.output_size != table_map.reference_size:
            raise LiveCaptureError(
                "capture normalization does not match calibrated canvas"
            )
    measured = load_measured_calibrations(
        _REPO_ROOT / "configs" / "vision" / platform
    )
    seat_mapping = load_platform_seat_mapping(platform, layout)
    confidence_gate = build_confidence_gate(measured)
    orchestrator = ApplicationOrchestrator(
        state_engine=PlatformMappedStateEngine(seat_mapping),
        hand_memory=InMemoryHandMemory(),
        confidence_gate=confidence_gate,
    )
    next_hand_number = 1

    def next_hand_state() -> PokerState:
        nonlocal next_hand_number
        next_hand_number += 1
        return _seed_state(hand_id=f"live-{next_hand_number}")

    orchestrator.start_hand(_seed_state(hand_id="live-1"))
    if frame_source is None:
        frame_source = DeviceFrameSource(
            build_capture_backend(
                source,
                device_index=device_index,
                api=api,
                normalization=normalization,
            ),
            device_serial,
        )
    return RealtimePipeline(
        frame_source,
        vision,
        table_map,
        orchestrator,
        # A valid hero hand is immutable within a deal. Requiring two
        # identical frames prevents one half-rendered / miscaptured frame
        # from becoming the canonical hand shown to the player.
        hero_confirmation_frames=2,
        confirmation_frames={
            "board_cards": 2,
            "pot": 2,
            "stacks": 2,
            "bet_size": 2,
            "action": 2,
            "street": 2,
            "dealer_pos": 2,
            "actor": 2,
            "slot_stacks": 2,
            "slot_actions": 2,
            "slot_occupancies": 2,
        },
        new_hand_state_factory=next_hand_state,
        equity_input_guard=build_equity_input_guard(confidence_gate, seat_mapping),
    )


@dataclass(frozen=True)
class LiveStreamHealth:
    """Observable health of the capture loop.

    Emitted through :func:`live_analysis_stream`'s ``on_health`` hook so a
    caller can alert or log failures. After a previously presented frame,
    the stream also yields an unavailable snapshot before retry backoff.
    ``exhausted`` means the frame source ran out (a finite replay), which is
    a clean stop rather than a failure.
    """

    consecutive_failures: int
    total_failures: int
    backoff_seconds: float
    exhausted: bool = False

    def __post_init__(self) -> None:
        for name in ("consecutive_failures", "total_failures"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if isinstance(self.backoff_seconds, bool) or not isinstance(
            self.backoff_seconds, (int, float)
        ):
            raise TypeError("backoff_seconds must be a number")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be >= 0")
        if not isinstance(self.exhausted, bool):
            raise TypeError("exhausted must be a bool")

    @property
    def degraded(self) -> bool:
        """True while the loop is recovering from a transient capture fault."""
        return self.consecutive_failures > 0


async def live_analysis_stream(
    device_serial: str = DEFAULT_DEVICE_SERIAL,
    interval_seconds: float = 0.0,
    source: str = "adb",
    *,
    device_index: int = 0,
    api: str = "MSMF",
    normalization=None,
    max_consecutive_failures: int = 5,
    backoff_initial_seconds: float = 0.5,
    backoff_max_seconds: float = 8.0,
    on_health: Callable[[LiveStreamHealth], None] | None = None,
) -> AsyncIterator[DesktopFrame]:
    """Yield fresh analysis while the selected capture source is available.

    Capture and recognition are CPU-bound and run off the event loop, so the
    server stays responsive between frames. ``source`` selects the capture
    backend (see :func:`build_capture_backend`).

    ``interval_seconds`` is a **minimum** period, not a fixed one: the loop
    sleeps only ``max(0, interval_seconds - step_duration)``. It therefore
    defaults to ``0.0`` — run as fast as the source can supply frames. The
    earlier fixed 1.0s sleep dominated end-to-end latency: with ~110-280ms of
    real work per step it capped the pipeline near 0.8fps and added up to a
    full second of avoidable lag before any frame was even looked at.

    Capture faults fall into two classes and are handled differently:

    * :class:`LiveCaptureError` — the *device* went away (ADB dropped, USB
      re-enumeration). Transient, so the loop backs off exponentially and
      retries, reporting each attempt through ``on_health``.
    * anything else — a programming or configuration fault. Raised
      immediately; retrying a bug only hides it.
    """
    try:
        pipeline = await asyncio.to_thread(
            build_pipeline,
            device_serial,
            source=source,
            device_index=device_index,
            api=api,
            normalization=normalization,
        )
    except LiveCaptureError:
        raise
    except Exception as exc:
        raise LiveCaptureError(
            f"capture engine initialization failed: {exc}"
        ) from exc
    # Recognition promotes measured seat, stack, dealer, Hero-turn, and
    # completed-action evidence through the Android mapping.  Strategy
    # Providers are registered in one place (strategy.registry) so capability
    # growth never touches this wiring again.  When no registered Provider
    # covers a spot, advice still emits an auditable ABSTAIN rather than
    # inventing a strategy.
    rules_key = None
    rules = TableRulesResult(None, "table_rules_unverified")
    strategy_session = None
    if isinstance(interval_seconds, bool) or not isinstance(
        interval_seconds, (int, float)
    ):
        raise TypeError("interval_seconds must be a number")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be >= 0")
    if not isinstance(max_consecutive_failures, int) or isinstance(
        max_consecutive_failures, bool
    ):
        raise TypeError("max_consecutive_failures must be an int")
    if max_consecutive_failures < 0:
        raise ValueError("max_consecutive_failures must be >= 0")
    if on_health is not None and not callable(on_health):
        raise TypeError("on_health must be callable or None")
    consecutive_failures = 0
    total_failures = 0
    backoff = float(backoff_initial_seconds)
    while True:
        started = time.monotonic()
        try:
            step = await asyncio.to_thread(pipeline.step)
        except LiveCaptureError as exc:
            # Device-level fault: the source may come back, so recover
            # instead of tearing the whole stream down on one dropped frame.
            consecutive_failures += 1
            total_failures += 1
            if strategy_session is not None:
                strategy_session.invalidate()
            latest = getattr(pipeline, "latest_analysis", None)
            unavailable = latest() if callable(latest) else None
            if unavailable is not None:
                # Deliver the invalidated snapshot before backoff. It reuses
                # the last captured frame id, not a fabricated new frame.
                yield DesktopFrame(
                    unavailable, advice_unavailable_reason="capture_unavailable",
                    table_rules_revision=rules_key,
                )
            if on_health is not None:
                on_health(
                    LiveStreamHealth(
                        consecutive_failures=consecutive_failures,
                        total_failures=total_failures,
                        backoff_seconds=backoff,
                    )
                )
            if consecutive_failures > max_consecutive_failures:
                raise LiveCaptureError(
                    f"capture source unavailable after {consecutive_failures} "
                    f"consecutive failures: {exc}"
                ) from exc
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, float(backoff_max_seconds))
            continue
        except TableMapError as exc:
            raise LiveCaptureError(str(exc)) from exc
        except Exception as exc:
            raise LiveCaptureError(f"capture engine failed: {exc}") from exc
        if step is None:
            # Frame source exhausted (a finite replay finished). Stop
            # cleanly rather than spinning on a source that will never
            # produce another frame.
            if on_health is not None:
                on_health(
                    LiveStreamHealth(
                        consecutive_failures=0,
                        total_failures=total_failures,
                        backoff_seconds=0.0,
                        exhausted=True,
                    )
                )
            return
        consecutive_failures = 0
        backoff = float(backoff_initial_seconds)
        try:
            document = load_user_table_rules(
                _REPO_ROOT / "configs/game/wpk-capture-card.json"
            )
            next_key = table_rules_revision(document)
            if next_key != rules_key:
                rules = validate_table_rules(document)
                if strategy_session is not None:
                    strategy_session.invalidate()
                strategy_session = (
                    LiveStrategySession(
                        StrategyOrchestrator(build_strategy_router()),
                        rules.game_config,
                        action_line_resolver=build_action_line_resolver(),
                    ) if rules.game_config is not None else None
                )
                rules_key = next_key
        except (OSError, ValueError):
            if strategy_session is not None:
                strategy_session.invalidate()
            strategy_session = None
            rules_key = None
            rules = TableRulesResult(None, "table_rules_invalid")
        if strategy_session is None:
            yield DesktopFrame(
                step.analysis, advice_unavailable_reason=rules.unavailable_reason,
                table_rules_revision=rules_key,
            )
        else:
            desktop_frame = strategy_session.frame(
                step.analysis,
                pipeline.current_state(),
                action_history=pipeline.action_history(),
            )
            yield DesktopFrame(
                desktop_frame.analysis, desktop_frame.advice,
                desktop_frame.advice_unavailable_reason,
                table_rules_revision=rules_key,
            )
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)


__all__ = [
    "LiveCaptureError",
    "build_confidence_gate",
    "load_measured_calibration",
    "load_measured_calibrations",
    "load_platform_seat_mapping",
    "DeviceFrameSource",
    "build_capture_backend",
    "build_pipeline",
    "live_analysis_stream",
    "load_calibration",
    "DEFAULT_DEVICE_SERIAL",
    "LiveStreamHealth",
]
