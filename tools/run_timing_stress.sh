#!/usr/bin/env bash
# 本地验证计时测试：pytest-xdist 并行 + CPU 占满，模拟 CI 慢机器。
# 用法：从仓库根目录 ./tools/run_timing_stress.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
if ! "$PY" -c "import xdist" 2>/dev/null; then
  echo "安装 pytest-xdist…"
  uv pip install --python "$PY" pytest-xdist
fi
FILES=(
  tests/tools/test_screen_aa_local_policy.py
  tests/desktop/test_aa_solver_advice.py
  tests/desktop/test_live_stream.py
  tests/desktop/test_aa_video_source.py
  tests/strategy/test_local_resolver.py
  tests/desktop/test_aa_study_ui.py
  tests/tools/test_aa_policy_readiness_study.py
  tests/desktop/test_aa_analysis.py
  tests/desktop/test_aa_policy_worker.py
  tests/tools/test_ci_changes.py
)
NCPU="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
HOGS=$((NCPU > 2 ? NCPU - 1 : 1))
echo "CPU 占满进程数: $HOGS, pytest -n 4"
for RUN in 1 2 3; do
  echo "===== 压力轮次 $RUN/3 ====="
  for _ in $(seq 1 "$HOGS"); do
    python3 -c 'while True: pass' &
  done
  HOG_PIDS=($(jobs -p))
  trap 'kill "${HOG_PIDS[@]}" 2>/dev/null || true' EXIT
  PYTHONPATH=src:. "$PY" -m pytest -n 4 -p no:cacheprovider "${FILES[@]}" -q
  kill "${HOG_PIDS[@]}" 2>/dev/null || true
  wait "${HOG_PIDS[@]}" 2>/dev/null || true
  trap - EXIT
done
echo "===== timing 标记测试再跑 3 轮 ====="
for RUN in 1 2 3; do
  echo "===== timing 轮次 $RUN/3 ====="
  for _ in $(seq 1 "$HOGS"); do
    python3 -c 'while True: pass' &
  done
  HOG_PIDS=($(jobs -p))
  trap 'kill "${HOG_PIDS[@]}" 2>/dev/null || true' EXIT
  PYTHONPATH=src:. "$PY" -m pytest -n 4 -p no:cacheprovider -m timing tests -q
  kill "${HOG_PIDS[@]}" 2>/dev/null || true
  wait "${HOG_PIDS[@]}" 2>/dev/null || true
  trap - EXIT
done
echo "全部压力轮次通过。"
