"""AA eight-seat monitor: shared session, explicit controls, no game inputs."""

import argparse
import json
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, Response

from .aa_reader import AA8Reader, preflight_profile
from .aa_session import AARecognitionSession
from .aa_turn_runtime import observation_runtime_status
from .aa_sources import source_factory
from .aa_table_config import AATableConfigStore
from .aa_issues import save_issue
from .aa_analysis import AAConditionalAnalysis
from .aa_review import AAReviewDesk, ReviewError
from .aa_saved_strategy import SavedStrategyInputs
from .aa_analysis_records import AAAnalysisRecordStore, AnalysisRecordError
from .aa_hand_input import AAHandInput, HandInputError, digest
from .aa_study_records import AAStudyRecordStore, StudyRecordError
from poker_engine.strategy.river_bounds_v1 import river_payoff_bounds


def ui_root():
    frozen = getattr(sys, "_MEIPASS", None)
    root = Path(frozen) if frozen else Path(__file__).resolve().parents[3]
    return root / "ui" / "aa-live"


def create_app(profile_path, *, replay_pool=None, replay_first=None,
               replay_last=None, replay_playlist=None, allow_capture=False,
               session=None, rules_path=None, records_dir=None, bundle_sha256=None,
               analysis_service=None, review_service=None, study_service=None,
               hand_input_service=None, analysis_records_service=None):
    profile_path = Path(profile_path)
    service = session or AARecognitionSession(
        source_factory(profile_path, replay_pool=replay_pool,
                       replay_first=replay_first, replay_last=replay_last,
                       replay_playlist=replay_playlist,
                       allow_capture=allow_capture),
        lambda: AA8Reader(profile_path, bundle_sha256=bundle_sha256),
        interval_seconds=0.03,
    )
    rules = AATableConfigStore(rules_path)
    analysis = analysis_service or AAConditionalAnalysis()
    review = review_service or AAReviewDesk(records_dir)
    study = study_service or AAStudyRecordStore(records_dir)
    hand_input = hand_input_service or AAHandInput()
    analysis_records = analysis_records_service or AAAnalysisRecordStore(
        None if records_dir is None else Path(records_dir) / "analysis-records",
        analysis=analysis, rules_revision=lambda: rules.get()["revision"])
    saved_strategy = SavedStrategyInputs(profile_path, bundle_sha256)
    controls_lock = threading.RLock()
    profile_status = (preflight_profile(profile_path, bundle_sha256=bundle_sha256)
                      if bundle_sha256 else preflight_profile(profile_path))

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.stop()
        analysis.cancel()
        review.close()
        study.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.aa_session = service
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if request.headers.get("X-AA-Live") != "1":
                return Response("需要页面发起的操作", status_code=403)
            if origin:
                parsed = urlsplit(origin)
                if (parsed.scheme not in {"http", "https"}
                        or parsed.netloc != request.url.netloc):
                    return Response("拒绝跨来源操作", status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != (
                    "application/json"):
                return Response("需要 JSON 请求", status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return FileResponse(ui_root() / "index.html")

    @app.get("/app.js")
    def script():
        return FileResponse(ui_root() / "app.js",
                            media_type="text/javascript")

    @app.get("/style.css")
    def style():
        return FileResponse(ui_root() / "style.css", media_type="text/css")

    @app.get("/controls.js")
    def controls_script():
        return FileResponse(ui_root() / "controls.js", media_type="text/javascript")

    @app.get("/analysis.js")
    def analysis_script():
        return FileResponse(ui_root() / "analysis.js", media_type="text/javascript")

    @app.get("/review.js")
    def review_script():
        return FileResponse(ui_root() / "review.js", media_type="text/javascript")

    @app.get("/study.js")
    def study_script_view():
        return FileResponse(ui_root() / "study.js", media_type="text/javascript")

    def study_call(function, *args):
        try:
            return function(*args)
        except StudyRecordError as exc:
            raise HTTPException(400, str(exc)) from None
        except (ValueError, TypeError, OSError, KeyError):
            raise HTTPException(400, "研究记录未完成，请检查示例来源与记录目录") from None

    def hand_call(function, *args):
        try:
            return function(*args)
        except HandInputError as exc:
            raise HTTPException(400, str(exc)) from None
        except (ValueError, TypeError, OSError, KeyError):
            raise HTTPException(400, "牌局输入未完成，请检查字段与假设") from None

    async def record_body(request, keys, limit=220000):
        raw = await request.body()
        if len(raw) > limit:
            raise HTTPException(413, "分析记录请求过大")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "分析记录请求需要 JSON") from None
        if not isinstance(body, dict) or set(body) != set(keys):
            raise HTTPException(400, "分析记录请求字段不完整")
        return body

    def record_call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except AnalysisRecordError as exc:
            raise HTTPException(400, str(exc)) from None
        except (ValueError, TypeError, OSError, KeyError):
            raise HTTPException(400, "分析记录未完成，请检查记录目录与内容") from None

    @app.post("/api/analysis/records")
    async def save_analysis_record(request: Request):
        """Freeze the CURRENT completed analysis; the server owns the numbers."""
        body = await record_body(request, ("job_id", "input_sha256", "facts",
                                           "assumptions", "source", "label"))
        return record_call(analysis_records.save, job_id=body["job_id"],
                           expected_input_sha256=body["input_sha256"],
                           facts=body["facts"], assumptions=body["assumptions"],
                           source=body["source"], label=body["label"])

    @app.get("/api/analysis/records")
    def list_analysis_records():
        return {"items": record_call(analysis_records.recent)}

    @app.get("/api/analysis/records/{record_id}")
    def open_analysis_record(record_id: str):
        return record_call(analysis_records.get, record_id)

    @app.get("/api/analysis/records/{record_id}/scenario")
    def analysis_record_scenario(record_id: str):
        return record_call(analysis_records.scenario, record_id)

    @app.get("/api/hand-input/template")
    def hand_input_template():
        return hand_call(hand_input.template)

    @app.get("/hand_input.js")
    def hand_input_script():
        return FileResponse(ui_root() / "hand_input.js",
                            media_type="text/javascript")

    @app.get("/analysis_records.js")
    def analysis_records_script():
        return FileResponse(ui_root() / "analysis_records.js",
                            media_type="text/javascript")

    @app.get("/api/hand-input/facts/{issue_id}")
    def hand_input_facts(issue_id: str):
        record = review_call(review.get, issue_id)
        return hand_call(hand_input.from_record, record)

    @app.post("/api/hand-input/build")
    async def hand_input_build(request: Request):
        body = await review_body(request, ("facts", "assumptions", "rules_source",
                                           "rules_revision"))
        if body["rules_source"] not in ("document", "table"):
            raise HTTPException(400, "请选择规则来自手工场景或本桌设置")
        facts = body["facts"]
        if not isinstance(facts, dict) or not isinstance(body["assumptions"], dict):
            raise HTTPException(400, "牌局事实与假设必须是 JSON 对象")
        with controls_lock:
            current = rules.get()
            if body["rules_source"] == "table":
                if body["rules_revision"] != current["revision"]:
                    raise HTTPException(400, "本桌规则已变更，请重新载入后再计算")
                if not current["conditional_analysis_ready"]:
                    raise HTTPException(
                        400, "本桌规则不完整或含不支持的特殊机制：请先在「本桌规则」补齐")
                facts = {**facts, "table_rules": {
                    "value": current["simulation_rules"],
                    "provenance": "human_confirmed",
                    "candidate": {"revision": current["revision"]}}}
        result = hand_call(hand_input.build, facts, body["assumptions"])
        result["rules_source"] = body["rules_source"]
        if result.get("document") is not None:
            # The exact table-rules version this receipt was verified against, so
            # the form can send the verified revision instead of whatever the page
            # happens to see when the human later presses compute.
            result["verified_rules"] = {
                "rules_source": body["rules_source"],
                "rules_revision": current["revision"],
                "effective_rules_sha256": digest(result["document"].get("rules")),
            }
        return result

    @app.get("/api/study/examples")
    def study_examples():
        return study_call(study.examples_view)

    @app.get("/api/study/examples/{example_id}/view")
    def study_example_view(example_id: str):
        return study_call(study.view, example_id)

    @app.get("/api/study/records")
    def study_records():
        return study_call(study.recent)

    @app.post("/api/study/records")
    async def save_study_record(request: Request):
        body = await review_body(request, ("example_id",))
        return study_call(study.save, body["example_id"])

    @app.get("/api/study/records/{record_id}")
    def study_record(record_id: str):
        return study_call(study.get, record_id)

    async def review_body(request, keys):
        raw = await request.body()
        if len(raw) > 16000:
            raise HTTPException(413, "复查请求过大")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "复查请求需要 JSON") from None
        if not isinstance(body, dict) or set(body) != set(keys):
            raise HTTPException(400, "复查请求字段不完整")
        return body

    def review_call(function, *args):
        try:
            return function(*args)
        except ReviewError as exc:
            raise HTTPException(400, str(exc)) from None
        except (ValueError, TypeError, OSError, KeyError):
            raise HTTPException(400, "操作未完成，请检查输入、记录和 API 状态") from None

    @app.get("/api/review/config")
    def review_config():
        return review_call(review.config)

    @app.post("/api/review/config")
    async def set_review_config(request: Request):
        body = await review_body(request, ("api_key", "model", "daily_limit"))
        return review_call(review.configure, body["api_key"], body["model"],
                           body["daily_limit"])

    @app.post("/api/review/clear-key")
    async def clear_review_key(request: Request):
        await review_body(request, ())
        return review_call(review.clear_key)

    @app.get("/api/review/issues")
    def review_issues():
        return {"items": review_call(review.recent)}

    @app.post("/api/review/mark")
    async def review_mark(request: Request):
        await review_body(request, ())
        with controls_lock:
            evidence, current_rules = service.evidence(), rules.get()
        return review_call(review.mark, evidence, current_rules)

    @app.get("/api/review/issues/{issue_id}")
    def review_issue(issue_id: str):
        return review_call(review.get, issue_id)

    @app.get("/api/review/issues/{issue_id}/image")
    def review_image(issue_id: str):
        return Response(review_call(review.image, issue_id), media_type="image/jpeg")

    @app.post("/api/review/issues/{issue_id}/human")
    async def review_human(issue_id: str, request: Request):
        body = await review_body(request, ("verdict", "note", "revision"))
        return review_call(review.review, issue_id, body["verdict"],
                           body["note"], body["revision"])

    @app.post("/api/review/issues/{issue_id}/ai")
    async def review_ai(issue_id: str, request: Request):
        body = await review_body(request, ("consent",))
        return review_call(review.start, issue_id, body["consent"])

    @app.get("/api/status")
    def status():
        with controls_lock:
            result = service.snapshot()
            table_rules = rules.get()
            analysis_status = analysis.status()
            binding = analysis_status.get("binding", {})
            if (binding and analysis_status["status"] not in ("IDLE", "CANCELLED")
                    and (binding.get("table_rules_revision") != (
                    table_rules["revision"]) or binding.get("generation") != (
                        result["generation"]))):
                analysis_status = analysis.cancel()
        result.update(profile=profile_status,
                      replay_available=replay_pool is not None or (
                          replay_playlist is not None),
                      capture_available=allow_capture,
                      issue_recording_available=records_dir is not None,
                      table_rules=table_rules,
                      analysis=analysis_status,
                      strategy_scope="AA8_OBSERVATION_ONLY_NO_ADVICE")
        # Recheck after other status services finish; never trust a deadline or
        # advice supplied in a reader payload or a custom session snapshot.
        result["realtime"] = observation_runtime_status(result, now=time.monotonic())
        result["realtime"]["rules_revision"] = table_rules["revision"]
        return result

    @app.post("/api/review/issues/{issue_id}/river-input")
    async def saved_river_input(issue_id: str, request: Request):
        await review_body(request, ())
        return review_call(saved_strategy.from_record, review, issue_id)

    @app.post("/api/review/issues/{issue_id}/river-study")
    async def manual_river_bounds(issue_id: str, request: Request):
        body = await review_body(request, (
            "hero_cards", "board_cards", "pot_before", "call_cost", "opponents",
            "max_hero_deduction", "mode"))
        if body["mode"] != "manual_hypothesis":
            raise HTTPException(400, "当前只接受明确的人工假设")
        try:
            result = river_payoff_bounds(
                body["hero_cards"], body["board_cards"], body["pot_before"],
                body["call_cost"], body["opponents"],
                max_hero_deduction=body["max_hero_deduction"])
        except (ValueError, TypeError, ArithmeticError):
            raise HTTPException(400, "请核对两张手牌、五张公共牌、金额与对手数") from None
        return review_call(review.save_river_study, issue_id, body, result)

    @app.get("/api/preview.jpg")
    def preview():
        content = service.preview()
        if content is None:
            raise HTTPException(404, "当前没有新鲜画面")
        return Response(content, media_type="image/jpeg")

    @app.post("/api/start")
    async def start(request: Request):
        try:
            options = await request.json()
        except ValueError:
            raise HTTPException(400, "无法读取 JSON") from None
        if not isinstance(options, dict) or set(options) - {
                "mode", "device_index", "api", "fps"}:
            raise HTTPException(400, "来源设置字段不受支持")
        if options.get("mode") not in {"capture-card", "development-replay"}:
            raise HTTPException(400, "请选择来源")
        if "fps" in options and (type(options["fps"]) is not int
                                 or options["fps"] != 30):
            raise HTTPException(400, "当前 AA 来源仅请求 30 FPS 采集")
        if options["mode"] == "capture-card" and not allow_capture:
            raise HTTPException(403, "本次启动未启用采集卡")
        if (options["mode"] == "development-replay" and replay_pool is None
                and replay_playlist is None):
            raise HTTPException(400, "未配置开发回放")
        profile = (preflight_profile(profile_path, bundle_sha256=bundle_sha256)
                   if bundle_sha256 else preflight_profile(profile_path))
        if not profile["ready"]:
            raise HTTPException(409, {"message": "AA 识别资源未准备好",
                                      "errors": profile["errors"]})
        with controls_lock:
            analysis.cancel()
            service.start(options)
            return service.snapshot()

    @app.post("/api/stop")
    def stop():
        with controls_lock:
            analysis.cancel()
            service.stop()
            return service.snapshot()

    @app.get("/api/rules")
    def get_rules():
        return rules.get()

    @app.post("/api/rules")
    async def update_rules(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"document", "revision"}:
                raise ValueError("规则请求需要 document 和 revision")
            with controls_lock:
                result = rules.save(body["document"], body["revision"])
                analysis.cancel()
                # Rule changes invalidate the old observation/analysis context.
                service.stop()
                return result
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/issues")
    async def record_issue(request: Request):
        if records_dir is None:
            raise HTTPException(403, "本次启动没有配置问题记录目录")
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"note", "category"}:
                raise ValueError("问题记录需要 note 和 category")
            with controls_lock:
                evidence, current_rules = service.evidence(), rules.get()
            return save_issue(records_dir, evidence, body["note"],
                              body["category"], current_rules)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/analysis/example/{kind}")
    def analysis_example(kind: str):
        names = {"terminal": "terminal-multiway-river-manual.json",
                 "threeway": "threeway-river-response-manual.json"}
        if kind not in names:
            raise HTTPException(404, "未知示例")
        root = ui_root().parent.parent
        path = root / "configs" / "strategy" / "examples" / names[kind]
        return {"scope": "MANUAL_EXAMPLE_NOT_CURRENT_TABLE",
                "document": json.loads(path.read_text(encoding="utf-8"))}

    @app.post("/api/analysis")
    async def start_analysis(request: Request):
        raw = await request.body()
        if len(raw) > 220000:
            raise HTTPException(413, "分析输入过大")
        try:
            from tools.analyze_terminal_multiway import unique_object
            body = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(body, dict) or set(body) != {
                    "kind", "document", "rules_source", "rules_revision"}:
                raise ValueError("分析请求字段不完整")
            if body["rules_source"] not in ("document", "table"):
                raise ValueError("请选择规则来自手工场景或本桌设置")
            document = body["document"]
            if not isinstance(document, dict):
                raise ValueError("场景必须为 JSON 对象")
            with controls_lock:
                current = rules.get()
                if body["rules_revision"] != current["revision"]:
                    raise ValueError("本桌规则已变更，请重新检查分析输入")
                if body["rules_source"] == "table":
                    if not current["conditional_analysis_ready"]:
                        raise ValueError("本桌规则不完整或含不支持的特殊机制")
                    document["rules"] = current["simulation_rules"]
                observation = service.snapshot()
                return analysis.start(body["kind"], document, binding={
                    "table_rules_revision": current["revision"],
                    "generation": observation["generation"],
                    "rules_source": body["rules_source"],
                    "effective_rules": document.get("rules"),
                    "input_source": "MANUAL_HYPOTHESIS_NOT_LIVE_STATE",
                })
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/analysis/cancel")
    def cancel_analysis():
        with controls_lock:
            return analysis.cancel()

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="AA 扑克八座识别监控")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--replay-pool", type=Path)
    parser.add_argument("--replay-first", type=int)
    parser.add_argument("--replay-last", type=int)
    parser.add_argument("--replay-playlist", type=Path)
    parser.add_argument("--rules-path", type=Path)
    parser.add_argument("--records-dir", type=Path)
    parser.add_argument("--bundle-sha256")
    parser.add_argument("--allow-capture", action="store_true")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    app = create_app(args.profile, replay_pool=args.replay_pool,
                     replay_first=args.replay_first, replay_last=args.replay_last,
                     replay_playlist=args.replay_playlist,
                     rules_path=args.rules_path, records_dir=args.records_dir,
                     bundle_sha256=args.bundle_sha256,
                     allow_capture=args.allow_capture)
    if args.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(
            f"http://127.0.0.1:{args.port}")).start()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
