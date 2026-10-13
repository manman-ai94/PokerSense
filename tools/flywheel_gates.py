"""The three gates a change passes before it goes onto the Mac (飞轮第一期).

    PYTHONPATH=src:. .venv/bin/python tools/flywheel_gates.py --base origin/main \\
        [--frames <录像文件夹>/frames.jsonl ...]                 # gate 1: recordings
        [--pools aa_real,noisy --seeds 1,2 --deals 600           # gate 2: simulation
         --strategy range_multiway@hu=1+aa_preflop [--head-strategy NAME]
         --sim-args "--mushroom 3 --mushroom-take 0.135 --reads 100" --workers 6]
        [--tests tests/desktop ... | --no-tests]                  # gate 3: tests
        --out <目录>

It compares the code as it is now (this checkout, uncommitted changes
included) with ``--base`` (checked out into a temporary git worktree) and
says pass or fail for each gate, with the reasons, in ``<out>/gates.json``
and in plain lines on the screen; the exit status is 0 only when every gate
that ran passed.

1. Recordings (``--frames``): each version works the advice out again from
   the same window logs (``tools/aa_session_report.py --replay-advice``, the
   heads-up solver taken as done). Fails when fewer hands get advice on
   every decision, fewer decisions get advice, or more stalls show; every
   decision whose advised action changed is listed (to look at, not a fail).
2. Simulation (``--pools``): each version plays the same deals on each pool
   and seed (``tools/run_scoreboard.py``), and the per-deal results are paired.
   Fails on a pool and seed where the new code is clearly worse (the whole 95%
   interval of the difference below 0). ``--head-strategy`` scores a different
   strategy name on the new code (a new option against the old default).
3. Tests (``--tests``): flake8 on the Python files that differ from
   ``--base`` and pytest on the given paths (default: the test files that
   differ and the test folders of the changed packages). The pull request's
   three checks still run the full suite; this is the fast local look.

Recordings and scoreboard outputs stay in ``--out`` (keep it in the private
data folder: the logs are other players' hands). Numbers from the simulation
are simulated table points, never real results.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
Z95 = 1.96


# -- the two versions ------------------------------------------------------------

def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def base_tree(ref, folder):
    """``ref`` checked out (detached) into ``folder``; returns its commit."""
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    git("worktree", "add", "--detach", str(folder), commit)
    return commit


def remove_tree(folder):
    subprocess.run(["git", "worktree", "remove", "--force", str(folder)], cwd=ROOT,
                   capture_output=True, text=True)
    shutil.rmtree(folder, ignore_errors=True)


def run_tool(tree, args, log):
    """Run a tool with ``tree``'s code (and this interpreter); its output
    goes to ``log``. Returns the exit status."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(["src", "."]))
    with open(log, "w", encoding="utf-8") as handle:
        return subprocess.run([sys.executable, *args], cwd=tree, env=env,
                              stdout=handle, stderr=subprocess.STDOUT).returncode


# -- gate 1: the recordings -----------------------------------------------------

REPLAY_LIMITS = (
    # (summary path, label, higher is better)
    (("fully_advised", "advised"), "每一步都有建议的手", True),
    (("advised",), "有建议的决策", True),
    (("stalls_over_2s",), "卡顿超过 2 秒", False),
)


def _get(summary, path):
    for key in path:
        summary = (summary or {}).get(key)
    return summary


def decision_changes(base, head):
    """Decisions whose first advised action differs, matched by hand (its
    id and start) and the decision's place in the hand."""
    changes = []
    for old, new in zip(base["hands"], head["hands"]):
        if (old.get("hand_id"), old.get("start_pts")) != (
                new.get("hand_id"), new.get("start_pts")):
            continue
        for index, (was, now) in enumerate(zip(old["decisions"], new["decisions"])):
            before = (was.get("advice") or [None])[0]
            after = (now.get("advice") or [None])[0]
            if before != after:
                changes.append({"hand_id": new.get("hand_id"),
                                "video_seconds": new.get("video_seconds"),
                                "start_pts": new.get("start_pts"),
                                "decision": index, "street": now.get("street"),
                                "your_cards": new.get("your_cards"),
                                "before": before, "after": after,
                                "kind_before": was.get("kind"),
                                "kind_after": now.get("kind"),
                                "you_did": now.get("you_did")})
    return changes


def replay_verdict(base, head):
    """Pass or fail, the reasons, and the numbers side by side."""
    rows, reasons = [], []
    for path, label, higher in REPLAY_LIMITS:
        old, new = _get(base["summary"], path), _get(head["summary"], path)
        rows.append({"what": label, "base": old, "head": new})
        if old is None or new is None:
            continue
        if (new < old) if higher else (new > old):
            reasons.append(f"{label}从 {old} 变成 {new}")
    total = _get(head["summary"], ("fully_advised", "hands"))
    return {"passed": not reasons, "reasons": reasons, "numbers": rows,
            "hands": total, "changed_decisions": decision_changes(base, head)}


def replay_gate(base_dir, head_dir, frames, out):
    reports = {}
    for name, tree in (("base", base_dir), ("head", head_dir)):
        target = out / f"replay-{name}.json"
        args = ["tools/aa_session_report.py", "--replay-advice", "--out", str(target)]
        for path in frames:
            args += ["--frames", str(Path(path).resolve())]
        status = run_tool(tree, args, out / f"replay-{name}.log")
        if status != 0 or not target.exists():
            return {"passed": False, "reasons": [f"{name} 版重放失败（见 replay-{name}.log）"]}
        reports[name] = json.loads(target.read_text(encoding="utf-8"))
    return replay_verdict(reports["base"], reports["head"])


# -- gate 2: the simulation -----------------------------------------------------

def paired(base_report, head_report, base_name, head_name):
    """The head's minus the base's big blinds per 100 hands over the deals
    both played, with a 95% interval (normal approximation over deals)."""
    old = {seed: values[base_name] for seed, values in base_report["per_deal"]}
    new = {seed: values[head_name] for seed, values in head_report["per_deal"]}
    seeds = sorted(set(old) & set(new))
    diffs = [100 * (new[seed] - old[seed]) for seed in seeds]
    if len(diffs) < 2:
        raise ValueError("need at least two deals played by both versions")
    mean = sum(diffs) / len(diffs)
    spread = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
    half = Z95 * spread / math.sqrt(len(diffs))
    return {"deals": len(diffs), "difference_bb100": round(mean, 2),
            "ci95": [round(mean - half, 2), round(mean + half, 2)],
            "base_bb100": round(100 * sum(old[s] for s in seeds) / len(seeds), 2),
            "head_bb100": round(100 * sum(new[s] for s in seeds) / len(seeds), 2)}


def sim_verdict(runs):
    """Fails when a run's whole interval is below 0 (clearly worse)."""
    reasons = [f"{run['pool']} 第 {run['seed']} 批牌：差 {run['difference_bb100']}"
               f"（区间 {run['ci95'][0]} 到 {run['ci95'][1]}）"
               for run in runs if run["ci95"][1] < 0]
    return {"passed": not reasons, "reasons": reasons, "runs": runs}


def sim_gate(base_dir, head_dir, args, out):
    runs = []
    for pool in args.pools:
        for seed in args.seeds:
            reports = {}
            for name, tree, strategy in (("base", base_dir, args.strategy),
                                         ("head", head_dir, args.head_strategy)):
                target = out / f"sim-{pool}-s{seed}-{name}.json"
                tool = ["tools/run_scoreboard.py", "--deals", str(args.deals),
                        "--pool", pool, "--seed", str(seed), "--strategies", strategy,
                        "--reference", strategy, "--workers", str(args.workers),
                        "--out", str(target), *shlex.split(args.sim_args)]
                status = run_tool(tree, tool, target.with_suffix(".log"))
                if status != 0 or not target.exists():
                    log = target.with_suffix(".log").name
                    return {"passed": False, "reasons": [f"{name} 版模拟失败（见 {log}）"]}
                reports[name] = json.loads(target.read_text(encoding="utf-8"))
            runs.append({"pool": pool, "seed": seed,
                         **paired(reports["base"], reports["head"], args.strategy,
                                  args.head_strategy)})
    return sim_verdict(runs)


# -- gate 3: the tests ----------------------------------------------------------

def changed_files(base_commit):
    """Files that differ from the base: committed, staged or not."""
    names = git("diff", "--name-only", base_commit).splitlines()
    names += git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({name for name in names if (ROOT / name).exists()})


def default_tests(changed):
    """The changed test files and the test folders of the changed packages."""
    paths = set()
    for name in changed:
        parts = Path(name).parts
        if parts[0] == "tests" and name.endswith(".py"):
            paths.add(name)
        elif parts[:2] == ("src", "poker_engine") and len(parts) > 3:
            if (ROOT / "tests" / parts[2]).is_dir():
                paths.add(f"tests/{parts[2]}")
        elif parts[0] == "tools" and (ROOT / "tests" / "tools").is_dir():
            stem = Path(name).stem
            candidate = ROOT / "tests" / "tools" / f"test_{stem}.py"
            if candidate.exists():
                paths.add(candidate.relative_to(ROOT).as_posix())
    # A folder already covers the files in it.
    return sorted(p for p in paths
                  if not any(p != q and p.startswith(q + "/") for q in paths))


def tests_gate(base_commit, paths, out):
    changed = changed_files(base_commit)
    python = [name for name in changed if name.endswith(".py")]
    reasons = []
    if python and run_tool(ROOT, ["-m", "flake8", *python], out / "flake8.log"):
        reasons.append("flake8 有问题（见 flake8.log）")
    paths = default_tests(changed) if paths is None else paths
    if paths and run_tool(ROOT, ["-m", "pytest", "-q", *paths], out / "pytest.log"):
        reasons.append("测试没全过（见 pytest.log）")
    return {"passed": not reasons, "reasons": reasons, "flake8_files": len(python),
            "test_paths": paths}


# -- report ---------------------------------------------------------------------

def lines(result):
    """The result in plain words, a line or two per gate."""
    text = [f"和 {result['base'][:7]} 比（现在的代码 {result['head'][:7]}"
            + ("，含未提交的改动）" if result["head_dirty"] else "）")]
    names = {"replay": "录像重放", "sim": "模拟", "tests": "测试"}
    for key in ("replay", "sim", "tests"):
        gate = result["gates"].get(key)
        if gate is None:
            text.append(f"{names[key]}：没跑")
            continue
        verdict = "过" if gate["passed"] else "不过：" + "；".join(gate["reasons"])
        text.append(f"{names[key]}：{verdict}")
        if key == "replay" and "numbers" in gate:
            text += [f"  {row['what']}：{row['base']} → {row['head']}"
                     for row in gate["numbers"]]
            text.append(f"  建议变了的决策：{len(gate['changed_decisions'])} 处")
        if key == "sim":
            text += [f"  {run['pool']} 第 {run['seed']} 批：{run['base_bb100']} → "
                     f"{run['head_bb100']}，差 {run['difference_bb100']}"
                     f"（区间 {run['ci95'][0]} 到 {run['ci95'][1]}，{run['deals']} 局，"
                     "模拟牌桌的积分）" for run in gate.get("runs", [])]
    ran = [gate for gate in result["gates"].values() if gate is not None]
    overall = ("全过" if ran and all(g["passed"] for g in ran)
               else "没过" if ran else "一道都没跑")
    text.append("三道关：" + overall)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--frames", type=Path, action="append", default=[])
    parser.add_argument("--pools", type=lambda text: text.split(","), default=[])
    parser.add_argument("--seeds", type=lambda text: [int(s) for s in text.split(",")],
                        default=[1, 2])
    parser.add_argument("--deals", type=int, default=600)
    parser.add_argument("--strategy", default="range_multiway@hu=1+aa_preflop")
    parser.add_argument("--head-strategy")
    parser.add_argument("--sim-args", default="")
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--tests", nargs="*")
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.head_strategy = args.head_strategy or args.strategy
    args.out.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    folder = Path(tempfile.mkdtemp(prefix="gates-base-"))
    folder.rmdir()
    base = base_tree(args.base, folder)
    try:
        gates = {"replay": None, "sim": None, "tests": None}
        if args.frames:
            gates["replay"] = replay_gate(folder, ROOT, args.frames, args.out)
        if args.pools:
            gates["sim"] = sim_gate(folder, ROOT, args, args.out)
        if not args.no_tests:
            gates["tests"] = tests_gate(base, args.tests, args.out)
    finally:
        remove_tree(folder)
    ran = [gate for gate in gates.values() if gate is not None]
    result = {"schema_version": 1, "base": base, "head": head, "head_dirty": dirty,
              "strategy": args.strategy, "head_strategy": args.head_strategy,
              "passed": bool(ran) and all(gate["passed"] for gate in ran),
              "gates": gates}
    (args.out / "gates.json").write_text(json.dumps(result, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
    print("\n".join(lines(result)))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
