"""Command line entry point for the capture-card calibration toolkit.

Every subcommand works on a private calibration dataset directory created by
``init``. Nothing here touches ``configs/`` or the packaged application:
promoting drafts into the repository is stage L's job and stays a manual,
reviewed step.

Exit codes are 0 unless an error occurred. ``--strict`` turns unmet
requirements into a non-zero exit so the checks can gate a CI job without
making interactive use miserable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

from . import SCHEMA_VERSION
from .audit import audit_labels
from .boundary import (
    EDGES,
    MAX_BOUNDARY_DRIFT_PX,
    ContentBounds,
    EdgeFlags,
    content_bounds,
    edge_content_flags,
    load_gray,
    merge_edge_flags,
    summarize_drift,
)
from .coverage import evaluate_coverage
from .dataset import (
    FrameEntry,
    build_frame_label_skeleton,
    create_skeleton,
    read_frame_manifest,
    read_frames_jsonl,
    read_roi_measurements_csv,
    write_device_template,
    write_frames_jsonl,
)
from .geometry import write_geometry_drafts
from .hashing import verify_sha256sums, write_sha256sums
from .layout_id import build_layout_id
from .record import (
    probe_device,
    record_session,
    update_device_manifest,
    write_session_log,
)
from .review_frames import (
    build_card,
    encode_frame_image,
    index_issues,
    render_card_json,
    render_review_html,
)
from .viewpoint import (
    classify_viewpoint,
    render_viewpoint_report,
)
from .stack_transcribe import (
    apply_stack_values,
    collect_stack_gaps,
    render_stack_csv,
    render_stack_worksheet,
)
from .stack_auto import (
    render_auto_report,
    render_proposal_csv,
    run_stack_auto,
)
from .sampler import SampleOptions, default_reader, sample_session
from .report import (
    STATUS_PASS,
    ReportInputs,
    determine_status,
    render_review_report,
)
from .schema import DeviceAndCapture, FieldMetrics, SchemaError
from .splits import build_split_plan, validate_split_plan
from poker_engine.perceptual.capture.capture_card_backend import default_capture_api
from poker_engine.perceptual.capture.normalization import NormalizationConfig

CANVAS_HELP = "normalized canvas size as WIDTHxHEIGHT, e.g. 1080x1920"
_CAPTURE_APIS = ["MSMF", "DSHOW", "AVFOUNDATION", "ANY"]


def _parse_size(text: str) -> tuple[int, int]:
    parts = text.lower().replace("*", "x").split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected integer dimensions, got {text!r}"
        ) from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("dimensions must be positive")
    return (width, height)


def _load_labels(root: Path) -> list:
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        return []
    return read_frames_jsonl(path)


def _load_inputs(root: Path) -> ReportInputs:
    inputs = ReportInputs()

    device_path = root / "source" / "device_and_capture.json"
    if device_path.is_file():
        inputs.device = DeviceAndCapture.from_json(
            device_path.read_text(encoding="utf-8")
        )

    normalization_path = root / "normalization" / "normalization.json"
    if normalization_path.is_file():
        payload = json.loads(normalization_path.read_text(encoding="utf-8"))
        inputs.normalization_version = payload.get("version")
        source_size = payload.get("source_size")
        if source_size:
            inputs.raw_size = (int(source_size[0]), int(source_size[1]))
        output_size = payload.get("output_size")
        if output_size:
            inputs.normalized_size = (int(output_size[0]), int(output_size[1]))

    labels = _load_labels(root)
    if labels:
        inputs.coverage = evaluate_coverage(labels)

    metrics_path = root / "evidence" / "field_metrics.json"
    if metrics_path.is_file():
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("fields", [])
        inputs.field_metrics = [FieldMetrics.from_dict(row) for row in rows]

    replay_path = root / "replay" / "replay.draft.json"
    if replay_path.is_file():
        inputs.replay_evidence = json.loads(replay_path.read_text(encoding="utf-8"))

    sums_path = root / "SHA256SUMS"
    if sums_path.is_file():
        hashes = {}
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, separator, relative = line.partition("  ")
            if separator:
                hashes[relative] = digest
        inputs.hashes = hashes

    geometry_path = root / "geometry" / "table_map.draft.json"
    if geometry_path.is_file():
        table_map = json.loads(geometry_path.read_text(encoding="utf-8"))
        inputs.layout_id = table_map.get("layout_id", inputs.layout_id)
        inputs.platform_id = table_map.get("platform_id", inputs.platform_id)

    return inputs


# --- subcommands -----------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> int:
    root = create_skeleton(args.root)
    device = write_device_template(root / "source" / "device_and_capture.json")
    print(f"dataset skeleton created at {root}")
    print(f"fill in the stage A manifest: {device}")
    print("privacy: raw video and full frames must never enter Git")
    return 0


def _cmd_check_labels(args: argparse.Namespace) -> int:
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1
    sessions = sorted({label.session_id for label in labels})
    hands = sorted({label.group_id for label in labels})
    print(f"frames:   {len(labels)}")
    print(f"sessions: {len(sessions)} ({', '.join(sessions) or 'none'})")
    print(f"hands:    {len(hands)}")
    return 0


def _cmd_label_frame(args: argparse.Namespace) -> int:
    """Stage F: emit a valid all-UNKNOWN FrameLabel skeleton for a frame.

    This is not a pass — a skeleton is an UNKNOWN-filled template the labeller
    promotes field by field. It guarantees the JSONL line is schema-valid
    (all 8 slots present, UNKNOWN carries no value) so the human only fills
    what is actually readable on the frame.
    """
    root = Path(args.root)
    manifest_path = root / "normalized" / "manifest.json"
    if not manifest_path.is_file():
        print(f"no normalized manifest at {manifest_path} (run stage D first)")
        return 1

    if args.reviewer == "REPLACE_ME" or not args.reviewer.strip():
        print("error: --reviewer must name a real reviewer, not REPLACE_ME")
        return 1

    entries = read_frame_manifest(manifest_path)
    by_file = {entry.file: entry for entry in entries}

    # --frame can be a full file name or an index (positional in manifest).
    targets: list[FrameEntry] = []
    if args.frame:
        if args.frame in by_file:
            targets.append(by_file[args.frame])
        else:
            try:
                index = int(args.frame)
            except ValueError:
                print(f"error: --frame {args.frame!r} is not in the manifest")
                return 1
            if not 0 <= index < len(entries):
                print(f"error: frame index {index} out of range (0..{len(entries)-1})")
                return 1
            targets.append(entries[index])
    else:
        # No --frame: emit a skeleton for every eligible frame.
        targets = [e for e in entries if e.stable]
        if not targets:
            print("error: no stable frames in manifest")
            return 1

    # Skip frames we already labelled (do not create a duplicate line).
    out_path = root / "labels" / "frames.jsonl"
    existing: set[str] = set()
    if out_path.is_file():
        try:
            existing = {label.frame for label in read_frames_jsonl(out_path)}
        except SchemaError as exc:
            print(f"existing labels invalid, refusing to append: {exc}")
            return 1

    new_labels = []
    for entry in targets:
        if entry.file in existing:
            print(f"skip (already labelled): {entry.file}")
            continue
        try:
            new_labels.append(
                build_frame_label_skeleton(
                    entry,
                    hand_id=args.hand_id,
                    reviewer=args.reviewer,
                    notes=args.notes,
                )
            )
        except SchemaError as exc:
            print(f"error building skeleton for {entry.file}: {exc}")
            return 1

    if not new_labels:
        print("nothing to add (all targets already labelled)")
        return 0

    written = write_frames_jsonl(out_path, new_labels)
    print(f"wrote {written} skeleton label(s) to {out_path}")
    for label in new_labels:
        print(f"  - {label.frame}")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    root = Path(args.root)
    labels = _load_labels(root)
    if not labels:
        print(f"no labels found under {root / 'labels'}")
        return 1
    report = evaluate_coverage(labels)
    print(f"frames: {report.frame_count}  sessions: {len(report.sessions)}")
    print()
    print(f"{'field':<20} {'pos':>8} {'neg':>8}  status")
    print("-" * 48)
    for item in report.requirements:
        status = "ok" if item.met else "GAP"
        print(
            f"{item.field:<20} {item.measured_positive:>8} "
            f"{item.measured_negative:>8}  {status}"
        )
    if report.is_complete:
        print("\nstage G minimum coverage: met")
        return 0
    print(f"\nstage G minimum coverage: {len(report.unmet)} field(s) short")
    print("top-up list:")
    for line in report.gap_lines:
        print(f"  - {line}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}")
    return 1 if args.strict else 0


def _cmd_splits(args: argparse.Namespace) -> int:
    root = Path(args.root)
    labels = _load_labels(root)
    if not labels:
        print(f"no labels found under {root / 'labels'}")
        return 1
    plan = build_split_plan(labels)
    problems = validate_split_plan(plan, labels)
    for assignment in plan.assignments:
        print(
            f"{assignment.name:<12} groups={len(assignment.groups):<5} "
            f"frames={len(assignment.frames)}"
        )
    for assignment in plan.auxiliary:
        print(f"{assignment.name:<12} frames={len(assignment.frames)}")
    written = plan.write(root / "splits")
    print(f"\nwrote {len(written)} split files to {root / 'splits'}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("no hand-level leakage detected")
    return 0


def _cmd_geometry(args: argparse.Namespace) -> int:
    root = Path(args.root)
    csv_path = root / "labels" / "roi_measurements.csv"
    if not csv_path.is_file():
        print(f"no ROI measurements at {csv_path}")
        return 1
    measurements = read_roi_measurements_csv(csv_path)
    written = write_geometry_drafts(
        measurements,
        root / "geometry",
        platform_id=args.platform_id,
        layout_id=args.layout_id,
        canvas=args.canvas,
    )
    print(f"wrote {len(written)} geometry drafts:")
    for name, path in sorted(written.items()):
        print(f"  - {name}: {path}")
    return 0


def _cmd_layout_id(args: argparse.Namespace) -> int:
    layout = build_layout_id(
        phone_model=args.phone,
        capture_card_model=args.card,
        uvc_width=args.uvc[0],
        uvc_height=args.uvc[1],
        fps=args.fps,
        canvas_width=args.canvas[0],
        canvas_height=args.canvas[1],
        version=args.version,
    )
    print(layout)
    return 0


def _cmd_boundary(args: argparse.Namespace) -> int:
    root = Path(args.root)
    manifest_path = root / "normalized" / "manifest.json"
    if not manifest_path.is_file():
        print(f"no frame manifest at {manifest_path}")
        return 1
    entries = json.loads(
        manifest_path.read_text(encoding="utf-8")
    ).get("frames", [])
    if not entries:
        print("frame manifest lists no frames")
        return 1

    frames_dir = root / "normalized" / "frames"
    groups: dict[tuple[str, bool], list[ContentBounds]] = {}
    flags: list[EdgeFlags] = []
    blank = 0
    missing = 0
    for entry in entries:
        path = frames_dir / entry["file"]
        if not path.is_file():
            missing += 1
            continue
        gray = load_gray(path)
        flags.append(edge_content_flags(gray))
        bounds = content_bounds(gray)
        if bounds is None:
            blank += 1
            continue
        key = (str(entry.get("scene", "")), bool(entry.get("stable", True)))
        groups.setdefault(key, []).append(bounds)

    measured = sum(len(items) for items in groups.values())
    print(f"frames measured: {measured} (blank {blank}, missing {missing})")

    summaries = []
    for (scene, stable), items in sorted(groups.items()):
        summary = summarize_drift(items, scene=scene, stable=stable)
        if summary is not None:
            summaries.append(summary)

    print()
    header = (
        f"{'scene':<16} {'stable':<7} {'frames':>7} "
        f"{'drift L/R/T/B':>16} {'worst':>6}"
    )
    print(header)
    print("-" * len(header))
    for item in summaries:
        drift = item.drift_by_edge()
        cell = (
            f"{drift['left']}/{drift['right']}/"
            f"{drift['top']}/{drift['bottom']}"
        )
        print(
            f"{item.scene:<16} {str(item.stable):<7} "
            f"{item.frame_count:>7} {cell:>16} {item.worst_drift:>6}"
        )

    merged = merge_edge_flags(flags)
    print("\nedge evidence (does the canvas reach the frame border?):")
    for edge in EDGES:
        verdict = "content" if merged.as_dict()[edge] else "NO CONTENT"
        print(f"  {edge:<7} {verdict}")

    judged = [item for item in summaries if item.scene == args.scene]
    judged = [item for item in judged if item.stable]
    print()
    if not judged:
        print(f"no stable '{args.scene}' frames available to judge")
        return 1
    worst = max(item.worst_drift for item in judged)
    ok = worst <= MAX_BOUNDARY_DRIFT_PX
    print(
        f"stage C boundary drift: {'PASS' if ok else 'FAIL'} "
        f"(worst {worst} px, tolerance {MAX_BOUNDARY_DRIFT_PX} px)"
    )

    if args.json_out:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "frames_measured": measured,
            "blank_frames": blank,
            "missing_files": missing,
            "tolerance_px": MAX_BOUNDARY_DRIFT_PX,
            "judged_scene": args.scene,
            "worst_drift_px": worst,
            "verdict": "PASS" if ok else "FAIL",
            "edge_evidence": merged.as_dict(),
            "groups": [
                {
                    "scene": item.scene,
                    "stable": item.stable,
                    "frame_count": item.frame_count,
                    "drift_px": item.drift_by_edge(),
                    "worst_drift_px": item.worst_drift,
                    "within_tolerance": item.within_tolerance,
                }
                for item in summaries
            ],
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")
    return 0 if (ok or not args.strict) else 1


def _cmd_audit_labels(args: argparse.Namespace) -> int:
    """Stage F: cross-field consistency audit of ``labels/frames.jsonl``.

    The audit reports *logical* contradictions a machine can decide without
    looking at a pixel (street vs board count, board monotonicity, dealer
    uniqueness, occupancy vs stack, empty-slot dealer, pot monotonicity). It
    never rewrites a label — it flags a field so the owner can confirm or fix
    it. Rules that depend on fields the owner has not labelled yet (action)
    stay silent, so an under-labelled dataset does not drown the report.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1

    report = audit_labels(labels, rules=args.rules)

    print(f"frames: {report.frames_checked}  hands: {report.hands_checked}  "
          f"sessions: {', '.join(report.sessions) or 'none'}")
    print(f"violations: {len(report.issues)} "
          f"({report.error_count} ERROR, {report.warn_count} WARN)")
    print()
    print(f"{'rule':<26} {'checked':>8} {'violated':>9}")
    print("-" * 46)
    for result in report.results:
        print(f"{result.rule:<26} {result.checked:>8} {result.violated:>9}")

    if report.issues:
        for issue in report.issues:
            slot = f" slot={issue.slot_id}" if issue.slot_id is not None else ""
            print(
                f"  [{issue.severity}] {issue.rule}{slot} {issue.frame} :: "
                f"{issue.message}"
            )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}")

    if args.strict and report.has_errors:
        return 1
    return 0


def _cmd_review_frames(args: argparse.Namespace) -> int:
    """Stage F: render a labeller-facing review page for label top-up.

    Every frame is rendered as a card showing the normalized PNG, the audit
    findings that point at it (if any), and a slot-by-slot read-out of what is
    already labelled, with the still-missing fields highlighted. This does not
    edit a label; it makes the ``UNKNOWN`` fields a human can actually see.
    The output HTML is self-contained (images inlined) and lives in the private
    dataset's ``reports/`` directory, never in Git.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1
    if not labels:
        print("no labelled frames to review")
        return 1

    # Optional focus filter: only review frames from a given session, so the
    # labeller can work the primary 6-8 handed bucket without a 100+-frame dump.
    if args.session and labels:
        filtered = [label for label in labels if label.session_id == args.session]
        print(
            f"filtered to session {args.session}: "
            f"{len(filtered)} of {len(labels)} frame(s)"
        )
        labels = filtered

    report = audit_labels(labels, rules=args.rules)
    issue_index = index_issues(report)

    frames_dir = root / "normalized" / "frames"

    cards = []
    for label in labels:
        if args.limit is not None and len(cards) >= args.limit:
            break
        label_path = frames_dir / label.frame if frames_dir.is_dir() else None
        image_bytes = b"" if args.include_images is False else None
        card = build_card(
            label,
            image_path=label_path,
            image_bytes=image_bytes,
            issue_bucket=issue_index,
            include_image=args.include_images,
        )
        cards.append(card)

    # A frame explicitly excluded from the image pass still gets a page: this
    # surfaces what audit said about it, which is useful even without pixels.
    summary = (
        f"{len(labels)} labelled frame(s) across "
        f"{len(report.sessions)} session(s) · {report.hands_checked} hand(s) · "
        f"audit {report.error_count} ERROR / {report.warn_count} WARN"
    )

    target = Path(args.out) if args.out else root / "reports" / "review-frames.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.json_out:
        Path(args.json_out).write_text(
            render_card_json(cards), encoding="utf-8"
        )
        print(f"wrote {args.json_out}")
    target.write_text(
        render_review_html(cards, summary=summary), encoding="utf-8"
    )
    print(f"reviewed {len(cards)} frame(s) → {target}")
    return 0


def _cmd_stack_worksheet(args: argparse.Namespace) -> int:
    """Stage F: render a stack-value transcription worksheet.

    Stage H/I are blocked because OCCUPIED seats with an UNKNOWN ``stack``
    de-qualify a frame from being a "stable positive". This renders each such
    target (OCCUPIED = stack not yet VALID) with a zoomed crop of the stack
    pill so the digits are legible, plus a CSV template to fill in. It does
    NOT write any value — the labeller reads and transcribes.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1

    gaps = collect_stack_gaps(labels, session=args.session)
    if not gaps:
        print("no OCCUPIED-but-stack-UNKNOWN targets to transcribe")
        return 1
    if args.limit is not None:
        gaps = gaps[: args.limit]

    frames_dir = root / "normalized" / "frames"
    by_frame = {label.frame: label for label in labels}
    summary = (
        f"{len(gaps)} target(s) — {len({g.frame for g in gaps})} frame(s) "
        f"across {len({g.hand_id for g in gaps})} hand(s)"
    )

    target = Path(args.out) if args.out else root / "reports" / "stack-worksheet.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_stack_worksheet(
            gaps, by_frame, frames_dir,
            title="Stack value transcription",
            summary=summary,
            include_images=args.include_images,
        ),
        encoding="utf-8",
    )
    print(f"wrote {target}")

    csv_target = (
        Path(args.csv_out) if args.csv_out else root / "reports" / "stack-values.csv"
    )
    csv_target.write_text(render_stack_csv(gaps), encoding="utf-8")
    print(f"wrote {csv_target}")
    print("fill the 'value' column, then run: stack-apply --csv <file>")
    return 0


def _cmd_stack_apply(args: argparse.Namespace) -> int:
    """Stage F: promote labeller-confirmed stack values to VALID.

    Reads the filled CSV (frame, slot_id, value), backs up ``frames.jsonl``,
    and promotes only the non-blank values that match an OCCUPIED-UNKNOWN
    target. Blank / unknown / already-set cells are skipped and counted — a
    value is never invented or defaulted.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"no values CSV at {csv_path}")
        return 1

    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != {
            "frame", "slot_id", "value",
        }:
            print(f"CSV must have columns frame,slot_id,value — got "
                  f"{reader.fieldnames}")
            return 1
        for row in reader:
            rows.append(row)

    result = apply_stack_values(
        path, rows,
        backup_dir=root / "reports" / "backups",
    )
    print(result.summary_line())
    if result.backup_path:
        print(f"backup: {result.backup_path}")
    print(f"total rows: {result.total}")
    return 0


def _cmd_stack_auto(args: argparse.Namespace) -> int:
    """Stage F: propose stack values by reading the pill pixels (no writes).

    Builds a 0-9 digit template library from the already-confirmed ``VALID``
    stacks on a hand-isolated train split, reads every OCCUPIED-but-UNKNOWN
    stack pill, and gates each read on a two-way confidence test (winning
    digit must beat the runner-up by ``MARGIN_THRESHOLD`` and actually fit,
    ``best_dist < FIT_THRESHOLD``). Accepted reads are written to a proposal
    CSV in the exact shape ``stack-apply`` consumes — never to
    ``frames.jsonl`` — so the write path stays the single audited writer.

    The run also scores the reader against the confirmed stacks on the eval
    split and writes a review report with the false-VALID / UNKNOWN counts,
    so an auditor (or Kimi K3) can re-check every decision before anything is
    applied.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1
    if not labels:
        print("no labelled frames to propose for")
        return 1

    frames_dir = root / "normalized" / "frames"
    if not frames_dir.is_dir():
        print(f"no normalized frames at {frames_dir}")
        return 1

    result = run_stack_auto(
        path, frames_dir,
        session=args.session,
        eval_ratio=args.eval_ratio,
    )
    s = result.summary
    print("template library:", s.template_digit_samples,
          f"samples across {s.digits_covered} digits "
          f"(train {s.train_frames} frames / {s.train_stacks} stacks)")
    print(f"proposals: {s.accepted} / {s.targets} OCCUPIED-but-UNKNOWN targets")
    print(f"reader accuracy on eval: {s.eval_total} confirmed stacks "
          f"(accepted {s.eval_accepted} / UNKNOWN {s.eval_unknown}); "
          f"correct {s.accepted_correct} / false {s.accepted_false}; "
          f"precision {s.eval_precision:.1%}, recall {s.eval_recall:.1%}")
    if result.mismatches:
        print(f"!! {len(result.mismatches)} accepted read(s) disagree with "
              f"ground truth — review before applying:")
        for m in result.mismatches:
            print(f"   {m.frame} slot {m.slot_id}: read {m.value} "
                  f"vs {m.known_value}")

    # Write the review report and the proposal CSV (the report always; the CSV
    # only when there is at least one accepted target).
    report_target = (
        Path(args.report_out)
        if args.report_out
        else root / "reports" / "stack-auto-report.md"
    )
    report_target.parent.mkdir(parents=True, exist_ok=True)
    report_target.write_text(
        render_auto_report(s, result.candidates, result.mismatches),
        encoding="utf-8",
    )
    print(f"wrote {report_target}")

    csv_target = (
        Path(args.csv_out)
        if args.csv_out
        else root / "reports" / "stack-auto-proposal.csv"
    )
    csv_target.parent.mkdir(parents=True, exist_ok=True)
    csv_target.write_text(render_proposal_csv(result.candidates), encoding="utf-8")
    print(f"wrote {csv_target}")

    if result.summary.accepted:
        print(
            "apply the confident reads with: stack-apply --csv "
            f"{csv_target}"
        )
    return 0


def _cmd_viewpoint(args: argparse.Namespace) -> int:
    """Stage F: review whether each frame is the owner *playing* or *watching*.

    This does not auto-classify (the failure-closed philosophy and the guide's
    rule 1-2 forbid guessing which table a frame belongs to). It extracts the
    explainable signals (revealed hero cards, the three-button action band,
    hero-seat presence) and renders a contact sheet where the verdict is a
    *suggestion* and the image is authoritative — so the owner can confirm by
    eye which frames are their own play. ``--seed-from-session`` lets the
    owner pre-mark the known-good session(s) to bias the signal expectations.
    """
    root = Path(args.root)
    path = root / "labels" / "frames.jsonl"
    if not path.is_file():
        print(f"no labels at {path}")
        return 1
    try:
        labels = read_frames_jsonl(path)
    except SchemaError as exc:
        print(f"label file is invalid: {exc}")
        return 1
    if not labels:
        print("no labelled frames to review")
        return 1

    frames_dir = root / "normalized" / "frames"
    entries: list[dict[str, object]] = []
    live = spectate = unknown = 0
    for label in labels:
        if args.limit is not None and len(entries) >= args.limit:
            break
        frame_path = frames_dir / label.frame
        image = ""
        signals = None
        if frame_path.is_file():
            try:
                evidence = classify_viewpoint(
                    frame_path,
                    scene=label.scene,
                    hero_occupied=args.seat_occupied if args.seat_occupied is not None
                    else None,
                )
                signals = evidence.to_dict()
                image = encode_frame_image(frame_path)
            except ValueError:
                signals = None
        if signals is not None:
            verdict = str(signals["verdict"])
        else:
            verdict = "UNKNOWN"
        if verdict == "LIVE":
            live += 1
        elif verdict == "SPECTATE":
            spectate += 1
        else:
            unknown += 1
        entries.append(
            {
                "frame": label.frame,
                "verdict": verdict,
                "confidence": (signals or {}).get("confidence", "LOW"),
                "image": image,
                "meta": f"{label.session_id} · {label.hand_id}",
                "signals": signals,
            }
        )

    total = len(entries)
    summary = (
        f"{total} frame(s) · LIVE {live} / SPECTATE {spectate} / UNKNOWN {unknown} · "
        f"verdicts are suggestions; the image is authoritative"
    )
    target = Path(args.out) if args.out else root / "reports" / "viewpoint-review.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.json_out:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "total": total,
            "live": live,
            "spectate": spectate,
            "unknown": unknown,
            "entries": [
                {k: v for k, v in entry.items() if k != "image"}
                for entry in entries
            ],
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")
    target.write_text(
        render_viewpoint_report(entries, title="Viewpoint review", summary=summary),
        encoding="utf-8",
    )
    print(f"reviewed {total} frame(s) → {target}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    inputs = _load_inputs(root)
    if args.platform_id:
        inputs.platform_id = args.platform_id
    if args.layout_id:
        inputs.layout_id = args.layout_id
    text = render_review_report(inputs)
    target = Path(args.out) if args.out else root / "evidence" / "review_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    status, reasons = determine_status(inputs)
    print(f"status: {status}")
    if reasons:
        print(f"{len(reasons)} reason(s):")
        for reason in reasons:
            print(f"  - {reason}")
    print(f"wrote {target}")
    if args.strict and status != STATUS_PASS:
        return 1
    return 0


def _cmd_hash(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if args.verify:
        problems = verify_sha256sums(root)
        if problems:
            print(f"{len(problems)} problem(s):")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("all hashes match")
        return 0
    target = write_sha256sums(root)
    print(f"wrote {target}")
    return 0


def _cmd_manifest(args: argparse.Namespace) -> int:
    root = Path(args.root)
    path = root / "normalized" / "manifest.json"
    if not path.is_file():
        print(f"no frame manifest at {path}")
        return 1
    entries = read_frame_manifest(path)
    print(f"frames: {len(entries)}")
    groups = sorted({entry.group_id for entry in entries})
    print(f"groups: {len(groups)}")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    info = probe_device(
        device_index=args.device,
        api=args.api,
        width=args.size[0],
        height=args.size[1],
        fps=args.fps,
        fourcc=args.fourcc,
    )
    print("probed UVC parameters:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    root = Path(args.root)
    create_skeleton(root)
    session_id = args.session
    raw = root / "source" / "raw" / f"{session_id}.mkv"
    log_path = root / "source" / "probe" / f"{session_id}.capture.json"

    print(f"recording session {session_id} -> {raw}")
    print("signal events will be written even on disconnect/reconnect")
    print("stop with Ctrl+C (the video is finalized on exit)")

    try:
        log = record_session(
            raw,
            session_id=session_id,
            device_index=args.device,
            api=args.api,
            width=args.size[0],
            height=args.size[1],
            fps=args.fps,
            fourcc=args.fourcc,
            codec=args.codec,
            max_seconds=args.max_seconds or None,
        )
    except KeyboardInterrupt:
        print("\ninterrupted; finalizing the recorded video…")
        return 130

    write_session_log(log_path, log)
    print(f"\nrecorded {log.written_frames} frame(s) "
          f"({log.duration_s:.1f}s) with {len(log.events)} signal event(s)")

    if args.update_manifest:
        recording = {
            "container": raw.suffix.lstrip(".") or "mkv",
            "codec": args.codec or "",
        }
        update_device_manifest(
            root,
            uvc={
                "frame_size": [log.width, log.height] if log.width else [],
                "fps": log.fps_requested,
            },
            recording=recording,
            sessions=[
                {
                    "id": session_id,
                    "raw": raw.name,
                    "duration_s": round(log.duration_s, 3),
                    "frames": log.written_frames,
                }
            ],
        )
        print(f"updated {root / 'source' / 'device_and_capture.json'}")
    return 0


# --- parser ----------------------------------------------------------------

def _cmd_sample(args: argparse.Namespace) -> int:
    root = Path(args.root)
    session_id = args.session
    normalization_path = root / "normalization" / "normalization.json"
    if not normalization_path.is_file():
        print(f"no normalization config at {normalization_path} "
              f"(run stage C first)")
        return 1
    config = NormalizationConfig.from_json(
        normalization_path.read_text(encoding="utf-8")
    )
    options = SampleOptions(
        stable_interval_ms=args.interval_ms,
        exclude_nongame=args.exclude_nongame,
    )
    reader = default_reader(
        root / "source" / "raw" / f"{session_id}.mkv",
        max_seconds=args.max_seconds,
    )
    print(f"sampling session {session_id} into {root / 'normalized'}…")
    written, entries = sample_session(
        root,
        session_id,
        normalization_config=config,
        options=options,
        reader=reader,
    )
    print(f"wrote {written} frame(s), {entries} manifest entr(ies)")
    print(f"manifest: {root / 'normalized' / 'manifest.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capture-card-calibration",
        description=(
            "Hardware-independent tooling for "
            "docs/capture-card-calibration-guide.zh-CN.md"
        ),
    )
    parser.add_argument(
        "--schema-version",
        action="version",
        version=f"capture-card-calibration schema {SCHEMA_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a private dataset skeleton")
    init.add_argument("--root", type=Path, required=True)
    init.set_defaults(func=_cmd_init)

    check = sub.add_parser("check-labels", help="validate labels/frames.jsonl")
    check.add_argument("--root", type=Path, required=True)
    check.set_defaults(func=_cmd_check_labels)

    labelframe = sub.add_parser(
        "label-frame",
        help="stage F: emit a valid all-UNKNOWN FrameLabel skeleton",
    )
    labelframe.add_argument("--root", type=Path, required=True)
    labelframe.add_argument(
        "--frame",
        default=None,
        help="file name or manifest index; omit to emit for every stable frame",
    )
    labelframe.add_argument("--hand-id", default="hand_0000")
    labelframe.add_argument("--reviewer", required=True)
    labelframe.add_argument("--notes", default="")
    labelframe.set_defaults(func=_cmd_label_frame)

    coverage = sub.add_parser("coverage", help="stage G coverage check")
    coverage.add_argument("--root", type=Path, required=True)
    coverage.add_argument("--json-out", type=Path, default=None)
    coverage.add_argument("--strict", action="store_true")
    coverage.set_defaults(func=_cmd_coverage)

    audit = sub.add_parser(
        "audit-labels",
        help="stage F: cross-field consistency audit of labels/frames.jsonl",
    )
    audit.add_argument("--root", type=Path, required=True)
    audit.add_argument(
        "--rules",
        nargs="*",
        default=None,
        help="only run these rules (names from the audit report)",
    )
    audit.add_argument("--json-out", type=Path, default=None)
    audit.add_argument("--strict", action="store_true")
    audit.set_defaults(func=_cmd_audit_labels)

    review = sub.add_parser(
        "review-frames",
        help="stage F: render a labeller-facing page for label top-up",
    )
    review.add_argument("--root", type=Path, required=True)
    review.add_argument("--out", type=Path, default=None,
                        help="output HTML path (default: reports/review-frames.html)")
    review.add_argument("--json-out", type=Path, default=None,
                        help="also dump machine-readable cards as JSON")
    review.add_argument("--limit", type=int, default=None,
                        help="only render the first N frames")
    review.add_argument("--session", default=None,
                        help="only review frames from this session id "
                             "(e.g. session_002), to focus a top-up pass")
    review.add_argument(
        "--rules",
        nargs="*",
        default=None,
        help="audit rules to run (default: all)",
    )
    review.add_argument(
        "--include-images",
        action="store_false",
        default=True,
        help="omit normalized frame images (labels + audit only)",
    )
    review.set_defaults(func=_cmd_review_frames)

    viewpoint = sub.add_parser(
        "viewpoint",
        help="stage F: review which frames are the owner playing vs watching",
    )
    viewpoint.add_argument("--root", type=Path, required=True)
    viewpoint.add_argument("--out", type=Path, default=None,
                           help="output HTML path (default: "
                                "reports/viewpoint-review.html)")
    viewpoint.add_argument("--json-out", type=Path, default=None,
                           help="also dump machine-readable verdicts as JSON")
    viewpoint.add_argument("--limit", type=int, default=None,
                           help="only review the first N frames")
    viewpoint.add_argument(
        "--seat-occupied",
        type=lambda v: None if v in ("", "none", "null") else (v.lower() == "true"),
        default=None,
        help="pre-set hero-seat occupancy (true/false) for all frames; "
             "omit to leave it as a signal the labeller confirms by eye",
    )
    viewpoint.set_defaults(func=_cmd_viewpoint)

    stackws = sub.add_parser(
        "stack-worksheet",
        help="stage F: render a stack-value transcription worksheet",
    )
    stackws.add_argument("--root", type=Path, required=True)
    stackws.add_argument("--out", type=Path, default=None,
                         help="output HTML (default: reports/stack-worksheet.html)")
    stackws.add_argument("--csv-out", type=Path, default=None,
                         help="fill-in CSV (default: reports/stack-values.csv)")
    stackws.add_argument("--session", default=None,
                         help="only target this session (e.g. session_002)")
    stackws.add_argument("--limit", type=int, default=None,
                         help="only render the first N targets (quick pilot)")
    stackws.add_argument("--include-images", action="store_false", default=True,
                         help="omit crops/frame thumbnails (labels only)")
    stackws.set_defaults(func=_cmd_stack_worksheet)

    stackapply = sub.add_parser(
        "stack-apply",
        help="stage F: promote labeller-confirmed stack values to VALID",
    )
    stackapply.add_argument("--root", type=Path, required=True)
    stackapply.add_argument("--csv", type=Path, required=True,
                            help="filled CSV with frame,slot_id,value")
    stackapply.set_defaults(func=_cmd_stack_apply)

    stackauto = sub.add_parser(
        "stack-auto",
        help="stage F: propose stack values by reading pill pixels (no writes)",
    )
    stackauto.add_argument("--root", type=Path, required=True)
    stackauto.add_argument("--session", default=None,
                           help="only propose for this session (e.g. session_002)")
    stackauto.add_argument("--eval-ratio", type=float, default=0.4,
                           help="held-out fraction for the confidence gate "
                                "eval (0<r<1)")
    stackauto.add_argument("--report-out", type=Path, default=None,
                           help="review report Markdown "
                                "(default: reports/stack-auto-report.md)")
    stackauto.add_argument("--csv-out", type=Path, default=None,
                           help="proposal CSV to feed stack-apply "
                                "(default: reports/stack-auto-proposal.csv)")
    stackauto.set_defaults(func=_cmd_stack_auto)

    splits = sub.add_parser("splits", help="stage H hand-isolated splits")
    splits.add_argument("--root", type=Path, required=True)
    splits.set_defaults(func=_cmd_splits)

    geometry = sub.add_parser("geometry", help="stage E geometry drafts")
    geometry.add_argument("--root", type=Path, required=True)
    geometry.add_argument("--platform-id", default="wepoker_android_capture_card")
    geometry.add_argument("--layout-id", required=True)
    geometry.add_argument("--canvas", type=_parse_size, required=True, help=CANVAS_HELP)
    geometry.set_defaults(func=_cmd_geometry)

    layout = sub.add_parser("layout-id", help="build a section 6 layout id")
    layout.add_argument("--phone", required=True)
    layout.add_argument("--card", required=True)
    layout.add_argument("--uvc", type=_parse_size, required=True)
    layout.add_argument("--fps", type=float, required=True)
    layout.add_argument("--canvas", type=_parse_size, required=True)
    layout.add_argument("--version", type=int, default=1)
    layout.set_defaults(func=_cmd_layout_id)

    boundary = sub.add_parser(
        "boundary", help="stage C content boundary drift (section 6)"
    )
    boundary.add_argument("--root", type=Path, required=True)
    boundary.add_argument(
        "--scene",
        default="table",
        help="scene whose stable frames decide the verdict (default: table)",
    )
    boundary.add_argument("--json-out", type=Path, default=None)
    boundary.add_argument("--strict", action="store_true")
    boundary.set_defaults(func=_cmd_boundary)

    report = sub.add_parser("report", help="stage 17 acceptance report")
    report.add_argument("--root", type=Path, required=True)
    report.add_argument("--out", type=Path, default=None)
    report.add_argument("--platform-id", default=None)
    report.add_argument("--layout-id", default=None)
    report.add_argument("--strict", action="store_true")
    report.set_defaults(func=_cmd_report)

    hashing = sub.add_parser("hash", help="write or verify SHA256SUMS")
    hashing.add_argument("--root", type=Path, required=True)
    hashing.add_argument("--verify", action="store_true")
    hashing.set_defaults(func=_cmd_hash)

    manifest = sub.add_parser("manifest", help="inspect normalized/manifest.json")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.set_defaults(func=_cmd_manifest)

    probe = sub.add_parser("probe", help="probe a live UVC device (stage A)")
    probe.add_argument("--device", type=int, default=0)
    probe.add_argument("--api", default=default_capture_api(), choices=_CAPTURE_APIS)
    probe.add_argument("--size", type=_parse_size, default=(1920, 1080))
    probe.add_argument("--fps", type=int, default=30)
    probe.add_argument("--fourcc", default=None)
    probe.set_defaults(func=_cmd_probe)

    record = sub.add_parser("record", help="record a capture session (stage B)")
    record.add_argument("--root", type=Path, required=True)
    record.add_argument("--session", required=True, help="e.g. session_001")
    record.add_argument("--device", type=int, default=0)
    record.add_argument("--api", default=default_capture_api(), choices=_CAPTURE_APIS)
    record.add_argument("--size", type=_parse_size, default=(1920, 1080))
    record.add_argument("--fps", type=int, default=30)
    record.add_argument("--fourcc", default="YUY2")
    record.add_argument(
        "--codec", default=None, choices=["FFV1", "MJPG", "H264", "HEVC"]
    )
    record.add_argument("--max-seconds", type=float, default=None)
    record.add_argument("--update-manifest", action="store_true")
    record.set_defaults(func=_cmd_record)

    sample = sub.add_parser("sample", help="stage D: sample + dedup + manifest")
    sample.add_argument("--root", type=Path, required=True)
    sample.add_argument("--session", required=True, help="e.g. session_001")
    sample.add_argument("--interval-ms", type=int, default=700,
                        help="stable-state sampling cadence (ms)")
    sample.add_argument("--max-seconds", type=float, default=None)
    sample.add_argument("--exclude-nongame", action="store_true",
                        help="drop phone home/register/menu frames")
    sample.set_defaults(func=_cmd_sample)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
