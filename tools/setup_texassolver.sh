#!/usr/bin/env bash
# Download and build TexasSolver's command-line solver into the private data
# directory (macOS, Apple Silicon or Intel).
#
#   tools/setup_texassolver.sh
#
# TexasSolver (https://github.com/bupticybee/TexasSolver) is AGPL-3.0 and its
# author asks that the program not be redistributed. PokerSense only calls it
# as a separate program on this machine: never commit its source or binary,
# and never share the built folder.
#
# Result: $POKERSENSE_DATA_ROOT/third_party/TexasSolver-console/install/console_solver
# (data root defaults to ~/Projects/PokerSense_data).
set -euo pipefail

REPO_URL="https://github.com/bupticybee/TexasSolver.git"
COMMIT="6dfb65b4d7ed081da509e8d8c3d82138c4708267"   # console branch, 2026-08-19
DATA_ROOT="${POKERSENSE_DATA_ROOT:-$HOME/Projects/PokerSense_data}"
SOURCE="$DATA_ROOT/third_party/TexasSolver-console"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v brew >/dev/null; then
    echo "Homebrew is needed: https://brew.sh" >&2
    exit 1
fi
for formula in cmake libomp; do
    brew list --versions "$formula" >/dev/null || brew install "$formula"
done
OMP="$(brew --prefix libomp)"

if [ ! -d "$SOURCE/.git" ]; then
    mkdir -p "$(dirname "$SOURCE")"
    git clone --filter=blob:none --no-checkout "$REPO_URL" "$SOURCE"
fi
git -C "$SOURCE" fetch --depth 1 origin "$COMMIT"
git -C "$SOURCE" checkout --quiet "$COMMIT"

# Apple's compiler needs OpenMP spelled out (Homebrew's libomp); the bundled
# googletest and pybind11 still declare old CMake versions, and pybind11's
# configure step needs a Python that has distutils (the system one does).
cmake -S "$SOURCE" -B "$SOURCE/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DPYTHON_EXECUTABLE=/usr/bin/python3 \
    -DOpenMP_C_FLAGS="-Xpreprocessor -fopenmp -I$OMP/include" -DOpenMP_C_LIB_NAMES=omp \
    -DOpenMP_CXX_FLAGS="-Xpreprocessor -fopenmp -I$OMP/include" -DOpenMP_CXX_LIB_NAMES=omp \
    -DOpenMP_omp_LIBRARY="$OMP/lib/libomp.dylib" \
    -DCMAKE_EXE_LINKER_FLAGS="-L$OMP/lib -lomp -Wl,-rpath,$OMP/lib"
cmake --build "$SOURCE/build" --target console_solver -j "$(sysctl -n hw.ncpu)"
cmake --install "$SOURCE/build"

echo "TexasSolver ready: $SOURCE/install/console_solver"
