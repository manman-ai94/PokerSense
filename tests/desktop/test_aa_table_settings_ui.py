"""Run the shipped browser logic without capture or private media."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_table_settings_interactions():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [shutil.which("node"), str(root / "tests/ui/test_aa_table_settings_ui.mjs")],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: 10 AA table settings" in result.stdout
