from pathlib import Path
import shutil
import subprocess

import pytest


def test_the_solver_advice_panel_renders_each_status():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the observer page's script")
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [node, str(root / "tests/ui/test_aa_solver_advice_ui.js")],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "solver advice panel cases passed" in completed.stdout
