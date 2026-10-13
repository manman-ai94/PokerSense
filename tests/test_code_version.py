import subprocess

from poker_engine import __version__
from poker_engine import code_version as module


def test_the_checkout_names_its_commit():
    info = module.code_version()
    assert info["version"] == __version__
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=module.ROOT,
                          capture_output=True, text=True)
    if head.returncode == 0:
        assert info["commit"] == head.stdout.strip()
        assert info["dirty"] in (True, False)


def test_outside_a_checkout_the_commit_is_unknown_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    module.code_version.cache_clear()
    try:
        assert module.code_version() == {"version": __version__, "commit": None,
                                         "dirty": None}
    finally:
        module.code_version.cache_clear()
