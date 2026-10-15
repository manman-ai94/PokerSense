"""Bounded manual river analysis in a disposable spawned process.

This facade never consumes capture frames or emits Advice. Its binding is an
opaque caller-owned revision receipt; the caller must cancel on input changes.
"""

from copy import deepcopy
import hashlib
import json
import math
import multiprocessing
import threading
import time
import uuid


MAX_INPUT_BYTES = 200_000
MAX_OUTPUT_BYTES = 2_000_000
MAX_BINDING_BYTES = 16_000


def _json_bytes(value, *, limit, name):
    def check(item, depth=0):
        if depth > 48:
            raise ValueError(f"{name}_nesting_limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError(f"{name}_requires_string_keys")
            for child in item.values():
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError(f"{name}_requires_plain_json_values")
    check(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, OverflowError) as exc:
        raise ValueError(f"{name}_invalid_json") from exc
    if len(raw) > limit:
        raise ValueError(f"{name}_byte_limit_exceeded")
    return raw


def _analysis_worker(sender, kind, document):
    """Fixed import paths and fixed compute caps; no file or command input."""
    try:
        if document.get("mode") != "manual_hypothesis":
            raise ValueError("explicit_manual_hypothesis_required")
        if kind == "terminal":
            from tools.analyze_terminal_multiway import scenario_from_dict, encode
            from poker_engine.strategy.terminal_multiway_v1 import (
                analyze_terminal_multiway,
            )
            value = analyze_terminal_multiway(
                scenario_from_dict(document), max_joint_assignments=4096)
        elif kind == "threeway":
            from tools.analyze_threeway_river import scenario_from_dict, encode
            from poker_engine.strategy.threeway_river_v1 import analyze_threeway_river
            value = analyze_threeway_river(
                scenario_from_dict(document), max_joint_assignments=128,
                max_nodes=20000)
        else:
            raise ValueError("unsupported_analysis_kind")
        result = encode(value)
        status = "BLOCKED" if value.status == "BLOCKED" else "COMPLETE"
        message = {"status": status, "error": None, "result": result}
        raw = _json_bytes(message, limit=MAX_OUTPUT_BYTES, name="analysis_output")
    except Exception as exc:
        raw = json.dumps({"status": "ERROR", "result": None,
                          "error": f"{type(exc).__name__}: {str(exc)[:500]}"},
                         ensure_ascii=True).encode("utf-8")
    try:
        sender.send_bytes(raw)
    finally:
        sender.close()


class AAConditionalAnalysis:
    """One manual analysis job, hard timeout, detached mutable input/output.

    ``_test_worker`` is a private trusted-code test hook. HTTP callers must only
    supply kind/document/binding and cannot select workers, limits or commands.
    """

    def __init__(self, timeout_seconds=10, max_input_bytes=MAX_INPUT_BYTES,
                 *, _test_worker=None):
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("positive_finite_timeout_required")
        if (type(max_input_bytes) is not int
                or not 1 <= max_input_bytes <= MAX_INPUT_BYTES):
            raise ValueError("input_limit_must_be_between_1_and_200000")
        if _test_worker is not None and not callable(_test_worker):
            raise TypeError("private_test_worker_must_be_callable")
        self._timeout = float(timeout_seconds)
        self._input_limit = max_input_bytes
        self._worker = _test_worker or _analysis_worker
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._process = self._timer = None
        self._revision = 0
        self._report = self._empty_report()

    def _empty_report(self):
        return {"status": "IDLE", "revision": self._revision, "id": None,
                "job_id": None, "kind": None, "input_sha256": None,
                "binding": {}, "manual_notlive": True, "strategy_eligible": False,
                "advice_emitted": False, "error": None, "result": None}

    def status(self):
        with self._lock:
            return deepcopy(self._report)

    def start(self, kind, document, *, binding):
        if kind not in ("terminal", "threeway"):
            raise ValueError("unsupported_analysis_kind")
        if type(document) is not dict or document.get("mode") != "manual_hypothesis":
            raise ValueError("explicit_manual_hypothesis_document_required")
        if type(binding) is not dict:
            raise ValueError("binding_must_be_json_object")
        raw = _json_bytes(document, limit=self._input_limit, name="analysis_input")
        bound = _json_bytes(binding, limit=MAX_BINDING_BYTES, name="analysis_binding")
        with self._lock:
            if (self._report["status"] == "RUNNING"
                    or self._process is not None and self._process.is_alive()):
                raise RuntimeError("analysis_already_running_or_stopping")
            self._revision += 1
            job_id = uuid.uuid4().hex
            self._report = {**self._empty_report(), "status": "RUNNING",
                            "id": job_id, "job_id": job_id, "kind": kind,
                            "input_sha256": hashlib.sha256(raw).hexdigest(),
                            "binding": json.loads(bound)}
            receiver, sender = self._context.Pipe(duplex=False)
            process = self._context.Process(
                target=self._worker, args=(sender, kind, json.loads(raw)),
                daemon=True, name="AA-manual-conditional-analysis")
            deadline = time.monotonic() + self._timeout
            self._process = process
            try:
                process.start()
            except Exception as exc:
                receiver.close()
                self._process = None
                self._set_terminal("ERROR", f"worker_start_failed:{type(exc).__name__}")
                return deepcopy(self._report)
            finally:
                sender.close()
            timer = threading.Timer(max(0, deadline - time.monotonic()),
                                    self._expire, args=(job_id, process))
            timer.daemon = True
            self._timer = timer
            timer.start()
            threading.Thread(target=self._watch, args=(
                job_id, process, receiver, deadline), daemon=True,
                name="AA-analysis-result-watch").start()
            return deepcopy(self._report)

    def _set_terminal(self, status, error, result=None):
        self._revision += 1
        self._report.update(status=status, revision=self._revision,
                            error=error, result=result)

    def _terminate(self, process):
        if process is None:
            return
        with self._process_lock:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.3)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.3)

    def _expire(self, job_id, process):
        with self._lock:
            if (self._report["job_id"] != job_id
                    or self._report["status"] != "RUNNING"):
                return
            self._set_terminal("TIMED_OUT", "analysis_deadline_exceeded")
        self._terminate(process)

    def cancel(self):
        with self._lock:
            process = self._process
            if self._timer is not None:
                self._timer.cancel()
            # Invalidate before termination so an in-flight result cannot publish.
            self._set_terminal("CANCELLED", "analysis_cancelled")
        self._terminate(process)
        return self.status()

    def _watch(self, job_id, process, receiver, deadline):
        try:
            self._collect(job_id, process, receiver, deadline)
        finally:
            self._terminate(process)

    def _collect(self, job_id, process, receiver, deadline):
        message = None
        failure = "analysis_worker_exited_without_result"
        try:
            while time.monotonic() < deadline:
                with self._lock:
                    if (self._report["job_id"] != job_id
                            or self._report["status"] != "RUNNING"):
                        return
                ready = receiver.poll(0.025)
                if not ready and not process.is_alive():
                    # The child may send and exit between poll() returning
                    # False and the liveness check. Drain its queued final
                    # message before treating the exit as an empty result.
                    ready = receiver.poll(0)
                    if not ready:
                        break
                if ready:
                    message = json.loads(receiver.recv_bytes(MAX_OUTPUT_BYTES))
                    self._validate_message(message)
                    break
        except (EOFError, OSError, ValueError, TypeError, UnicodeError) as exc:
            message = None
            failure = f"analysis_worker_protocol_error:{type(exc).__name__}"
        finally:
            receiver.close()
        with self._lock:
            if (self._report["job_id"] != job_id
                    or self._report["status"] != "RUNNING"):
                return
            if self._timer is not None:
                self._timer.cancel()
            timed_out = time.monotonic() >= deadline
            # Stop the worker and publish the end state under one lock, so a
            # caller never sees a dead worker whose job still reads RUNNING,
            # nor a finished job whose worker still blocks the next start.
            self._terminate(process)
            if timed_out:
                self._set_terminal("TIMED_OUT", "analysis_deadline_exceeded")
            elif message is None:
                self._set_terminal("ERROR", failure)
            else:
                self._set_terminal(message["status"], message["error"],
                                   message["result"])

    @staticmethod
    def _validate_message(message):
        if (type(message) is not dict or set(message) != {"status", "error", "result"}
                or message["status"] not in ("COMPLETE", "BLOCKED", "ERROR")
                or message["error"] is not None and type(message["error"]) is not str):
            raise ValueError("invalid_worker_envelope")
        result = message["result"]
        if message["status"] == "ERROR":
            if result is not None:
                raise ValueError("error_cannot_publish_partial_analysis")
        elif (type(result) is not dict or result.get("strategy_eligible") is not False
              or result.get("advice_emitted") is not False
              or result.get("status") not in (
                  "BLOCKED", "COMPLETE_CONDITIONAL", "COMPLETE_CONDITIONAL_ABSTRACTION")
              or (message["status"] == "BLOCKED") != (result["status"] == "BLOCKED")):
            raise ValueError("worker_result_cannot_authorize_live_advice")
