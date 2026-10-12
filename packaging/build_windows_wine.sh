#!/usr/bin/env bash
# Cross-build the Windows AA installer on Linux using Wine (Windows Python +
# PyInstaller + Inno Setup). For CI-free verification when GitHub Actions minutes
# are exhausted. Real capture/MSMF still needs a Windows machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CACHE="${POKERSENSE_WINE_CACHE:-$HOME/.cache/pokersense-wine}"
DL="${CACHE}-dl"
export WINEPREFIX="${WINEPREFIX:-$CACHE/prefix}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEARCH=win64

PYTHON_VER=3.11.9
WIN_PYTHON='C:\Python311\python.exe'
INNO_DIR='C:\Inno Setup 6'
ISCC="${INNO_DIR}\ISCC.exe"
ARTIFACTS="${POKERSENSE_ARTIFACTS:-/opt/cursor/artifacts}"
LOG="${CACHE}/build.log"
STAMP="${CACHE}/.wine-build-stamp"

mkdir -p "$DL" "$CACHE" "$ARTIFACTS"
: >"$LOG"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

need_cmd() {
  command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }
}

need_cmd wine
need_cmd winepath
need_cmd unzip
need_cmd curl
wine_python() {
  # Wine 9 + Windows Python: redirecting stdout to a file breaks ([WinError 6]);
  # always pipe through tee when capturing logs.
  wine "$WIN_PYTHON" "$@" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}

wine_exe() {
  wine "$@" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}

ensure_wine_prefix() {
  if [[ ! -d "$WINEPREFIX" ]]; then
    log "init wine prefix $WINEPREFIX"
    wineboot -i 2>&1 | tee -a "$LOG" || true
    wineserver -w || true
  fi
}

install_windows_python() {
  if wine "$WIN_PYTHON" -c "import sys; print(sys.version)" </dev/null 2>/dev/null | grep -q 3.11; then
    log "Windows Python already at $WIN_PYTHON"
    return 0
  fi
  local nupkg="$DL/python-${PYTHON_VER}.nupkg"
  if [[ ! -f "$nupkg" ]]; then
    log "download python ${PYTHON_VER} nuget"
    curl -fsSL -o "$nupkg" \
      "https://www.nuget.org/api/v2/package/python/${PYTHON_VER}"
  fi
  local tmp="$CACHE/python-extract"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  unzip -q "$nupkg" -d "$tmp"
  local dest="$WINEPREFIX/drive_c/Python311"
  rm -rf "$dest"
  cp -a "$tmp/tools" "$dest"
  log "installed Windows Python to C:\\Python311"
}

install_inno_setup() {
  local marker="$WINEPREFIX/drive_c/Inno Setup 6/ISCC.exe"
  if [[ -f "$marker" ]]; then
    log "Inno Setup already installed"
    return 0
  fi
  local exe="$DL/innosetup-6.7.1.exe"
  if [[ ! -f "$exe" ]]; then
    log "download Inno Setup 6.7.1"
    curl -fsSL -o "$exe" \
      "https://github.com/jrsoftware/issrc/releases/download/is-6_7_1/innosetup-6.7.1.exe"
  fi
  log "silent install Inno Setup"
  wine_exe "$exe" /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER "/DIR=${INNO_DIR}"
  wineserver -w || true
  [[ -f "$marker" ]] || { log "ISCC.exe not found after install"; exit 1; }

  local lang="$WINEPREFIX/drive_c/Inno Setup 6/Languages"
  mkdir -p "$lang"
  local isl="$lang/ChineseSimplified.isl"
  if [[ ! -f "$isl" ]]; then
    curl -fsSL -o "$isl" \
      "https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/ChineseSimplified.isl"
    # Inno reads UTF-8 with BOM
    python3 - "$isl" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
b = p.read_bytes()
if not b.startswith(b"\xef\xbb\xbf"):
    p.write_bytes(b"\xef\xbb\xbf" + b)
PY
  fi
}

pip_install_project() {
  local hash
  hash="$(git -C "$ROOT" rev-parse HEAD):$(sha256sum "$ROOT/pyproject.toml" | awk '{print $1}')"
  if [[ -f "$STAMP" ]] && [[ "$(cat "$STAMP")" == "$hash" ]]; then
    log "pip install skipped (unchanged)"
    return 0
  fi
  log "pip install -e .[desktop,perceptual,packaging]"
  wine_python -m ensurepip --upgrade </dev/null || true
  wine_python -m pip install --disable-pip-version-check -U pip wheel </dev/null
  wine_python -m pip install --disable-pip-version-check -e ".[desktop,perceptual,packaging]" </dev/null
  # NumPy 2.x pulls ucrtbase.crealf under Wine 9 and breaks PyInstaller/cv2 hooks.
  log "Wine workaround: pin numpy 1.26.4 for PyInstaller (real Windows CI keeps 2.4.6)"
  wine_python -m pip install --disable-pip-version-check "numpy==1.26.4" --force-reinstall </dev/null
  echo "$hash" >"$STAMP"
}

smoke_imports() {
  log "smoke: pokerkit, phevaluator (Wine; opencv checked on frozen exe)"
  wine_python -c "import pokerkit, phevaluator; print('imports_ok')" </dev/null
}

pyinstaller_build() {
  log "PyInstaller (Wine win32)"
  rm -rf "$ROOT/build/wine-pyinstaller" "$ROOT/dist/PokerSense-AA"
  wine_python -m PyInstaller packaging/pokersense.spec \
    --distpath dist --workpath build/wine-pyinstaller --noconfirm </dev/null
  [[ -f "$ROOT/dist/PokerSense-AA/PokerSense-AA.exe" ]] || {
    log "missing dist/PokerSense-AA/PokerSense-AA.exe"; exit 1
  }
}

frozen_self_test() {
  log "frozen --self-test (Wine)"
  local out="$CACHE/self-test.json"
  rm -f "$out"
  set +e
  wine_exe "$ROOT/dist/PokerSense-AA/PokerSense-AA.exe" --self-test </dev/null | tee "$out.raw"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ $rc -ne 0 ]]; then
    log "--self-test exit $rc"
    return $rc
  fi
  python3 - <<'PY' "$out.raw"
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
start = raw.find("{")
if start < 0:
    raise SystemExit("no JSON in self-test output")
data = json.loads(raw[start:])
print(json.dumps(data, indent=2, ensure_ascii=False))
if data.get("result") != "SELF_TEST_PASS":
    raise SystemExit("SELF_TEST_FAIL")
PY
}

frozen_dependency_note() {
  log "note: Wine cannot reliably import opencv-python (ucrtbase.crealf); use --self-test on real Windows for cv2"
  wine_exe "$ROOT/dist/PokerSense-AA/PokerSense-AA.exe" --version </dev/null || true
}

inno_build() {
  log "Inno Setup compiler (Wine)"
  local win_iss
  win_iss="$(winepath -w "$ROOT/packaging/pokersense.iss")"
  wine_exe "$ISCC" "$win_iss" || {
    log "retry ISCC without Chinese language file"
    rm -f "$WINEPREFIX/drive_c/Inno Setup 6/Languages/ChineseSimplified.isl"
    wine_exe "$ISCC" "$win_iss"
  }
  [[ -f "$ROOT/dist/PokerSense-AA-Setup.exe" ]] || {
    log "missing dist/PokerSense-AA-Setup.exe"; exit 1
  }
  cp -f "$ROOT/dist/PokerSense-AA-Setup.exe" "$ARTIFACTS/PokerSense-AA-Setup.exe"
  sha256sum "$ARTIFACTS/PokerSense-AA-Setup.exe" | tee -a "$LOG"
  log "installer -> $ARTIFACTS/PokerSense-AA-Setup.exe"
}

main() {
  log "build_windows_wine.sh start (repo $ROOT)"
  ensure_wine_prefix
  install_windows_python
  install_inno_setup
  pip_install_project
  smoke_imports
  pyinstaller_build
  frozen_self_test || log "WARN: frozen --self-test failed under Wine (see log)"
  frozen_dependency_note
  inno_build
  log "done"
}

main "$@"
