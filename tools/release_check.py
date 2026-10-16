"""One check of a new version before it goes to 杜's computer or the Mac (装新版前的复查).

    PYTHONPATH=src:. .venv/bin/python tools/release_check.py <旧版> <新版> \\
        --recording <录像文件夹> [...]     # 1. 录像日志重放：几分钟
        [--measure <录像文件夹> ...]        # 2. 按原速重放：录像多长就跑多久，两版各一遍
        [--p30 <杜的录像文件夹>]            # 3. 第二台机器验收（新版），也按原速重放两版
        [--solver] [--tests <路径> ... | --no-tests] [--exclude 开始秒-结束秒 ...]
        [--cache <目录>] [--keep-going] [--plan] [--window-open-ok] --out <目录>

Both versions (any git refs: ``d5297a3``, ``origin/main``) are checked out
into temporary git worktrees and every step runs each version's own code;
the steps are the existing tools, not new ones:

0. Tests (new version): flake8 over what CI checks, and pytest on the tests
   of what changed between the two (``flywheel_gates.default_tests``), or
   ``--tests``. Fails when either fails.
1. Recording logs (``--recording``: a recording folder, its ``frames.jsonl``,
   or a folder of recordings): each version works the advice out again from
   the window's own log (``tools/aa_session_report.py --replay-advice``, the
   readings as they were). Fails when fewer hands get advice on every
   decision, fewer get it past the flop, or fewer decisions get advice; every
   decision whose advised action changed is listed by street and by which
   rule answered before and after (``tools/aa_compare_advice.py``), and where
   the opponents still in showed their cards both answers are valued in
   chips against those cards. The heads-up solve is taken as done at once
   here (check or call, as in ``aa_session_report``) unless ``--solver``;
   a changed decision where that stand-in answered is listed apart and
   labelled, not counted or valued as changed advice (10/16: a rough fold
   that turned into "solver call, equity 0%" was nearly taken for a bug).
   Stalls cannot be seen in a log replay (they are the log's own).
2. Played at recorded pace (``--measure``, ``--p30``): each version plays the
   recording through the live session with advice on, solver included
   (``tools/measure_aa_realtime.py --advice``), so recognition changes,
   stalls and late advice show. Each field's coverage
   (``p30_acceptance.field_coverage``), stalls over 2 s, dropped frames,
   latency and the advice in real time are set side by side; it fails when
   the new version is clearly worse (the margins are ``*_MARGIN`` below).
   Both versions are played in this check, one after the other, so the two
   runs meet the same machine; the order alternates from one recording to
   the next. A run from an earlier check is not reused: the same recognition
   code read the dealer button on 93.8% of the Samsung recording's frames in
   one check and on 89.1% in the next (986f986 and ab44f8f differ only in
   ``aa_solver_input.py``). The runs are kept in ``--cache`` (default
   ``PokerSense_private/release-check/measure-cache``), so a check cut short
   and run again with the same versions and ``--out`` picks up the runs it
   finished; a new ``--out`` plays both again. A version checked against
   itself is played twice: the gap between its two runs is the run-to-run
   noise.
3. Second seat (``--p30``): ``tools/p30_acceptance.py run`` of the new
   version on its measured log. Fails unless the verdict is 通过.

The slow steps do not run when a fast one failed (``--keep-going`` runs them
anyway). ``--plan`` only says what would run and for how long. The check
does not start while the window (port 8771) is open, since peng may be at
the table; ``--window-open-ok`` once he is not. The held-out part of the
9/9 recording (300-820 s) is always skipped; ``--exclude`` skips more on
every recording.

Writes ``<out>/复查单.md`` (one short page in Chinese, also printed) and
``<out>/release_check.json``; exit status 0 only when every step that ran
passed. Keep ``--out`` in the private data folder: the logs hold other
players' hands. Chips here are table points (积分), never money.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()
# Never looked at (300-600 s) or used for evaluation before (600-820 s):
# skipped in every development, tuning or measuring run (AGENTS.md).
HOLDOUT = {"aa_phone_record_20260909_031030_54322c62": ((300.0, 820.0),)}
WINDOW_PORT = 8771
FLAKE8_PATHS = ("src", "tests", "tools", "research/hu_root", "research/coverage_bridge")
# Played at recorded pace, two runs of one version differ a little (which
# frames get dropped); these are for two runs one after the other in one
# check (checking a version against itself shows the gap). Worse than these
# is the new version's doing.
FRAME_MARGIN = 0.01        # a field's coverage over frames
SHARE_MARGIN = 0.03        # hands or decisions advised in real time
COUNT_MARGIN = 2           # ... and never less than this many of them
STALL_MARGIN = 1           # stalls over 2 s
DROP_MARGIN = 0.02         # dropped frames
LATENCY_MARGIN = (1.5, 100.0)   # p95 ms: this many times and this much more
KINDS = {"preflop": "翻前", "solver": "求解器", "multiway": "范围规则", "rough": "粗略",
         None: "没有建议"}
ACTIONS = {"fold": "弃牌", "check": "过牌", "call": "跟注", "raise": "加注", None: "无"}
STREETS = {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}
EXAMPLES = 8                    # changed decisions written out on the page
STAND_IN = "求解器替身（不是真实建议）"
STEPS = (("tests", "测试和代码检查"), ("replay", "录像日志重放"),
         ("measure", "按原速重放"), ("p30", "杜的 P30 验收"))


# -- the two versions ------------------------------------------------------------

def checkout(ref):
    """``ref`` in a temporary worktree: (commit, folder)."""
    from tools.flywheel_gates import base_tree
    folder = Path(tempfile.mkdtemp(prefix="release-check-"))
    folder.rmdir()
    return base_tree(ref, folder), folder


def windows_for(path, extra=()):
    """The parts of a recording to skip: ``extra`` and the held-out part."""
    found = [window for name, held in HOLDOUT.items() if name in str(path)
             for window in held]
    return tuple(sorted(set(found) | set(extra)))


def window_open(port=WINDOW_PORT):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


# -- 0: tests -------------------------------------------------------------------

def changed_between(old, new, cwd=ROOT):
    from tools.flywheel_gates import git
    return [name for name in git("diff", "--name-only", old, new, cwd=cwd).splitlines()
            if name]


def tests_step(tree, old, new, paths, out):
    from tools.flywheel_gates import default_tests, run_tool
    changed = changed_between(old, new)
    paths = default_tests(changed, root=tree) if paths is None else paths
    reasons = []
    flake8 = [path for path in FLAKE8_PATHS if (tree / path).exists()]
    if run_tool(tree, ["-m", "flake8", *flake8], out / "flake8.log"):
        reasons.append("flake8 有问题（见 flake8.log）")
    tested = run_tool(tree, ["-m", "pytest", "-q", *paths], out / "pytest.log") \
        if paths else 0
    if tested:
        reasons.append("测试没全过（见 pytest.log）")
    return {"passed": not reasons, "reasons": reasons, "changed_files": len(changed),
            "test_paths": paths, "pytest_tail": _tail(out / "pytest.log")}


def _tail(log):
    """pytest's last line ("12 passed, 1 skipped in 3.2s")."""
    try:
        lines = [line.strip("= \n") for line in
                 log.read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return None
    return next((line for line in reversed(lines) if line), None)


# -- 1: recording logs ----------------------------------------------------------

def recording_logs(paths):
    """(name, frames.jsonl) of each recording given: a recording folder, its
    log, or a folder holding recordings."""
    found = []
    for path in map(Path, paths):
        if path.is_file():
            found.append(path)
        elif (path / "frames.jsonl").is_file():
            found.append(path / "frames.jsonl")
        else:
            found += sorted(path.rglob("frames.jsonl"))
    return [(log.parent.name, log) for log in found]


def _seconds(row):
    for key in ("source_video_pts", "video_seconds"):
        if isinstance(row.get(key), (int, float)):
            return row[key]
    return None


def kept_log(name, path, windows, out):
    """The log to replay: ``path``, or a copy without the rows inside
    ``windows`` (None when they cannot be told apart)."""
    if not windows:
        return path
    target = out / "logs" / f"{name}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    timed = False
    with open(path, encoding="utf-8") as source, open(target, "w",
                                                      encoding="utf-8") as kept:
        for line in source:
            if not line.strip():
                continue
            seconds = _seconds(json.loads(line))
            timed |= seconds is not None
            if seconds is None or not any(a <= seconds < b for a, b in windows):
                kept.write(line)
    if not timed:
        target.unlink()
        return None
    return target


def slim(report):
    """What ``aa_compare_advice.answer`` reads of an advice report."""
    item = {key: report.get(key) for key in ("status", "kind", "reason")
            if report.get(key) is not None}
    rows = report.get("advice") or []
    if rows:
        item["advice"] = [{key: rows[0][key] for key in ("action", "to")
                           if rows[0].get(key) is not None}]
    if isinstance(report.get("range_equity"), dict):
        item["range_equity"] = {"value": report["range_equity"].get("value")}
    if report.get("options"):
        item["options"] = [{"action": row.get("action"),
                            "big_blinds": row.get("big_blinds")}
                           for row in report["options"]]
    return item


def replay_main(argv):
    """``_replay``: run inside a version's worktree, with its code. The
    session report of the logs with the advice worked out again, and that
    advice on every frame with your buttons up."""
    here = str(HERE.parent)
    sys.path[:] = [entry for entry in sys.path if entry != here]
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--solver", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    import tools.aa_session_report as report_tool

    if args.solver:                          # AASolverAdvice(None): TexasSolver
        report_tool._Solved = lambda: None
    seen, original = [], report_tool.replayed_advice

    def kept(rows):
        advice = original(rows)
        up = [(row["fields"].get("hero_controls") or {}).get("visible") for row in rows]
        seen.append({"rows": len(rows), "reports": {
            str(index): slim(item) for index, item in enumerate(advice) if up[index]}})
        return advice

    report_tool.replayed_advice = kept
    hands, names = [], []
    for item in json.loads(args.logs.read_text(encoding="utf-8")):
        # One log at a time: a long session's log is hundreds of megabytes.
        logs = [(item["name"], report_tool.load(item["path"]))]
        hands += report_tool.session_report(logs, replay_advice=True)["hands"]
        names.append(item["name"])
    result = {"summary": report_tool.summarize(hands),
              "logs": [{"name": name, **item} for name, item in zip(names, seen)]}
    args.out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


def replay(tree, logs_file, out, label, solver):
    from tools.flywheel_gates import run_tool
    target = out / f"replay-{label}.json"
    args = [str(HERE), "_replay", "--logs", str(logs_file), "--out", str(target)]
    status = run_tool(tree, args + (["--solver"] if solver else []),
                      out / f"replay-{label}.log")
    if status or not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


REPLAY_LIMITS = (
    # (summary path, label)
    (("fully_advised", "advised"), "每一步都有建议的手"),
    (("fully_advised", "past_preflop_advised"), "其中打到翻牌后的"),
    (("advised",), "有建议的决策"),
)


def _get(summary, path):
    for key in path:
        summary = (summary or {}).get(key)
    return summary


def _reports(log, rows):
    """A version's advice report on each row (an empty one where your
    buttons were not up)."""
    if log["rows"] != rows:
        raise ValueError("两版读到的帧数不一样")
    found = [{} for _ in range(rows)]
    for index, item in log["reports"].items():
        found[int(index)] = item
    return found


def changed_decisions(name, rows, old, new):
    """Your decisions in one log whose advised action (or bet size) differs,
    each valued against the cards shown where the opponents showed them."""
    from tools.aa_compare_advice import decision, shown_value, turns
    final = {}
    for row in rows:
        history = row["fields"].get("actions_v1")
        if history and history.get("hand_id") is not None:
            final[history["hand_id"]] = history
    found = []
    for indexes in turns(rows):
        item = decision(name, rows, indexes, old, new, final)
        before, after = item["before"] or {}, item["after"] or {}
        sized = (not item["changed"] and before.get("action") == "raise"
                 and before.get("to") != after.get("to"))
        if not (item["changed"] or sized):
            continue
        item["size_only"] = sized
        if item.get("video_seconds") is None:         # a log measured from video
            item["video_seconds"] = _seconds(rows[indexes[0]])
        for label, reports in (("before", old), ("after", new)):
            if item[label] is None:
                item[f"reason_{label}"] = reports[indexes[-1]].get("reason")
        try:
            item["shown"] = shown_value(rows, indexes, item)
        except Exception:                 # a hand it cannot price
            item["shown"] = None
        found.append(item)
    return found


def stand_in(answer, solver):
    """Whether ``answer`` came from the stand-in for TexasSolver: without
    ``--solver`` every heads-up solve comes back at once as check or call
    against a made-up range, so its action and share mean nothing."""
    return not solver and (answer or {}).get("kind") == "solver"


def why(changes, solver=True):
    """The changes grouped by street and the rule that answered before and
    after, most first: [(text, count)]."""
    def kind(answer):
        return ("替身" if stand_in(answer, solver) else
                (answer or {}).get("kind"))

    def action(answer):
        if stand_in(answer, solver):
            return "替身"
        value = (answer or {}).get("action")
        return ACTIONS.get(value, value)

    groups = {}
    for item in changes:
        if item["size_only"]:
            continue
        before, after = item["before"] or {}, item["after"] or {}
        key = (item["street"], kind(before), kind(after))
        group = groups.setdefault(key, Counter())
        move = f"{action(before)}→{action(after)}"
        if not after and item.get("reason_after"):
            move += f"（{item['reason_after']}）"
        group[move] += 1
    order = sorted(groups.items(), key=lambda pair: -sum(pair[1].values()))
    names = {**KINDS, "替身": "求解器替身"}
    return [(f"{STREETS.get(street, street)} · {names.get(old, old)} → "
             f"{names.get(new, new)}：" + "、".join(
                 f"{move} {n}" for move, n in moves.most_common()),
             sum(moves.values())) for (street, old, new), moves in order]


def priced(changes):
    """The changed decisions valued against shown cards, added up."""
    values = [item["shown"] for item in changes if not item["size_only"]
              and item.get("shown")
              and None not in (item["shown"]["before"], item["shown"]["after"])]
    if not values:
        return None
    return {"decisions": len(values),
            "better": sum(v["after"] > v["before"] for v in values),
            "worse": sum(v["after"] < v["before"] for v in values),
            "chips_before": round(sum(v["before"] for v in values), 1),
            "chips_after": round(sum(v["after"] for v in values), 1)}


def compare_replays(logs, old, new, solver=False):
    """The verdict on the recording logs: numbers side by side, and every
    changed decision. ``logs`` gives (name, rows) in the replays' order;
    ``solver``: whether the replays ran TexasSolver or its stand-in."""
    numbers, reasons = [], []
    for path, label in REPLAY_LIMITS:
        before, after = _get(old["summary"], path), _get(new["summary"], path)
        numbers.append({"what": label, "old": before, "new": after})
        if None not in (before, after) and after < before:
            reasons.append(f"{label}从 {before} 变成 {after}")
    changes = []
    for (name, rows), was, now in zip(logs, old["logs"], new["logs"]):
        changes += changed_decisions(name, rows, _reports(was, len(rows)),
                                     _reports(now, len(rows)))
    for item in changes:
        item["stand_in"] = any(stand_in(item[label], solver)
                               for label in ("before", "after"))
        if item["stand_in"]:
            item["note"] = STAND_IN
    real = [item for item in changes if not item["stand_in"]]
    standing = [item for item in changes if item["stand_in"]]
    summary = new["summary"]
    return {"passed": not reasons, "reasons": reasons, "numbers": numbers,
            "logs": len(new["logs"]),
            "hands": _get(summary, ("fully_advised", "hands")),
            "decisions": summary.get("your_decisions"),
            "solver_taken_as_done": (summary.get("advised_by_kind") or {}).get(
                "solver", 0),
            "changed": sum(not item["size_only"] for item in real),
            "size_only": sum(item["size_only"] for item in real),
            "stand_in": len(standing), "stand_in_why": why(standing, solver),
            "why": why(real), "priced": priced(real), "changes": changes}


def replay_step(trees, paths, extra, out, solver):
    from tools.aa_session_report import load
    logs, skipped = [], []
    for name, path in recording_logs(paths):
        kept = kept_log(name, path, windows_for(path, extra), out)
        if kept is None:
            skipped.append(name)
        else:
            logs.append({"name": name, "path": str(Path(kept).resolve())})
    if not logs:
        return {"passed": False, "reasons": ["没有能重放的录像日志"], "skipped": skipped}
    spec = out / "replay-logs.json"
    spec.write_text(json.dumps(logs, ensure_ascii=False, indent=1), encoding="utf-8")
    runs = {}
    for label in ("old", "new"):
        runs[label] = replay(trees[label], spec, out, label, solver)
        if runs[label] is None:
            return {"passed": False, "reasons": [
                f"{'旧' if label == 'old' else '新'}版重放失败（见 replay-{label}.log）"]}
    rows = ((item["name"], [row for row in load(item["path"]) if row.get("fields")])
            for item in logs)                    # one log at a time
    try:
        result = compare_replays(rows, runs["old"], runs["new"], solver)
    except ValueError as error:                  # the replays do not line up
        return {"passed": False, "reasons": [str(error)]}
    result["skipped"] = skipped
    result["solver"] = solver
    return result


# -- 2: played at recorded pace -------------------------------------------------

def recorded_minutes(folder, windows=()):
    """The recording's length less the parts skipped, or None."""
    try:
        info = json.loads((Path(folder) / "recording.json").read_text(encoding="utf-8"))
        seconds = float(info["recorded_seconds"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    cut = sum(max(0.0, min(b, seconds) - a) for a, b in windows if a < seconds)
    return round((seconds - cut) / 60, 1)


def measure_dir(cache, commits, label, folder, windows, out):
    """Where the ``label`` version's run of ``folder`` is kept in the check of
    these two ``commits`` writing to ``out``: another check never finds it."""
    key = json.dumps([str(Path(folder).resolve()), [list(w) for w in windows],
                      "advice", commits["old"], commits["new"], label, str(out)])
    tag = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return cache / commits[label][:12] / f"{Path(folder).name}-{tag}"


def measured(target):
    """Whether ``target`` holds a measurement that played to the end."""
    try:
        summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (summary.get("run") or {}).get("status") == "ENDED" and (
        target / "frames.jsonl").is_file()


def measure(tree, commits, label, folder, windows, cache, out):
    """Play ``folder`` at recorded pace with ``tree``'s code (or reuse this
    check's finished run of it): (folder of the run, reused)."""
    from tools.flywheel_gates import run_tool
    target = measure_dir(cache, commits, label, folder, windows, out)
    log = out / f"measure-{Path(folder).name}-{label}.log"
    if measured(target):
        return target, True
    if target.exists():                    # an earlier run cut short
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    args = ["tools/measure_aa_realtime.py", "--video", str(Path(folder).resolve()),
            "--out", str(target), "--advice"]
    for low, high in windows:
        args += ["--exclude", f"{low:g}-{high:g}"]
    run_tool(tree, args, log)
    return target, False


def run_numbers(target):
    """What one run at recorded pace showed."""
    from tools.aa_session_report import session_report
    from tools.p30_acceptance import field_coverage, read_frames
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    rows = [row for row in read_frames(target / "frames.jsonl") if row.get("fields")]
    coverage = {key: value for key, value in field_coverage(rows).items()
                if isinstance(value, dict)}
    report = session_report([(target.name, rows)])["summary"]
    late = ((summary.get("summary") or {}).get("latency_ms") or {}).get(
        "arrival_to_published") or {}
    fully = report["fully_advised"]
    return {"run": (summary.get("run") or {}).get("status"),
            "coverage": coverage,
            "stalls_over_2s": report["stalls_over_2s"],
            "dropped": (summary.get("summary") or {}).get("frames_dropped_fraction"),
            "latency_p95_ms": late.get("p95"),
            "fully_advised": {"value": _share(fully["advised"], fully["hands"]),
                              "n": fully["hands"]},
            "advised": {"value": _share(report["advised"], report["your_decisions"]),
                        "n": report["your_decisions"]},
            "seconds_to_advice_median": report["seconds_to_advice_median"]}


def _share(hits, total):
    return round(hits / total, 4) if total else None


def _worse(old, new, margin):
    """Whether a share fell by more than run-to-run noise: ``margin``, or
    ``COUNT_MARGIN`` of its cases when there are few."""
    if None in (old.get("value"), new.get("value")):
        return False
    room = max(margin, COUNT_MARGIN / new["n"]) if new.get("n") else margin
    return old["value"] - new["value"] > room + 1e-9


def compare_runs(old, new, labels):
    """Rows (what, old, new, worse) and the reasons a recording fails."""
    rows, reasons = [], []

    def add(what, before, after, worse):
        rows.append({"what": what, "old": before, "new": after, "worse": worse})
        if worse:
            reasons.append(f"{what}：{_text(before)} → {_text(after)}")

    for label, version in (("旧版", old), ("新版", new)):
        if version["run"] != "ENDED":
            reasons.append(f"{label}没放完（{version['run']}）")
    for key, value in new["coverage"].items():
        before = old["coverage"].get(key) or {}
        margin = FRAME_MARGIN if (value.get("n") or 0) >= 1000 else SHARE_MARGIN
        add(labels.get(key, key), before.get("value"), value.get("value"),
            _worse(before, value, margin))
    add("每一步都有建议的手", old["fully_advised"]["value"], new["fully_advised"]["value"],
        _worse(old["fully_advised"], new["fully_advised"], SHARE_MARGIN))
    add("有建议的决策", old["advised"]["value"], new["advised"]["value"],
        _worse(old["advised"], new["advised"], SHARE_MARGIN))
    add("卡顿超过 2 秒", old["stalls_over_2s"], new["stalls_over_2s"],
        new["stalls_over_2s"] > old["stalls_over_2s"] + STALL_MARGIN)
    add("丢帧", old["dropped"], new["dropped"],
        None not in (old["dropped"], new["dropped"])
        and new["dropped"] > old["dropped"] + DROP_MARGIN)
    times, more = LATENCY_MARGIN
    before, after = old["latency_p95_ms"], new["latency_p95_ms"]
    add("画面延迟 p95（毫秒）", before, after, None not in (before, after)
        and after > before * times and after - before > more)
    add("建议出来的中位秒数", old["seconds_to_advice_median"],
        new["seconds_to_advice_median"], False)
    return rows, reasons


def field_labels():
    from tools import p30_acceptance
    groups = ("FIELDS", "TURN_FIELDS", "POSTFLOP_FIELDS")
    return {key: label for name in groups
            for key, label, _ in getattr(p30_acceptance, name, ())}


def finished_at(target):
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(
            (target / "summary.json").stat().st_mtime))
    except OSError:
        return None


def measure_step(trees, commits, folders, extra, cache, out):
    labels, recordings, reasons = field_labels(), [], []
    for index, folder in enumerate(folders):
        windows = windows_for(folder, extra)
        runs, reused = {}, {}
        for label in ("old", "new") if index % 2 == 0 else ("new", "old"):
            print(f"按原速重放 {Path(folder).name}（{'旧' if label == 'old' else '新'}版"
                  f" {commits[label][:7]}）……", flush=True)
            target, reused[label] = measure(trees[label], commits, label, folder,
                                            windows, cache, out)
            runs[label] = target
        item = {"recording": Path(folder).name,
                "minutes": recorded_minutes(folder, windows),
                "skipped_windows": [list(w) for w in windows], "reused": reused,
                "runs": {label: str(runs[label]) for label in ("old", "new")},
                "finished_at": {label: finished_at(runs[label])
                                for label in ("old", "new")}}
        if not all(measured(path) for path in runs.values()):
            item["reasons"] = ["没放完（见 measure-*.log）"]
        else:
            numbers = {label: run_numbers(path) for label, path in runs.items()}
            item["rows"], item["reasons"] = compare_runs(numbers["old"], numbers["new"],
                                                         labels)
        reasons += [f"{item['recording']} {reason}" for reason in item["reasons"]]
        recordings.append(item)
    return {"passed": not reasons, "reasons": reasons, "recordings": recordings}


# -- 3: the second seat ---------------------------------------------------------

def p30_step(tree, folder, frames, extra, out):
    from tools.flywheel_gates import run_tool
    target = out / "p30"
    if target.exists():                    # this check's own earlier output
        shutil.rmtree(target)
    args = ["tools/p30_acceptance.py", "run", "--video", str(Path(folder).resolve()),
            "--out", str(target), "--frames", str(frames)]
    for low, high in windows_for(folder, extra):
        args += ["--exclude", f"{low:g}-{high:g}"]
    run_tool(tree, args, out / "p30.log")
    try:
        report = json.loads((target / "acceptance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"passed": False, "reasons": ["验收没跑完（见 p30.log）"]}
    accepted = report["acceptance"]
    misses = [f"{row['label']} {_text(row['value'])}（线 {_text(row['line'])}）"
              f"{'：' + row['note'] if row.get('note') else ''}"
              for row in accepted["rows"] if row["verdict"] != "通过"]
    return {"passed": accepted["overall"] == "通过", "overall": accepted["overall"],
            "reasons": [] if accepted["overall"] == "通过" else misses,
            "counts": accepted["counts"], "rows": accepted["rows"],
            "table": str(target / "验收表.md")}


# -- the page -------------------------------------------------------------------

def _text(value):
    if value is None:
        return "—"
    if isinstance(value, float) and 0 <= value <= 1:
        return f"{value:.1%}"
    return str(value)


def advice_text(answer):
    """One answer as the window would say it: rule, action, size, share."""
    if not answer:
        return "没有建议"
    text = (f"{KINDS.get(answer['kind'], answer['kind'])}"
            f"{ACTIONS.get(answer['action'], answer['action'])}")
    if answer.get("to"):
        text += f"到 {answer['to']}"
    if answer.get("share") is not None:
        text += f"（胜率 {answer['share']:.0%}）"
    return text


def example(item):
    """One changed decision in a line, to look up in the recording."""
    def said(answer):
        if item.get("stand_in") and (answer or {}).get("kind") == "solver":
            return STAND_IN
        return advice_text(answer)

    seconds = item.get("video_seconds")
    where = (f"，录像第 {seconds:.0f} 秒" if isinstance(seconds, (int, float))
             else "")
    board = f"｜{item['board']}" if item.get("board") else ""
    did = ACTIONS.get(item.get("you_did"), item.get("you_did")) or "不知道"
    return (f"{item['log']} {item['hand_id']}{where}：{STREETS.get(item['street'], '')}"
            f" {item.get('hero') or '?'}{board}，{said(item['before'])} → "
            f"{said(item['after'])}，你{did}")


def headline(step, result):
    """The main numbers of one step, in one line."""
    if step == "tests":
        paths = "、".join(result.get("test_paths") or []) or "没有相关测试"
        return f"flake8 和相关测试（{paths}）：{result.get('pytest_tail') or '—'}"
    if step == "replay" and "numbers" in result:
        parts = [f"{row['what']} {_text(row['old'])} → {_text(row['new'])}"
                 for row in result["numbers"]]
        parts.append(f"建议变了 {result['changed']} 处" + (
            f"（另 {result['stand_in']} 处是求解器替身，不算）"
            if result.get("stand_in") else ""))
        return f"{result['logs']} 段、{result['hands']} 手、{result['decisions']} 个决策；" \
            + "；".join(parts)
    if step == "measure":
        return "；".join(f"{item['recording']}（{_text(item['minutes'])} 分钟）"
                        for item in result.get("recordings", []))
    if step == "p30" and "overall" in result:
        return "、".join(f"{verdict} {n}" for verdict, n in result["counts"].items())
    return ""


def page(result):
    """The check on one short page, in Chinese."""
    ran = {key: value for key, value in result["steps"].items() if value is not None}
    verdict = ("通过" if ran and all(step["passed"] for step in ran.values())
               else "没过" if ran else "什么都没跑")
    missing = [name for key, name in STEPS if result["steps"].get(key) is None]
    skipped = f"（没跑：{'、'.join(missing)}）" if missing and ran else ""
    lines = [f"# 装新版前复查：{verdict}{skipped}", "",
             f"旧版 {result['old'][:7]} → 新版 {result['new'][:7]}　·　本机时间 "
             f"{result['finished']}　·　用时 {result['minutes']} 分钟", "",
             "| 检查 | 结论 | 主要数字 |", "|---|---|---|"]
    for key, name in STEPS:
        step = result["steps"].get(key)
        if step is None:
            note = result.get("not_run", {}).get(key, "没要求")
            lines.append(f"| {name} | 没跑 | {note} |")
            continue
        word = "通过" if step["passed"] else "没过：" + "；".join(step["reasons"])
        lines.append(f"| {name} | {word} | {headline(key, step)} |")
    replay_result = result["steps"].get("replay") or {}
    if replay_result.get("why") or replay_result.get("stand_in"):
        lines += ["", f"## 建议变了的 {replay_result['changed']} 处（按哪条规则给的）", ""]
        lines += [f"- {text}" for text, _ in replay_result["why"]]
        if replay_result.get("size_only"):
            lines.append(f"- 同样加注、只是金额变了：{replay_result['size_only']} 处")
        value = replay_result.get("priced")
        if value:
            lines.append(
                f"- 对手亮了牌、能事后估值的 {value['decisions']} 处：新版好 "
                f"{value['better']}、差 {value['worse']}；这几处合计 {value['chips_before']}"
                f" → {value['chips_after']} 积分（只是这几手的事后估值，不是胜率结论）")
        if replay_result.get("stand_in"):
            lines.append(
                f"- 另有 {replay_result['stand_in']} 处一边是{STAND_IN}：这次重放没真跑"
                "求解器，替身面对下注就跟、没下注就过，牌力也是编的，所以没算进上面，"
                "也不估值；要看真实建议，加 --solver 重跑：")
            lines += [f"  - {text}" for text, _ in replay_result["stand_in_why"]]
        shown = sorted((item for item in replay_result["changes"]
                        if not item["size_only"]),
                       key=lambda item: bool(item.get("stand_in")))
        lines += ["", f"例子（前 {min(len(shown), EXAMPLES)} 处，全部在 release_check.json）："]
        lines += [f"- {example(item)}" for item in shown[:EXAMPLES]]
    for item in (result["steps"].get("measure") or {}).get("recordings", []):
        if not item.get("rows"):
            continue
        done = item.get("finished_at") or {}
        lines += ["", f"## 按原速重放：{item['recording']}", "",
                  f"两版都在这次复查里放：旧版 {done.get('old') or '—'}、新版 "
                  f"{done.get('new') or '—'} 放完。", "",
                  "| 项目 | 旧版 | 新版 | |", "|---|---|---|---|"]
        lines += [f"| {row['what']} | {_text(row['old'])} | {_text(row['new'])} | "
                  f"{'变差' if row['worse'] else ''} |" for row in item["rows"]]
    lines += ["", "说明："]
    if replay_result.get("numbers"):
        solver = ("单挑转牌、河牌真跑了求解器" if replay_result.get("solver") else
                  f"单挑转牌、河牌的求解器当作立刻算完（{replay_result['solver_taken_as_done']}"
                  " 个决策），只在按原速重放里真算")
        lines.append(f"- 录像日志重放用当时读到的画面，新旧两版各算一遍建议；{solver}；"
                     "卡顿只有按原速重放才量得出来。")
    lines.append("- 9 月 9 日保留录像的 300–820 秒一律跳过。积分只是牌桌点数，不是钱。")
    return "\n".join(lines) + "\n"


# -- main -----------------------------------------------------------------------

def plan(args, commits, cache):
    """What would run, and roughly how long the slow part takes."""
    return [f"旧版 {commits['old'][:7]} → 新版 {commits['new'][:7]}",
            "测试：" + ("不跑" if args.no_tests else "flake8 和相关测试"),
            f"录像日志重放：{len(recording_logs(args.recording))} 段",
            *measure_plan(args, commits, cache)]


def measure_plan(args, commits, cache):
    """Each recording to play at recorded pace, and the minutes it takes."""
    lines, total = [], 0.0
    for folder in [*args.measure, *([args.p30] if args.p30 else [])]:
        windows = windows_for(folder, args.exclude)
        minutes = recorded_minutes(folder, windows)
        todo = [label for label in ("old", "new")
                if not measured(measure_dir(cache, commits, label, folder, windows,
                                            args.out))]
        total += (minutes or 0) * len(todo)
        done = (f"（另 {2 - len(todo)} 版这次复查已经放完）" if len(todo) < 2
                else "")
        lines.append(f"按原速重放 {Path(folder).name}：{_text(minutes)} 分钟 × "
                     f"{len(todo)} 版{done}")
    lines.append(f"按原速重放合计约 {round(total)} 分钟"
                 + ("，另加 P30 离线座位检查几分钟" if args.p30 else ""))
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_replay"]:
        return replay_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", help="旧版：已经装着的那版（提交号、分支或标签）")
    parser.add_argument("new", help="新版：要装的那版")
    parser.add_argument("--recording", type=Path, action="append", default=[])
    parser.add_argument("--measure", type=Path, action="append", default=[])
    parser.add_argument("--p30", type=Path)
    parser.add_argument("--solver", action="store_true",
                        help="录像日志重放里也真跑求解器（每个单挑转牌、河牌最多 30 秒）")
    parser.add_argument("--tests", nargs="*")
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--exclude", action="append", default=[], metavar="START-END")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--window-open-ok", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    from poker_engine.desktop.aa_video_source import parse_windows
    from tools.flywheel_gates import git, remove_tree
    args.exclude = parse_windows(args.exclude)
    if args.cache is None:
        from poker_engine.data_paths import private_root
        args.cache = private_root() / "release-check" / "measure-cache"
    # The steps run in the worktrees: every path they get is absolute.
    args.out, args.cache = args.out.resolve(), args.cache.resolve()
    commits = {label: git("rev-parse", "--verify", f"{ref}^{{commit}}")
               for label, ref in (("old", args.old), ("new", args.new))}
    if args.plan:
        print("\n".join(plan(args, commits, args.cache)))
        return 0
    if not args.window_open_ok and window_open():
        print("信号灯窗口开着（端口 8771），可能正在打牌，先不跑。"
              "确认没在打牌再加 --window-open-ok。")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    trees = {}
    try:
        for label in ("old", "new"):
            if commits[label] in {commits.get(other) for other in trees}:
                trees[label] = next(trees[other] for other in trees
                                    if commits[other] == commits[label])
                continue
            _, trees[label] = checkout(commits[label])
        steps, not_run = {key: None for key, _ in STEPS}, {}
        if not args.no_tests:
            steps["tests"] = tests_step(trees["new"], commits["old"], commits["new"],
                                        args.tests, args.out)
        if args.recording:
            steps["replay"] = replay_step(trees, args.recording, args.exclude,
                                          args.out, args.solver)
        fast_failed = any(step and not step["passed"] for step in steps.values())
        folders = [*args.measure, *([args.p30] if args.p30 else [])]
        if folders and fast_failed and not args.keep_going:
            not_run["measure"] = not_run["p30"] = "前面没过，没跑（要跑加 --keep-going）"
        elif folders:
            print("\n".join(measure_plan(args, commits, args.cache)), flush=True)
            steps["measure"] = measure_step(trees, commits, folders, args.exclude,
                                            args.cache, args.out)
            if args.p30:
                new_run = measure_dir(args.cache, commits, "new", args.p30,
                                      windows_for(args.p30, args.exclude), args.out)
                steps["p30"] = (
                    p30_step(trees["new"], args.p30, new_run / "frames.jsonl",
                             args.exclude, args.out) if measured(new_run) else
                    {"passed": False, "reasons": ["新版没放完，验收没跑"]})
    finally:
        for folder in set(trees.values()):
            remove_tree(folder)
    result = {"schema_version": 1, "old": commits["old"], "new": commits["new"],
              "old_ref": args.old, "new_ref": args.new,
              "finished": time.strftime("%Y-%m-%d %H:%M"),
              "minutes": round((time.monotonic() - began) / 60, 1),
              "steps": steps, "not_run": not_run}
    ran = [step for step in steps.values() if step is not None]
    result["passed"] = bool(ran) and all(step["passed"] for step in ran)
    (args.out / "release_check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    text = page(result)
    (args.out / "复查单.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    if sys.argv[1:2] != ["_replay"]:
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(ROOT))
    sys.exit(main())
