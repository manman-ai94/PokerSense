"""Source-bound development field annotations + irreversible exposure history.

P0 of the selected #19 migration. Reference: Issue #27 comment
``PR19_FINAL_ARCHITECTURE_DECISION_READY``.

This module is a **data governance record store**, nothing else:

* Development annotations are recorded per (stable source identity, field, seat)
  as append-only revisions. Old revisions are never overwritten.
* ``UNKNOWN`` is a first-class label state; it never collapses to 0 / false /
  none, and ``NOT_APPLICABLE`` always carries context.
* Training / tuning / template-selection exposure is recorded at source level
  and only ever grows. No rename, replay move, crop rebuild, revision,
  retraction or store rebuild can turn exposed development data back into an
  untouched holdout.
* ``assess_use`` derives eligibility read-only and fails closed. Clients cannot
  submit ``training_eligible=true``.

Two identities, deliberately separate
------------------------------------

``source_key``
    *Evidence identity*: bound to the audit manifest reference, the audit
    digest, the media id, the media digest, the frame index and the frame
    digest. It identifies "this annotation was made against this audit".

``exposure_root_key``
    *Long-term content / exposure identity*: bound to the canonical
    ``media_sha256``, ``frame_index`` and ``frame_sha256`` only. Re-auditing
    the same bytes, rebuilding a manifest or renaming a media alias must never
    reset exposure history, so those provenance strings are excluded here.

Digests are canonicalised to lowercase before either key is derived, so an
upper/lower case spelling of the same digest cannot create two identities.

Positive consumption permission is closed
-----------------------------------------

Current main exposes **no reviewed consumer registry and no global annotation /
exposure store inventory**. This module therefore does not invent one: a
positive ``ALLOWED_FOR_PURPOSE`` verdict is not derivable here and ``assess_use``
resolves to ``BLOCKED`` with ``trusted_consumer_registry_unavailable`` and
``global_history_inventory_unavailable``. The value delivered by P0 is the
annotation revision history and the exposure history, not a pass for a training
system. False negatives are acceptable; a false ``ALLOWED`` is not.

Explicit non-goals of P0 (see ``docs/archive/AA-FIELD-ANNOTATIONS-V1.zh-CN.md``):

* No per-event hash chain (``previous_sha256`` / ``entry_sha256`` linkage) was
  migrated. Source / frame / artifact / snapshot hashes are retained as
  identity anchors, never as a chain.
* No UI, no HTTP endpoint, no export pipeline, no training execution, no crop
  generation, no model invocation.
* No promotion bridge into gold, confirmed poker facts, PHH actions, acceptance
  or strategy eligibility. This store is not a second truth source.
* No freeze adapter: ``exposure_projection`` emits a row view for a future
  controlled adapter. It is not attached to
  ``aa8_holdout_plan.validate_freeze`` and must not be described as bindable by
  that validator.

A persisted ``binding_status`` is never an authority
---------------------------------------------------

``binding_status`` on an exposure line is only the claim whoever wrote that
line made at the time. Every path that can *conclude* something about binding -
the new-write path ``record_exposure`` and every history recovery path
(``assess_use`` / ``exposure_projection``) - re-derives the effective binding
with the single shared validator ``_evaluate_exposure_binding`` from the same
inputs: the event's own source reference, the annotation revisions it
references, their parent lineage, the consumer targets and the run / manifest
reference. A stored ``BOUND``, a stored ``UNRESOLVED`` and a missing
``binding_status`` all go through the same re-derivation and all degrade to
``UNRESOLVED`` when the referenced revisions disagree with the event.

A mis-bound line is never deleted and never "cleaned": the contamination key
set is the conservative union of the lineage the event claims and the lineage
every referenced revision can prove, so a line that names source A while
consuming a revision of source B pollutes **both** A and B instead of
laundering the side it failed to name.
"""

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tools.aa_data_separation import assert_training_frames, validate_reservations

SCHEMA_VERSION = "aa-field-annotations-v1"

SUPPORTED_SLOT_COUNT = 8

FIELD_POT_DISPLAY = "pot_display"
FIELD_VISIBLE_ACTION_GLYPH = "visible_action_glyph"

STATUS_KNOWN = "KNOWN"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUSES = frozenset({STATUS_KNOWN, STATUS_UNKNOWN, STATUS_NOT_APPLICABLE})

MODEL_OUTPUT_SEEN_YES = "YES"
MODEL_OUTPUT_SEEN_NO = "NO"
MODEL_OUTPUT_SEEN_UNKNOWN = "UNKNOWN"
MODEL_OUTPUT_SEEN = frozenset({
    MODEL_OUTPUT_SEEN_YES,
    MODEL_OUTPUT_SEEN_NO,
    MODEL_OUTPUT_SEEN_UNKNOWN,
})

PURPOSE_TRAINING = "training"
PURPOSE_TUNING = "tuning"
PURPOSE_TEMPLATE_SELECTION = "template_selection"
PURPOSES = frozenset({PURPOSE_TRAINING, PURPOSE_TUNING, PURPOSE_TEMPLATE_SELECTION})

EVIDENCE_RESERVED = "RESERVED"
EVIDENCE_RELEASED = "RELEASED"
EVIDENCE_POSSIBLY_USED = "POSSIBLY_USED"
EVIDENCE_ACTUALLY_CONSUMED = "ACTUALLY_CONSUMED"
EVIDENCE_KINDS = frozenset({
    EVIDENCE_RESERVED,
    EVIDENCE_RELEASED,
    EVIDENCE_POSSIBLY_USED,
    EVIDENCE_ACTUALLY_CONSUMED,
})

VERDICT_BLOCKED = "BLOCKED"
VERDICT_ALLOWED_FOR_PURPOSE = "ALLOWED_FOR_PURPOSE"

SCOPE_ANNOTATION_ONLY = "ANNOTATION_ONLY"
SCOPE_PURPOSE_BOUND = "PURPOSE_BOUND"

COVERAGE_COMPLETE = "COMPLETE"
COVERAGE_INCOMPLETE = "INCOMPLETE"
COVERAGE_UNKNOWN = "UNKNOWN"

STATE_ACTUALLY_CONSUMED = "EXPOSED_ACTUALLY_CONSUMED"
STATE_POSSIBLY_USED = "EXPOSED_POSSIBLY_USED"
STATE_UNKNOWN = "EXPOSURE_UNKNOWN"
STATE_NONE_UNDER_COVERAGE = "NO_EXPOSURE_RECORDED_UNDER_DECLARED_COVERAGE"

# Exposure binding. ``BINDING_UNRESOLVED`` is the only safe reading of a line
# whose binding cannot be re-derived from the annotation revisions it
# references. Nothing in this module treats a persisted ``binding_status`` as
# an authority: the value stored on a line is a historical claim only.
BINDING_BOUND = "BOUND"
BINDING_UNRESOLVED = "UNRESOLVED"

IDENTITY_COMPLETE = "COMPLETE"
IDENTITY_INCOMPLETE = "INCOMPLETE"
IDENTITY_UNBOUND = "UNBOUND"

AMOUNT_ROLE_POT_DISPLAY_TOTAL = "pot_display_total"
WAGER_AMOUNT_ROLES = frozenset({
    "current_street_wager",
    "street_wager",
    "call_price",
    "cumulative_commitment",
    "total_commitment",
})

GLYPH_VALUES = frozenset({
    "fold", "check", "call", "bet", "raise", "all_in", "muck", "none",
})

FIELD_CONTRACTS = {
    FIELD_POT_DISPLAY: {
        "value_types": (int,),
        "unit_allowed": frozenset({"chips"}),
        "unit_required": True,
        "allowed_values": None,
        "forbidden_amount_roles": WAGER_AMOUNT_ROLES,
        "sequence_bound": False,
    },
    FIELD_VISIBLE_ACTION_GLYPH: {
        "value_types": (str,),
        "unit_allowed": frozenset(),
        "unit_required": False,
        "allowed_values": GLYPH_VALUES,
        "forbidden_amount_roles": frozenset(),
        "sequence_bound": True,
    },
}

# Fields whose meaning belongs to another truth source. Even after additional
# field vocabularies are added (P1) these stay rejected: annotations can never
# be the authority for acceptance, strategy eligibility or verified facts.
FORBIDDEN_TRUTH_FIELDS = frozenset({
    "full_actions",
    "acceptance",
    "full_visual_acceptance",
    "strategy_eligible",
    "strategy_ready",
    "canonical_verified",
    "confirmed_facts",
    "confirmed_poker_facts",
    "holdout_gold",
    "phh_confirmed_actions",
})

# Historic #19 field vocabulary deliberately NOT ported in P0.
P1_FIELD_CANDIDATES = frozenset({
    "seat_presence",
    "current_bet",
    "street_wager",
    "actor",
    "special_mode",
})

SHA_IDENTITY_FIELDS = (
    "source_audit_sha256",
    "media_sha256",
    "frame_sha256",
)
TEXT_IDENTITY_FIELDS = (
    "source_audit_ref",
    "source_audit_sha256",
    "media_id",
    "media_sha256",
    "frame_sha256",
)
CORE_IDENTITY_FIELDS = TEXT_IDENTITY_FIELDS + ("frame_index",)
REQUIRED_IDENTITY_FIELDS = CORE_IDENTITY_FIELDS + (
    "layout_id",
    "slot_count",
    "slot_mapping",
    "observation_snapshot_digest",
)
OPTIONAL_IDENTITY_FIELDS = ("implementation_revision", "parent_frame_ref")
IDENTITY_FIELDS = frozenset(REQUIRED_IDENTITY_FIELDS + OPTIONAL_IDENTITY_FIELDS)

# Long-term exposure root: canonical content + frame, never provenance strings.
EXPOSURE_ROOT_FIELDS = ("media_sha256", "frame_index", "frame_sha256")

# Long-term identity may never be expressed as a mutable location or a UI row.
FORBIDDEN_IDENTITY_KEYS = frozenset({
    "path",
    "file_path",
    "current_path",
    "media_path",
    "replay_path",
    "replay_name",
    "replay_file",
    "ui_index",
    "ui_row",
    "display_index",
})

ANNOTATION_FILE = "annotations.jsonl"
EXPOSURE_FILE = "exposures.jsonl"
LOCK_FILE = ".aa-annotation-store.lock"
LOCK_TIMEOUT_SECONDS = 5.0

REPO_ROOT = Path(__file__).resolve().parents[1]

# The only reservation authority this module recognises. It is read from the
# reviewed artifact in current main; a caller-supplied reservation mapping is
# never used as authority.
RESERVATION_ARTIFACT_RELATIVE = "configs/reproduction/aa_holdout_reservations_v1.json"

# Conservative gates, not design shortcuts. Current main has no reviewed
# consumer registry and no global store inventory, so a positive consumption
# permission cannot be derived. Both stay False until a reviewed adapter
# exists; assess_use fails closed on them until then.
TRUSTED_CONSUMER_REGISTRY_AVAILABLE = False
TRUSTED_HISTORY_INVENTORY_AVAILABLE = False

EXPOSURE_ROLES = frozenset({"development", "calibration", "holdout"})


class AnnotationError(Exception):
    """Base class for every fail-closed refusal of this module."""


class SourceIdentityError(AnnotationError):
    """Source reference is structurally unusable as a long-term identity."""


class UnsupportedFieldError(AnnotationError):
    """field_id is outside the vocabulary supported by this module."""


class ForbiddenTruthFieldError(AnnotationError):
    """field_id belongs to another truth source; annotations may not hold it."""


class FieldSemanticsMismatch(AnnotationError):
    """Caller mixed up two different amount / action semantics."""


class RevisionConflictError(AnnotationError):
    """expected_revision did not match the durable head revision."""


class LabelValidationError(AnnotationError):
    """Label violates the per-field contract or the UNKNOWN rules."""


class ExposureError(AnnotationError):
    """Exposure event is malformed for a historical fact record."""


class StoreIntegrityError(AnnotationError):
    """Store cannot be trusted for history coverage; never silently repaired."""


class StoreLockError(AnnotationError):
    """Store lock could not be acquired."""


@dataclass(frozen=True)
class Label:
    """A developer annotation value with an explicit epistemic status."""

    status: str
    value: object = None
    unit: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ObservationContext:
    """Comparison material bound to the annotation, never overwritten later."""

    model_output: object = None
    model_reason: str | None = None
    model_output_seen: str = MODEL_OUTPUT_SEEN_UNKNOWN
    implementation_revision: str | None = None


def utc_now():
    """UTC second-precision timestamp in ISO-8601 form."""
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace("+00:00", "Z")


def _is_int(value):
    return type(value) is int


def _is_non_empty_str(value):
    return isinstance(value, str) and value.strip() != ""


def _canonical_sha256(value):
    """Return the canonical lowercase digest, or None when not a SHA-256."""
    if not isinstance(value, str) or len(value) != 64:
        return None
    lowered = value.lower()
    for char in lowered:
        if char not in "0123456789abcdef":
            return None
    return lowered


def _looks_like_sha256(value):
    return _canonical_sha256(value) is not None


def _canonical_identity_ref(ref):
    """Lowercase every digest in a source reference / parent reference."""
    out = dict(ref)
    for name in SHA_IDENTITY_FIELDS:
        value = out.get(name)
        if isinstance(value, str):
            canonical = _canonical_sha256(value)
            if canonical is not None:
                out[name] = canonical
    return out


class _StoreLock:
    """Best-effort exclusive lock; enough for single-user local tooling."""

    def __init__(self, lock_path):
        self._lock_path = Path(lock_path)
        self._acquired = False

    def __enter__(self):
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                handle = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.close(handle)
                self._acquired = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise StoreLockError(
                        "store_lock_unavailable:" + str(self._lock_path)
                    )
                time.sleep(0.02)

    def __exit__(self, exc_type, exc, traceback):
        if self._acquired:
            try:
                os.remove(str(self._lock_path))
            except FileNotFoundError:
                pass
            self._acquired = False
        return False


class AnnotationStore:
    """Append-only JSONL record store for one annotation namespace."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._annotations = self.path / ANNOTATION_FILE
        self._exposures = self.path / EXPOSURE_FILE
        self._lock_path = self.path / LOCK_FILE

    def lock(self):
        return _StoreLock(self._lock_path)

    def read_annotations(self, *, validate=True):
        rows = self._read(self._annotations, "annotation")
        if validate:
            validate_annotation_rows(rows)
        return rows

    def read_exposures(self):
        return self._read(self._exposures, "exposure")

    def append_annotation(self, row):
        self._append(self._annotations, row)

    def append_exposure(self, row):
        self._append(self._exposures, row)

    def _read(self, target, event_type):
        if not target.exists():
            return []
        rows = []
        seen = set()
        raw_text = target.read_text(encoding="utf-8")
        for lineno, raw in enumerate(raw_text.splitlines(), start=1):
            if raw.strip() == "":
                raise StoreIntegrityError(f"{event_type}:blank_line:{lineno}")
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StoreIntegrityError(
                    f"{event_type}:malformed_json:{lineno}"
                ) from exc
            if not isinstance(row, dict):
                raise StoreIntegrityError(f"{event_type}:not_object:{lineno}")
            if row.get("schema_version") != SCHEMA_VERSION:
                raise StoreIntegrityError(
                    f"{event_type}:unknown_schema_version:{lineno}"
                )
            if row.get("event_type") != event_type:
                raise StoreIntegrityError(f"{event_type}:wrong_event_type:{lineno}")
            event_id = row.get("event_id")
            if not _is_non_empty_str(event_id):
                raise StoreIntegrityError(f"{event_type}:missing_event_id:{lineno}")
            if event_id in seen:
                raise StoreIntegrityError(f"{event_type}:duplicate_event_id:{lineno}")
            seen.add(event_id)
            rows.append(row)
        return rows

    def _append(self, target, row):
        line = json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def _coerce_store(store):
    if isinstance(store, AnnotationStore):
        return store
    return AnnotationStore(store)


def _coerce_label(label):
    if isinstance(label, Label):
        return label
    if isinstance(label, dict):
        known = {
            "status", "value", "unit", "reason",
        }
        unknown = set(label) - known
        if unknown:
            names = ",".join(sorted(unknown))
            raise LabelValidationError("unknown_label_keys:" + names)
        return Label(
            status=label.get("status"),
            value=label.get("value"),
            unit=label.get("unit"),
            reason=label.get("reason"),
        )
    raise LabelValidationError("label_must_be_label_or_mapping")


def _exposure_root_key(media_sha256, frame_index, frame_sha256):
    """Long-term content identity; provenance strings are excluded on purpose."""
    if media_sha256 is None or frame_sha256 is None:
        return None
    if not (_is_int(frame_index) and frame_index >= 0):
        return None
    return _fingerprint({
        "media_sha256": media_sha256,
        "frame_index": frame_index,
        "frame_sha256": frame_sha256,
    })


def _parent_gaps(parent):
    """Validate a parent frame reference fully; only one derivation level."""
    gaps = []
    if not isinstance(parent, dict) or not parent:
        return ["parent_frame_ref_empty_or_not_mapping"]
    unknown = sorted(set(parent) - set(IDENTITY_FIELDS))
    if unknown:
        gaps.append("unknown_parent_frame_ref_keys:" + ",".join(unknown))
    if parent.get("parent_frame_ref") is not None:
        gaps.append("nested_parent_not_supported")
    for name in TEXT_IDENTITY_FIELDS:
        if not _is_non_empty_str(parent.get(name)):
            gaps.append("parent_missing:" + name)
    for name in SHA_IDENTITY_FIELDS:
        value = parent.get(name)
        if value is not None and _canonical_sha256(value) is None:
            gaps.append("parent_bad_sha256:" + name)
    frame = parent.get("frame_index")
    if not (_is_int(frame) and frame >= 0):
        gaps.append("parent_bad_frame_index")
    return gaps


def _canonical_source_ref(source_ref, *, allow_incomplete):
    """Validate a source reference and derive its stable identity keys.

    Missing identity fields never raise when ``allow_incomplete`` is set; they
    are reported as gaps so that historical exposure facts stay recordable.
    Structural misuse (forbidden path/name/index keys, wrong key set) always
    raises, because those can never be a long-term identity.

    Parent lineage is validated **before** the identity class is derived, so a
    broken, reserved or nested parent can never yield ``COMPLETE``.
    """
    if source_ref is None or not isinstance(source_ref, dict):
        raise SourceIdentityError("source_ref_must_be_mapping")
    forbidden = sorted(set(source_ref) & FORBIDDEN_IDENTITY_KEYS)
    if forbidden:
        raise SourceIdentityError(
            "mutable_location_or_ui_index_not_an_identity:" + ",".join(forbidden)
        )
    unknown = sorted(set(source_ref) - set(IDENTITY_FIELDS))
    if unknown:
        raise SourceIdentityError("unknown_source_ref_keys:" + ",".join(unknown))

    ref = _canonical_identity_ref(source_ref)
    gaps = []
    for name in TEXT_IDENTITY_FIELDS:
        if not _is_non_empty_str(ref.get(name)):
            gaps.append("missing:" + name)
    for name in SHA_IDENTITY_FIELDS:
        value = ref.get(name)
        if value is not None and _canonical_sha256(value) is None:
            gaps.append("bad_sha256:" + name)
    frame = ref.get("frame_index")
    if not (_is_int(frame) and frame >= 0):
        gaps.append("bad_frame_index")
    for name in ("layout_id", "observation_snapshot_digest"):
        if not _is_non_empty_str(ref.get(name)):
            gaps.append("missing:" + name)

    slot_count = ref.get("slot_count")
    slot_mapping = ref.get("slot_mapping")
    if slot_count is None:
        gaps.append("missing:slot_count")
    elif not _is_int(slot_count):
        gaps.append("bad_slot_count")
    elif slot_count != SUPPORTED_SLOT_COUNT:
        # No slot-count guessing: legacy 9-slot layouts are not remapped here.
        gaps.append("slot_count_not_supported:" + str(slot_count))
    if slot_mapping is None:
        gaps.append("missing:slot_mapping")
    elif not isinstance(slot_mapping, dict):
        gaps.append("bad_slot_mapping")
    else:
        if _is_int(slot_count) and slot_count == SUPPORTED_SLOT_COUNT:
            if [str(index) for index in sorted(slot_mapping, key=str)] != [
                str(index) for index in range(SUPPORTED_SLOT_COUNT)
            ] or len(slot_mapping) != SUPPORTED_SLOT_COUNT:
                gaps.append("slot_mapping_incomplete")
            elif sorted(
                str(value) for value in slot_mapping.values()
            ) != [str(index) for index in range(SUPPORTED_SLOT_COUNT)]:
                gaps.append("slot_mapping_not_bijective")

    parent = ref.get("parent_frame_ref")
    parent_source_key = None
    parent_root_key = None
    parent_frame_index = None
    if parent is not None:
        canonical_parent = (
            _canonical_identity_ref(parent) if isinstance(parent, dict) else parent
        )
        parent_gaps = _parent_gaps(canonical_parent)
        if parent_gaps:
            gaps.extend(parent_gaps)
        else:
            parent_source_key = _fingerprint(
                {name: canonical_parent.get(name) for name in CORE_IDENTITY_FIELDS}
            )
            parent_root_key = _exposure_root_key(
                canonical_parent.get("media_sha256"),
                canonical_parent.get("frame_index"),
                canonical_parent.get("frame_sha256"),
            )
            parent_frame_index = canonical_parent.get("frame_index")

    core_missing = [
        name for name in TEXT_IDENTITY_FIELDS
        if not _is_non_empty_str(ref.get(name))
    ]
    if not (_is_int(frame) and frame >= 0):
        core_missing.append("frame_index")
    if core_missing:
        identity_class = IDENTITY_UNBOUND
    elif gaps:
        identity_class = IDENTITY_INCOMPLETE
    else:
        identity_class = IDENTITY_COMPLETE

    if not allow_incomplete and identity_class != IDENTITY_COMPLETE:
        raise SourceIdentityError(
            "source_identity_not_complete:" + ",".join(sorted(set(gaps)))
        )

    source_key = None
    if not core_missing:
        source_key = _fingerprint(
            {name: ref.get(name) for name in CORE_IDENTITY_FIELDS}
        )
    root_key = None
    if not core_missing:
        root_key = _exposure_root_key(
            ref.get("media_sha256"), frame, ref.get("frame_sha256")
        )

    normalised = {name: ref.get(name) for name in REQUIRED_IDENTITY_FIELDS}
    normalised["implementation_revision"] = ref.get("implementation_revision")
    normalised["parent_frame_ref"] = (
        canonical_parent if parent is not None and isinstance(parent, dict)
        else parent
    )
    return {
        "source_key": source_key,
        "exposure_root_key": root_key,
        "parent_source_key": parent_source_key,
        "parent_exposure_root_key": parent_root_key,
        "parent_frame_index": parent_frame_index,
        "identity_class": identity_class,
        "identity_gaps": sorted(set(gaps)),
        "frame_index": frame,
        "slot_count": slot_count,
        "slot_mapping": slot_mapping if isinstance(slot_mapping, dict) else {},
        "normalised": normalised,
    }


def _fingerprint(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _sha256_hex(blob.encode("utf-8"))


def _sha256_hex(blob):
    return hashlib.sha256(blob).hexdigest()


def _validate_field(field_id):
    if not _is_non_empty_str(field_id):
        raise UnsupportedFieldError("field_id_required")
    if field_id in FORBIDDEN_TRUTH_FIELDS:
        raise ForbiddenTruthFieldError(
            "annotations_are_not_a_truth_source_for:" + field_id
        )
    if field_id not in FIELD_CONTRACTS:
        if field_id in P1_FIELD_CANDIDATES:
            raise UnsupportedFieldError("field_not_supported_in_p0:" + field_id)
        raise UnsupportedFieldError("unsupported_field_id:" + field_id)


def _validate_label_for_field(field_id, label, *, amount_role, full_actions):
    contract = FIELD_CONTRACTS[field_id]
    if label.status not in STATUSES:
        raise LabelValidationError("unknown_label_status:" + str(label.status))

    if label.status == STATUS_KNOWN:
        if label.value is None:
            raise LabelValidationError("known_label_requires_value")
        if label.unit is not None and label.unit not in contract["unit_allowed"]:
            raise LabelValidationError("unit_not_allowed_for_field:" + field_id)
        if contract["unit_required"] and not _is_non_empty_str(label.unit):
            raise LabelValidationError("unit_required_for_field:" + field_id)
        if type(label.value) is bool or not isinstance(
            label.value, contract["value_types"]
        ):
            raise LabelValidationError("value_type_mismatch:" + field_id)
        allowed = contract["allowed_values"]
        if allowed is not None and label.value not in allowed:
            raise LabelValidationError("value_not_allowed:" + str(label.value))
        if isinstance(label.value, int) and label.value < 0:
            raise LabelValidationError("negative_amount_not_allowed")
    else:
        if label.value is not None:
            raise LabelValidationError("non_known_label_must_not_carry_value")
        if not _is_non_empty_str(label.reason):
            raise LabelValidationError(
                "reason_required_for:" + label.status
            )

    if contract["sequence_bound"] and full_actions is not None:
        raise FieldSemanticsMismatch("visible_action_glyph_vs_full_actions")
    if amount_role is not None:
        if amount_role in contract["forbidden_amount_roles"]:
            raise FieldSemanticsMismatch("pot_display_vs_wager_or_call_price")
        if field_id == FIELD_POT_DISPLAY and (
            amount_role != AMOUNT_ROLE_POT_DISPLAY_TOTAL
        ):
            raise FieldSemanticsMismatch("pot_display_amount_role_mismatch")


def _validate_seat(seat, identity):
    if seat is None:
        return
    if not _is_int(seat) or seat < 0:
        raise SourceIdentityError("seat_must_be_non_negative_int_or_null")
    slot_count = identity["slot_count"]
    if not _is_int(slot_count) or slot_count != SUPPORTED_SLOT_COUNT:
        raise SourceIdentityError("seat_not_mappable_without_supported_layout")
    mapping = identity["slot_mapping"]
    if str(seat) not in {str(value) for value in mapping.values()}:
        raise SourceIdentityError("seat_not_mapped_in_layout:" + str(seat))


def _group_key(source_key, field_id, seat):
    return source_key + "|" + field_id + "|" + ("null" if seat is None else str(seat))


def _row_identity(row):
    """Recompute the identity of one stored annotation row."""
    ref = row.get("source_ref")
    if not isinstance(ref, dict):
        raise StoreIntegrityError("annotation:missing_source_ref")
    try:
        return _canonical_source_ref(ref, allow_incomplete=True)
    except AnnotationError as exc:
        raise StoreIntegrityError("annotation:unusable_source_ref:" + str(exc))


def validate_annotation_rows(rows):
    """Full semantic validation of a recovered annotation store.

    Syntax alone is never enough: revision ids, group identity, label
    semantics, supersedes lineage and the revision graph shape are all
    re-derived from the stored ``source_ref``. A store that fails here is not
    repaired and not partially trusted.
    """
    by_revision = {}
    for row in rows:
        revision_id = row.get("revision_id")
        if not _is_non_empty_str(revision_id):
            raise StoreIntegrityError("annotation:missing_revision_id")
        if revision_id in by_revision:
            raise StoreIntegrityError(
                "annotation:duplicate_revision_id:" + revision_id
            )
        by_revision[revision_id] = row

    for revision_id, row in by_revision.items():
        identity = _row_identity(row)
        if identity["source_key"] is None:
            raise StoreIntegrityError(
                "annotation:unbound_source_key:" + revision_id
            )
        if identity["source_key"] != row.get("source_key"):
            raise StoreIntegrityError(
                "annotation:source_key_mismatch:" + revision_id
            )
        field_id = row.get("field_id")
        seat = row.get("seat")
        expected_group = _group_key(identity["source_key"], field_id, seat)
        if expected_group != row.get("group_key"):
            raise StoreIntegrityError("annotation:forged_group_key:" + revision_id)
        try:
            _validate_field(field_id)
        except AnnotationError as exc:
            raise StoreIntegrityError(
                "annotation:bad_field:" + revision_id + ":" + str(exc)
            )
        metadata = row.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        try:
            _validate_label_for_field(
                field_id,
                Label(
                    status=row.get("status"),
                    value=row.get("value"),
                    unit=row.get("unit"),
                    reason=row.get("reason"),
                ),
                amount_role=metadata.get("amount_role"),
                full_actions=(
                    [True] if metadata.get("full_actions_declared") else None
                ),
            )
        except AnnotationError as exc:
            raise StoreIntegrityError(
                "annotation:label_violation:" + revision_id + ":" + str(exc)
            )
        try:
            _validate_seat(seat, identity)
        except AnnotationError as exc:
            raise StoreIntegrityError(
                "annotation:bad_seat:" + revision_id + ":" + str(exc)
            )

    for revision_id, row in by_revision.items():
        supersedes = row.get("supersedes")
        expected = row.get("expected_revision")
        if supersedes is None:
            if expected is not None:
                raise StoreIntegrityError(
                    "annotation:expected_revision_without_supersedes:" + revision_id
                )
            continue
        if not _is_non_empty_str(supersedes):
            raise StoreIntegrityError("annotation:bad_supersedes:" + revision_id)
        target = by_revision.get(supersedes)
        if target is None:
            raise StoreIntegrityError("annotation:orphan_supersedes:" + revision_id)
        if target.get("group_key") != row.get("group_key"):
            raise StoreIntegrityError(
                "annotation:cross_group_supersedes:" + revision_id
            )
        if expected != supersedes:
            raise StoreIntegrityError(
                "annotation:expected_revision_mismatch:" + revision_id
            )

    for revision_id in by_revision:
        seen = set()
        cursor = revision_id
        while cursor is not None:
            if cursor in seen:
                raise StoreIntegrityError("annotation:revision_cycle:" + revision_id)
            seen.add(cursor)
            cursor = by_revision[cursor].get("supersedes")

    groups = {}
    for revision_id, row in by_revision.items():
        groups.setdefault(row.get("group_key"), []).append(revision_id)
    for group, revision_ids in groups.items():
        roots = [
            revision_id for revision_id in revision_ids
            if by_revision[revision_id].get("supersedes") is None
        ]
        superseded = {
            by_revision[revision_id].get("supersedes")
            for revision_id in revision_ids
            if by_revision[revision_id].get("supersedes") is not None
        }
        heads = [
            revision_id for revision_id in revision_ids
            if revision_id not in superseded
        ]
        if len(roots) != 1:
            raise StoreIntegrityError(
                "annotation:revision_root_not_unique:" + str(group)
            )
        if len(heads) != 1:
            raise StoreIntegrityError(
                "annotation:revision_head_not_unique:" + str(group)
            )


def _fold_annotations(records):
    """Return {group_key: [records in append order]} plus per-group head."""
    groups = {}
    for row in records:
        key = row.get("group_key")
        groups.setdefault(key, []).append(row)
    heads = {}
    for key, rows in groups.items():
        superseded = {
            row.get("supersedes")
            for row in rows
            if row.get("supersedes") is not None
        }
        live = [row for row in rows if row.get("revision_id") not in superseded]
        heads[key] = live
    return groups, heads


def _current_view(row, *, include_context):
    view = {
        "revision_id": row.get("revision_id"),
        "field_id": row.get("field_id"),
        "seat": row.get("seat"),
        "status": row.get("status"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "reason": row.get("reason"),
        "supersedes": row.get("supersedes"),
        "recorded_at": row.get("recorded_at"),
        "actor": row.get("actor"),
        "identity_class": row.get("identity_class"),
        "model_output": row.get("model_output"),
        "model_reason": row.get("model_reason"),
        "model_output_seen": row.get("model_output_seen"),
        "implementation_revision": row.get("implementation_revision"),
    }
    if include_context:
        view["source_ref"] = row.get("source_ref")
    return view


def get_annotations(store, source_ref=None, include_history=False, **filters):
    """Read current annotation values (and optionally the full revision chain).

    The winning value is folded through ``supersedes`` / revision identity,
    never guessed from a timestamp. The whole store is semantically validated
    first, so a syntactically valid but semantically broken store raises
    instead of returning a value.
    """
    resolved = _coerce_store(store)
    source_identity = None
    wanted_key = None
    if source_ref is not None:
        source_identity = _canonical_source_ref(source_ref, allow_incomplete=True)
        wanted_key = source_identity["source_key"]
    rows = resolved.read_annotations()
    if wanted_key is not None:
        rows = [row for row in rows if row.get("source_key") == wanted_key]
    field_filter = filters.get("field_id")
    if field_filter is not None:
        rows = [row for row in rows if row.get("field_id") == field_filter]
    if "seat" in filters and filters["seat"] is not None:
        rows = [row for row in rows if row.get("seat") == filters["seat"]]
    groups, heads = _fold_annotations(rows)
    current = {}
    conflicts = []
    for key, live in heads.items():
        if len(live) == 1:
            current[key] = _current_view(
                live[0], include_context=include_history
            )
        else:
            conflicts.append(
                {
                    "group_key": key,
                    "reason": "multiple_heads",
                    "revision_ids": sorted(row["revision_id"] for row in live),
                }
            )
    identity_class = source_identity["identity_class"] if source_identity else None
    identity_gaps = source_identity["identity_gaps"] if source_identity else []
    payload = {
        "source_key": wanted_key,
        "identity_class": identity_class,
        "identity_gaps": identity_gaps,
        "current": current,
        "conflicts": conflicts,
    }
    if include_history:
        payload["history"] = rows
    return payload


def append_annotation(
    store,
    source_ref,
    field_id,
    seat,
    label,
    expected_revision,
    actor,
    *,
    observation=None,
    amount_role=None,
    full_actions=None,
    recorded_at=None,
):
    """Append one annotation revision. Returns the new durable revision id.

    Old revisions are never overwritten; ``expected_revision`` must match the
    durable head for the same (source, field, seat) or the append is refused.
    The existing store is validated before the append, so a broken revision
    graph can never be "repaired" by opening a new root.
    """
    resolved = _coerce_store(store)
    _validate_field(field_id)
    identity = _canonical_source_ref(source_ref, allow_incomplete=True)
    if identity["source_key"] is None:
        raise SourceIdentityError("annotation_requires_core_source_identity")
    _validate_seat(seat, identity)
    resolved_label = _coerce_label(label)
    _validate_label_for_field(
        field_id,
        resolved_label,
        amount_role=amount_role,
        full_actions=full_actions,
    )
    context = observation or ObservationContext()
    if context.model_output_seen not in MODEL_OUTPUT_SEEN:
        raise LabelValidationError(
            "bad_model_output_seen:" + str(context.model_output_seen)
        )
    if not _is_non_empty_str(actor):
        raise LabelValidationError("annotator_actor_required")

    group = _group_key(identity["source_key"], field_id, seat)
    with resolved.lock():
        existing = [
            row for row in resolved.read_annotations()
            if row.get("group_key") == group
        ]
        _, heads = _fold_annotations(existing)
        live = heads.get(group, [])
        if len(live) > 1:
            raise RevisionConflictError("multiple_heads_for_group")
        head = live[0] if live else None
        head_revision = head.get("revision_id") if head else None
        if expected_revision is None and head_revision is not None:
            raise RevisionConflictError("expected_revision_required")
        if expected_revision is not None and head_revision is None:
            raise RevisionConflictError("expected_revision_not_found")
        if expected_revision is not None and expected_revision != head_revision:
            raise RevisionConflictError("revision_conflict")
        revision_id = "ann-" + uuid.uuid4().hex
        row = {
            "schema_version": SCHEMA_VERSION,
            "event_id": revision_id,
            "event_type": "annotation",
            "revision_id": revision_id,
            "group_key": group,
            "recorded_at": recorded_at or utc_now(),
            "actor": actor,
            "source_key": identity["source_key"],
            "exposure_root_key": identity["exposure_root_key"],
            "parent_source_key": identity["parent_source_key"],
            "parent_exposure_root_key": identity["parent_exposure_root_key"],
            "identity_class": identity["identity_class"],
            "identity_gaps": identity["identity_gaps"],
            "source_ref": identity["normalised"],
            "field_id": field_id,
            "seat": seat,
            "status": resolved_label.status,
            "value": resolved_label.value,
            "unit": resolved_label.unit,
            "reason": resolved_label.reason,
            "supersedes": head_revision,
            "expected_revision": expected_revision,
            "model_output": context.model_output,
            "model_reason": context.model_reason,
            "model_output_seen": context.model_output_seen,
            "implementation_revision": context.implementation_revision,
            "observation_snapshot_digest": identity["normalised"].get(
                "observation_snapshot_digest"
            ),
            "metadata": {
                "amount_role": amount_role,
                "full_actions_declared": full_actions is not None,
            },
        }
        try:
            resolved.append_annotation(row)
        except OSError as exc:
            raise StoreIntegrityError("annotation_persistence_failed") from exc
    return revision_id


def _query_keys(identity):
    """Every key whose exposure history applies to this identity."""
    keys = set()
    for name in (
        "source_key",
        "exposure_root_key",
        "parent_source_key",
        "parent_exposure_root_key",
    ):
        value = identity.get(name)
        if _is_non_empty_str(value):
            keys.add(value)
    return keys


def _event_keys(row):
    """Keys of one stored exposure event, recomputed when root keys are absent."""
    keys = set()
    for name in (
        "source_key",
        "exposure_root_key",
        "parent_source_key",
        "parent_exposure_root_key",
    ):
        value = row.get(name)
        if _is_non_empty_str(value):
            keys.add(value)
    ref = row.get("source_ref")
    if isinstance(ref, dict):
        try:
            identity = _canonical_source_ref(ref, allow_incomplete=True)
        except AnnotationError:
            return keys
        keys |= _query_keys(identity)
    return keys


def _event_effective_keys(row, bindings=None):
    """Claimed lineage + the lineage the referenced revisions can prove.

    A mis-bound event is therefore visible from both sides: the one it claimed
    and the one its revisions actually belong to.
    """
    keys = _event_keys(row)
    if bindings:
        entry = bindings.get(row.get("event_id"))
        if entry:
            keys |= set(entry.get("contamination_keys") or ())
    return keys


def _filter_events(events, keys, bindings=None):
    if not keys:
        return []
    return [
        row for row in events if _event_effective_keys(row, bindings) & keys
    ]


def _validate_consumer(consumer):
    """Validate the minimal consumer identity; never a permission by itself."""
    if consumer is None or not isinstance(consumer, dict):
        raise ExposureError("consumer_identity_required")
    consumer_id = consumer.get("consumer_id")
    if not _is_non_empty_str(consumer_id):
        raise ExposureError("consumer_id_required")
    digest_value = consumer.get("digest", consumer.get("sha256"))
    if not _is_non_empty_str(digest_value):
        raise ExposureError("consumer_digest_required")
    targets = consumer.get("required_targets")
    if not isinstance(targets, (list, tuple)) or not targets:
        raise ExposureError("consumer_required_targets_required")
    for target in targets:
        if not isinstance(target, dict):
            raise ExposureError("consumer_target_must_be_mapping")
        try:
            _validate_field(target.get("field_id"))
        except AnnotationError as exc:
            raise ExposureError("consumer_target_field_unsupported:" + str(exc))
        seat = target.get("seat")
        if seat is not None and not (_is_int(seat) and seat >= 0):
            raise ExposureError("consumer_target_seat_invalid:" + str(seat))
    return consumer_id


def _validate_run_ref(run_or_manifest_ref):
    if run_or_manifest_ref is None or not isinstance(run_or_manifest_ref, dict):
        raise ExposureError("run_or_manifest_ref_required")
    if not run_or_manifest_ref:
        raise ExposureError("run_or_manifest_ref_must_not_be_empty")
    if not _is_non_empty_str(run_or_manifest_ref.get("kind")):
        raise ExposureError("run_or_manifest_ref_kind_required")
    identity_value = (
        run_or_manifest_ref.get("digest")
        or run_or_manifest_ref.get("sha256")
        or run_or_manifest_ref.get("ref")
    )
    if not _is_non_empty_str(identity_value):
        raise ExposureError("run_or_manifest_ref_digest_required")


# --------------------------------------------------------------------------
# Central exposure binding validation
#
# One validator, two callers: the new-write path (``record_exposure``) and
# every history recovery path (``assess_use`` / ``exposure_projection``). A
# persisted ``binding_status`` is a historical claim and is never read here;
# the effective status is re-derived from the event's own source reference,
# the annotation revisions it references, their parent lineage, the consumer
# targets and the run / manifest reference.
# --------------------------------------------------------------------------


def _event_identity(row):
    """Re-derive the lineage an exposure event *claims*, never trusting keys."""
    ref = row.get("source_ref")
    if isinstance(ref, dict):
        try:
            return _canonical_source_ref(ref, allow_incomplete=True)
        except AnnotationError:
            pass
    return {
        "source_key": row.get("source_key"),
        "exposure_root_key": row.get("exposure_root_key"),
        "parent_source_key": row.get("parent_source_key"),
        "parent_exposure_root_key": row.get("parent_exposure_root_key"),
        "identity_class": row.get("identity_class"),
        "identity_gaps": list(row.get("identity_gaps") or []),
    }


def _revision_lineage(row):
    """Re-derive everything one stored annotation revision can prove."""
    identity = _row_identity(row)
    parent_gaps = []
    ref = row.get("source_ref")
    if isinstance(ref, dict) and ref.get("parent_frame_ref") is not None:
        parent = ref.get("parent_frame_ref")
        canonical = (
            _canonical_identity_ref(parent) if isinstance(parent, dict) else parent
        )
        parent_gaps = _parent_gaps(canonical)
    return {
        "revision_id": row.get("revision_id"),
        "source_key": identity["source_key"],
        "exposure_root_key": identity["exposure_root_key"],
        "parent_source_key": identity["parent_source_key"],
        "parent_exposure_root_key": identity["parent_exposure_root_key"],
        "identity_class": identity["identity_class"],
        "parent_gaps": sorted(set(parent_gaps)),
        "field_id": row.get("field_id"),
        "seat": row.get("seat"),
        "status": row.get("status"),
        "group_key": row.get("group_key"),
    }


def _candidate_key(lineage):
    """Stable identity of everything one revision candidate can prove.

    Two candidates are the same fact only when their whole derived lineage
    agrees. A copy of one store is therefore a duplicate, while the same
    revision id pointing at another source, parent, field, seat or label is a
    genuinely different candidate.
    """
    return (
        lineage.get("revision_id"),
        lineage.get("source_key"),
        lineage.get("exposure_root_key"),
        lineage.get("parent_source_key"),
        lineage.get("parent_exposure_root_key"),
        lineage.get("identity_class"),
        tuple(lineage.get("parent_gaps") or ()),
        lineage.get("field_id"),
        lineage.get("seat"),
        lineage.get("status"),
        lineage.get("group_key"),
    )


def _add_revision_candidate(index, lineage):
    """Register one derived lineage under its revision id, keeping every one.

    Identical derived content collapses into a single entry; anything that
    really differs is retained side by side so that no candidate can silently
    replace another.
    """
    bucket = index.setdefault(lineage.get("revision_id"), {})
    bucket[_candidate_key(lineage)] = lineage


def _revision_candidates(index, revision_id):
    """Every distinct lineage one revision id resolved to, in read order."""
    bucket = index.get(revision_id)
    if not bucket:
        return []
    return list(bucket.values())


def _index_from_rows(rows):
    """Single-store revision candidate index used by the new-write path."""
    index = {}
    for row in rows:
        revision_id = row.get("revision_id")
        if not _is_non_empty_str(revision_id):
            continue
        try:
            _add_revision_candidate(index, _revision_lineage(row))
        except (AnnotationError, StoreIntegrityError):
            continue
    return index


def _build_revision_index(paths):
    """revision id -> every re-derived lineage, merged over every store.

    A revision id that resolves to more than one *different* derived lineage is
    ambiguous. Every candidate is kept: the effective binding can never select
    one of them as the truth, and the conservative contamination union has to
    cover all of them, because there is no way to tell which one the wrong
    event actually consumed. Dropping the later candidate would make the result
    depend on the declared store order.
    """
    index = {}
    conflicts = set()
    for entry in paths:
        try:
            rows = AnnotationStore(entry).read_annotations()
        except (StoreIntegrityError, OSError, UnicodeDecodeError):
            continue
        for row in rows:
            revision_id = row.get("revision_id")
            if not _is_non_empty_str(revision_id):
                continue
            try:
                _add_revision_candidate(index, _revision_lineage(row))
            except (AnnotationError, StoreIntegrityError):
                continue
    for revision_id, bucket in index.items():
        if len(bucket) > 1:
            conflicts.add(revision_id)
    return index, conflicts


def _same_parent(claimed, proven):
    """Compare canonical parent *exposure root* identity, never display names.

    A re-audit, a manifest rebuild or a media alias rename changes the parent
    ``source_key`` but never the parent ``exposure_root_key``. Comparing the
    long-term root identity keeps those legal provenance aliases bindable
    while a real re-parent onto another frame stays refused.
    """
    claimed_root = claimed.get("parent_exposure_root_key")
    proven_root = proven.get("parent_exposure_root_key")
    claimed_source = claimed.get("parent_source_key")
    proven_source = proven.get("parent_source_key")
    if claimed_root is None and proven_root is None:
        if claimed_source is None and proven_source is None:
            return True
        return bool(
            _is_non_empty_str(claimed_source)
            and claimed_source == proven_source
        )
    if _is_non_empty_str(claimed_root) and claimed_root == proven_root:
        return True
    return bool(
        _is_non_empty_str(claimed_source)
        and claimed_source == proven_source
    )


def _event_targets(row):
    """(field, seat) pairs the recorded consumer required, or None."""
    consumer = row.get("consumer")
    if not isinstance(consumer, dict):
        return None
    targets = consumer.get("required_targets")
    if not isinstance(targets, (list, tuple)):
        return None
    pairs = set()
    for target in targets:
        if isinstance(target, dict):
            pairs.add((target.get("field_id"), target.get("seat")))
    return pairs


def _evaluate_exposure_binding(row, revision_index, *, revision_conflicts=()):
    """Re-derive the effective binding of one exposure event.

    ``row["binding_status"]`` is deliberately never consulted: it is only the
    historical claim of whoever wrote the line. Every conclusion below comes
    from the event's own source reference and from the annotation revisions it
    references, so a stored ``BOUND``, a stored ``UNRESOLVED`` and a missing
    value all reach the same verdict for the same underlying facts.

    ``contamination_keys`` is the conservative union of the lineage the event
    claims and the lineage every referenced revision can prove -- every
    candidate of an ambiguous revision included -- so a mis-bound event pollutes
    both sides rather than laundering the one it failed to name. Which
    candidate keeps that association can never depend on the order in which
    the stores happened to be read.
    """
    reasons = []
    contamination = set()
    identity = _event_identity(row)
    contamination |= _query_keys(identity)

    if identity.get("identity_class") != IDENTITY_COMPLETE:
        reasons.append("binding_event_identity_not_complete")

    revision_ids = row.get("annotation_revision_ids")
    if isinstance(revision_ids, (list, tuple)):
        revision_ids = [item for item in revision_ids if _is_non_empty_str(item)]
    else:
        revision_ids = []

    evidence_kind = row.get("evidence_kind")
    targets = _event_targets(row)
    if targets is None:
        reasons.append("binding_consumer_targets_unreadable")

    event_root = identity.get("exposure_root_key")
    event_source = identity.get("source_key")
    resolved = []
    for revision_id in revision_ids:
        candidates = _revision_candidates(revision_index, revision_id)
        if not candidates:
            reasons.append("binding_revision_unresolvable:" + revision_id)
            continue
        # An ambiguous revision is never bound, but every candidate it can
        # prove still belongs to the conservative contamination union: the
        # wrong event may have consumed any of them.
        if len(candidates) > 1 or revision_id in revision_conflicts:
            reasons.append("binding_revision_ambiguous:" + revision_id)
        for lineage in candidates:
            resolved.append(lineage)
            contamination |= _query_keys(lineage)

            revision_root = lineage.get("exposure_root_key")
            revision_source = lineage.get("source_key")
            if not (
                (_is_non_empty_str(revision_root) and revision_root == event_root)
                or (
                    _is_non_empty_str(revision_source)
                    and revision_source == event_source
                )
            ):
                reasons.append("binding_revision_lineage_mismatch:" + revision_id)
            if lineage.get("identity_class") != IDENTITY_COMPLETE:
                reasons.append(
                    "binding_revision_identity_not_complete:" + revision_id
                )
            if lineage.get("parent_gaps"):
                reasons.append("binding_revision_parent_incomplete:" + revision_id)
            if not _same_parent(identity, lineage):
                reasons.append("binding_parent_lineage_mismatch:" + revision_id)
            if targets is not None:
                pair = (lineage.get("field_id"), lineage.get("seat"))
                if pair not in targets:
                    reasons.append(
                        "binding_revision_target_mismatch:" + revision_id
                    )
            if evidence_kind == EVIDENCE_ACTUALLY_CONSUMED and (
                lineage.get("status") != STATUS_KNOWN
            ):
                reasons.append("binding_revision_not_known:" + revision_id)

    if not revision_ids and evidence_kind != EVIDENCE_RELEASED:
        reasons.append("binding_consumed_revision_set_missing")

    if targets is not None and resolved:
        covered = {(item.get("field_id"), item.get("seat")) for item in resolved}
        for field_id, seat in sorted(
            targets, key=lambda pair: (str(pair[0]), str(pair[1]))
        ):
            if (field_id, seat) not in covered:
                reasons.append(
                    "binding_consumer_target_not_covered:"
                    + f"{field_id}:{seat}"
                )

    consumer = row.get("consumer")
    if not isinstance(consumer, dict):
        reasons.append("binding_consumer_identity_missing")
    else:
        try:
            _validate_consumer(consumer)
        except AnnotationError as exc:
            reasons.append(
                "binding_consumer_identity_invalid:" + str(exc)[:60]
            )
    try:
        _validate_run_ref(row.get("run_or_manifest_ref"))
    except AnnotationError as exc:
        reasons.append("binding_run_ref_invalid:" + str(exc)[:60])

    return {
        "effective_binding_status": (
            BINDING_BOUND if not reasons else BINDING_UNRESOLVED
        ),
        "claimed_binding_status": row.get("binding_status"),
        "binding_reasons": sorted(set(reasons)),
        "contamination_keys": sorted(contamination),
    }


def _derive_bindings(events, revision_index, *, revision_conflicts=()):
    """Derived binding view per event id; stored claims are not read."""
    bindings = {}
    for row in events:
        event_id = row.get("event_id")
        if not _is_non_empty_str(event_id):
            continue
        bindings[event_id] = _evaluate_exposure_binding(
            row, revision_index, revision_conflicts=revision_conflicts
        )
    return bindings


def record_exposure(
    store,
    source_ref,
    annotation_revision_ids,
    purpose,
    run_or_manifest_ref,
    evidence_kind,
    *,
    consumer=None,
    policy_ref=None,
    artifact_ref=None,
    role=None,
    actor=None,
    policy_violation=False,
    recorded_at=None,
):
    """Append an irreversible source-level use / release / consumption fact.

    Historical facts are always recorded, including ones that violated policy:
    refusing to store them would let past contamination disappear from history.

    A recorded event is only bound when every consumed revision is proven to
    belong to this source lineage, to the consumer's exact (field, seat)
    targets and, for actual consumption, to a ``KNOWN`` label. Anything else is
    refused before a byte is written, because an unbound event would otherwise
    circulate as a trusted consumption fact.

    The parent lineage of each consumed revision is part of that proof: a
    caller may not re-parent an already annotated crop onto another frame and
    still obtain a trusted ``BOUND``. Such an event is still stored - history is
    never deleted - but as ``UNRESOLVED`` with ``policy_violation`` set and with
    contamination aliases covering both the claimed and the proven lineage.
    """
    resolved = _coerce_store(store)
    if purpose not in PURPOSES:
        raise ExposureError("unsupported_purpose:" + str(purpose))
    if evidence_kind not in EVIDENCE_KINDS:
        raise ExposureError("unsupported_evidence_kind:" + str(evidence_kind))
    _validate_run_ref(run_or_manifest_ref)
    _validate_consumer(consumer)
    identity = _canonical_source_ref(source_ref, allow_incomplete=True)
    if identity["source_key"] is None:
        raise SourceIdentityError("exposure_requires_core_source_identity")
    if not isinstance(annotation_revision_ids, (list, tuple)):
        raise ExposureError("annotation_revision_ids_must_be_sequence")
    for revision in annotation_revision_ids:
        if not _is_non_empty_str(revision):
            raise ExposureError("bad_annotation_revision_id")
    if evidence_kind != EVIDENCE_RELEASED and not annotation_revision_ids:
        raise ExposureError("consumed_revision_set_required")
    if artifact_ref is not None and not isinstance(artifact_ref, dict):
        raise ExposureError("artifact_ref_must_be_mapping")
    if role is not None and role not in EXPOSURE_ROLES:
        raise ExposureError("unsupported_exposure_role:" + str(role))
    if policy_violation not in (True, False):
        raise ExposureError("policy_violation_must_be_bool")

    lineage_keys = {
        identity["source_key"],
        identity["parent_source_key"],
    }
    lineage_keys.discard(None)
    root_keys = {
        identity["exposure_root_key"],
        identity["parent_exposure_root_key"],
    }
    root_keys.discard(None)

    rows = resolved.read_annotations()
    by_revision = {row.get("revision_id"): row for row in rows}
    targets = [
        (target.get("field_id"), target.get("seat"))
        for target in consumer.get("required_targets")
    ]
    seen_targets = set()
    bound = []
    for revision in annotation_revision_ids:
        row = by_revision.get(revision)
        if row is None:
            raise ExposureError("consumed_revision_not_found:" + revision)
        if row.get("source_key") not in lineage_keys:
            raise ExposureError("consumed_revision_source_mismatch:" + revision)
        row_root = row.get("exposure_root_key")
        if row_root is None:
            row_identity = _row_identity(row)
            row_root = row_identity.get("exposure_root_key")
        if row_root not in root_keys:
            raise ExposureError("consumed_revision_content_mismatch:" + revision)
        pair = (row.get("field_id"), row.get("seat"))
        if pair not in targets:
            raise ExposureError("consumed_revision_not_a_consumer_target:" + revision)
        if evidence_kind == EVIDENCE_ACTUALLY_CONSUMED and (
            row.get("status") != STATUS_KNOWN
        ):
            raise ExposureError("unknown_revision_cannot_be_consumed:" + revision)
        seen_targets.add(pair)
        bound.append({
            "revision_id": revision,
            "field_id": row.get("field_id"),
            "seat": row.get("seat"),
            "status": row.get("status"),
        })
    missing_targets = [
        pair for pair in targets
        if pair not in seen_targets and annotation_revision_ids
    ]
    if missing_targets:
        raise ExposureError(
            "consumer_target_not_consumed:"
            + ",".join(f"{field}:{seat}" for field, seat in missing_targets)
        )

    event_id = "exp-" + uuid.uuid4().hex
    row = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": "exposure",
        "recorded_at": recorded_at or utc_now(),
        "actor": actor,
        "source_key": identity["source_key"],
        "exposure_root_key": identity["exposure_root_key"],
        "parent_source_key": identity["parent_source_key"],
        "parent_exposure_root_key": identity["parent_exposure_root_key"],
        "source_ref": identity["normalised"],
        "purpose": purpose,
        "evidence_kind": evidence_kind,
        "annotation_revision_ids": list(annotation_revision_ids),
        "annotation_revision_refs": bound,
        "consumer": {
            "consumer_id": consumer.get("consumer_id"),
            "digest": consumer.get("digest", consumer.get("sha256")),
            "required_targets": [
                {"field_id": field, "seat": seat} for field, seat in targets
            ],
        },
        "run_or_manifest_ref": dict(run_or_manifest_ref),
        "artifact_ref": dict(artifact_ref) if artifact_ref else None,
        "role": role,
        "policy_ref": policy_ref,
        "policy_violation": policy_violation,
        "identity_class": identity["identity_class"],
    }
    # ``rows`` came from read_annotations(), so the revision graph has already
    # passed the B5 validation. What is still open is whether *this* event is
    # bound to that graph: the shared validator re-checks the child and parent
    # lineage, the consumer targets, the KNOWN status and the run reference.
    claim = _evaluate_exposure_binding(row, _index_from_rows(rows))
    row["binding_status"] = claim["effective_binding_status"]
    row["binding_reasons"] = claim["binding_reasons"]
    row["contamination_keys"] = claim["contamination_keys"]
    if row["binding_status"] != BINDING_BOUND:
        # A mis-bound fact is kept, never deleted, and never presented as a
        # trusted consumption fact: it is stored as a policy violation whose
        # contamination aliases cover both the claimed and the proven lineage.
        row["policy_violation"] = True
    try:
        with resolved.lock():
            resolved.append_exposure(row)
    except OSError as exc:
        raise StoreIntegrityError("exposure_persistence_failed") from exc
    return row


def _fold_exposure_state(rows, *, coverage_complete=False):
    """Monotonic union: releases and later revisions never reduce exposure.

    An empty event set is ``EXPOSURE_UNKNOWN`` unless every known store was
    declared and read: absence of records is never silently read as clean.
    """
    if not rows:
        return (
            STATE_NONE_UNDER_COVERAGE if coverage_complete else STATE_UNKNOWN
        )
    kinds = {row.get("evidence_kind") for row in rows}
    if EVIDENCE_ACTUALLY_CONSUMED in kinds:
        return STATE_ACTUALLY_CONSUMED
    intent_kinds = {EVIDENCE_RESERVED, EVIDENCE_RELEASED, EVIDENCE_POSSIBLY_USED}
    if kinds & intent_kinds:
        return STATE_POSSIBLY_USED
    return STATE_UNKNOWN


def load_trusted_reservations():
    """Load the reviewed reservation artifact shipped by current main.

    Returns ``(reservations, artifact_sha256, reasons)``. This mapping is the
    only reservation authority recognised here; a caller-supplied reservation
    mapping is compared against it and never replaces it.
    """
    path = REPO_ROOT / RESERVATION_ARTIFACT_RELATIVE
    if not path.is_file():
        return None, None, [
            "trusted_reservation_artifact_missing:" + RESERVATION_ARTIFACT_RELATIVE
        ]
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, [
            "trusted_reservation_artifact_unreadable:" + str(exc)[:60]
        ]
    if not isinstance(payload, dict):
        return None, None, ["trusted_reservation_artifact_not_object"]
    try:
        validate_reservations(payload)
    except Exception as exc:
        return None, None, [
            "trusted_reservation_artifact_invalid:" + str(exc)[:60]
        ]
    return payload, _sha256_hex(raw), []


def _read_declared_stores(own_store, declared_paths):
    """Common multi-store history reader used by assess and projection.

    Every declared store is read, then duplicate event ids with identical
    content are collapsed and conflicting ones are reported. Nothing here can
    prove that an undeclared store does not exist, so coverage stays
    ``UNKNOWN`` until a reviewed global inventory is wired in.

    The returned ``context`` carries the re-derived binding of every merged
    event plus the annotation revision index it was derived from. Callers must
    filter and conclude through that context: a persisted ``binding_status``
    is a historical claim, never a binding authority.
    """
    reasons = []
    events = []
    paths = []
    if declared_paths is None:
        reasons.append("exposure_history_coverage_undeclared")
        declared_paths = []
    elif not isinstance(declared_paths, (list, tuple)) or not declared_paths:
        reasons.append("exposure_history_coverage_undeclared")
        declared_paths = []

    own_key = str(Path(own_store.path).resolve()).casefold()
    seen_paths = set()
    for entry in declared_paths:
        target = Path(entry)
        if not target.exists():
            reasons.append("declared_store_missing:" + str(target))
            continue
        resolved = str(target.resolve()).casefold()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        paths.append(target)
        try:
            rows = AnnotationStore(target).read_exposures()
        except (StoreIntegrityError, OSError, UnicodeDecodeError):
            reasons.append("declared_store_unreadable:" + str(target))
            continue
        events.extend(rows)
    if own_key not in seen_paths:
        reasons.append("own_store_not_declared_in_history_coverage")
        paths.append(Path(own_store.path))
        try:
            events.extend(own_store.read_exposures())
        except (StoreIntegrityError, OSError, UnicodeDecodeError):
            reasons.append("declared_store_unreadable:" + own_key)
    if not TRUSTED_HISTORY_INVENTORY_AVAILABLE:
        reasons.append("global_history_inventory_unavailable")
    by_id = {}
    order = []
    conflicts = []
    for row in events:
        event_id = row.get("event_id")
        if not _is_non_empty_str(event_id):
            conflicts.append("history_event_without_id")
            continue
        existing = by_id.get(event_id)
        if existing is None:
            by_id[event_id] = row
            order.append(event_id)
            continue
        if _fingerprint(existing) == _fingerprint(row):
            continue
        conflicts.append("cross_store_event_id_conflict:" + event_id)
    merged = [by_id[event_id] for event_id in order]
    reasons.extend(conflicts)
    revision_index, revision_conflicts = _build_revision_index(paths)
    context = {
        "revision_index": revision_index,
        "bindings": _derive_bindings(
            merged, revision_index, revision_conflicts=revision_conflicts
        ),
    }
    return merged, reasons, context


def _annotation_target_reasons(payload, required_fields):
    """Report required-field coverage. Never a permission by itself."""
    reasons = []
    for field_id in sorted(set(required_fields)):
        try:
            _validate_field(field_id)
        except AnnotationError:
            reasons.append("required_field_unsupported:" + str(field_id))
            continue
        matches = [
            row for row in payload["current"].values()
            if row.get("field_id") == field_id
        ]
        if not matches:
            reasons.append("required_annotation_missing:" + field_id)
        elif not any(row.get("status") == STATUS_KNOWN for row in matches):
            reasons.append("required_annotation_not_known:" + field_id)
    if payload["conflicts"]:
        reasons.append("annotation_history_conflict")
    return reasons


def _resolve_consumption_set(store, source_ref, consumer):
    """Exact (field, seat) -> head revision set for the declared targets."""
    payload = get_annotations(store, source_ref, include_history=False)
    index = {
        (row.get("field_id"), row.get("seat")): row
        for row in payload["current"].values()
    }
    chosen = []
    issues = []
    for target in consumer.get("required_targets") or []:
        field_id = target.get("field_id")
        seat = target.get("seat")
        row = index.get((field_id, seat))
        label = f"{field_id}:{seat}"
        if row is None:
            issues.append("consumption_target_missing:" + label)
            continue
        if row.get("status") != STATUS_KNOWN:
            issues.append("consumption_target_not_known:" + label)
            continue
        chosen.append(row.get("revision_id"))
    return sorted(chosen), issues


def assess_use(
    store,
    source_ref,
    purpose,
    policy_bundle,
    *,
    actor=None,
    reserve=False,
    required_fields=None,
):
    """Derive purpose eligibility read-only. Clients cannot supply the verdict.

    Nothing supplied by the caller is an authority:

    * reservations come from the reviewed repository artifact, never from a
      caller mapping (a differing mapping is reported, not honoured);
    * a development role must be provable from that artifact's development
      intervals; "not reserved" is never a development proof;
    * arbitrary ``development_evidence_ref`` strings carry no authority;
    * positive consumption additionally needs a reviewed consumer identity and
      a global history inventory, neither of which exists on current main, so
      the verdict stays ``BLOCKED``.
    """
    resolved = _coerce_store(store)
    bundle = policy_bundle if isinstance(policy_bundle, dict) else {}
    reasons = []

    if policy_bundle is None or not isinstance(policy_bundle, dict):
        reasons.append("policy_bundle_missing")
    policy_ref = bundle.get("policy_ref")
    if not _is_non_empty_str(policy_ref):
        reasons.append("policy_ref_missing")
    if purpose not in PURPOSES:
        reasons.append("purpose_unsupported:" + str(purpose))

    identity = _canonical_source_ref(source_ref, allow_incomplete=True)
    if identity["identity_class"] != IDENTITY_COMPLETE:
        reasons.append(
            "source_identity_incomplete:" + ",".join(identity["identity_gaps"])
        )

    reservations, artifact_sha, reservation_reasons = load_trusted_reservations()
    reasons.extend(reservation_reasons)
    caller_reservations = bundle.get("reservations")
    if caller_reservations is not None:
        if reservations is None:
            reasons.append("caller_reservations_not_authoritative")
        elif _fingerprint(caller_reservations) != _fingerprint(reservations):
            reasons.append("caller_reservations_do_not_match_canonical_artifact")
    declared_artifact_sha = bundle.get("reservation_artifact_sha256")
    if declared_artifact_sha is not None and artifact_sha is not None:
        if declared_artifact_sha != artifact_sha:
            reasons.append("reservation_artifact_sha_mismatch")

    declared_role = bundle.get("role")
    if declared_role not in ("development", "calibration"):
        reasons.append("role_unknown:" + str(declared_role))
    if declared_role == "calibration":
        reasons.append("calibration_role_has_no_trusted_interval_authority")

    frames = [("child", identity["frame_index"])]
    if identity["parent_frame_index"] is not None:
        frames.append(("parent", identity["parent_frame_index"]))
    if reservations is None:
        reasons.append("trusted_reservations_unavailable")
    else:
        for label, frame in frames:
            try:
                assert_training_frames([frame], reservations)
            except Exception:
                reasons.append("frame_reserved_or_invalid:" + label)
        development = reservations.get("known_development_inclusive_intervals") or []
        exploration = reservations.get("known_exploration_frames") or []
        for label, frame in frames:
            if not _is_int(frame):
                continue
            in_development = any(
                _is_int(start) and _is_int(end) and start <= frame <= end
                for start, end in development
            )
            if not in_development:
                reasons.append(
                    "frame_not_in_trusted_development_intervals:" + label
                )
            if frame in exploration:
                reasons.append(
                    "exploration_frame_is_not_development_authority:" + label
                )

    consumer = bundle.get("consumer")
    consumer_issues = []
    if consumer is None:
        reasons.append("consumer_identity_missing")
    elif not isinstance(consumer, dict):
        reasons.append("consumer_identity_malformed")
    if not TRUSTED_CONSUMER_REGISTRY_AVAILABLE:
        reasons.append("trusted_consumer_registry_unavailable")

    annotations = {}
    try:
        annotations = get_annotations(resolved, source_ref, include_history=False)
    except AnnotationError as exc:
        reasons.append("annotation_store_integrity_error:" + str(exc)[:80])
    wanted = set(required_fields or bundle.get("required_fields") or [])
    if annotations:
        reasons.extend(_annotation_target_reasons(annotations, wanted))
        allow_assisted = bundle.get("allow_model_assisted_labels") is True
        for row in annotations["current"].values():
            seen = row.get("model_output_seen")
            if seen == MODEL_OUTPUT_SEEN_YES and not allow_assisted:
                reasons.append("model_assisted_label_without_policy")
                break

    coverage_rows, coverage_reasons, binding_context = _read_declared_stores(
        resolved, bundle.get("declared_store_paths")
    )
    reasons.extend(coverage_reasons)
    keys = _query_keys(identity)
    merged = _filter_events(
        coverage_rows, keys, binding_context["bindings"]
    )
    coverage_ok = False
    state = _fold_exposure_state(merged, coverage_complete=coverage_ok)
    if state == STATE_ACTUALLY_CONSUMED:
        if bundle.get("allow_reuse_of_exposed_development") is not True:
            reasons.append("exposed_development_reuse_not_declared")
    elif state == STATE_POSSIBLY_USED:
        if bundle.get("allow_reuse_of_exposed_development") is not True:
            reasons.append("possibly_used_reuse_not_declared")
    elif state == STATE_UNKNOWN:
        reasons.append("exposure_history_unknown")
    if any(row.get("policy_violation") for row in merged):
        reasons.append("known_policy_violation_exposure")
    for row in merged:
        if row.get("role") == "holdout" and row.get("purpose") in PURPOSES:
            reasons.append("holdout_training_history_cannot_be_redeveloped")
            break
    for row in merged:
        entry = binding_context["bindings"].get(row.get("event_id")) or {}
        if entry.get("effective_binding_status") != BINDING_BOUND:
            reasons.append(
                "exposure_event_not_bound:" + str(row.get("event_id"))
            )
            break

    allowed = not reasons and not consumer_issues
    receipt = None
    if allowed and reserve and isinstance(consumer, dict):
        try:
            chosen, consumer_issues = _resolve_consumption_set(
                resolved, source_ref, consumer
            )
            if consumer_issues:
                reasons.extend(consumer_issues)
            else:
                event = record_exposure(
                    resolved,
                    source_ref,
                    chosen,
                    purpose,
                    {
                        "kind": "consumption_reservation",
                        "policy_ref": policy_ref,
                        "actor": actor,
                        "digest": policy_ref,
                    },
                    EVIDENCE_RESERVED,
                    consumer=consumer,
                    policy_ref=policy_ref,
                    role=bundle.get("role"),
                    actor=actor,
                )
                verify = [
                    row for row in resolved.read_exposures()
                    if row.get("event_id") == event["event_id"]
                ]
                if not verify:
                    raise StoreIntegrityError("reservation_not_visible_after_write")
                receipt = {
                    "event_id": event["event_id"],
                    "evidence_kind": EVIDENCE_RESERVED,
                    "purpose": purpose,
                    "annotation_revision_ids": chosen,
                }
        except AnnotationError as exc:
            if "persistence" in str(exc) or "not_visible" in str(exc):
                reasons.append("consumption_record_not_durable")
            else:
                reasons.append("consumption_reservation_refused:" + str(exc))
        except OSError:
            reasons.append("consumption_record_not_durable")

    verdict = VERDICT_ALLOWED_FOR_PURPOSE if not reasons else VERDICT_BLOCKED
    # No reviewed global inventory exists, so coverage is never proven here and
    # an empty event set can never be reported as "no exposure recorded".
    coverage = COVERAGE_UNKNOWN
    return {
        "schema_version": SCHEMA_VERSION,
        "source_key": identity["source_key"],
        "exposure_root_key": identity["exposure_root_key"],
        "identity_class": identity["identity_class"],
        "purpose": purpose,
        "verdict": verdict,
        "usable_scope": (
            SCOPE_PURPOSE_BOUND if verdict == VERDICT_ALLOWED_FOR_PURPOSE
            else SCOPE_ANNOTATION_ONLY
        ),
        "reasons": sorted(set(reasons)) if reasons else [],
        "policy_ref": policy_ref,
        "exposure_state": state,
        "history_coverage": coverage,
        "reservation_receipt": receipt,
    }


def exposure_projection(store, scope):
    """Read-only row view for a future controlled freeze adapter.

    The rows carry ``used_for`` / ``role`` / ``artifact_sha256`` so that they
    are field compatible with ``aa8_holdout_plan.validate_freeze`` entries, but
    this projection is **not attached** to that validator: no adapter calls it
    and the validator does not inspect its integrity fields. A row may only be
    handed to the freeze gate after a reviewed adapter has verified history
    coverage, every ``unresolved`` entry, and the source / event / freeze-file
    hash bindings.

    ``freeze_bindable`` therefore expresses *projection-internal completeness
    only*, never "accepted by validate_freeze".

    Missing history is never projected as clean: unresolved gaps are carried on
    every row and mark it non-bindable.
    """
    resolved = _coerce_store(store)
    scope = scope or {}
    identity_targets = []
    for ref in scope.get("sources") or []:
        identity_targets.append(_canonical_source_ref(ref, allow_incomplete=True))
    coverage_rows, coverage_reasons, binding_context = _read_declared_stores(
        resolved, scope.get("declared_store_paths")
    )
    coverage = COVERAGE_UNKNOWN
    coverage_ok = False
    purposes = set(scope.get("purposes") or PURPOSES)

    rows = []
    unresolved_global = list(coverage_reasons)
    for identity in identity_targets:
        keys = _query_keys(identity)
        events = [
            row for row in _filter_events(
                coverage_rows, keys, binding_context["bindings"]
            )
            if row.get("purpose") in purposes
        ]
        state = _fold_exposure_state(events, coverage_complete=coverage_ok)
        unresolved_global.append(
            "exposure_history_coverage_unproven:" + str(identity["source_key"])
        )
        if not events:
            unresolved_global.append(
                "no_exposure_history_evidence:" + str(identity["source_key"])
            )
            rows.append(
                {
                    "source_key": identity["source_key"],
                    "exposure_root_key": identity["exposure_root_key"],
                    "parent_source_key": identity["parent_source_key"],
                    "parent_exposure_root_key": identity[
                        "parent_exposure_root_key"
                    ],
                    "used_for": None,
                    "role": "unknown",
                    "artifact_sha256": None,
                    "annotation_revision_ids": [],
                    "policy_ref": None,
                    "exposure_state": STATE_UNKNOWN,
                    "evidence_kind": None,
                    "policy_violation": False,
                    "freeze_bindable": False,
                    "freeze_adapter_attached": False,
                    "unresolved": ["no_exposure_history_evidence"],
                }
            )
            continue
        for event in events:
            artifact = event.get("artifact_ref") or {}
            artifact_sha = artifact.get("sha256")
            row_unresolved = list(unresolved_global)
            if not _is_non_empty_str(artifact_sha):
                row_unresolved.append("artifact_sha256_missing")
            if event.get("role") not in ("development", "calibration"):
                row_unresolved.append("exposure_role_unknown")
            if event.get("policy_violation"):
                row_unresolved.append("policy_violation_recorded")
            binding = binding_context["bindings"].get(event.get("event_id")) or {}
            if binding.get("effective_binding_status") != BINDING_BOUND:
                row_unresolved.append("exposure_event_not_bound")
                for reason in binding.get("binding_reasons") or ():
                    row_unresolved.append("binding_reason:" + reason)
            if state == STATE_UNKNOWN:
                row_unresolved.append("exposure_history_unknown")
            rows.append(
                {
                    "event_id": event.get("event_id"),
                    "source_key": event.get("source_key"),
                    "exposure_root_key": event.get("exposure_root_key"),
                    "parent_source_key": event.get("parent_source_key"),
                    "parent_exposure_root_key": event.get(
                        "parent_exposure_root_key"
                    ),
                    "used_for": event.get("purpose"),
                    "role": event.get("role") or "unknown",
                    "artifact_sha256": artifact_sha,
                    "annotation_revision_ids": list(
                        event.get("annotation_revision_ids") or []
                    ),
                    "policy_ref": event.get("policy_ref"),
                    "evidence_kind": event.get("evidence_kind"),
                    "policy_violation": bool(event.get("policy_violation")),
                    "exposure_state": state,
                    "binding_status": binding.get("effective_binding_status"),
                    "claimed_binding_status": binding.get(
                        "claimed_binding_status"
                    ),
                    "freeze_bindable": not row_unresolved,
                    "freeze_adapter_attached": False,
                    "unresolved": sorted(set(row_unresolved)),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "history_coverage": coverage,
        "freeze_adapter_attached": False,
        "rows": rows,
        "unresolved": sorted(set(unresolved_global)),
    }
