"""Preloaded, killable offline/shadow policy lookup; never a live-policy grant."""

from dataclasses import asdict
import hashlib
import json
import math
import multiprocessing
import threading
import time


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _lookup_worker(connection, policy):
    """A spawn child gets the frozen map only, no capture or network objects."""
    try:
        connection.send("READY")
        while True:
            request = connection.recv()
            if request is None:
                return
            request_key, information_key = request
            distribution = policy.get(information_key)
            if not distribution:
                connection.send((request_key, None))
                continue
            # Stable pseudo-random sampling by decision identity: retries and
            # child restarts cannot repeatedly roll the mixture's action.
            pick = int(request_key, 16) / (1 << 256)
            cumulative = 0.0
            action = None
            for candidate, probability in sorted(distribution.items()):
                cumulative += probability
                if pick < cumulative:
                    action = candidate
                    break
            connection.send((request_key, action))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


class AAIsolatedPolicyWorker:
    """Preload outside turn processing; one in-flight query, no waiting queue.

    This map interface is for offline/shadow experiments. Qualification,
    information encoding and rule/stack coverage remain the caller's duties.
    A timeout kills the process; it is not restarted during a turn.
    """

    def __init__(self, policy, *, seed=0):
        if type(seed) is not int or not isinstance(policy, dict):
            raise ValueError("policy mapping and integer seed required")
        self._policy = json.loads(_canonical(policy))
        for key, distribution in self._policy.items():
            if (not isinstance(key, str) or not key
                    or not isinstance(distribution, dict)):
                raise ValueError("invalid policy information key")
            invalid = any(
                not isinstance(action, str) or not action
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not math.isfinite(probability) or probability < 0
                for action, probability in distribution.items())
            if (not distribution or invalid
                    or not math.isclose(sum(distribution.values()), 1.0,
                                        rel_tol=0, abs_tol=1e-12)):
                raise ValueError("policy probabilities must sum to one")
        self.policy_sha256 = hashlib.sha256(_canonical(self._policy)).hexdigest()
        self.seed = seed
        self._process = self._connection = None
        self._lock = threading.Lock()
        self._ready = False

    def preload(self, *, startup_timeout=10):
        if self._process is not None:
            raise RuntimeError("worker already started; create a new worker")
        if not 0 < startup_timeout <= 30:
            raise ValueError("bounded startup timeout required")
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(target=_lookup_worker,
                                        args=(child, self._policy), daemon=True)
        self._process.start()
        child.close()
        try:
            self._ready = parent.poll(startup_timeout) and parent.recv() == "READY"
        except (EOFError, OSError):
            self._ready = False
        if not self._ready:
            self.close()
            raise RuntimeError("policy worker failed to preload")

    def _kill(self):
        self._ready = False
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
        if self._connection is not None:
            self._connection.close()

    def lookup(self, information_key, *, identity, state_key, rules_fingerprint,
               legal_actions, window, source_at, is_current, clock=time.monotonic):
        if not self._lock.acquire(blocking=False):
            return {"status": "ABSTAIN", "reason": "WORKER_BUSY", "action": None,
                    "strategy_eligible": False, "advice_emitted": False}
        try:
            return self._lookup(information_key, identity=identity, state_key=state_key,
                                rules_fingerprint=rules_fingerprint,
                                legal_actions=legal_actions, window=window,
                                source_at=source_at, is_current=is_current, clock=clock)
        finally:
            self._lock.release()

    def _lookup(self, information_key, *, identity, state_key, rules_fingerprint,
                legal_actions, window, source_at, is_current, clock):
        def abstain(reason):
            return {"status": "ABSTAIN", "reason": reason, "action": None,
                    "strategy_eligible": False, "advice_emitted": False}

        now = clock()
        reason = window.check(now=now, identity=identity, source_at=source_at)
        if reason != "WITHIN_BUDGET":
            return abstain(reason)
        if not self._ready:
            return abstain("WORKER_NOT_PRELOADED")
        if any(not isinstance(value, str) or not value or len(value) > 4096
               for value in (information_key, state_key, rules_fingerprint)):
            return abstain("MISSING_DECISION_IDENTITY")
        if (not isinstance(legal_actions, (tuple, list))
                or not 0 < len(legal_actions) <= 64
                or any(not isinstance(value, str) or not value or len(value) > 128
                       for value in legal_actions)):
            return abstain("INVALID_LEGAL_MENU")
        binding = {"turn": asdict(identity), "state": state_key,
                   "information": information_key, "rules": rules_fingerprint,
                   "policy": self.policy_sha256, "legal": sorted(legal_actions),
                   "seed": self.seed}
        request_key = hashlib.sha256(_canonical(binding)).hexdigest()
        deadline = now + window.computation_budget_seconds(
            now=now, identity=identity, source_at=source_at)
        try:
            self._connection.send((request_key, information_key))
            if not self._connection.poll(max(0, deadline - clock())):
                self._kill()
                return abstain("COMPUTATION_DEADLINE")
            received_key, action = self._connection.recv()
        except (EOFError, OSError):
            self._kill()
            return abstain("WORKER_FAILED")
        if clock() >= deadline:
            self._kill()
            return abstain("COMPUTATION_DEADLINE")
        if received_key != request_key:
            self._kill()
            return abstain("RESPONSE_IDENTITY_MISMATCH")
        if action is None:
            return abstain("POLICY_COVERAGE_MISS")
        # Caller owns its lock/state. Re-read rather than comparing a request
        # to its own copy after the process has finished.
        if not callable(is_current) or is_current(binding) is not True:
            return abstain("STATE_CHANGED")
        if clock() >= deadline:
            return abstain("COMPUTATION_DEADLINE")
        reason = window.record_first_result(now=clock(), identity=identity,
                                            source_at=source_at,
                                            legal=action in legal_actions)
        if reason != "WITHIN_BUDGET":
            return abstain(reason)
        return {"status": "SHADOW_RESULT", "action": action, "binding": binding,
                "request_key": request_key, "strategy_eligible": False,
                "advice_emitted": False}

    def close(self):
        self._kill()
        if self._process is not None:
            self._process.join(timeout=.2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=.2)
