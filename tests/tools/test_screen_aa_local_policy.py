"""Fake workers test transport/accounting only, never actual model evidence."""
import json
from pathlib import Path
import time
from types import SimpleNamespace

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

    def __init__(self, model, upstream):
        self.queries = []
        self.closed = False
        self.instances.append(self)

    def receive(self, seconds):
        assert 0 < seconds <= 120
        return {"status": "READY", "elapsed_ms": 0}

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
        assert client.queries[0][0] == client.queries[1][0] == client.queries[-1][0]
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
    context, questions, counts = screen.render_checked(FakeDecider(), request)
    assert json.loads(context) == {"state": request["state"], "rules": request["rules"]}
    assert questions[0]["question"] == request["question"]
    assert counts == {"context_tokens": 100, "prompt_tokens": 200}
    assert questions[0]["options"][0].startswith(request["options"][0]["id"] + ": ")
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
    write(directory / "config.json", {})
    config = screen.read_json(directory / "decider_config.json")
    config["temperature"] = 1.3
    write(directory / "decider_config.json", config)
    with pytest.raises(ValueError, match="configuration"):
        screen._check_config(directory, spec)


def hanging_fake_worker(connection, model, upstream):
    connection.send({"status": "READY"})
    connection.recv()
    time.sleep(60)


def test_actual_owned_process_is_terminated_on_external_timeout():
    client = screen.WorkerClient({}, {}, target=hanging_fake_worker)
    try:
        assert client.receive(10)["status"] == "READY"
        started = time.monotonic()
        assert client.query({"synthetic": True}, 0.05)["status"] == "TIMEOUT"
        assert time.monotonic() - started < 3
        assert not client.process.is_alive()
    finally:
        client.close()
