# Canonical Windows AA engineering preview 0.2.0.dev1.
# Private profiles, models, recordings and credentials remain external.
from pathlib import Path

root = Path(SPECPATH).resolve().parent
a = Analysis(
    [str(root / "packaging" / "aa_live_entry.py")],
    pathex=[str(root / "src"), str(root)],
    binaries=[], datas=[(str(root / "ui" / "aa-live"), "ui/aa-live"),
                       (str(root / "configs" / "strategy" / "examples" /
                            "terminal-multiway-river-manual.json"),
                        "configs/strategy/examples"),
                       (str(root / "configs" / "strategy" / "examples" /
                            "threeway-river-response-manual.json"),
                        "configs/strategy/examples")],
    hiddenimports=["uvicorn.loops.auto", "uvicorn.loops.asyncio",
                   "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
                   "uvicorn.protocols.websockets.auto",
                   "uvicorn.protocols.websockets.websockets_impl",
                   "uvicorn.lifespan.on", "uvicorn.lifespan.off"],
    excludes=["matplotlib", "pandas", "torch", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PokerSense-AA",
          console=True, strip=False, upx=False,
          icon=str(root / "packaging" / "assets" / "PokerSense.ico"),
          version=str(root / "packaging" / "windows-version.txt"))
coll = COLLECT(exe, a.binaries, a.datas, name="PokerSense-AA",
               strip=False, upx=False)
