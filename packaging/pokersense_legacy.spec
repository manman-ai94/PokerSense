# PyInstaller spec for the PokerSense desktop shell.
#
# Run from the repo root:
#   pyinstaller packaging/pokersense.spec --distpath dist --workpath build
#
# Known-untested: the Windows build has not been run on a real Windows
# machine (this project's dev environment is macOS-only so far). Hidden
# imports below are a best-effort based on known PyInstaller+uvicorn+
# pywebview gotchas -- expect to iterate once someone actually runs this
# on Windows. Do not read a green CI badge on this as "verified working."

import sys
from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH).resolve().parent
ASSET_DIR = REPO_ROOT / "packaging" / "assets"

if sys.platform == "darwin":
    app_icon = ASSET_DIR / "PokerSense.icns"
elif sys.platform == "win32":
    app_icon = ASSET_DIR / "PokerSense.ico"
else:
    app_icon = None

# uvicorn resolves some protocol/loop implementations dynamically, which
# PyInstaller's static import analysis can miss.
hidden_imports = [
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]
if sys.platform == "darwin":
    hidden_imports += ["webview.platforms.cocoa"]
elif sys.platform == "win32":
    hidden_imports += ["webview.platforms.edgechromium", "webview.platforms.winforms"]

a = Analysis(
    [str(REPO_ROOT / "packaging" / "entry.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "ui"), "ui"),
        # ADB live capture loads Android ROI calibration and shared card glyphs
        # at runtime. These must travel with the frozen app, not just exist in
        # the source checkout used to create it.
        (str(REPO_ROOT / "configs"), "configs"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PokerSense",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(app_icon) if app_icon is not None else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="PokerSense",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="PokerSense.app",
        icon=str(app_icon),
        bundle_identifier="com.pokersense.desktop",
        info_plist={
            "CFBundleShortVersionString": "0.2.0",
            "NSHighResolutionCapable": True,
            # macOS packaging remains a development convenience; the product
            # target is Windows LDPlayer over ADB.
        },
    )
