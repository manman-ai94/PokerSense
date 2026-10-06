"""One-shot, passive-only AA capture intake with no analysis or advice imports.

The CLI can prepare a capture plan, execute its built-in bounded FFmpeg
recorder after validating that plan, and sign off a hardware dry run.  It never
accepts a replay/source path and never imports desktop, recognition, strategy,
provider, equity, advice, ADB, or input-control code.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from typing import Any, Callable

from poker_engine.data_paths import private_root


PRIVATE_ROOT = private_root()
SCHEMA_VERSION = 1
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
SAFE_SESSION = re.compile(r"\Aaa-live-[a-z0-9][a-z0-9_-]{5,63}\Z")
SAFE_ID = re.compile(r"\A[a-z0-9][a-z0-9_-]{7,79}\Z")
CONFIRMATION = "可以开始本次被动实战采集"
GIB = 1024 ** 3

AUTHORIZATION_KEYS = {
    "schema_version", "status", "authorization_id", "nonce",
    "authorized_by", "authorized_at_utc", "expires_at_utc",
    "operator_confirmation", "phase", "platform_id", "capture_kind",
    "session_id", "source_recording_group_id", "output_root",
    "requested_duration_seconds", "device", "limits", "privacy",
    "rule_declaration", "identity_declaration", "forbidden_capabilities",
    "prior_hardware_receipt_sha256", "prior_dry_run_finalization_sha256",
    "prior_dry_run_plan_sha256", "prior_dry_run_authorization_sha256",
}
DEVICE_KEYS = {
    "friendly_name", "backend", "video_size", "framerate", "input_codec",
    "phone_model", "android_version", "app_version", "orientation",
    "video_adapter_model", "capture_card_model", "capture_card_firmware",
    "capture_card_serial", "device_instance_id", "usb_vid_pid", "host_os",
    "driver_version", "uvc_color_space", "uvc_color_range",
    "dshow_input_name", "normalization_sha256", "layout_sha256",
    "pnp_instance_suffix", "interface_number", "pnp_service", "pnp_class",
    "pnp_class_guid", "driver_device_id", "driver_provider", "driver_inf",
    "hardware_fingerprint_sha256",
}
LIMIT_KEYS = {
    "segment_seconds", "size_limit_bytes", "minimum_free_bytes",
    "minimum_start_free_bytes", "graceful_stop_seconds",
    "wall_clock_grace_seconds",
}
PRIVACY_KEYS = {
    "raw_media_private", "public_upload_allowed", "git_eligible",
    "audio_enabled", "post_capture_segment_hashing",
    "full_frames_in_public_bundle", "nicknames_in_metadata",
    "avatars_in_metadata", "direct_account_identifiers_in_metadata",
    "chat_or_room_identifiers_in_metadata", "privacy_review_status",
    "privacy_review_evidence_sha256", "retention_policy_id",
}
RULE_KEYS = {
    "table_size", "fields", "verification_status", "author_review",
    "independent_review", "rule_fingerprint",
}
RULE_FIELD_NAMES = {
    "small_blind", "big_blind", "ante", "ante_mode", "straddle_mode",
    "straddle_amount", "rake_percent", "rake_cap_bb", "rake_application",
    "rake_rounding", "rake_distribution", "minimum_chip",
}
RULE_FIELD_KEYS = {"status", "value", "evidence_sha256"}
IDENTITY_KEYS = {
    "method", "direct_nickname_storage", "pseudonym_secret_in_manifest",
    "stable_player_keys_available", "mapping_artifact_sha256",
    "verification_status", "avatar_storage",
    "direct_account_identifier_storage", "chat_or_room_identifier_storage",
    "privacy_review_evidence_sha256",
}
FORBIDDEN_KEYS = {
    "recognition", "strategy", "provider", "equity", "advice",
    "live_control", "automated_input", "network", "audio", "emulator",
    "adb",
}
PLAN_KEYS = {
    "schema_version", "status", "authorization_sha256", "authorization",
    "prior_hardware_receipt_sha256", "prior_hardware_receipt",
    "prior_dry_run_finalization_sha256", "prior_dry_run_finalization",
    "prior_dry_run_plan_sha256", "prior_dry_run_plan",
    "prior_dry_run_authorization_sha256", "prior_dry_run_authorization",
    "ffmpeg_contract", "state_machine", "source_partition",
    "capture_permitted", "ready_for_offline_review", "ready_for_calibration",
    "model_fit_executed", "strategy_eligible", "advice_emitted",
    "live_control", "human_signoff_required", "blockers_for_calibration",
}
FFMPEG_KEYS = {
    "binary", "input_backend", "device_friendly_name", "video_size",
    "framerate", "input_codec", "stream_copy", "audio",
    "segment_seconds", "shell", "user_extra_arguments_allowed",
}
SIGNOFF_KEYS = {
    "schema_version", "status", "finalization_receipt_sha256", "session_id",
    "authorization_sha256", "plan_sha256", "source_recording_group_id",
    "hardware_fingerprint_sha256", "capture_ended_at_utc", "signed_off_by",
    "signed_off_at_utc", "review_scope", "ffmpeg_contract_sha256",
    "ffmpeg_binary_sha256", "observed_device_sha256",
    "ordered_segment_manifest_sha256", "source_integrity_status",
    "capture_only_reviewed", "strategy_authorized", "advice_authorized",
    "live_control_authorized",
}
FINALIZATION_KEYS = {
    "schema_version", "status", "plan_sha256", "authorization_sha256",
    "authorization_use_receipt_sha256", "ordered_segment_manifest_sha256",
    "hardware_fingerprint_sha256", "ffmpeg_contract_sha256",
    "ffmpeg_binary_sha256", "observed_device", "observed_device_sha256",
    "session_id", "phase", "source_recording_group_id", "recording_root",
    "started_at_utc", "ended_at_utc", "stop_reason", "exit_code",
    "forced_termination", "metadata_files", "segments", "progress",
    "source_integrity_status", "source_partition", "blockers",
    "platform_verified", "rule_fingerprint", "identity_status",
    "legal_menu_count", "all_opportunities_reviewed", "special_modes",
    "data_readiness", "ready_for_offline_review", "ready_for_calibration",
    "model_fit_executed", "strategy_eligible", "advice_emitted",
    "live_control", "human_signoff_required",
}
METADATA_FILE_KEYS = {"role", "relative_path", "sha256", "size_bytes"}
SEGMENT_KEYS = {
    "segment_index", "relative_path", "csv_start_pts", "csv_end_pts_exclusive",
    "csv_gap_seconds", "sha256", "size_bytes", "mtime_ns",
}
PROGRESS_KEYS = {"frame", "drop_frames", "dup_frames", "out_time", "progress"}
AUTHORIZATION_USE_KEYS = {
    "schema_version", "status", "authorization_sha256", "plan_sha256",
    "session_id", "consumed_at_utc", "ffmpeg_path", "ffmpeg_sha256",
    "ffmpeg_size_bytes", "ffmpeg_mtime_ns", "ffmpeg_contract_sha256",
    "observed_device", "observed_device_sha256",
}
DEVICE_PROBE_KEYS = {
    "probe_method", "friendly_name", "device_instance_id", "usb_vid_pid",
    "pnp_instance_suffix", "interface_number", "pnp_service", "pnp_class",
    "pnp_class_guid", "driver_device_id", "driver_version",
    "driver_provider", "driver_inf", "dshow_input_name", "status",
}

STATE_MACHINE = [
    "AWAITING_HUMAN_AUTHORIZATION",
    "AUTHORIZED_NOT_STARTED",
    "PREFLIGHT_PASSED",
    "RECORDING_PASSIVE",
    "STOPPING",
    "CAPTURE_FINALIZED_UNREVIEWED",
]
FFMPEG_CONTRACT = {
    "binary": "ffmpeg",
    "input_backend": "dshow",
    "device_friendly_name": "UGREEN 25854",
    "video_size": [1920, 1080],
    "framerate": 30,
    "input_codec": "mjpeg",
    "stream_copy": True,
    "audio": False,
    "segment_seconds": 60,
    "shell": False,
    "user_extra_arguments_allowed": False,
}
CALIBRATION_BLOCKERS = [
    "capture_only_metadata_not_full_decode",
    "platform_visual_review_pending",
    "privacy_review_pending",
    "real_rule_fingerprint_missing",
    "stable_player_identity_missing_or_not_independently_verified",
    "hand_boundaries_and_censored_intervals_missing",
    "complete_decision_opportunity_census_missing",
    "predecision_state_and_legal_menus_missing",
    "same_rule_independent_session_missing",
    "session_split_not_frozen",
    "independent_evidence_review_missing",
    "live_use_forbidden_by_capture_intake_contract",
]
_STATUS_FIELDS = {
    "state", "exit_code", "device", "expected_platform",
    "duration_limit_seconds", "size_limit_bytes", "minimum_free_bytes",
    "audio", "recognition_running", "strategy_running", "ffmpeg_path",
    "ffmpeg_sha256", "dshow_input_name", "command_sha256",
}
CAPTURE_FAILURE_BLOCKERS = {
    *("recording_status_mismatch:" + key for key in _STATUS_FIELDS),
    "ffmpeg_binary_changed_during_capture",
    "ffmpeg_binary_unavailable_after_capture",
    "capture_stop_reason_invalid_or_forced",
    "capture_was_forced_or_stop_reason_missing",
    "status_segment_count_differs_from_files",
    "status_recorded_bytes_differs_from_final_segments",
    "final_segments_exceed_authorized_size_limit",
    "recording_pts_exceed_authorized_duration",
    "ffmpeg_out_time_differs_from_segment_timeline",
    "ffmpeg_out_time_missing_or_invalid",
    "capture_end_must_follow_start",
    "capture_time_outside_authorization_window",
    "recording_wall_time_exceeds_authorized_limit",
    "capture_start_or_end_time_invalid",
    "ffmpeg_progress_has_no_positive_frame_count",
    "ffmpeg_reported_dropped_frames",
    "ffmpeg_reported_duplicated_frames",
    "ffmpeg_progress_did_not_reach_end",
    "ffmpeg_frame_density_differs_from_30fps_timeline",
}


def _exact(value: Any, keys: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("exact_" + name + "_fields_required")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_nlink,
        getattr(info, "st_file_attributes", 0),
    )


def _read_snapshot(path: Path, maximum: int = 16 * 1024 * 1024) -> tuple[bytes, str]:
    before = path.lstat()
    if (path.is_symlink() or _is_reparse(before)
            or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
        raise ValueError("input_must_be_plain_single_link_file")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("opened_input_must_be_regular_file")
        chunks, total = [], 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError("metadata_input_exceeds_size_limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = path.lstat()
    if (not stat.S_ISREG(after.st_mode) or not stat.S_ISREG(final.st_mode)
            or _identity(before) != _identity(opened)
            or _identity(opened) != _identity(after)
            or _identity(after) != _identity(final)
            or path.is_symlink() or _is_reparse(final)):
        raise ValueError("input_changed_during_read")
    raw = b"".join(chunks)
    return raw, _sha_bytes(raw)


def _hash_file_snapshot(path: Path, maximum: int) -> tuple[str, int, int]:
    before = path.lstat()
    if (path.is_symlink() or _is_reparse(before)
            or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
        raise ValueError("segment_must_be_plain_single_link_file")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    digest, total = hashlib.sha256(), 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("opened_segment_must_be_regular_file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError("segment_exceeds_authorized_size_limit")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = path.lstat()
    if (not stat.S_ISREG(after.st_mode) or not stat.S_ISREG(final.st_mode)
            or _identity(before) != _identity(opened)
            or _identity(opened) != _identity(after)
            or _identity(after) != _identity(final)
            or path.is_symlink() or _is_reparse(final)):
        raise ValueError("segment_changed_during_hash")
    return digest.hexdigest(), total, final.st_mtime_ns


def _json(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("utf8_bom_forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("strict_utf8_required") from exc
    value = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("json_document_must_be_object")
    return value


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(name + "_must_be_rfc3339_utc")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(name + "_must_be_rfc3339_utc") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError(name + "_must_be_rfc3339_utc")
    return result.astimezone(timezone.utc)


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(name + "_must_be_exact_decimal_string_or_null")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(name + "_must_be_exact_decimal_string_or_null") from exc
    if not number.is_finite() or number < 0 or positive and number <= 0:
        raise ValueError("invalid_" + name)
    return number


def _hex_or_none(value: Any, name: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not HEX64.fullmatch(value)):
        raise ValueError(name + "_must_be_sha256_or_null")
    return value


def _plain_root(path: Path) -> Path:
    raw = path.lstat()
    if path.is_symlink() or _is_reparse(raw) or not stat.S_ISDIR(raw.st_mode):
        raise ValueError("private_root_must_be_plain_directory")
    return path.resolve(strict=True)


def _probe_ffmpeg_binary() -> dict[str, Any]:
    located = shutil.which("ffmpeg")
    if not located:
        raise ValueError("ffmpeg_missing_before_authorization_consumption")
    path = Path(located).resolve(strict=True)
    digest, size, mtime = _hash_file_snapshot(path, GIB)
    return {
        "path": path.as_posix(), "sha256": digest,
        "size_bytes": size, "mtime_ns": mtime,
    }


def _validate_device_probe(value: Any) -> dict[str, Any]:
    _exact(value, DEVICE_PROBE_KEYS, "observed_capture_device")
    for key in DEVICE_PROBE_KEYS - {"status"}:
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError("observed_device_field_missing:" + key)
    if value["status"].upper() != "OK":
        raise ValueError("observed_capture_device_not_ready")
    if not re.fullmatch(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}",
                        value["usb_vid_pid"].upper()):
        raise ValueError("observed_device_vid_pid_invalid")
    instance = value["device_instance_id"]
    vid_pid = re.search(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", instance.upper())
    interface = re.search(r"&MI_([0-9A-F]{2})", instance.upper())
    if (vid_pid is None or interface is None
            or value["usb_vid_pid"].upper() != vid_pid.group(0)
            or value["interface_number"].upper() != interface.group(1)
            or _normalized_dshow_instance_id(value["dshow_input_name"])
            != instance.casefold()
            or value["interface_number"].upper() != "00"
            or value["pnp_service"].casefold() != "usbvideo"
            or value["pnp_class"].casefold() not in {"camera", "image"}
            or value["driver_device_id"].casefold()
            != value["device_instance_id"].casefold()
            or value["pnp_instance_suffix"].casefold()
            != value["device_instance_id"].rsplit("\\", 1)[-1].casefold()):
        raise ValueError("observed_device_is_not_unique_video_interface")
    return value


def _parse_dshow_input_name(text: str, friendly_name: str) -> str:
    lines = text.splitlines()
    matches = []
    for index, line in enumerate(lines):
        if f'"{friendly_name}" (video)' not in line:
            continue
        for candidate in lines[index + 1:index + 4]:
            match = re.search(r'Alternative name "([^"]+)"', candidate)
            if match:
                matches.append(match.group(1))
                break
    if len(matches) != 1 or not matches[0].startswith("@device_pnp_"):
        raise ValueError("unique_dshow_alternative_device_name_required")
    return matches[0]


def _normalized_dshow_instance_id(alternative: str) -> str:
    folded = alternative.casefold()
    start = folded.find("usb#")
    end = folded.find("#{", start)
    if start < 0 or end <= start:
        raise ValueError("dshow_alternative_name_has_no_pnp_identity")
    return folded[start:end].replace("#", "\\")


def _probe_windows_capture_device(ffmpeg_identity: dict[str, Any]) -> dict[str, Any]:
    if os.name != "nt":
        raise ValueError("physical_capture_requires_windows_device_probe")
    dshow = subprocess.run([
        ffmpeg_identity["path"], "-hide_banner", "-list_devices", "true",
        "-f", "dshow", "-i", "dummy"], capture_output=True, text=True,
        encoding="utf-8", timeout=20, shell=False)
    alternative = _parse_dshow_input_name(dshow.stderr, "UGREEN 25854")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise ValueError("windows_powershell_missing_for_device_probe")
    script = (
        "$items=@(Get-CimInstance Win32_PnPEntity | "
        "Where-Object {$_.Name -eq 'UGREEN 25854' -and "
        "$_.Service -eq 'usbvideo'});"
        "if($items.Count -ne 1){exit 41};"
        "$d=$items[0];"
        "$drivers=@(Get-CimInstance Win32_PnPSignedDriver | "
        "Where-Object {$_.DeviceID -eq $d.PNPDeviceID});"
        "if($drivers.Count -ne 1){exit 42};"
        "$driver=$drivers[0];"
        "[pscustomobject]@{friendly_name=$d.Name;"
        "device_instance_id=$d.PNPDeviceID;status=$d.Status;"
        "pnp_service=$d.Service;pnp_class=$d.PNPClass;"
        "pnp_class_guid=$d.ClassGuid;driver_device_id=$driver.DeviceID;"
        "driver_version=$driver.DriverVersion;"
        "driver_provider=$driver.DriverProviderName;"
        "driver_inf=$driver.InfName} | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
        shell=False)
    if result.returncode != 0 or result.stderr.strip():
        raise ValueError("unique_ready_capture_device_probe_failed")
    try:
        raw = json.loads(result.stdout, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError("capture_device_probe_json_invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("capture_device_probe_must_return_one_device")
    instance = raw.get("device_instance_id")
    if not isinstance(instance, str):
        raise ValueError("capture_device_instance_id_missing")
    match = re.search(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", instance.upper())
    interface = re.search(r"&MI_([0-9A-F]{2})", instance.upper())
    suffix = instance.rsplit("\\", 1)[-1].strip()
    normalized_dshow_id = _normalized_dshow_instance_id(alternative)
    if (match is None or interface is None
            or normalized_dshow_id != instance.casefold()):
        raise ValueError("dshow_alternative_name_differs_from_pnp_device")
    observed = {
        "probe_method": "windows_cim_pnp_dshow_v2",
        "friendly_name": raw.get("friendly_name"),
        "device_instance_id": instance,
        "usb_vid_pid": match.group(0) if match else None,
        "pnp_instance_suffix": suffix,
        "interface_number": interface.group(1) if interface else None,
        "pnp_service": raw.get("pnp_service"),
        "pnp_class": raw.get("pnp_class"),
        "pnp_class_guid": raw.get("pnp_class_guid"),
        "driver_device_id": raw.get("driver_device_id"),
        "driver_version": raw.get("driver_version"),
        "driver_provider": raw.get("driver_provider"),
        "driver_inf": raw.get("driver_inf"),
        "dshow_input_name": alternative,
        "status": raw.get("status"),
    }
    return _validate_device_probe(observed)


def _device_probe_for_test(authorization: dict[str, Any]) -> dict[str, Any]:
    device = authorization["device"]
    return _validate_device_probe({
        "probe_method": "TEST_ONLY_INJECTED_RECORD_FUNCTION",
        "friendly_name": device["friendly_name"],
        "device_instance_id": device["device_instance_id"]
        or "USB\\VID_1234&PID_ABCD&MI_00\\TEST-SUFFIX",
        "usb_vid_pid": device["usb_vid_pid"] or "VID_1234&PID_ABCD",
        "pnp_instance_suffix": device["pnp_instance_suffix"] or "TEST-SUFFIX",
        "interface_number": device["interface_number"] or "00",
        "pnp_service": device["pnp_service"] or "usbvideo",
        "pnp_class": device["pnp_class"] or "Camera",
        "pnp_class_guid": device["pnp_class_guid"] or "TEST-CLASS-GUID",
        "driver_device_id": device["driver_device_id"]
        or "USB\\VID_1234&PID_ABCD&MI_00\\TEST-SUFFIX",
        "driver_version": device["driver_version"] or "TEST-DRIVER",
        "driver_provider": device["driver_provider"] or "TEST-PROVIDER",
        "driver_inf": device["driver_inf"] or "test.inf",
        "dshow_input_name": device["dshow_input_name"]
        or ("@device_pnp_\\\\?\\usb#vid_1234&pid_abcd&mi_00#"
            "test-suffix#{class}\\global"),
        "status": "OK",
    })


def _direct_private_json(path: Path, private_root: Path, *, new: bool = False) -> Path:
    root = _plain_root(private_root)
    if _plain_root(path.parent) != root:
        raise ValueError("metadata_must_be_direct_private_json")
    if not new:
        raw = path.lstat()
        if path.is_symlink() or _is_reparse(raw):
            raise ValueError("metadata_links_are_forbidden")
    candidate = path.resolve(strict=not new)
    if (candidate.parent != root or candidate.suffix.lower() != ".json"
            or candidate.name.endswith((" ", "."))):
        raise ValueError("metadata_must_be_direct_private_json")
    if new and candidate.exists():
        raise ValueError("private_metadata_output_must_be_new")
    return candidate


def _private_session_receipt(path: Path, private_root: Path) -> Path:
    root = _plain_root(private_root)
    _plain_root(path.parent)
    raw = path.lstat()
    if path.is_symlink() or _is_reparse(raw):
        raise ValueError("metadata_links_are_forbidden")
    candidate = path.resolve(strict=True)
    if (candidate.name != "capture-finalization-receipt.json"
            or candidate.parent.parent != root
            or not SAFE_SESSION.fullmatch(candidate.parent.name)):
        raise ValueError("receipt_must_belong_to_new_aa_live_private_session")
    return candidate


def _validate_rules(value: Any) -> list[str]:
    _exact(value, RULE_KEYS, "rule_declaration")
    if type(value["table_size"]) is not int or value["table_size"] not in (6, 7, 8):
        raise ValueError("rule_table_size_must_be_exact_6_7_or_8")
    if (not isinstance(value["fields"], dict)
            or set(value["fields"]) != RULE_FIELD_NAMES):
        raise ValueError("exact_rule_field_inventory_required")
    resolved = {}
    for name, field in value["fields"].items():
        _exact(field, RULE_FIELD_KEYS, "rule_field")
        if field["status"] not in ("UNKNOWN", "OPERATOR_DECLARED"):
            raise ValueError("rule_field_status_cannot_claim_verification")
        if not isinstance(field["evidence_sha256"], list) or any(
                not isinstance(digest, str) or not HEX64.fullmatch(digest)
                for digest in field["evidence_sha256"]):
            raise ValueError("rule_field_evidence_hash_list_required")
        if field["status"] == "UNKNOWN":
            if field["value"] is not None or field["evidence_sha256"]:
                raise ValueError("unknown_rule_field_must_be_null_without_evidence")
        elif field["value"] is None:
            raise ValueError("operator_declared_rule_field_requires_value")
        resolved[name] = field["value"]
    small = _decimal(resolved["small_blind"], "small_blind", positive=True)
    big = _decimal(resolved["big_blind"], "big_blind", positive=True)
    numbers = {key: _decimal(
        resolved[key], key, positive=key == "minimum_chip") for key in (
            "ante", "straddle_amount", "rake_percent", "rake_cap_bb",
            "minimum_chip")}
    if (small is None) != (big is None) or small is not None and big <= small:
        raise ValueError("declared_blinds_must_satisfy_zero_less_small_less_big")
    if resolved["ante_mode"] not in (None, "none", "per_dealt_player"):
        raise ValueError("invalid_or_unknown_ante_mode_required")
    if (resolved["ante_mode"] is None) != (numbers["ante"] is None):
        raise ValueError("ante_value_and_mode_must_both_be_known_or_unknown")
    if resolved["ante_mode"] == "none" and numbers["ante"] != 0:
        raise ValueError("ante_must_be_zero_when_mode_is_none")
    if resolved["straddle_mode"] not in (
            None, "none", "mandatory_utg", "optional_explicit_utg"):
        raise ValueError("invalid_or_unknown_straddle_mode_required")
    if (resolved["straddle_mode"] is None) != (
            numbers["straddle_amount"] is None):
        raise ValueError("straddle_value_and_mode_must_both_be_known_or_unknown")
    if resolved["straddle_mode"] == "none" and numbers["straddle_amount"] != 0:
        raise ValueError("straddle_must_be_zero_when_mode_is_none")
    if (resolved["straddle_mode"] not in (None, "none")
            and big is not None and numbers["straddle_amount"] <= big):
        raise ValueError("declared_straddle_must_exceed_big_blind")
    if resolved["rake_application"] not in (None, "all_pots", "postflop_only"):
        raise ValueError("invalid_or_unknown_rake_application_required")
    if resolved["rake_rounding"] not in (
            None, "exact", "floor_to_chip", "ceil_to_chip"):
        raise ValueError("invalid_or_unknown_rake_rounding_required")
    if resolved["rake_distribution"] not in (
            None, "proportional_all_pots", "main_pot_first"):
        raise ValueError("invalid_or_unknown_rake_distribution_required")
    if numbers["rake_percent"] is not None and numbers["rake_percent"] > 1:
        raise ValueError("rake_percent_must_not_exceed_one")
    known = any(field["status"] == "OPERATOR_DECLARED"
                for field in value["fields"].values())
    expected_status = "PARTIAL_OPERATOR_DECLARATION" if known else "UNKNOWN"
    if value["verification_status"] != expected_status:
        raise ValueError("capture_intake_cannot_claim_verified_rules")
    if (value["author_review"] is not None
            or value["independent_review"] is not None
            or value["rule_fingerprint"] is not None):
        raise ValueError("capture_intake_cannot_claim_rule_review_or_fingerprint")
    return ["real_rule_fingerprint_missing"]


def _validate_identity(value: Any) -> list[str]:
    _exact(value, IDENTITY_KEYS, "identity_declaration")
    if (value["method"] != "session_pseudonym_v1"
            or value["direct_nickname_storage"] is not False
            or value["pseudonym_secret_in_manifest"] is not False
            or value["avatar_storage"] is not False
            or value["direct_account_identifier_storage"] is not False
            or value["chat_or_room_identifier_storage"] is not False
            or type(value["stable_player_keys_available"]) is not bool
            or value["verification_status"] not in (
                "UNKNOWN", "OPERATOR_DECLARED")):
        raise ValueError("private_pseudonymous_identity_contract_required")
    mapping = _hex_or_none(
        value["mapping_artifact_sha256"], "mapping_artifact_sha256")
    if value["privacy_review_evidence_sha256"] is not None:
        raise ValueError("identity_privacy_review_cannot_be_predeclared")
    if value["stable_player_keys_available"] and mapping is None:
        raise ValueError("stable_player_keys_require_private_mapping_hash")
    if not value["stable_player_keys_available"] and mapping is not None:
        raise ValueError("unknown_identity_cannot_claim_mapping_artifact")
    if value["stable_player_keys_available"] != (
            value["verification_status"] == "OPERATOR_DECLARED"):
        raise ValueError("identity_status_must_match_stable_key_availability")
    return ["stable_player_identity_missing_or_not_independently_verified"]


def validate_authorization(
    value: Any, *, private_root: Path = PRIVATE_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    _exact(value, AUTHORIZATION_KEYS, "capture_authorization")
    root = _plain_root(private_root)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported_capture_authorization_schema")
    if value["status"] != "AUTHORIZED_ONCE_FOR_PASSIVE_CAPTURE":
        raise ValueError("one_time_capture_authorization_required")
    if (not isinstance(value["authorization_id"], str)
            or not SAFE_ID.fullmatch(value["authorization_id"])):
        raise ValueError("safe_authorization_id_required")
    if not isinstance(value["nonce"], str) or not HEX64.fullmatch(value["nonce"]):
        raise ValueError("unique_sha256_nonce_required")
    if (not isinstance(value["authorized_by"], str)
            or not value["authorized_by"].strip()
            or value["authorized_by"] == "REPLACE_ME"):
        raise ValueError("named_capture_authorizer_required")
    authorized = _utc(value["authorized_at_utc"], "authorized_at_utc")
    expires = _utc(value["expires_at_utc"], "expires_at_utc")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (not authorized <= current <= expires
            or expires - authorized > timedelta(hours=24)):
        raise ValueError("capture_authorization_expired_or_invalid_window")
    if value["operator_confirmation"] != CONFIRMATION:
        raise ValueError("explicit_passive_capture_confirmation_required")
    phase = value["phase"]
    if phase not in ("hardware_dry_run", "development_capture"):
        raise ValueError("invalid_capture_phase")
    duration = value["requested_duration_seconds"]
    if type(duration) is not int:
        raise ValueError("capture_duration_must_be_exact_int")
    allowed = 5 <= duration <= 30 if phase == "hardware_dry_run" else (
        60 <= duration <= 1800)
    if not allowed:
        raise ValueError("capture_duration_outside_phase_limit")
    if current + timedelta(seconds=duration + 20) > expires:
        raise ValueError("authorization_window_too_short_for_capture")
    if (value["platform_id"] != "aa_poker"
            or value["capture_kind"] != "PASSIVE_VIDEO_ONLY"):
        raise ValueError("aa_passive_video_only_authorization_required")
    if not isinstance(value["session_id"], str) or not SAFE_SESSION.fullmatch(
            value["session_id"]):
        raise ValueError("safe_new_aa_live_session_id_required")
    if (not isinstance(value["source_recording_group_id"], str)
            or not SAFE_ID.fullmatch(value["source_recording_group_id"])):
        raise ValueError("safe_source_recording_group_id_required")
    if not isinstance(value["output_root"], str):
        raise ValueError("declared_private_output_root_required")
    try:
        declared_root = Path(value["output_root"]).resolve(strict=True)
    except (OSError, TypeError) as exc:
        raise ValueError("declared_private_output_root_required") from exc
    if declared_root != root or value["output_root"] != root.as_posix():
        raise ValueError("capture_output_root_mismatch")

    _exact(value["device"], DEVICE_KEYS, "capture_device")
    device = value["device"]
    if (device["friendly_name"] != "UGREEN 25854"
            or device["backend"] != "dshow"
            or device["video_size"] != [1920, 1080]
            or type(device["framerate"]) is not int
            or device["framerate"] != 30
            or device["input_codec"] != "mjpeg"):
        raise ValueError("fixed_physical_capture_card_contract_required")
    fingerprint = _hex_or_none(
        device["hardware_fingerprint_sha256"],
        "hardware_fingerprint_sha256")
    detail_names = (
        "phone_model", "android_version", "app_version", "orientation",
        "video_adapter_model", "capture_card_model", "capture_card_firmware",
        "device_instance_id", "usb_vid_pid", "pnp_instance_suffix",
        "interface_number", "pnp_service", "pnp_class", "pnp_class_guid",
        "driver_device_id", "driver_version", "driver_provider", "driver_inf",
        "host_os", "uvc_color_space", "uvc_color_range", "dshow_input_name",
    )
    for key in detail_names:
        if device[key] is not None and (
                not isinstance(device[key], str) or not device[key].strip()):
            raise ValueError("device_detail_must_be_nonempty_string_or_null:" + key)
    if device["capture_card_serial"] is not None and (
            not isinstance(device["capture_card_serial"], str)
            or not device["capture_card_serial"].strip()):
        raise ValueError("capture_card_serial_must_be_nonempty_string_or_null")
    for key in ("normalization_sha256", "layout_sha256"):
        _hex_or_none(device[key], key)
    if fingerprint is not None:
        if (any(device[key] is None for key in detail_names)
                or device["orientation"] != "portrait"
                or device["normalization_sha256"] is None
                or device["layout_sha256"] is None):
            raise ValueError("hardware_fingerprint_requires_complete_device_manifest")
        instance = device["device_instance_id"]
        vid_pid = re.search(
            r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", instance.upper())
        interface = re.search(r"&MI_([0-9A-F]{2})", instance.upper())
        if (vid_pid is None or interface is None
                or device["usb_vid_pid"].upper() != vid_pid.group(0)
                or device["interface_number"].upper() != interface.group(1)
                or device["interface_number"].upper() != "00"
                or device["pnp_instance_suffix"].casefold()
                != instance.rsplit("\\", 1)[-1].casefold()
                or device["pnp_service"].casefold() != "usbvideo"
                or device["pnp_class"].casefold() not in {"camera", "image"}
                or device["driver_device_id"].casefold() != instance.casefold()
                or _normalized_dshow_instance_id(device["dshow_input_name"])
                != instance.casefold()):
            raise ValueError("hardware_manifest_video_interface_identity_invalid")
        payload = {key: device[key] for key in sorted(DEVICE_KEYS)
                   if key != "hardware_fingerprint_sha256"}
        if fingerprint != _canonical_sha(payload):
            raise ValueError("hardware_fingerprint_differs_from_device_manifest")

    _exact(value["limits"], LIMIT_KEYS, "capture_limits")
    expected_limits = {
        "segment_seconds": 60,
        "size_limit_bytes": 20 * GIB,
        "minimum_free_bytes": 20 * GIB,
        "minimum_start_free_bytes": 25 * GIB,
        "graceful_stop_seconds": 15,
        "wall_clock_grace_seconds": 20,
    }
    if any(type(item) is not int for item in value["limits"].values()):
        raise ValueError("capture_limits_must_be_exact_ints")
    if value["limits"] != expected_limits:
        raise ValueError("fixed_bounded_capture_limits_required")

    _exact(value["privacy"], PRIVACY_KEYS, "capture_privacy")
    if value["privacy"] != {
            "raw_media_private": True,
            "public_upload_allowed": False,
            "git_eligible": False,
            "audio_enabled": False,
            "post_capture_segment_hashing": True,
            "full_frames_in_public_bundle": False,
            "nicknames_in_metadata": False,
            "avatars_in_metadata": False,
            "direct_account_identifiers_in_metadata": False,
            "chat_or_room_identifiers_in_metadata": False,
            "privacy_review_status": "PENDING",
            "privacy_review_evidence_sha256": None,
            "retention_policy_id": "private-session-manual-retention-v1"}:
        raise ValueError("private_no_audio_capture_contract_required")
    _exact(value["forbidden_capabilities"], FORBIDDEN_KEYS,
           "forbidden_capabilities")
    if any(item is not False for item in value["forbidden_capabilities"].values()):
        raise ValueError("capture_cannot_enable_analysis_advice_or_control")
    _validate_rules(value["rule_declaration"])
    _validate_identity(value["identity_declaration"])
    prior = _hex_or_none(value["prior_hardware_receipt_sha256"],
                         "prior_hardware_receipt_sha256")
    prior_finalization = _hex_or_none(
        value["prior_dry_run_finalization_sha256"],
        "prior_dry_run_finalization_sha256")
    prior_plan = _hex_or_none(
        value["prior_dry_run_plan_sha256"], "prior_dry_run_plan_sha256")
    prior_authorization = _hex_or_none(
        value["prior_dry_run_authorization_sha256"],
        "prior_dry_run_authorization_sha256")
    prior_hashes = (prior, prior_finalization, prior_plan, prior_authorization)
    if phase == "hardware_dry_run" and any(
            item is not None for item in prior_hashes):
        raise ValueError("dry_run_cannot_claim_prior_hardware_receipt")
    if phase == "development_capture" and any(
            item is None for item in prior_hashes):
        raise ValueError("development_capture_requires_signed_dry_run")
    return value


def validate_dry_run_signoff(value: Any) -> None:
    _exact(value, SIGNOFF_KEYS, "hardware_dry_run_signoff")
    if (type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["status"] != "HARDWARE_DRY_RUN_SIGNED_OFF"
            or not isinstance(value["finalization_receipt_sha256"], str)
            or not HEX64.fullmatch(value["finalization_receipt_sha256"])
            or not isinstance(value["authorization_sha256"], str)
            or not HEX64.fullmatch(value["authorization_sha256"])
            or not isinstance(value["plan_sha256"], str)
            or not HEX64.fullmatch(value["plan_sha256"])
            or not isinstance(value["session_id"], str)
            or not SAFE_SESSION.fullmatch(value["session_id"])
            or not isinstance(value["source_recording_group_id"], str)
            or not SAFE_ID.fullmatch(value["source_recording_group_id"])
            or not isinstance(value["hardware_fingerprint_sha256"], str)
            or not HEX64.fullmatch(value["hardware_fingerprint_sha256"])
            or not isinstance(value["ffmpeg_contract_sha256"], str)
            or not HEX64.fullmatch(value["ffmpeg_contract_sha256"])
            or value["ffmpeg_contract_sha256"]
            != _canonical_sha(FFMPEG_CONTRACT)
            or not isinstance(value["ffmpeg_binary_sha256"], str)
            or not HEX64.fullmatch(value["ffmpeg_binary_sha256"])
            or not isinstance(value["observed_device_sha256"], str)
            or not HEX64.fullmatch(value["observed_device_sha256"])
            or not isinstance(value["ordered_segment_manifest_sha256"], str)
            or not HEX64.fullmatch(value[
                "ordered_segment_manifest_sha256"])
            or value["source_integrity_status"]
            != "SEGMENT_BYTES_HASHED_NOT_DECODED"
            or not isinstance(value["signed_off_by"], str)
            or not value["signed_off_by"].strip()
            or value["signed_off_by"] == "REPLACE_ME"
            or value["review_scope"] != "capture_integrity_and_privacy_only"
            or value["capture_only_reviewed"] is not True
            or value["strategy_authorized"] is not False
            or value["advice_authorized"] is not False
            or value["live_control_authorized"] is not False):
        raise ValueError("exact_hardware_dry_run_signoff_required")
    ended = _utc(value["capture_ended_at_utc"], "capture_ended_at_utc")
    signed = _utc(value["signed_off_at_utc"], "signed_off_at_utc")
    if signed < ended:
        raise ValueError("dry_run_signoff_must_follow_capture_end")


def build_plan(
    authorization: dict[str, Any], authorization_sha256: str, *,
    private_root: Path = PRIVATE_ROOT,
    prior_hardware_receipt: dict[str, Any] | None = None,
    prior_hardware_receipt_sha256: str | None = None,
    prior_dry_run_finalization: dict[str, Any] | None = None,
    prior_dry_run_finalization_sha256: str | None = None,
    prior_dry_run_plan: dict[str, Any] | None = None,
    prior_dry_run_plan_sha256: str | None = None,
    prior_dry_run_authorization: dict[str, Any] | None = None,
    prior_dry_run_authorization_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(authorization_sha256, str) or not HEX64.fullmatch(
            authorization_sha256):
        raise ValueError("external_authorization_sha256_required")
    validate_authorization(authorization, private_root=private_root, now=now)
    phase = authorization["phase"]
    declared_prior = authorization["prior_hardware_receipt_sha256"]
    declared_finalization = authorization[
        "prior_dry_run_finalization_sha256"]
    declared_plan = authorization["prior_dry_run_plan_sha256"]
    declared_authorization = authorization[
        "prior_dry_run_authorization_sha256"]
    if phase == "development_capture":
        if (prior_hardware_receipt is None
                or prior_hardware_receipt_sha256 != declared_prior):
            raise ValueError("declared_signed_dry_run_receipt_required")
        if (prior_dry_run_finalization is None
                or prior_dry_run_finalization_sha256 != declared_finalization):
            raise ValueError("declared_dry_run_finalization_required")
        if (prior_dry_run_plan is None
                or prior_dry_run_plan_sha256 != declared_plan
                or prior_dry_run_authorization is None
                or prior_dry_run_authorization_sha256 != declared_authorization):
            raise ValueError("declared_dry_run_plan_and_authorization_required")
        validate_authorization(
            prior_dry_run_authorization, private_root=private_root,
            now=_utc(prior_dry_run_authorization["authorized_at_utc"],
                     "authorized_at_utc"))
        validate_plan(
            prior_dry_run_plan, prior_dry_run_plan_sha256,
            private_root=private_root,
            now=_utc(prior_dry_run_authorization["authorized_at_utc"],
                     "authorized_at_utc"))
        if (prior_dry_run_plan["authorization_sha256"]
                != prior_dry_run_authorization_sha256
                or prior_dry_run_plan["authorization"]
                != prior_dry_run_authorization):
            raise ValueError("dry_run_plan_and_authorization_source_disagree")
        validate_finalization_receipt(prior_dry_run_finalization)
        verify_finalization_receipt_from_recording(
            prior_dry_run_finalization, prior_dry_run_plan,
            prior_dry_run_plan_sha256)
        validate_dry_run_signoff(prior_hardware_receipt)
        if (prior_dry_run_finalization["status"]
                != "CAPTURE_FINALIZED_UNREVIEWED"
                or prior_dry_run_finalization["phase"] != "hardware_dry_run"
                or prior_hardware_receipt["finalization_receipt_sha256"]
                != prior_dry_run_finalization_sha256
                or prior_hardware_receipt["session_id"]
                != prior_dry_run_finalization["session_id"]
                or prior_hardware_receipt["authorization_sha256"]
                != prior_dry_run_finalization["authorization_sha256"]
                or prior_hardware_receipt["plan_sha256"]
                != prior_dry_run_finalization["plan_sha256"]
                or prior_hardware_receipt["source_recording_group_id"]
                != prior_dry_run_finalization["source_recording_group_id"]
                or prior_hardware_receipt["hardware_fingerprint_sha256"]
                != prior_dry_run_finalization["hardware_fingerprint_sha256"]
                or prior_hardware_receipt["ffmpeg_contract_sha256"]
                != prior_dry_run_finalization["ffmpeg_contract_sha256"]
                or prior_hardware_receipt["ffmpeg_binary_sha256"]
                != prior_dry_run_finalization["ffmpeg_binary_sha256"]
                or prior_hardware_receipt["observed_device_sha256"]
                != prior_dry_run_finalization["observed_device_sha256"]
                or prior_hardware_receipt["ordered_segment_manifest_sha256"]
                != prior_dry_run_finalization[
                    "ordered_segment_manifest_sha256"]
                or prior_hardware_receipt["capture_ended_at_utc"]
                != prior_dry_run_finalization["ended_at_utc"]):
            raise ValueError("signed_dry_run_chain_disagrees")
        hardware = authorization["device"]["hardware_fingerprint_sha256"]
        if (hardware is None
                or hardware != prior_hardware_receipt[
                    "hardware_fingerprint_sha256"]):
            raise ValueError("development_capture_hardware_must_match_dry_run")
        if (prior_hardware_receipt["session_id"] == authorization["session_id"]
                or prior_hardware_receipt["source_recording_group_id"]
                == authorization["source_recording_group_id"]):
            raise ValueError("dry_run_and_capture_need_distinct_sessions")
        if _utc(authorization["authorized_at_utc"], "authorized_at_utc") < _utc(
                prior_hardware_receipt["signed_off_at_utc"], "signed_off_at_utc"):
            raise ValueError("development_authorization_must_follow_dry_run_signoff")
    elif (prior_hardware_receipt is not None
          or prior_hardware_receipt_sha256 is not None
          or prior_dry_run_finalization is not None
          or prior_dry_run_finalization_sha256 is not None
          or prior_dry_run_plan is not None
          or prior_dry_run_plan_sha256 is not None
          or prior_dry_run_authorization is not None
          or prior_dry_run_authorization_sha256 is not None):
        raise ValueError("unexpected_prior_hardware_receipt")
    blockers = list(CALIBRATION_BLOCKERS)
    if authorization["device"]["hardware_fingerprint_sha256"] is None:
        blockers.insert(0, "hardware_fingerprint_pending_dry_run")
    result = {
        "schema_version": 1,
        "status": ("READY_FOR_AUTHORIZED_HARDWARE_DRY_RUN" if phase
                   == "hardware_dry_run" else
                   "READY_FOR_AUTHORIZED_PASSIVE_CAPTURE"),
        "authorization_sha256": authorization_sha256,
        "authorization": authorization,
        "prior_hardware_receipt_sha256": prior_hardware_receipt_sha256,
        "prior_hardware_receipt": prior_hardware_receipt,
        "prior_dry_run_finalization_sha256": (
            prior_dry_run_finalization_sha256),
        "prior_dry_run_finalization": prior_dry_run_finalization,
        "prior_dry_run_plan_sha256": prior_dry_run_plan_sha256,
        "prior_dry_run_plan": prior_dry_run_plan,
        "prior_dry_run_authorization_sha256": (
            prior_dry_run_authorization_sha256),
        "prior_dry_run_authorization": prior_dry_run_authorization,
        "ffmpeg_contract": dict(FFMPEG_CONTRACT),
        "state_machine": list(STATE_MACHINE),
        "source_partition": "UNASSIGNED_QUARANTINE",
        "capture_permitted": True,
        "ready_for_offline_review": False,
        "ready_for_calibration": False,
        "model_fit_executed": False,
        "strategy_eligible": False,
        "advice_emitted": False,
        "live_control": False,
        "human_signoff_required": True,
        "blockers_for_calibration": blockers,
    }
    return result


def validate_plan(
    value: Any, plan_sha256: str, *, private_root: Path = PRIVATE_ROOT,
    now: datetime | None = None,
) -> None:
    _exact(value, PLAN_KEYS, "passive_capture_plan")
    rebuilt = build_plan(
        value["authorization"], value["authorization_sha256"],
        private_root=private_root,
        prior_hardware_receipt=value["prior_hardware_receipt"],
        prior_hardware_receipt_sha256=value["prior_hardware_receipt_sha256"],
        prior_dry_run_finalization=value["prior_dry_run_finalization"],
        prior_dry_run_finalization_sha256=value[
            "prior_dry_run_finalization_sha256"],
        prior_dry_run_plan=value["prior_dry_run_plan"],
        prior_dry_run_plan_sha256=value["prior_dry_run_plan_sha256"],
        prior_dry_run_authorization=value["prior_dry_run_authorization"],
        prior_dry_run_authorization_sha256=value[
            "prior_dry_run_authorization_sha256"],
        now=now,
    )
    if rebuilt != value:
        raise ValueError("saved_capture_plan_differs_from_recalculation")
    if not isinstance(plan_sha256, str) or not HEX64.fullmatch(plan_sha256):
        raise ValueError("external_plan_sha256_required")


def build_dry_run_signoff(
    receipt: dict[str, Any], receipt_sha256: str, *, reviewer: str,
    signed_at_utc: str,
) -> dict[str, Any]:
    validate_finalization_receipt(receipt)
    if (not isinstance(receipt_sha256, str) or not HEX64.fullmatch(receipt_sha256)
            or receipt["phase"] != "hardware_dry_run"
            or receipt["status"] != "CAPTURE_FINALIZED_UNREVIEWED"
            or receipt["hardware_fingerprint_sha256"] is None
            or Decimal(receipt["segments"][-1][
                "csv_end_pts_exclusive"]) < Decimal("5")):
        raise ValueError("successful_hardware_dry_run_receipt_required")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("named_dry_run_reviewer_required")
    _utc(signed_at_utc, "signed_at_utc")
    result = {
        "schema_version": 1,
        "status": "HARDWARE_DRY_RUN_SIGNED_OFF",
        "finalization_receipt_sha256": receipt_sha256,
        "session_id": receipt["session_id"],
        "authorization_sha256": receipt["authorization_sha256"],
        "plan_sha256": receipt["plan_sha256"],
        "source_recording_group_id": receipt["source_recording_group_id"],
        "hardware_fingerprint_sha256": receipt[
            "hardware_fingerprint_sha256"],
        "ffmpeg_contract_sha256": receipt["ffmpeg_contract_sha256"],
        "ffmpeg_binary_sha256": receipt["ffmpeg_binary_sha256"],
        "observed_device_sha256": receipt["observed_device_sha256"],
        "ordered_segment_manifest_sha256": receipt[
            "ordered_segment_manifest_sha256"],
        "source_integrity_status": receipt["source_integrity_status"],
        "capture_ended_at_utc": receipt["ended_at_utc"],
        "signed_off_by": reviewer,
        "signed_off_at_utc": signed_at_utc,
        "review_scope": "capture_integrity_and_privacy_only",
        "capture_only_reviewed": True,
        "strategy_authorized": False,
        "advice_authorized": False,
        "live_control_authorized": False,
    }
    validate_dry_run_signoff(result)
    return result


def _safe_segments(recording_root: Path, rows: list[list[str]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("nonempty_segment_manifest_required")
    expected, result, previous_end = set(), [], None
    for index, row in enumerate(rows):
        name = f"segment_{index:04d}.mkv"
        if len(row) != 3 or row[0] != name:
            raise ValueError("ordered_segment_names_required")
        try:
            start, end = Decimal(row[1]), Decimal(row[2])
        except InvalidOperation as exc:
            raise ValueError("finite_segment_timestamps_required") from exc
        if (not start.is_finite() or not end.is_finite() or start < 0
                or end <= start or index == 0 and start != 0):
            raise ValueError("finite_contiguous_segment_timestamps_required")
        gap = None if previous_end is None else start - previous_end
        if gap is not None and (gap < 0 or gap > Decimal("0.002")):
            raise ValueError("segment_gap_or_overlap_exceeds_two_ms")
        path = recording_root / name
        digest, size, mtime = _hash_file_snapshot(path, 20 * GIB)
        expected.add(name)
        result.append({
            "segment_index": index,
            "relative_path": name,
            "csv_start_pts": str(start),
            "csv_end_pts_exclusive": str(end),
            "csv_gap_seconds": None if gap is None else str(gap),
            "sha256": digest,
            "size_bytes": size,
            "mtime_ns": mtime,
        })
        previous_end = end
    actual = {path.name for path in recording_root.glob("segment_*.mkv")}
    if actual != expected:
        raise ValueError("segment_csv_and_file_set_must_match")
    return result


def _progress(raw: bytes) -> dict[str, int | str | None]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("strict_utf8_progress_required") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    def integer(key: str) -> int | None:
        value = values.get(key)
        if value is None:
            return None
        try:
            result = int(value)
        except ValueError as exc:
            raise ValueError("invalid_progress_" + key) from exc
        if result < 0:
            raise ValueError("invalid_progress_" + key)
        return result

    return {
        "frame": integer("frame"),
        "drop_frames": integer("drop_frames"),
        "dup_frames": integer("dup_frames"),
        "out_time": values.get("out_time"),
        "progress": values.get("progress"),
    }


def _out_time_seconds(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("ffmpeg_out_time_missing_or_invalid")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("ffmpeg_out_time_missing_or_invalid")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = Decimal(parts[2])
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("ffmpeg_out_time_missing_or_invalid") from exc
    if (hours < 0 or not 0 <= minutes < 60 or not seconds.is_finite()
            or not 0 <= seconds < 60):
        raise ValueError("ffmpeg_out_time_missing_or_invalid")
    return Decimal(hours * 3600 + minutes * 60) + seconds


def finalize_recording_metadata(
    recording_root: Path, plan: dict[str, Any], plan_sha256: str,
) -> dict[str, Any]:
    root = _plain_root(recording_root)
    authorization = plan["authorization"]
    expected_root = _plain_root(Path(authorization["output_root"]))
    if root.parent != expected_root or root.name != authorization["session_id"]:
        raise ValueError("recording_root_differs_from_authorized_session")
    snapshots = {}
    for role, name in (
        ("status", "status.json"), ("segments_csv", "segments.csv"),
        ("progress", "progress.log"), ("capture_log", "capture.log"),
    ):
        raw, digest = _read_snapshot(root / name)
        snapshots[role] = (raw, digest, (root / name).stat().st_size)
    authorization_use_path = (
        expected_root / ".aa-passive-capture-v1-authorizations"
        / (authorization["nonce"] + ".json"))
    authorization_use_raw, authorization_use_sha = _read_snapshot(
        authorization_use_path)
    authorization_use = _json(authorization_use_raw)
    _exact(authorization_use, AUTHORIZATION_USE_KEYS,
           "authorization_use_receipt")
    if (type(authorization_use["schema_version"]) is not int
            or authorization_use["schema_version"] != 1
            or authorization_use["status"]
            != "AUTHORIZATION_CONSUMED_NO_AUTOMATIC_RETRY"
            or authorization_use["authorization_sha256"]
            != plan["authorization_sha256"]
            or authorization_use["plan_sha256"] != plan_sha256
            or authorization_use["session_id"] != authorization["session_id"]
            or not isinstance(authorization_use["ffmpeg_path"], str)
            or not authorization_use["ffmpeg_path"]
            or not isinstance(authorization_use["ffmpeg_sha256"], str)
            or not HEX64.fullmatch(authorization_use["ffmpeg_sha256"])
            or type(authorization_use["ffmpeg_size_bytes"]) is not int
            or authorization_use["ffmpeg_size_bytes"] < 0
            or type(authorization_use["ffmpeg_mtime_ns"]) is not int
            or authorization_use["ffmpeg_mtime_ns"] < 0
            or authorization_use["ffmpeg_contract_sha256"]
            != _canonical_sha(plan["ffmpeg_contract"])
            or authorization_use["observed_device_sha256"]
            != _canonical_sha(authorization_use["observed_device"])):
        raise ValueError("authorization_use_receipt_disagrees_with_capture")
    _validate_device_probe(authorization_use["observed_device"])
    _utc(authorization_use["consumed_at_utc"], "consumed_at_utc")
    status = _json(snapshots["status"][0])
    try:
        csv_text = snapshots["segments_csv"][0].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("strict_utf8_segments_csv_required") from exc
    segments = _safe_segments(root, list(csv.reader(csv_text.splitlines())))
    progress = _progress(snapshots["progress"][0])
    metadata_files = [{
        "role": role,
        "relative_path": name,
        "sha256": snapshots[role][1],
        "size_bytes": snapshots[role][2],
    } for role, name in (
        ("status", "status.json"), ("segments_csv", "segments.csv"),
        ("progress", "progress.log"), ("capture_log", "capture.log"),
    )]
    failures = []
    expected_command_sha = _canonical_sha(_build_ffmpeg_command(
        root, authorization["requested_duration_seconds"],
        authorization_use["ffmpeg_path"],
        authorization_use["observed_device"]["dshow_input_name"]))
    required_status = {
        "state": "stopped",
        "exit_code": 0,
        "device": authorization["device"]["friendly_name"],
        "expected_platform": "AA_phone_8seat_unvalidated",
        "duration_limit_seconds": authorization["requested_duration_seconds"],
        "size_limit_bytes": authorization["limits"]["size_limit_bytes"],
        "minimum_free_bytes": authorization["limits"]["minimum_free_bytes"],
        "audio": False,
        "recognition_running": False,
        "strategy_running": False,
        "ffmpeg_path": authorization_use["ffmpeg_path"],
        "ffmpeg_sha256": authorization_use["ffmpeg_sha256"],
        "dshow_input_name": authorization_use[
            "observed_device"]["dshow_input_name"],
        "command_sha256": expected_command_sha,
    }
    for key, expected in required_status.items():
        if status.get(key) != expected or type(status.get(key)) is not type(expected):
            failures.append("recording_status_mismatch:" + key)
    if authorization_use["ffmpeg_path"] != "TEST_ONLY_INJECTED_RECORD_FUNCTION":
        try:
            binary_sha, binary_size, binary_mtime = _hash_file_snapshot(
                Path(authorization_use["ffmpeg_path"]), GIB)
            if (binary_sha != authorization_use["ffmpeg_sha256"]
                    or binary_size != authorization_use["ffmpeg_size_bytes"]
                    or binary_mtime != authorization_use["ffmpeg_mtime_ns"]):
                failures.append("ffmpeg_binary_changed_during_capture")
        except (OSError, ValueError):
            failures.append("ffmpeg_binary_unavailable_after_capture")
    stop_reason = status.get("stop_reason")
    allowed_stop_reasons = {
        "duration_or_source_end", "user_stop", "user_interrupt", "size_limit",
        "low_disk_space", "wall_clock_limit",
    }
    forced = (not isinstance(stop_reason, str)
              or "forced_termination" in stop_reason)
    if stop_reason not in allowed_stop_reasons:
        failures.append("capture_stop_reason_invalid_or_forced")
    if forced:
        failures.append("capture_was_forced_or_stop_reason_missing")
    if (type(status.get("segment_files")) is not int
            or status.get("segment_files") != len(segments)):
        failures.append("status_segment_count_differs_from_files")
    total_bytes = sum(item["size_bytes"] for item in segments)
    reported_bytes = status.get("recorded_bytes")
    if type(reported_bytes) is not int or reported_bytes != total_bytes:
        failures.append("status_recorded_bytes_differs_from_final_segments")
    if total_bytes > authorization["limits"]["size_limit_bytes"]:
        failures.append("final_segments_exceed_authorized_size_limit")
    final_pts = Decimal(segments[-1]["csv_end_pts_exclusive"])
    if final_pts > Decimal(authorization["requested_duration_seconds"]) + Decimal(
            "0.100"):
        failures.append("recording_pts_exceed_authorized_duration")
    try:
        progress_end = _out_time_seconds(progress["out_time"])
        if abs(progress_end - final_pts) > Decimal("0.100"):
            failures.append("ffmpeg_out_time_differs_from_segment_timeline")
        expected_frames = final_pts * Decimal("30")
        frame_error = abs(Decimal(progress["frame"] or 0) - expected_frames)
        if frame_error > max(Decimal("3"), expected_frames * Decimal("0.10")):
            failures.append("ffmpeg_frame_density_differs_from_30fps_timeline")
    except ValueError:
        failures.append("ffmpeg_out_time_missing_or_invalid")
    try:
        started = _utc(status.get("started_utc"), "started_utc")
        ended = _utc(status.get("ended_utc"), "ended_utc")
        if ended <= started:
            failures.append("capture_end_must_follow_start")
        authorized = _utc(
            authorization["authorized_at_utc"], "authorized_at_utc")
        expires = _utc(authorization["expires_at_utc"], "expires_at_utc")
        if started < authorized or ended > expires:
            failures.append("capture_time_outside_authorization_window")
        if ((ended - started).total_seconds()
                > authorization["requested_duration_seconds"]
                + authorization["limits"]["wall_clock_grace_seconds"] + 1):
            failures.append("recording_wall_time_exceeds_authorized_limit")
    except ValueError:
        failures.append("capture_start_or_end_time_invalid")
    if progress["frame"] is None or progress["frame"] <= 0:
        failures.append("ffmpeg_progress_has_no_positive_frame_count")
    if progress["drop_frames"] != 0:
        failures.append("ffmpeg_reported_dropped_frames")
    if progress["dup_frames"] != 0:
        failures.append("ffmpeg_reported_duplicated_frames")
    if progress["progress"] != "end":
        failures.append("ffmpeg_progress_did_not_reach_end")
    for role, name in (
        ("status", "status.json"), ("segments_csv", "segments.csv"),
        ("progress", "progress.log"), ("capture_log", "capture.log"),
    ):
        _, digest = _read_snapshot(root / name)
        if digest != snapshots[role][1]:
            raise ValueError("recording_metadata_changed_during_finalization:" + name)
    final_names = {path.name for path in root.glob("segment_*.mkv")}
    if final_names != {item["relative_path"] for item in segments}:
        raise ValueError("segment_file_set_changed_during_finalization")
    for item in segments:
        info = (root / item["relative_path"]).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or _is_reparse(info) or info.st_size != item["size_bytes"]
                or info.st_mtime_ns != item["mtime_ns"]):
            raise ValueError("segment_identity_changed_after_hash")
    _plain_root(root)
    clean = not failures
    blockers = list(plan["blockers_for_calibration"])
    if not clean:
        blockers = failures + blockers
    return {
        "schema_version": 1,
        "status": ("CAPTURE_FINALIZED_UNREVIEWED" if clean
                   else "FAILED_QUARANTINED"),
        "plan_sha256": plan_sha256,
        "authorization_sha256": plan["authorization_sha256"],
        "authorization_use_receipt_sha256": authorization_use_sha,
        "ordered_segment_manifest_sha256": _canonical_sha(segments),
        "hardware_fingerprint_sha256": authorization["device"][
            "hardware_fingerprint_sha256"],
        "ffmpeg_contract_sha256": _canonical_sha(plan["ffmpeg_contract"]),
        "ffmpeg_binary_sha256": authorization_use["ffmpeg_sha256"],
        "observed_device": authorization_use["observed_device"],
        "observed_device_sha256": authorization_use[
            "observed_device_sha256"],
        "session_id": authorization["session_id"],
        "phase": authorization["phase"],
        "source_recording_group_id": authorization[
            "source_recording_group_id"],
        "recording_root": root.as_posix(),
        "started_at_utc": status.get("started_utc"),
        "ended_at_utc": status.get("ended_utc"),
        "stop_reason": stop_reason,
        "exit_code": status.get("exit_code"),
        "forced_termination": forced,
        "metadata_files": metadata_files,
        "segments": segments,
        "progress": progress,
        "source_integrity_status": (
            "SEGMENT_BYTES_HASHED_NOT_DECODED" if clean
            else "FAILED_OR_PARTIAL_SEGMENTS_PRESERVED"),
        "source_partition": "UNASSIGNED_QUARANTINE",
        "blockers": blockers,
        "platform_verified": False,
        "rule_fingerprint": None,
        "identity_status": "UNKNOWN",
        "legal_menu_count": 0,
        "all_opportunities_reviewed": False,
        "special_modes": "UNKNOWN",
        "data_readiness": "BLOCKED",
        "ready_for_offline_review": False,
        "ready_for_calibration": False,
        "model_fit_executed": False,
        "strategy_eligible": False,
        "advice_emitted": False,
        "live_control": False,
        "human_signoff_required": True,
    }


def validate_finalization_receipt(value: Any) -> None:
    _exact(value, FINALIZATION_KEYS, "capture_finalization_receipt")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["status"] not in (
                "CAPTURE_FINALIZED_UNREVIEWED", "FAILED_QUARANTINED")
            or not isinstance(value["plan_sha256"], str)
            or not HEX64.fullmatch(value["plan_sha256"])
            or not isinstance(value["authorization_sha256"], str)
            or not HEX64.fullmatch(value["authorization_sha256"])
            or not isinstance(value["authorization_use_receipt_sha256"], str)
            or not HEX64.fullmatch(value[
                "authorization_use_receipt_sha256"])
            or not isinstance(value["ordered_segment_manifest_sha256"], str)
            or not HEX64.fullmatch(value[
                "ordered_segment_manifest_sha256"])
            or (value["hardware_fingerprint_sha256"] is not None
                and (not isinstance(value["hardware_fingerprint_sha256"], str)
                     or not HEX64.fullmatch(value[
                         "hardware_fingerprint_sha256"])))
            or not isinstance(value["ffmpeg_contract_sha256"], str)
            or not HEX64.fullmatch(value["ffmpeg_contract_sha256"])
            or value["ffmpeg_contract_sha256"]
            != _canonical_sha(FFMPEG_CONTRACT)
            or not isinstance(value["ffmpeg_binary_sha256"], str)
            or not HEX64.fullmatch(value["ffmpeg_binary_sha256"])
            or not isinstance(value["observed_device_sha256"], str)
            or not HEX64.fullmatch(value["observed_device_sha256"])
            or value["observed_device_sha256"]
            != _canonical_sha(value["observed_device"])
            or value["source_partition"] != "UNASSIGNED_QUARANTINE"
            or value["platform_verified"] is not False
            or value["rule_fingerprint"] is not None
            or value["identity_status"] != "UNKNOWN"
            or type(value["legal_menu_count"]) is not int
            or value["legal_menu_count"] != 0
            or value["all_opportunities_reviewed"] is not False
            or value["special_modes"] != "UNKNOWN"
            or value["data_readiness"] != "BLOCKED"
            or value["ready_for_offline_review"] is not False
            or value["ready_for_calibration"] is not False
            or value["model_fit_executed"] is not False
            or value["strategy_eligible"] is not False
            or value["advice_emitted"] is not False
            or value["live_control"] is not False
            or value["human_signoff_required"] is not True):
        raise ValueError("capture_receipt_cannot_promote_or_change_scope")
    _validate_device_probe(value["observed_device"])
    if (not isinstance(value["session_id"], str)
            or not SAFE_SESSION.fullmatch(value["session_id"])
            or value["phase"] not in ("hardware_dry_run", "development_capture")
            or not isinstance(value["source_recording_group_id"], str)
            or not SAFE_ID.fullmatch(value["source_recording_group_id"])
            or not isinstance(value["recording_root"], str)
            or not isinstance(value["metadata_files"], list)
            or not isinstance(value["segments"], list) or not value["segments"]
            or not isinstance(value["blockers"], list) or not value["blockers"]
            or len(value["blockers"]) != len(set(value["blockers"]))
            or any(not isinstance(item, str) or not item
                   for item in value["blockers"])
            or not set(CALIBRATION_BLOCKERS).issubset(value["blockers"])):
        raise ValueError("capture_receipt_identity_or_lists_invalid")
    base_blockers = set(CALIBRATION_BLOCKERS) | {
        "hardware_fingerprint_pending_dry_run"}
    receipt_blockers = set(value["blockers"])
    if not receipt_blockers.issubset(
            base_blockers | CAPTURE_FAILURE_BLOCKERS):
        raise ValueError("unknown_capture_failure_blocker")
    fingerprint_pending = "hardware_fingerprint_pending_dry_run" in value[
        "blockers"]
    if (value["hardware_fingerprint_sha256"] is None) != fingerprint_pending:
        raise ValueError("hardware_fingerprint_and_blocker_disagree")
    success = value["status"] == "CAPTURE_FINALIZED_UNREVIEWED"
    time_invalid = False
    time_order_invalid = False
    try:
        started = _utc(value["started_at_utc"], "started_at_utc")
        ended = _utc(value["ended_at_utc"], "ended_at_utc")
    except ValueError:
        time_invalid = True
        if success or "capture_start_or_end_time_invalid" not in value["blockers"]:
            raise
        started = ended = None
    if started is not None and ended <= started:
        time_order_invalid = True
        if success or "capture_end_must_follow_start" not in value["blockers"]:
            raise ValueError("capture_receipt_time_order_invalid")
    if type(value["forced_termination"]) is not bool:
        raise ValueError("capture_receipt_time_or_forced_status_invalid")
    roles = {}
    expected_metadata = {
        "status": "status.json", "segments_csv": "segments.csv",
        "progress": "progress.log", "capture_log": "capture.log",
    }
    for row in value["metadata_files"]:
        _exact(row, METADATA_FILE_KEYS, "capture_metadata_file")
        if (row["role"] in roles or expected_metadata.get(row["role"])
                != row["relative_path"]
                or not isinstance(row["sha256"], str)
                or not HEX64.fullmatch(row["sha256"])
                or type(row["size_bytes"]) is not int
                or row["size_bytes"] < 0):
            raise ValueError("capture_metadata_file_invalid")
        roles[row["role"]] = row
    if set(roles) != set(expected_metadata):
        raise ValueError("capture_metadata_file_roles_incomplete")
    previous_end = None
    for index, row in enumerate(value["segments"]):
        _exact(row, SEGMENT_KEYS, "capture_segment")
        if (type(row["segment_index"]) is not int
                or row["segment_index"] != index
                or row["relative_path"] != f"segment_{index:04d}.mkv"
                or not isinstance(row["sha256"], str)
                or not HEX64.fullmatch(row["sha256"])
                or type(row["size_bytes"]) is not int or row["size_bytes"] <= 0
                or type(row["mtime_ns"]) is not int or row["mtime_ns"] < 0):
            raise ValueError("capture_segment_identity_invalid")
        try:
            start = Decimal(row["csv_start_pts"])
            end = Decimal(row["csv_end_pts_exclusive"])
            gap = (None if row["csv_gap_seconds"] is None
                   else Decimal(row["csv_gap_seconds"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("capture_segment_pts_invalid") from exc
        if (not start.is_finite() or not end.is_finite() or start < 0
                or end <= start or index == 0 and (start != 0 or gap is not None)
                or index > 0 and (gap is None or gap < 0
                                  or gap > Decimal("0.002")
                                  or start - previous_end != gap)):
            raise ValueError("capture_segment_pts_invalid")
        previous_end = end
    if _canonical_sha(value["segments"]) != value[
            "ordered_segment_manifest_sha256"]:
        raise ValueError("ordered_segment_manifest_hash_mismatch")
    _exact(value["progress"], PROGRESS_KEYS, "capture_progress")
    progress_blockers = {
        "frame": "ffmpeg_progress_has_no_positive_frame_count",
        "drop_frames": "ffmpeg_reported_dropped_frames",
        "dup_frames": "ffmpeg_reported_duplicated_frames",
    }
    for key in ("frame", "drop_frames", "dup_frames"):
        count = value["progress"][key]
        if count is None:
            if success or progress_blockers[key] not in value["blockers"]:
                raise ValueError("capture_progress_counts_invalid")
        elif type(count) is not int or count < 0:
            raise ValueError("capture_progress_counts_invalid")
    final_pts = Decimal(value["segments"][-1]["csv_end_pts_exclusive"])
    out_time_invalid = False
    try:
        out_time_differs = abs(
            _out_time_seconds(value["progress"]["out_time"])
            - final_pts) > Decimal("0.100")
    except ValueError:
        out_time_invalid = True
        if (success or "ffmpeg_out_time_missing_or_invalid"
                not in value["blockers"]):
            raise
        out_time_differs = False
    if out_time_differs:
        if (success or "ffmpeg_out_time_differs_from_segment_timeline"
                not in value["blockers"]):
            raise ValueError("capture_progress_and_segment_timeline_disagree")
    density_differs = False
    if value["progress"]["frame"] is not None:
        expected_frames = final_pts * Decimal("30")
        density_differs = abs(
            Decimal(value["progress"]["frame"]) - expected_frames) > max(
                Decimal("3"), expected_frames * Decimal("0.10"))
        if density_differs:
            if (success or "ffmpeg_frame_density_differs_from_30fps_timeline"
                    not in value["blockers"]):
                raise ValueError(
                    "capture_frame_density_differs_from_30fps_timeline")
    if success and (
            value["source_integrity_status"]
            != "SEGMENT_BYTES_HASHED_NOT_DECODED"
            or value["forced_termination"] is not False
            or type(value["exit_code"]) is not int or value["exit_code"] != 0
            or value["progress"]["frame"] <= 0
            or value["progress"]["drop_frames"] != 0
            or value["progress"]["dup_frames"] != 0
            or value["progress"]["progress"] != "end"
            or value["stop_reason"] not in {
                "duration_or_source_end", "user_stop", "user_interrupt",
                "size_limit", "low_disk_space", "wall_clock_limit"}):
        raise ValueError("successful_capture_receipt_has_failed_quality")
    if not success and value["source_integrity_status"] != (
            "FAILED_OR_PARTIAL_SEGMENTS_PRESERVED"):
        raise ValueError("failed_capture_receipt_must_remain_quarantined")
    if not success:
        allowed_stop_reasons = {
            "duration_or_source_end", "user_stop", "user_interrupt",
            "size_limit", "low_disk_space", "wall_clock_limit",
        }
        progress = value["progress"]
        visible_conditions = {
            "capture_start_or_end_time_invalid": time_invalid,
            "capture_end_must_follow_start": time_order_invalid,
            "ffmpeg_out_time_missing_or_invalid": out_time_invalid,
            "ffmpeg_out_time_differs_from_segment_timeline": out_time_differs,
            "ffmpeg_frame_density_differs_from_30fps_timeline": density_differs,
            "ffmpeg_progress_has_no_positive_frame_count": (
                progress["frame"] is None or progress["frame"] <= 0),
            "ffmpeg_reported_dropped_frames": progress["drop_frames"] != 0,
            "ffmpeg_reported_duplicated_frames": progress["dup_frames"] != 0,
            "ffmpeg_progress_did_not_reach_end": progress["progress"] != "end",
            "capture_was_forced_or_stop_reason_missing": value[
                "forced_termination"],
            "capture_stop_reason_invalid_or_forced": value[
                "stop_reason"] not in allowed_stop_reasons,
            "recording_status_mismatch:exit_code": (
                type(value["exit_code"]) is not int or value["exit_code"] != 0),
        }
        for blocker, condition in visible_conditions.items():
            if condition != (blocker in value["blockers"]):
                raise ValueError("failed_capture_visible_blocker_mismatch:" + blocker)
        if not receipt_blockers & CAPTURE_FAILURE_BLOCKERS:
            raise ValueError("failed_capture_requires_specific_failure_blocker")
    elif receipt_blockers & CAPTURE_FAILURE_BLOCKERS:
        raise ValueError("successful_capture_cannot_contain_failure_blocker")


def verify_finalization_receipt_from_recording(
    receipt: dict[str, Any], plan: dict[str, Any], plan_sha256: str,
) -> None:
    validate_finalization_receipt(receipt)
    if receipt["plan_sha256"] != plan_sha256:
        raise ValueError("finalization_receipt_plan_hash_mismatch")
    rebuilt = finalize_recording_metadata(
        Path(receipt["recording_root"]), plan, plan_sha256)
    if rebuilt != receipt:
        raise ValueError("saved_finalization_receipt_differs_from_recording")


def _write_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _consume_authorization(
    private_root: Path, plan: dict[str, Any], plan_sha256: str,
    ffmpeg_identity: dict[str, Any], observed_device: dict[str, Any],
) -> Path:
    ledger = private_root / ".aa-passive-capture-v1-authorizations"
    if not ledger.exists():
        ledger.mkdir()
    info = ledger.lstat()
    if ledger.is_symlink() or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("authorization_ledger_must_be_plain_directory")
    target = ledger / (plan["authorization"]["nonce"] + ".json")
    _write_new(target, {
        "schema_version": 1,
        "status": "AUTHORIZATION_CONSUMED_NO_AUTOMATIC_RETRY",
        "authorization_sha256": plan["authorization_sha256"],
        "plan_sha256": plan_sha256,
        "session_id": plan["authorization"]["session_id"],
        "consumed_at_utc": datetime.now(timezone.utc).isoformat(),
        "ffmpeg_path": ffmpeg_identity["path"],
        "ffmpeg_sha256": ffmpeg_identity["sha256"],
        "ffmpeg_size_bytes": ffmpeg_identity["size_bytes"],
        "ffmpeg_mtime_ns": ffmpeg_identity["mtime_ns"],
        "ffmpeg_contract_sha256": _canonical_sha(plan["ffmpeg_contract"]),
        "observed_device": observed_device,
        "observed_device_sha256": _canonical_sha(observed_device),
    })
    return target


def _build_ffmpeg_command(
    output: Path, duration: int, ffmpeg_path: str, dshow_input_name: str,
) -> list[str]:
    return [
        ffmpeg_path, "-hide_banner", "-n", "-nostats", "-stats_period", "1",
        "-progress", str(output / "progress.log"), "-f", "dshow",
        "-rtbufsize", "256M", "-video_size", "1920x1080", "-framerate",
        "30", "-vcodec", "mjpeg", "-i", "video=" + dshow_input_name,
        "-map", "0:v:0", "-an", "-c:v", "copy", "-t", str(duration),
        "-f", "segment", "-segment_time", "60", "-reset_timestamps", "0",
        "-segment_list", str(output / "segments.csv"), "-segment_list_type",
        "csv", str(output / "segment_%04d.mkv"),
    ]


def _record_bounded(
    output: Path, duration: int, ffmpeg_identity: dict[str, Any],
    observed_device: dict[str, Any],
) -> None:
    output.mkdir(exist_ok=False)
    status = {
        "state": "starting",
        "recorder_pid": os.getpid(),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "device": "UGREEN 25854",
        "expected_platform": "AA_phone_8seat_unvalidated",
        "duration_limit_seconds": duration,
        "size_limit_bytes": 20 * GIB,
        "minimum_free_bytes": 20 * GIB,
        "audio": False,
        "recognition_running": False,
        "strategy_running": False,
        "codec": "original MJPEG packets; no additional video encoding",
        "timestamp_note": "container timestamps are not phone clock or latency",
        "ffmpeg_path": ffmpeg_identity["path"],
        "ffmpeg_sha256": ffmpeg_identity["sha256"],
        "dshow_input_name": observed_device["dshow_input_name"],
    }

    def write_status() -> None:
        temporary = output / "status.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(status, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output / "status.json")

    write_status()
    command = _build_ffmpeg_command(
        output, duration, ffmpeg_identity["path"],
        observed_device["dshow_input_name"])
    status["command_sha256"] = _canonical_sha(command)
    started = time.monotonic()
    with (output / "capture.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=log, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        status["capture_pid"] = process.pid
        reason = "duration_or_source_end"
        try:
            try:
                while process.poll() is None:
                    segments = list(output.glob("segment_*.mkv"))
                    size = sum(path.stat().st_size for path in segments)
                    status.update(
                        state="recording" if size else "starting",
                        recorded_bytes=size, segment_files=len(segments),
                        updated_utc=datetime.now(timezone.utc).isoformat())
                    write_status()
                    if (output / "STOP").exists():
                        reason = "user_stop"
                        break
                    if size >= status["size_limit_bytes"]:
                        reason = "size_limit"
                        break
                    if shutil.disk_usage(output.parent).free < status[
                            "minimum_free_bytes"]:
                        reason = "low_disk_space"
                        break
                    if time.monotonic() - started > duration + 20:
                        reason = "wall_clock_limit"
                        break
                    time.sleep(1)
            except KeyboardInterrupt:
                reason = "user_interrupt"
        finally:
            forced = False
            if process.poll() is None:
                try:
                    if process.stdin is None:
                        raise OSError("ffmpeg stdin unavailable")
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                    process.wait(timeout=15)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired,
                        KeyboardInterrupt):
                    process.kill()
                    process.wait()
                    forced = True
                    reason += "_forced_termination"
            if process.stdin is not None:
                process.stdin.close()
            segments = list(output.glob("segment_*.mkv"))
            final_size = sum(path.stat().st_size for path in segments)
            status.update(
                state="stopped" if process.returncode == 0 else "failed",
                stop_reason=reason, exit_code=process.returncode,
                forced_termination=forced, recorded_bytes=final_size,
                segment_files=len(segments),
                ended_utc=datetime.now(timezone.utc).isoformat())
            write_status()


def run_authorized_capture(
    plan_path: Path, expected_plan_sha256: str, authorization_path: Path,
    expected_authorization_sha256: str, *,
    private_root: Path = PRIVATE_ROOT,
    prior_hardware_receipt_path: Path | None = None,
    expected_prior_hardware_receipt_sha256: str | None = None,
    prior_dry_run_finalization_path: Path | None = None,
    expected_prior_dry_run_finalization_sha256: str | None = None,
    prior_dry_run_plan_path: Path | None = None,
    expected_prior_dry_run_plan_sha256: str | None = None,
    prior_dry_run_authorization_path: Path | None = None,
    expected_prior_dry_run_authorization_sha256: str | None = None,
    record_function: Callable[[Path, int], Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = _plain_root(private_root)
    plan_path = _direct_private_json(plan_path, root)
    authorization_path = _direct_private_json(authorization_path, root)
    if prior_hardware_receipt_path is not None:
        prior_hardware_receipt_path = _direct_private_json(
            prior_hardware_receipt_path, root)
    if prior_dry_run_finalization_path is not None:
        prior_dry_run_finalization_path = _private_session_receipt(
            prior_dry_run_finalization_path, root)
    if prior_dry_run_plan_path is not None:
        prior_dry_run_plan_path = _direct_private_json(
            prior_dry_run_plan_path, root)
    if prior_dry_run_authorization_path is not None:
        prior_dry_run_authorization_path = _direct_private_json(
            prior_dry_run_authorization_path, root)
    raw, actual_sha = _read_snapshot(plan_path)
    if actual_sha != expected_plan_sha256:
        raise ValueError("capture_plan_differs_from_external_sha256")
    plan = _json(raw)
    validate_plan(plan, actual_sha, private_root=root, now=now)
    authorization, authorization_sha = _load_bound(
        authorization_path, expected_authorization_sha256)
    if (authorization_sha != plan["authorization_sha256"]
            or authorization != plan["authorization"]):
        raise ValueError("capture_plan_and_authorization_source_disagree")
    if plan["authorization"]["phase"] == "development_capture":
        if (prior_hardware_receipt_path is None
                or expected_prior_hardware_receipt_sha256 is None
                or prior_dry_run_finalization_path is None
                or expected_prior_dry_run_finalization_sha256 is None
                or prior_dry_run_plan_path is None
                or expected_prior_dry_run_plan_sha256 is None
                or prior_dry_run_authorization_path is None
                or expected_prior_dry_run_authorization_sha256 is None):
            raise ValueError("signed_dry_run_source_required_at_capture_time")
        prior, prior_sha = _load_bound(
            prior_hardware_receipt_path,
            expected_prior_hardware_receipt_sha256)
        if (prior_sha != plan["prior_hardware_receipt_sha256"]
                or prior != plan["prior_hardware_receipt"]):
            raise ValueError("capture_plan_and_dry_run_source_disagree")
        finalization, finalization_sha = _load_private_session_receipt(
            prior_dry_run_finalization_path,
            expected_prior_dry_run_finalization_sha256, root)
        if (finalization_sha != plan["prior_dry_run_finalization_sha256"]
                or finalization != plan["prior_dry_run_finalization"]):
            raise ValueError("capture_plan_and_dry_run_finalization_disagree")
        dry_plan, dry_plan_sha = _load_bound(
            prior_dry_run_plan_path, expected_prior_dry_run_plan_sha256)
        dry_authorization, dry_authorization_sha = _load_bound(
            prior_dry_run_authorization_path,
            expected_prior_dry_run_authorization_sha256)
        if (dry_plan_sha != plan["prior_dry_run_plan_sha256"]
                or dry_plan != plan["prior_dry_run_plan"]
                or dry_authorization_sha
                != plan["prior_dry_run_authorization_sha256"]
                or dry_authorization != plan["prior_dry_run_authorization"]):
            raise ValueError("capture_plan_and_original_dry_run_sources_disagree")
    elif (prior_hardware_receipt_path is not None
          or expected_prior_hardware_receipt_sha256 is not None
          or prior_dry_run_finalization_path is not None
          or expected_prior_dry_run_finalization_sha256 is not None
          or prior_dry_run_plan_path is not None
          or expected_prior_dry_run_plan_sha256 is not None
          or prior_dry_run_authorization_path is not None
          or expected_prior_dry_run_authorization_sha256 is not None):
        raise ValueError("unexpected_dry_run_source_for_hardware_probe")
    authorization = plan["authorization"]
    target = root / authorization["session_id"]
    if target.exists():
        raise ValueError("capture_session_directory_must_be_new")
    if shutil.disk_usage(root).free < authorization["limits"][
            "minimum_start_free_bytes"]:
        raise ValueError("insufficient_free_space_before_capture")
    ffmpeg_identity = (
        _probe_ffmpeg_binary() if record_function is None else {
            "path": "TEST_ONLY_INJECTED_RECORD_FUNCTION",
            "sha256": _sha_bytes(b"TEST_ONLY_INJECTED_RECORD_FUNCTION"),
            "size_bytes": 0,
            "mtime_ns": 0,
        })
    observed_device = (
        _probe_windows_capture_device(ffmpeg_identity)
        if record_function is None
        else _device_probe_for_test(authorization))
    device = authorization["device"]
    if device["hardware_fingerprint_sha256"] is not None:
        comparisons = {
            "friendly_name": "friendly_name",
            "device_instance_id": "device_instance_id",
            "usb_vid_pid": "usb_vid_pid",
            "pnp_instance_suffix": "pnp_instance_suffix",
            "interface_number": "interface_number",
            "pnp_service": "pnp_service",
            "pnp_class": "pnp_class",
            "pnp_class_guid": "pnp_class_guid",
            "driver_device_id": "driver_device_id",
            "driver_version": "driver_version",
            "driver_provider": "driver_provider",
            "driver_inf": "driver_inf",
            "dshow_input_name": "dshow_input_name",
        }
        if any(device[declared] != observed_device[observed]
               for declared, observed in comparisons.items()):
            raise ValueError("observed_capture_device_differs_from_manifest")
    if (authorization["phase"] == "development_capture"
            and ffmpeg_identity["sha256"] != plan[
                "prior_hardware_receipt"]["ffmpeg_binary_sha256"]):
        raise ValueError("development_ffmpeg_binary_must_match_dry_run")
    if (authorization["phase"] == "development_capture"
            and _canonical_sha(observed_device) != plan[
                "prior_hardware_receipt"]["observed_device_sha256"]):
        raise ValueError("development_device_probe_must_match_dry_run")
    validate_authorization(
        authorization, private_root=root,
        now=now or datetime.now(timezone.utc))
    lock = root / ".aa-passive-capture-v1.device.lock"
    lock_descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    lock_identity = _identity(os.fstat(lock_descriptor))
    receipt = None
    try:
        os.write(lock_descriptor, (json.dumps({
            "pid": os.getpid(), "session_id": authorization["session_id"],
            "plan_sha256": actual_sha,
        }) + "\n").encode("utf-8"))
        os.fsync(lock_descriptor)
        lock_identity = _identity(os.fstat(lock_descriptor))
        _consume_authorization(
            root, plan, actual_sha, ffmpeg_identity, observed_device)
        if record_function is None:
            def record_function(output, duration):
                return _record_bounded(
                    output, duration, ffmpeg_identity, observed_device)
        try:
            record_function(target, authorization["requested_duration_seconds"])
        finally:
            if target.is_dir() and not (target / "intake-plan.json").exists():
                (target / "intake-plan.json").write_bytes(raw)
        receipt = finalize_recording_metadata(target, plan, actual_sha)
        _write_new(target / "capture-finalization-receipt.json", receipt)
        return receipt
    except (Exception, KeyboardInterrupt) as exc:
        if target.is_dir() and not (target / "capture-attempt-failure.json").exists():
            _write_new(target / "capture-attempt-failure.json", {
                "schema_version": 1,
                "status": "FAILED_QUARANTINED",
                "plan_sha256": actual_sha,
                "session_id": authorization["session_id"],
                "failure": type(exc).__name__ + ":" + str(exc),
                "automatic_retry": False,
                "files_deleted": False,
                "strategy_eligible": False,
                "advice_emitted": False,
                "live_control": False,
                "human_signoff_required": True,
            })
        raise
    finally:
        os.close(lock_descriptor)
        try:
            final_lock = lock.lstat()
            if (not lock.is_symlink() and not _is_reparse(final_lock)
                    and _identity(final_lock) == lock_identity):
                lock.unlink()
        except FileNotFoundError:
            pass


def _load_bound(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    raw, actual = _read_snapshot(path)
    if actual != expected_sha256:
        raise ValueError("metadata_differs_from_external_sha256")
    return _json(raw), actual


def _load_private_session_receipt(
    path: Path, expected_sha256: str, private_root: Path,
) -> tuple[dict[str, Any], str]:
    checked = _private_session_receipt(path, private_root)
    receipt, actual = _load_bound(checked, expected_sha256)
    if (receipt.get("session_id") != checked.parent.name
            or not isinstance(receipt.get("recording_root"), str)
            or Path(receipt["recording_root"]).resolve(strict=True)
            != checked.parent.resolve(strict=True)):
        raise ValueError("finalization_receipt_path_and_identity_disagree")
    return receipt, actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="create a passive capture plan only")
    plan.add_argument("--authorization", type=Path, required=True)
    plan.add_argument("--authorization-sha256", required=True)
    plan.add_argument("--prior-hardware-receipt", type=Path)
    plan.add_argument("--prior-hardware-receipt-sha256")
    plan.add_argument("--prior-dry-run-finalization", type=Path)
    plan.add_argument("--prior-dry-run-finalization-sha256")
    plan.add_argument("--prior-dry-run-plan", type=Path)
    plan.add_argument("--prior-dry-run-plan-sha256")
    plan.add_argument("--prior-dry-run-authorization", type=Path)
    plan.add_argument("--prior-dry-run-authorization-sha256")
    plan.add_argument("--output", type=Path, required=True)
    record = commands.add_parser("record", help="consume one plan and record once")
    record.add_argument("--plan", type=Path, required=True)
    record.add_argument("--plan-sha256", required=True)
    record.add_argument("--authorization", type=Path, required=True)
    record.add_argument("--authorization-sha256", required=True)
    record.add_argument("--prior-hardware-receipt", type=Path)
    record.add_argument("--prior-hardware-receipt-sha256")
    record.add_argument("--prior-dry-run-finalization", type=Path)
    record.add_argument("--prior-dry-run-finalization-sha256")
    record.add_argument("--prior-dry-run-plan", type=Path)
    record.add_argument("--prior-dry-run-plan-sha256")
    record.add_argument("--prior-dry-run-authorization", type=Path)
    record.add_argument("--prior-dry-run-authorization-sha256")
    signoff = commands.add_parser(
        "signoff-dry-run", help="record human signoff of a finalized dry run")
    signoff.add_argument("--receipt", type=Path, required=True)
    signoff.add_argument("--receipt-sha256", required=True)
    signoff.add_argument("--plan", type=Path, required=True)
    signoff.add_argument("--plan-sha256", required=True)
    signoff.add_argument("--reviewer", required=True)
    signoff.add_argument("--signed-at-utc", required=True)
    signoff.add_argument("--output", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="validate a final receipt")
    inspect.add_argument("--receipt", type=Path, required=True)
    inspect.add_argument("--receipt-sha256", required=True)
    inspect.add_argument("--plan", type=Path, required=True)
    inspect.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    try:
        root = _plain_root(PRIVATE_ROOT)
        if args.command == "plan":
            args.authorization = _direct_private_json(
                args.authorization, root)
            args.output = _direct_private_json(args.output, root, new=True)
            authorization, actual = _load_bound(
                args.authorization, args.authorization_sha256)
            optional_pairs = (
                (args.prior_hardware_receipt,
                 args.prior_hardware_receipt_sha256),
                (args.prior_dry_run_finalization,
                 args.prior_dry_run_finalization_sha256),
                (args.prior_dry_run_plan, args.prior_dry_run_plan_sha256),
                (args.prior_dry_run_authorization,
                 args.prior_dry_run_authorization_sha256),
            )
            if any((path is None) != (digest is None)
                   for path, digest in optional_pairs):
                raise ValueError("optional_source_and_sha256_must_be_paired")
            prior, prior_sha = None, None
            finalization, finalization_sha = None, None
            dry_plan, dry_plan_sha = None, None
            dry_authorization, dry_authorization_sha = None, None
            if args.prior_hardware_receipt is not None:
                args.prior_hardware_receipt = _direct_private_json(
                    args.prior_hardware_receipt, root)
                if args.prior_hardware_receipt_sha256 is None:
                    raise ValueError("prior_hardware_receipt_sha256_required")
                prior, prior_sha = _load_bound(
                    args.prior_hardware_receipt,
                    args.prior_hardware_receipt_sha256)
            if args.prior_dry_run_finalization is not None:
                args.prior_dry_run_finalization = _private_session_receipt(
                    args.prior_dry_run_finalization, root)
                if args.prior_dry_run_finalization_sha256 is None:
                    raise ValueError(
                        "prior_dry_run_finalization_sha256_required")
                finalization, finalization_sha = _load_private_session_receipt(
                    args.prior_dry_run_finalization,
                    args.prior_dry_run_finalization_sha256, root)
            if args.prior_dry_run_plan is not None:
                if args.prior_dry_run_plan_sha256 is None:
                    raise ValueError("prior_dry_run_plan_sha256_required")
                args.prior_dry_run_plan = _direct_private_json(
                    args.prior_dry_run_plan, root)
                dry_plan, dry_plan_sha = _load_bound(
                    args.prior_dry_run_plan,
                    args.prior_dry_run_plan_sha256)
            if args.prior_dry_run_authorization is not None:
                if args.prior_dry_run_authorization_sha256 is None:
                    raise ValueError(
                        "prior_dry_run_authorization_sha256_required")
                args.prior_dry_run_authorization = _direct_private_json(
                    args.prior_dry_run_authorization, root)
                dry_authorization, dry_authorization_sha = _load_bound(
                    args.prior_dry_run_authorization,
                    args.prior_dry_run_authorization_sha256)
            result = build_plan(
                authorization, actual, prior_hardware_receipt=prior,
                prior_hardware_receipt_sha256=prior_sha,
                prior_dry_run_finalization=finalization,
                prior_dry_run_finalization_sha256=finalization_sha,
                prior_dry_run_plan=dry_plan,
                prior_dry_run_plan_sha256=dry_plan_sha,
                prior_dry_run_authorization=dry_authorization,
                prior_dry_run_authorization_sha256=dry_authorization_sha)
            _write_new(args.output, result)
        elif args.command == "record":
            result = run_authorized_capture(
                args.plan, args.plan_sha256, args.authorization,
                args.authorization_sha256,
                prior_hardware_receipt_path=args.prior_hardware_receipt,
                expected_prior_hardware_receipt_sha256=(
                    args.prior_hardware_receipt_sha256),
                prior_dry_run_finalization_path=(
                    args.prior_dry_run_finalization),
                expected_prior_dry_run_finalization_sha256=(
                    args.prior_dry_run_finalization_sha256),
                prior_dry_run_plan_path=args.prior_dry_run_plan,
                expected_prior_dry_run_plan_sha256=(
                    args.prior_dry_run_plan_sha256),
                prior_dry_run_authorization_path=(
                    args.prior_dry_run_authorization),
                expected_prior_dry_run_authorization_sha256=(
                    args.prior_dry_run_authorization_sha256))
        elif args.command == "signoff-dry-run":
            args.receipt = _private_session_receipt(args.receipt, root)
            args.plan = _direct_private_json(args.plan, root)
            args.output = _direct_private_json(args.output, root, new=True)
            receipt, actual = _load_private_session_receipt(
                args.receipt, args.receipt_sha256, root)
            saved_plan, plan_sha = _load_bound(args.plan, args.plan_sha256)
            validate_plan(
                saved_plan, plan_sha,
                now=_utc(saved_plan["authorization"]["authorized_at_utc"],
                         "authorized_at_utc"))
            verify_finalization_receipt_from_recording(
                receipt, saved_plan, plan_sha)
            result = build_dry_run_signoff(
                receipt, actual, reviewer=args.reviewer,
                signed_at_utc=args.signed_at_utc)
            _write_new(args.output, result)
        else:
            args.receipt = _private_session_receipt(args.receipt, root)
            receipt, _ = _load_private_session_receipt(
                args.receipt, args.receipt_sha256, root)
            args.plan = _direct_private_json(args.plan, root)
            saved_plan, plan_sha = _load_bound(args.plan, args.plan_sha256)
            validate_plan(
                saved_plan, plan_sha,
                now=_utc(saved_plan["authorization"]["authorized_at_utc"],
                         "authorized_at_utc"))
            verify_finalization_receipt_from_recording(
                receipt, saved_plan, plan_sha)
            result = receipt
    except (OSError, ValueError, TypeError, ArithmeticError) as exc:
        parser.exit(2, "AA passive capture intake rejected: " + str(exc) + "\n")
    print(json.dumps({
        key: result[key] for key in result
        if key in ("status", "session_id", "capture_permitted",
                   "source_partition", "data_readiness", "blockers")
    }, ensure_ascii=False, indent=2))
    return 2 if result.get("status") == "FAILED_QUARANTINED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
