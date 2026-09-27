"""Bounded synthetic local-model input/latency screen, not poker qualification.

No downloads, training, live state, profitability or full-hand model play. Torch
and transformers are lazy imports confined to an externally supervised worker.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

from poker_engine.strategy.aa_external_local_policy import (
    ExternalLocalResearchPolicy, REQUEST_FORMAT, select_action,
)
from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_policy_encoding_v2 import encode_decision_v2
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools.aa_full_hand_lab import DEFAULT_RULES, read_json, rules_for
from tools.aa_policy_readiness_study import run_bounded


ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_SEEDS = (8100000, 8100001)
CONTEXT_CAP, PROMPT_CAP, MAX_BATCH_SECONDS = 4096, 8192, 600
MODEL_SPECS = (
    {"id": "Mapika/decider-0.8b",
     "revision": "a0a01d6f8135298f400a8c856b355793012ae971",
     "version": "0.8b-v1", "temperature": 1.03,
     "weights_sha256": (
         "6926f82ef7e9ea408ad881555204daa6bb694ca82509c4d1514b7be2e713563d"),
     "weights_size": 1504827608},
    {"id": "Mapika/decider-2b",
     "revision": "d61c1c16089572df5d180329b9fea4997a90090c",
     "version": "v10", "temperature": 1.30,
     "weights_sha256": (
         "1bf79b6aa6966a0faf930940799b1f54a831368d9738123722d483597c0ac2e7"),
     "weights_size": 3763692048},
)
UPSTREAM_COMMIT = "a5120cce45b9ff70964fac54ea6e8c1ac5b08c7f"
UPSTREAM_FILES = {
    "decider/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "decider/infer.py": (
        "6359e5989fe922054c99446115a25d22acf1a943f0dea097409eaa49e2ef84f1"),
    "decider/model.py": (
        "2feae466895e84b7637ee3504522d809d88dded0b290f6c87b071e4b7f43e027"),
    "decider/prompt.py": (
        "f21ae1016a11ca3500b5a8e2e8c3ef524434d196bbd4891199b96a33b3ad6314"),
    "decider/temperature.py": (
        "1b88c270b788a21b01dd31803dadfcc3a61ba0246576c1de04881b1db10a8735"),
}
MODEL_FILES = ("config.json", "decider_config.json", "tokenizer_config.json",
               "tokenizer.json", "generation_config.json", "chat_template.jinja",
               "source-metadata.json")


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic(path, value):
    path = Path(path)
    pending = path.with_suffix(".pending.json")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True,
                  indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def _contains_auto_map(value):
    if isinstance(value, dict):
        return "auto_map" in value or any(_contains_auto_map(v) for v in value.values())
    return isinstance(value, list) and any(_contains_auto_map(v) for v in value)


def _check_config(directory, spec):
    directory = Path(directory)
    config = read_json(directory / "config.json")
    tokenizer = read_json(directory / "tokenizer_config.json")
    cfg = read_json(directory / "decider_config.json")
    if any(_contains_auto_map(value) for value in (config, tokenizer, cfg)):
        raise ValueError("auto_map_remote_code_refused")
    if (cfg.get("version") != spec["version"]
            or cfg.get("temperature") != spec["temperature"]
            or cfg.get("schema_first") is not False
            or cfg.get("neutralize_none") is not False
            or cfg.get("layout", "plain") != "plain"
            or cfg.get("chat_template", False) is not False
            or cfg.get("temperature_by_type") is not None):
        raise ValueError("unfrozen_decider_configuration")


def _manifest_model(directory, spec):
    directory = Path(directory).resolve()
    files = {}
    for name in MODEL_FILES:
        path = directory / name
        files[name] = ({"sha256": _sha(path), "size": path.stat().st_size}
                       if path.is_file() else None)
    metadata = directory / "source-metadata.json"
    if metadata.is_file() and read_json(metadata).get("sha") != spec["revision"]:
        raise ValueError("model_revision_mismatch")
    files["model.safetensors"] = {
        "sha256": spec["weights_sha256"], "size": spec["weights_size"]}
    return {**spec, "directory": str(directory), "files": files}


def _source_hashes():
    names = ["tools/screen_aa_local_policy.py",
             "src/poker_engine/strategy/aa_external_local_policy.py",
             "src/poker_engine/strategy/aa_policy_encoding_v2.py",
             "src/poker_engine/strategy/aa_full_hand_arena.py",
             "src/poker_engine/strategy/aa_rules_v2.py"]
    return {name: _sha(ROOT / name) for name in names}


def frozen_queries():
    queries = []
    for count in (6, 7, 8):
        rules = rules_for(DEFAULT_RULES, count)
        adapter = ExternalLocalResearchPolicy(
            rules, lambda request: None, model_id="input-contract-only",
            model_revision="no-model-inference")
        for path_index, path_name in enumerate(("check_call", "min_raise_first")):
            seed = DEVELOPMENT_SEEDS[path_index]
            arena = AAFullHandArena(rules).reset(seed)
            seen = set()
            for index in range(1000):
                if arena.terminal:
                    break
                obs = arena.observe(arena.actor)
                if arena.street not in seen:
                    request = adapter.prepare_request(obs)
                    queries.append({
                        "id": f"n{count}-{path_name}-{arena.street}",
                        "table_size": count, "path": path_name, "street": arena.street,
                        "development_seed": seed, "action_index": index,
                        "observation": obs, "request": request,
                        "exact_key": encode_decision_v2(obs)["exact_key"],
                        "request_sha256": canonical_hash(request),
                    })
                    seen.add(arena.street)
                action = "check_call"
                if index == 0 and path_name == "min_raise_first":
                    action = next(a.id for a in arena.legal_actions()
                                  if a.kind == "raise_to")
                arena.step(action)
            if seen != {"preflop", "flop", "turn", "river"}:
                raise ValueError("development_query_schedule_incomplete")
    if len(queries) != 24:
        raise ValueError("development_query_denominator_mismatch")
    return queries


def initial_results(manifest):
    return {
        "manifest_sha256": manifest["sha256"], "started": False,
        "evidence": "SYNTHETIC_INPUT_LATENCY_SCREEN_NOT_FULL_HAND_PLAY",
        "strategy_eligible": False, "profitability": "NOT_ASSESSED",
        "expected_queries": 48, "models": [{
            "id": model["id"], "load": {"status": "NOT_RUN"},
            "warmup": {"status": "NOT_RUN", "included_in_denominator": False},
            "hard_deadline": {"status": "NOT_RUN", "budget_ms": 300,
                              "included_in_denominator": False},
            "queries": [{"id": query["id"], "status": "NOT_RUN", "action": None,
                         "elapsed_ms": None, "reason": None}
                        for query in manifest["queries"]],
        } for model in manifest["models"]],
    }


def freeze(output, model_08b, model_2b, upstream_package):
    output = Path(output)
    if output.exists():
        raise ValueError("freeze_requires_new_output_directory")
    queries = frozen_queries()
    manifest = {
        "schema_version": 1, "kind": "AA_LOCAL_FEASIBILITY_SCREEN_V1",
        "request_format": REQUEST_FORMAT, "context_cap": CONTEXT_CAP,
        "prompt_cap": PROMPT_CAP, "batch_cap_seconds": MAX_BATCH_SECONDS,
        "query_timeout_seconds": 10, "warmup_timeout_seconds": 10,
        "load_timeout_seconds": 120, "hard_deadline_seconds": 0.3,
        "seeds": list(DEVELOPMENT_SEEDS), "sample_kind": "DEVELOPMENT_ONLY",
        "option_rendering": "id: text", "queries": queries,
        "models": [_manifest_model(path, spec) for path, spec in
                   zip((model_08b, model_2b), MODEL_SPECS)],
        "upstream": {"directory": str(Path(upstream_package).resolve()),
                     "commit": UPSTREAM_COMMIT, "files": UPSTREAM_FILES},
        "source_sha256": _source_hashes(), "expected_queries": 48,
        "pokerkit_version": importlib.metadata.version("pokerkit"),
        "strategy_eligible": False, "advice_emitted": False,
    }
    manifest["sha256"] = canonical_hash(manifest)
    output.mkdir(parents=True)
    _atomic(output / "manifest.json", manifest)
    _atomic(output / "results.json", initial_results(manifest))
    return manifest


def load_manifest(output):
    manifest = read_json(Path(output) / "manifest.json")
    payload = {key: val for key, val in manifest.items() if key != "sha256"}
    if canonical_hash(payload) != manifest.get("sha256"):
        raise ValueError("manifest_digest_mismatch")
    fixed_budgets = {"query_timeout_seconds": 10, "warmup_timeout_seconds": 10,
                     "load_timeout_seconds": 120, "hard_deadline_seconds": 0.3,
                     "batch_cap_seconds": MAX_BATCH_SECONDS}
    if (manifest["source_sha256"] != _source_hashes()
            or manifest["context_cap"] != CONTEXT_CAP
            or manifest["prompt_cap"] != PROMPT_CAP
            or manifest["seeds"] != list(DEVELOPMENT_SEEDS)
            or len(manifest["queries"]) != 24 or len(manifest["models"]) != 2
            or manifest["expected_queries"] != 48
            or any(manifest.get(key) != val for key, val in fixed_budgets.items())
            or manifest["upstream"]["files"] != UPSTREAM_FILES
            or manifest["upstream"]["commit"] != UPSTREAM_COMMIT):
        raise ValueError("frozen_protocol_mismatch")
    for actual, expected in zip(manifest["models"], MODEL_SPECS):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("frozen_model_identity_mismatch")
    expected_ids = [f"n{n}-{path}-{street}" for n in (6, 7, 8)
                    for path in ("check_call", "min_raise_first")
                    for street in ("preflop", "flop", "turn", "river")]
    if [query["id"] for query in manifest["queries"]] != expected_ids:
        raise ValueError("frozen_query_schedule_mismatch")
    return manifest


def verify_assets(model, upstream):
    for group in (model, upstream):
        directory = Path(group["directory"])
        for name, receipt in group["files"].items():
            path = directory / name
            if receipt is None or not path.is_file() or path.is_symlink():
                raise FileNotFoundError("model_or_upstream_asset_missing:" + name)
            digest = receipt if isinstance(receipt, str) else receipt["sha256"]
            if (isinstance(receipt, dict)
                    and path.stat().st_size != receipt["size"]):
                raise ValueError("asset_size_mismatch:" + name)
            if _sha(path) != digest:
                raise ValueError("asset_digest_mismatch:" + name)
    _check_config(model["directory"], model)


def render_checked(decider, request):
    """Validate full context and full untruncated upstream prompt before scoring."""
    context = json.dumps({"state": request["state"], "rules": request["rules"]},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    options = [row["id"] + ": " + row["text"] for row in request["options"]]
    if not 2 <= len(options) <= 255 or len(options) != len(set(options)):
        raise ValueError("unsupported_option_count")
    context_ids = decider.m.tok.encode("Context:\n" + context, add_special_tokens=False)
    if len(context_ids) > CONTEXT_CAP:
        raise ValueError("CONTEXT_OVERFLOW")
    questions = [{"question": request["question"], "options": options}]
    rendered, items = decider._decide_items(
        [(context, questions)], max_ctx_tokens=CONTEXT_CAP)
    if (rendered != [(context, questions)] or len(items) != 1
            or items[0]["perms"] != [list(range(len(options)))]
            or items[0]["nopts"] != [len(options)]
            or items[0]["ids"][:len(context_ids)] != context_ids):
        raise ValueError("PROMPT_MUTATION_OR_TRUNCATION")
    if len(items[0]["ids"]) > PROMPT_CAP:
        raise ValueError("PROMPT_OVERFLOW")
    return context, questions, {"context_tokens": len(context_ids),
                                "prompt_tokens": len(items[0]["ids"])}


def _error(exc):
    text = str(exc)
    status = ("OOM" if "out of memory" in text.lower() else
              "CONTEXT_OVERFLOW" if "CONTEXT_OVERFLOW" in text else
              "PROMPT_OVERFLOW" if "PROMPT_OVERFLOW" in text else
              "ERROR")
    return {"status": status, "error_type": type(exc).__name__, "reason": text}


def model_worker(connection, model, upstream):
    """One owned, preloaded model process; every request executes a fresh forward."""
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
                "DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[key] = "1"
    try:
        _check_config(model["directory"], model)
        sys.path.insert(0, upstream["directory"])
        import torch
        from decider.infer import Decider
        decider = Decider(model["directory"], device="cuda", dtype=torch.bfloat16,
                          use_graphs=False)
        if (decider.layout != "plain" or decider.schema_first
                or decider.neutralize_none or decider.T != model["temperature"]
                or decider.T_by_type is not None):
            raise ValueError("loaded_model_configuration_mismatch")
        torch.cuda.synchronize()
        connection.send({"status": "READY", "device": str(decider.dev),
                         "torch": torch.__version__,
                         "transformers": importlib.metadata.version("transformers")})
    except BaseException as exc:
        connection.send(_error(exc))
        return
    while True:
        try:
            query = connection.recv()
        except EOFError:
            return
        if query is None:
            return
        started = time.perf_counter()
        try:
            rules = AARuleProfileV2.from_dict(query["observation"]["rules"])
            adapter = ExternalLocalResearchPolicy(
                rules, lambda req: None, model_id=model["id"],
                model_revision=model["revision"])
            request = adapter.prepare_request(query["observation"])
            if (canonical_hash(request) != query["request_sha256"]
                    or request != query["request"]
                    or encode_decision_v2(query["observation"])["exact_key"]
                    != query["exact_key"]):
                raise ValueError("query_request_identity_mismatch")
            context, questions, counts = render_checked(decider, request)
            torch.cuda.synchronize()
            inference_started = time.perf_counter()
            answers = decider.decide(context, questions, max_ctx_tokens=CONTEXT_CAP)
            torch.cuda.synchronize()
            inference_ms = (time.perf_counter() - inference_started) * 1000
            if len(answers) != 1 or set(answers[0]["probs"]) != set(
                    questions[0]["options"]):
                raise ValueError("invalid_model_output_menu")
            ids = [option["id"] for option in request["options"]]
            scores = {action: answers[0]["probs"][text] for action, text in
                      zip(ids, questions[0]["options"])}
            action = select_action(scores, ids)
            response = {"status": "VALID", "action": action, "scores": scores,
                        "inference_ms": inference_ms, **counts,
                        "cached": False, "scores_are_gto_frequencies": False}
        except BaseException as exc:
            response = _error(exc)
        response["worker_elapsed_ms"] = (time.perf_counter() - started) * 1000
        connection.send(response)


class WorkerClient:
    def __init__(self, model, upstream, target=model_worker):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=target, args=(child, model, upstream))
        self.process.start()
        child.close()

    def receive(self, seconds):
        started = time.monotonic()
        if seconds <= 0 or not self.connection.poll(seconds):
            self.close()
            return {"status": "TIMEOUT", "reason": "owned_worker_deadline",
                    "elapsed_ms": (time.monotonic() - started) * 1000}
        try:
            value = self.connection.recv()
        except (EOFError, OSError):
            value = {"status": "ERROR", "reason": "worker_exited_without_response"}
        value["elapsed_ms"] = (time.monotonic() - started) * 1000
        return value

    def query(self, query, seconds):
        started = time.monotonic()
        try:
            self.connection.send(query)
        except (BrokenPipeError, EOFError, OSError):
            return {"status": "ERROR", "reason": "worker_unavailable"}
        value = self.receive(max(0, seconds - (time.monotonic() - started)))
        value["elapsed_ms"] = (time.monotonic() - started) * 1000
        if value["status"] != "TIMEOUT" and value["elapsed_ms"] > seconds * 1000:
            self.close()
            return {"status": "TIMEOUT", "reason": "late_response_discarded",
                    "elapsed_ms": value["elapsed_ms"]}
        return value

    def close(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        self.connection.close()


def _summary(report):
    rows = [row for model in report["models"] for row in model["queries"]]
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    report["summary"] = {
        "denominator": 48, "status_counts": counts,
        "valid_fraction": sum(row["status"] in ("VALID", "LATE_VALID")
                              for row in rows) / 48,
        "within_300ms_fraction": counts.get("VALID", 0) / 48,
        "all_opportunity_elapsed_ms": [row["elapsed_ms"] for row in rows],
        "full_hand_executability": "NOT_ASSESSED",
        "live_end_to_end_latency": "NOT_ASSESSED",
    }


def run_screen(output, *, batch_seconds=600, client_factory=WorkerClient,
               asset_verifier=verify_assets):
    if type(batch_seconds) is not int or not 1 <= batch_seconds <= MAX_BATCH_SECONDS:
        raise ValueError("invalid_batch_budget")
    started = time.monotonic()
    # Leave time for owned-worker teardown and final atomic report persistence.
    deadline = started + batch_seconds - min(15, batch_seconds / 5)
    output = Path(output)
    manifest = load_manifest(output)
    report = read_json(output / "results.json")
    if report != initial_results(manifest):
        raise ValueError("screen_already_started_or_mismatched")
    report["started"] = True

    def save():
        report["elapsed_seconds"] = time.monotonic() - started
        _summary(report)
        _atomic(output / "results.json", report)

    save()
    for spec, result in zip(manifest["models"], report["models"]):
        if time.monotonic() >= deadline:
            result["load"] = {"status": "NOT_RUN", "reason": "batch_budget"}
            save()
            continue
        client = None
        try:
            try:
                asset_verifier(spec, manifest["upstream"])
            except (FileNotFoundError, ValueError) as exc:
                result["load"] = {"status": "MODEL_NOT_READY", "reason": str(exc)}
                for row in result["queries"]:
                    row.update(status="MODEL_NOT_READY", reason=str(exc))
                save()
                continue
            load_started = time.monotonic()
            client = client_factory(spec, manifest["upstream"])
            result["load"] = client.receive(min(120, deadline - time.monotonic()))
            result["load"]["elapsed_ms"] = (time.monotonic() - load_started) * 1000
            save()
            if result["load"]["status"] != "READY":
                for row in result["queries"]:
                    row["reason"] = "model_load_failed"
                save()
                continue
            result["warmup"] = client.query(
                manifest["queries"][0], min(10, deadline - time.monotonic()))
            result["warmup"]["included_in_denominator"] = False
            save()
            alive = result["warmup"]["status"] != "TIMEOUT"
            for query, row in zip(manifest["queries"], result["queries"]):
                if not alive or time.monotonic() >= deadline:
                    row["reason"] = "worker_unavailable_or_batch_budget"
                    continue
                response = client.query(query, min(10, deadline - time.monotonic()))
                if response["status"] == "VALID" and response["elapsed_ms"] > 300:
                    response["status"] = "LATE_VALID"
                row.update(response)
                alive = response["status"] != "TIMEOUT"
                save()
            if alive and time.monotonic() < deadline:
                result["hard_deadline"] = client.query(
                    manifest["queries"][0], min(0.3, deadline - time.monotonic()))
                result["hard_deadline"].update(
                    budget_ms=300, included_in_denominator=False)
                if (result["hard_deadline"]["status"] == "VALID"
                        and result["hard_deadline"]["elapsed_ms"] > 300):
                    result["hard_deadline"]["status"] = "LATE_VALID"
            save()
        except Exception as exc:
            result["load"] = _error(exc)
            for row in result["queries"]:
                if row["status"] == "NOT_RUN":
                    row["reason"] = "worker_or_loading_error"
            save()
        finally:
            if client is not None:
                client.close()
    report["completed"] = True
    save()
    return report


def supervised_run(output, batch_seconds=600):
    if type(batch_seconds) is not int or not 1 <= batch_seconds <= MAX_BATCH_SECONDS:
        raise ValueError("invalid_batch_budget")
    output = Path(output).resolve()
    command = [sys.executable, "-m", "tools.screen_aa_local_policy", "_run",
               "--output", str(output), "--batch-seconds", str(batch_seconds)]
    result = run_bounded(command, seconds=batch_seconds - min(10, batch_seconds / 5),
                         cwd=ROOT,
                         log_path=output / "screen.log")
    _atomic(output / "supervisor.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "_run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-08b", type=Path)
    parser.add_argument("--model-2b", type=Path)
    parser.add_argument("--upstream-package", type=Path)
    parser.add_argument("--batch-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.phase == "freeze":
        if None in (args.model_08b, args.model_2b, args.upstream_package):
            parser.error("freeze requires both model directories and upstream package")
        result = freeze(args.output, args.model_08b, args.model_2b,
                        args.upstream_package)
        print(json.dumps({"manifest_sha256": result["sha256"], "queries": 48}))
    elif args.phase == "run":
        print(json.dumps(supervised_run(args.output, args.batch_seconds)))
    else:
        run_screen(args.output, batch_seconds=args.batch_seconds)


if __name__ == "__main__":
    main()
