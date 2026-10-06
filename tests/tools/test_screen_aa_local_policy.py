"""Fake workers test transport/accounting only, never actual model evidence."""
from copy import deepcopy
from contextlib import contextmanager
import json
import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
import socket
import struct
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_frozen_policy import canonical_hash  # noqa: E402
from tools import screen_aa_local_policy as screen  # noqa: E402


def write(path, value):
    Path(path).write_text(json.dumps(value), encoding="utf-8")


def fixture_model(tmp_path, index):
    spec = screen.MODEL_SPECS[index]
    directory = tmp_path / str(index)
    directory.mkdir()
    for name in screen.MODEL_FILES:
        write(directory / name, {})
    write(directory / "config.json", {
        "architectures": ["Qwen3_5ForCausalLM"], "model_type": "qwen3_5_text"})
    write(directory / "tokenizer_config.json", {"tokenizer_class": "Qwen2Tokenizer"})
    write(directory / "source-metadata.json", {"sha": spec["revision"]})
    write(directory / "decider_config.json", {
        "version": spec["version"], "temperature": spec["temperature"],
        "neutralize_none": False, "schema_first": False,
    })
    return directory


@pytest.fixture
def frozen(tmp_path):
    left, right = (fixture_model(tmp_path, index) for index in (0, 1))
    output = tmp_path / "study"
    screen.freeze(output, left, right, tmp_path / "no-upstream")
    return output


def test_freeze_preserves_24_inputs_48_rows_and_expected_missing_weight_digest(frozen):
    manifest = screen.load_manifest(frozen)
    assert len(manifest["queries"]) == 24
    assert {q["development_seed"] for q in manifest["queries"]} == {8100000, 8100001}
    assert {q["street"] for q in manifest["queries"]} == {
        "preflop", "flop", "turn", "river"}
    for query in manifest["queries"]:
        assert query["request_sha256"] == canonical_hash(query["request"])
        assert "seed" not in json.dumps(query["request"])
        assert query["observation"]["simulation_only"] is True
        assert len(query["exact_key"]) == 64
    for model in manifest["models"]:
        assert model["files"]["model.safetensors"]["sha256"] == model["weights_sha256"]
    initial = screen.read_json(frozen / "results.json")
    assert initial["expected_queries"] == 48
    assert sum(len(model["queries"]) for model in initial["models"]) == 48
    assert all(row["status"] == "NOT_RUN" for model in initial["models"]
               for row in model["queries"])
    with pytest.raises(ValueError, match="new_output"):
        screen.freeze(frozen, "a", "b", "c")


def test_missing_models_stay_in_full_denominator_without_importing_torch(frozen):
    def forbidden(*args):
        pytest.fail("must not construct worker for missing assets")
    report = screen.run_screen(frozen, client_factory=forbidden)
    assert report["summary"]["status_counts"] == {"MODEL_NOT_READY": 48}
    assert report["summary"]["valid_fraction"] == 0
    assert report["summary"]["full_hand_executability"] == "NOT_ASSESSED"
    with pytest.raises(ValueError, match="already_started"):
        screen.run_screen(frozen, client_factory=forbidden)


class FakeClient:
    """Synthetic protocol response source; contains no model inference."""
    instances = []

    def __init__(self, model, upstream, runtime=None):
        self.queries = []
        self.closed = False
        self.ready = {"status": "READY",
                      **screen.expected_ready(model, upstream, runtime)}
        self.instances.append(self)

    def receive(self, seconds):
        assert 0 < seconds <= 120
        return {**self.ready, "elapsed_ms": 0}

    def query(self, query, seconds):
        self.queries.append((query["id"], seconds))
        return {"status": "VALID", "action": "check_call", "elapsed_ms": 400,
                "inference_ms": 390, "cached": False}

    def close(self):
        self.closed = True


def test_warmup_and_hard_deadline_are_separate_all_48_diagnostic_rows_count(frozen):
    FakeClient.instances.clear()
    report = screen.run_screen(frozen, client_factory=FakeClient,
                               asset_verifier=lambda *args: None)
    assert report["summary"]["status_counts"] == {"LATE_VALID": 48}
    assert report["summary"]["valid_fraction"] == 1
    assert report["summary"]["within_300ms_fraction"] == 0
    assert len(report["summary"]["all_opportunity_elapsed_ms"]) == 48
    for client, model in zip(FakeClient.instances, report["models"]):
        assert client.closed and len(client.queries) == 26
        assert client.queries[0][0] == client.queries[1][0]
        assert client.queries[-1][0] == "n8-min_raise_first-river"
        assert client.queries[0][1] == 10 and client.queries[-1][1] == 0.3
        assert model["warmup"]["included_in_denominator"] is False
        assert model["hard_deadline"]["status"] == "LATE_VALID"
        assert model["hard_deadline"]["included_in_denominator"] is False


def test_timeout_preserves_unexecuted_suffix_and_next_model(frozen):
    class TimeoutClient(FakeClient):
        def query(self, query, seconds):
            super().query(query, seconds)
            return {"status": "TIMEOUT", "elapsed_ms": 10000}
    report = screen.run_screen(frozen, client_factory=TimeoutClient,
                               asset_verifier=lambda *args: None)
    assert report["summary"]["status_counts"] == {"NOT_RUN": 48}
    for model in report["models"]:
        assert model["warmup"]["status"] == "TIMEOUT"
        assert model["hard_deadline"]["status"] == "NOT_RUN"
        assert all(row["reason"] for row in model["queries"])


def test_query_timeout_is_counted_separately_from_not_run_suffix(frozen):
    class QueryTimeoutClient(FakeClient):
        def query(self, query, seconds):
            value = super().query(query, seconds)
            return (value if len(self.queries) == 1 else
                    {"status": "TIMEOUT", "elapsed_ms": 10000})
    report = screen.run_screen(frozen, client_factory=QueryTimeoutClient,
                               asset_verifier=lambda *args: None)
    assert report["summary"]["status_counts"] == {"NOT_RUN": 46, "TIMEOUT": 2}


def test_load_failure_never_loses_planned_queries(frozen):
    class OomClient(FakeClient):
        def receive(self, seconds):
            return {"status": "OOM", "reason": "out of memory"}
    report = screen.run_screen(frozen, client_factory=OomClient,
                               asset_verifier=lambda *args: None)
    assert report["summary"]["status_counts"] == {"NOT_RUN": 48}
    assert all(model["load"]["status"] == "OOM" for model in report["models"])


def test_tampered_denominator_rejected_even_when_manifest_self_rehashed(frozen):
    path = frozen / "manifest.json"
    data = screen.read_json(path)
    data["queries"].pop()
    data.pop("sha256")
    data["sha256"] = canonical_hash(data)
    write(path, data)
    with pytest.raises(ValueError, match="protocol_mismatch"):
        screen.load_manifest(frozen)


def test_tampered_results_cannot_hide_missing_opportunities(frozen):
    path = frozen / "results.json"
    data = screen.read_json(path)
    data["models"][0]["queries"].pop()
    write(path, data)
    with pytest.raises(ValueError, match="already_started_or_mismatched"):
        screen.run_screen(frozen)


@pytest.mark.parametrize("value", [0, -1, 601, 1.5, True])
def test_whole_batch_budget_cannot_exceed_cap(frozen, value):
    with pytest.raises(ValueError, match="batch_budget"):
        screen.run_screen(frozen, batch_seconds=value)


class FakeDecider:
    def __init__(self, context_count=100, prompt_count=200, corrupt=False):
        self.m = SimpleNamespace(tok=SimpleNamespace(
            encode=lambda *args, **kwargs: list(range(context_count))))
        self.context_count = context_count
        self.prompt_count = prompt_count
        self.corrupt = corrupt

    def _decide_items(self, requests, max_ctx_tokens):
        assert max_ctx_tokens == 4096
        n = len(requests[0][1][0]["options"])
        ids = list(range(self.context_count))
        ids += [-1] * max(0, self.prompt_count - self.context_count)
        if self.corrupt:
            ids[0] = -2
        return requests, [{"ids": ids, "perms": [list(range(n))], "nopts": [n]}]


def test_render_checks_complete_context_and_prompt_without_truncation(frozen):
    request = screen.load_manifest(frozen)["queries"][0]["request"]
    fake = FakeDecider()
    items, counts = screen.render_checked(fake, request)
    assert counts["context_tokens"] == 100 and counts["prompt_tokens"] == 200
    assert counts["validated_prompt_ids_sha256"] == canonical_hash(items[0]["ids"])
    for fake, message in ((FakeDecider(context_count=4097), "CONTEXT_OVERFLOW"),
                          (FakeDecider(prompt_count=8193), "PROMPT_OVERFLOW"),
                          (FakeDecider(corrupt=True), "TRUNCATION")):
        with pytest.raises(ValueError, match=message):
            screen.render_checked(fake, request)


def test_config_refuses_remote_code_flags_and_wrong_temperature(tmp_path):
    directory = fixture_model(tmp_path, 0)
    spec = screen.MODEL_SPECS[0]
    screen._check_config(directory, spec)
    write(directory / "config.json", {"nested": {"auto_map": {}}})
    with pytest.raises(ValueError, match="remote_code"):
        screen._check_config(directory, spec)
    write(directory / "config.json", {
        "architectures": ["Qwen3_5ForCausalLM"], "model_type": "qwen3_5_text"})
    config = screen.read_json(directory / "decider_config.json")
    config["temperature"] = 1.3
    write(directory / "decider_config.json", config)
    with pytest.raises(ValueError, match="configuration"):
        screen._check_config(directory, spec)


def hanging_fake_worker(connection, model, upstream, runtime):
    connection.send({"status": "READY"})
    connection.recv()
    time.sleep(60)


def test_actual_owned_process_is_terminated_on_external_timeout():
    client = screen.WorkerClient({}, {}, target=hanging_fake_worker)
    try:
        assert client.receive(10)["status"] == "READY"
        started = time.perf_counter()
        assert client.query({"synthetic": True}, 0.05)["status"] == "TIMEOUT"
        assert time.perf_counter() - started < 3
        assert not client.process.is_alive()
    finally:
        client.close()


def unread_fake_worker(connection, model, upstream, runtime):
    connection.send({"status": "READY"})
    time.sleep(60)


def test_unread_pipe_serialization_and_large_send_have_one_external_deadline():
    client = screen.WorkerClient({}, {}, target=unread_fake_worker)
    try:
        assert client.receive(10)["status"] == "READY"
        result = client.query({"payload": b"x" * (8 * 1024 * 1024)}, 0.3)
        assert result["status"] == "TIMEOUT"
        assert 280 <= result["acceptance_stopped_ms"] < 750
        assert result["elapsed_ms"] < 1500
        assert result["cleanup_ms"] >= 0 and result["worker_terminated"]
        assert not result["transport_thread_alive"]
    finally:
        client.close()


def partial_response_worker(sock):
    connection = Connection(sock.detach())
    connection.send({"status": "READY"})
    connection.recv()
    # A genuine stream frame prefix arrives, then the body never completes.
    connection._send(struct.pack("!i", 1000000) + b"partial")
    time.sleep(60)


def test_partial_response_recv_is_bounded_not_just_poll():
    left, right = socket.socketpair()
    client = screen.WorkerClient.__new__(screen.WorkerClient)
    client.connection = Connection(left.detach())
    client._closed = False
    context = multiprocessing.get_context("spawn")
    client.process = context.Process(target=partial_response_worker, args=(right,))
    client.process.start()
    right.close()
    try:
        assert client.receive(10)["status"] == "READY"
        result = client.query({"synthetic": True}, 0.3)
        assert result["status"] == "TIMEOUT"
        assert 280 <= result["acceptance_stopped_ms"] < 750
        assert result["elapsed_ms"] < 1500 and result["worker_terminated"]
        assert not result["transport_thread_alive"]
    finally:
        client.close()


@pytest.mark.parametrize("change", ["pokerkit_version", "runtime", "source"])
def test_runtime_and_transitive_source_drift_rejected_after_self_rehash(frozen, change):
    path = frozen / "manifest.json"
    data = screen.read_json(path)
    assert "src/poker_engine/strategy/aa_frozen_policy.py" in data["source_sha256"]
    assert "tools/aa_policy_readiness_study.py" in data["source_sha256"]
    assert "tools/aa_full_hand_lab.py" in data["source_sha256"]
    assert "pyproject.toml" in data["source_sha256"]
    if change == "pokerkit_version":
        data["pokerkit_version"] = "WRONG_RUNTIME_VERSION"
    elif change == "runtime":
        data["runtime_identity"]["executable"]["sha256"] = "0" * 64
    else:
        data["source_sha256"]["tools/aa_full_hand_lab.py"] = "0" * 64
    data.pop("sha256")
    data["sha256"] = canonical_hash(data)
    write(path, data)
    with pytest.raises(ValueError, match="protocol_mismatch"):
        screen.load_manifest(frozen)


@pytest.mark.parametrize("name", [
    "adapter_config.json", "special_tokens_map.json", "added_tokens.json",
    "tokenizer.model", "bad.bin", "bad.pt", "bad.pickle",
])
def test_unregistered_model_files_refused_even_when_weights_missing(tmp_path, name):
    directory = fixture_model(tmp_path, 0)
    write(directory / name, {})
    with pytest.raises(ValueError, match="unregistered_model_files"):
        screen._manifest_model(directory, screen.MODEL_SPECS[0])


def test_runtime_records_dependency_versions_metadata_and_record_hashes():
    runtime = screen.runtime_identity()
    assert runtime["python_version"] == sys.version
    assert len(runtime["executable"]["sha256"]) == 64
    for key in ("METADATA", "RECORD", "module"):
        assert len(runtime["packages"]["pokerkit"][key]["sha256"]) == 64
    assert set(runtime["packages"]) == set(screen.RUNTIME_PACKAGES)


def test_ready_must_match_actual_loaded_modules_paths_runtime_and_dtype(frozen):
    manifest = screen.load_manifest(frozen)
    model, upstream, runtime = (manifest["models"][0], manifest["upstream"],
                                manifest["runtime_identity"])
    expected = screen.expected_ready(model, upstream, runtime)
    screen.validate_ready(expected, model, upstream, runtime)
    for key, value in (("dtype", "torch.float32"), ("tokenizer_name_or_path", "remote"),
                       ("runtime_identity", {}), ("upstream_modules", {})):
        changed = deepcopy(expected)
        changed[key] = value
        with pytest.raises(ValueError, match="worker_identity"):
            screen.validate_ready(changed, model, upstream, runtime)


@pytest.mark.parametrize("corrupt", [False, True])
def test_scoring_uses_exact_verified_items_once_under_no_grad(monkeypatch, corrupt):
    """Pure tensor stand-ins verify data flow, not CUDA or model performance."""
    state = {"no_grad": False, "forward_calls": 0}
    items = [{"ids": [11, 12, 13], "nopts": [2], "types": ["choice"]}]

    class Tensor:
        def __init__(self, value):
            self.value = value

        def tolist(self):
            return deepcopy(self.value)

        def to(self, device):
            assert device == "cuda"
            return self

        def cpu(self):
            return self

    @contextmanager
    def no_grad():
        state["no_grad"] = True
        yield
        state["no_grad"] = False

    def collate(received, pad):
        assert received is items and pad == 0 and state["no_grad"]
        return {"input_ids": Tensor([[99 if corrupt else 11, 12, 13, 0]]),
                "attention_mask": Tensor([[1, 1, 1, 0]]),
                "slot_idx": Tensor([2]), "slot_batch": Tensor([0]),
                "nopts": Tensor([2])}

    def slot_logits(*args):
        assert state["no_grad"]
        assert args[0].tolist() == [[11, 12, 13, 0]]
        state["forward_calls"] += 1
        return Tensor([[1, 2]])

    temperatures = SimpleNamespace(
        for_items=lambda temperature, by_type, received: temperature,
        slot_temperatures=lambda temperature, received: temperature,
        scaled_softmax=lambda logits, temperature: Tensor([[0.25, 0.75]]))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=no_grad))
    monkeypatch.setitem(sys.modules, "decider",
                        SimpleNamespace(temperature=temperatures))
    monkeypatch.setitem(sys.modules, "decider.model", SimpleNamespace(collate=collate))
    decider = SimpleNamespace(T=1.03, T_by_type={}, dev="cuda", m=SimpleNamespace(
        tok=SimpleNamespace(pad_token_id=0), slot_logits=slot_logits))
    if corrupt:
        with pytest.raises(ValueError, match="forward_input"):
            screen.score_verified_items(decider, items)
        assert state["forward_calls"] == 0
    else:
        scores, receipt = screen.score_verified_items(decider, items)
        assert scores == [0.25, 0.75] and state["forward_calls"] == 1
        assert receipt["attention_valid_tokens"] == 3
        assert receipt["forward_input_ids_sha256"] == canonical_hash([[11, 12, 13, 0]])


@pytest.mark.parametrize("index", (0, 1))
def test_loaded_config_accepts_upstream_empty_temperature_map_only(index):
    spec = screen.MODEL_SPECS[index]
    values = {"layout": "plain", "schema_first": False, "neutralize_none": False,
              "T": spec["temperature"], "T_by_type": {}}
    screen.validate_loaded_config(SimpleNamespace(**values), spec)
    for field, value in (("T_by_type", None), ("T_by_type", {"choice": 1.03}),
                         ("T_by_type", []), ("layout", "chat"),
                         ("T", 1.04), ("schema_first", True),
                         ("neutralize_none", True)):
        changed = {**values, field: value}
        with pytest.raises(ValueError, match="loaded_model_configuration_mismatch"):
            screen.validate_loaded_config(SimpleNamespace(**changed), spec)


@pytest.mark.parametrize("index", (0, 1))
@pytest.mark.parametrize("temperature_map", ({}, None))
def test_actual_worker_constructor_and_ready_chain_use_upstream_map_semantics(
        tmp_path, monkeypatch, index, temperature_map):
    """Stub weights/runtime; actual worker, guard and READY execute, no forward."""
    directory = fixture_model(tmp_path, index)
    model = screen._manifest_model(directory, screen.MODEL_SPECS[index])
    upstream_dir = tmp_path / "stub-upstream"
    (upstream_dir / "decider").mkdir(parents=True)
    upstream = {"directory": str(upstream_dir), "files": {}}
    for name in screen.UPSTREAM_FILES:
        if not name.endswith(".py"):
            continue
        path = upstream_dir / name
        path.write_text("# Stub source identity, not a model implementation.\n")
        upstream["files"][name] = screen._sha(path)
        module_name = ("decider" if name.endswith("__init__.py") else
                       name[:-3].replace("/", "."))
        module = ModuleType(module_name)
        module.__file__ = str(path)
        monkeypatch.setitem(sys.modules, module_name, module)
    runtime = {"packages": {}, "clock": screen.clock_identity()}
    for name in ("torch", "transformers"):
        path = tmp_path / (name + "-stub.py")
        path.write_text("# Stub runtime identity only.\n")
        module = ModuleType(name)
        module.__file__ = str(path)
        module.__version__ = "stub-test-only"
        runtime["packages"][name] = {
            "version": module.__version__, "module": screen._file_receipt(path)}
        monkeypatch.setitem(sys.modules, name, module)
    calls = []
    sys.modules["torch"].bfloat16 = "torch.bfloat16"
    sys.modules["torch"].cuda = SimpleNamespace(
        synchronize=lambda: calls.append("sync"))
    tokenizer = type("Qwen2Tokenizer", (), {})()
    tokenizer.name_or_path = str(directory)
    loaded_model = type("Qwen3_5ForCausalLM", (), {})()
    loaded_model.name_or_path = str(directory)
    loaded_model.parameters = lambda: iter([SimpleNamespace(dtype="torch.bfloat16")])
    loaded_model.config = SimpleNamespace(
        model_type="qwen3_5_text", architectures=["Qwen3_5ForCausalLM"])

    def constructor(path, **kwargs):
        assert path == str(directory)
        assert kwargs == {"device": "cuda", "dtype": "torch.bfloat16",
                          "use_graphs": False}
        calls.append("construct")
        return SimpleNamespace(
            layout="plain", schema_first=False, neutralize_none=False,
            T=model["temperature"], T_by_type=temperature_map, dev="cuda",
            m=SimpleNamespace(tok=tokenizer, lm=loaded_model))

    sys.modules["decider.infer"].Decider = constructor
    monkeypatch.setattr(screen, "_require_runtime", lambda expected: expected)
    monkeypatch.setattr(screen, "verify_assets", lambda *args: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
                "DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        monkeypatch.delenv(key, raising=False)
    responses = []

    def receive():
        calls.append("receive-stop")
        return None

    connection = SimpleNamespace(send=responses.append, recv=receive)
    screen.model_worker(connection, model, upstream, runtime)
    assert len(responses) == 1
    if temperature_map == {}:
        assert responses[0]["status"] == "READY"
        screen.validate_ready(responses[0], model, upstream, runtime)
        assert calls == ["construct", "sync", "receive-stop"]
    else:
        assert responses[0]["status"] == "ERROR"
        assert responses[0]["reason"] == "loaded_model_configuration_mismatch"
        assert calls == ["construct"]


@pytest.mark.parametrize("finish,expected", [(0.2999, "VALID"), (0.3001, "TIMEOUT")])
def test_deadline_uses_high_resolution_clock_for_transport_and_parent(
        monkeypatch, finish, expected):
    # Both real times quantize to 296.875ms on a 15.625ms coarse timer. They
    # must nevertheless fall on opposite sides of the fixed 300ms deadline.
    assert int(0.2999 * 64) / 64 == int(0.3001 * 64) / 64 == 0.296875
    clock = {"now": 0.0, "phase": "parent", "reads": [], "coarse_reads": 0}

    def high_resolution():
        clock["reads"].append(clock["phase"])
        return clock["now"]

    def coarse():
        clock["coarse_reads"] += 1
        return int(clock["now"] * 64) / 64

    class ImmediateThread:
        def __init__(self, target, daemon):
            assert daemon
            self.target = target

        def start(self):
            clock["phase"] = "transport"
            self.target()
            clock["phase"] = "parent"

        def join(self, timeout):
            pass

        def is_alive(self):
            return False

    def receive():
        clock["now"] = finish
        return {"status": "VALID"}

    def cleanup():
        clock["now"] += 0.005

    monkeypatch.setattr(screen.time, "perf_counter", high_resolution)
    monkeypatch.setattr(screen.time, "monotonic", coarse)
    monkeypatch.setattr(screen.threading, "Thread", ImmediateThread)
    client = screen.WorkerClient.__new__(screen.WorkerClient)
    client.connection = SimpleNamespace(send=lambda value: None, recv=receive)
    client.process = SimpleNamespace(is_alive=lambda: False)
    client.close = cleanup
    response = client.query({"synthetic": True}, 0.3)
    assert response["status"] == expected
    assert "transport" in clock["reads"] and "parent" in clock["reads"]
    assert clock["coarse_reads"] == 0
    if expected == "TIMEOUT":
        assert response["acceptance_stopped_ms"] == pytest.approx(300.1)
        assert response["cleanup_ms"] == pytest.approx(5.0)
        assert response["elapsed_ms"] == pytest.approx(305.1)
    else:
        assert response["elapsed_ms"] == pytest.approx(299.9)


def test_frozen_and_ready_clock_identity_refuse_clock_drift(frozen):
    manifest = screen.load_manifest(frozen)
    assert manifest["clock"] == manifest["runtime_identity"]["clock"]
    assert manifest["clock"] == screen.clock_identity()
    model, upstream, runtime = (manifest["models"][0], manifest["upstream"],
                                manifest["runtime_identity"])
    ready = screen.expected_ready(model, upstream, runtime)
    ready["clock"] = {**ready["clock"], "implementation": "coarse_clock"}
    with pytest.raises(ValueError, match="worker_identity"):
        screen.validate_ready(ready, model, upstream, runtime)
    manifest["clock"]["resolution"] = 0.015625
    manifest.pop("sha256")
    manifest["sha256"] = canonical_hash(manifest)
    write(frozen / "manifest.json", manifest)
    with pytest.raises(ValueError, match="protocol_mismatch"):
        screen.load_manifest(frozen)


def test_coarse_or_adjustable_perf_counter_is_refused(monkeypatch):
    cases = ((0.015625, True, False), (0.0000001, False, False),
             (0.0000001, True, True))
    for resolution, monotonic, adjustable in cases:
        monkeypatch.setattr(screen.time, "get_clock_info", lambda name: SimpleNamespace(
            implementation="fake", resolution=resolution,
            monotonic=monotonic, adjustable=adjustable))
        with pytest.raises(ValueError, match="high_resolution_monotonic_clock"):
            screen.clock_identity()


def test_supervisor_reports_high_resolution_elapsed_and_labels_helper_clock(
        tmp_path, monkeypatch):
    ticks = iter((10.0, 10.1234))
    monkeypatch.setattr(screen.time, "perf_counter", lambda: next(ticks))

    def fake_bounded(command, *, seconds, cwd, log_path):
        assert seconds == 590
        return {"status": "EXITED", "returncode": 0, "elapsed_seconds": 0.109375}

    monkeypatch.setattr(screen, "run_bounded", fake_bounded)
    result = screen.supervised_run(tmp_path, 600)
    assert result["elapsed_seconds"] == pytest.approx(0.1234)
    assert result["helper_elapsed_seconds"] == 0.109375
    assert result["clock"]["name"] == "perf_counter"
    assert result["helper_elapsed_clock"] == "monotonic_in_reused_run_bounded"
