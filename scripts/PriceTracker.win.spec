# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

_spec_file = Path(globals().get("__file__", Path.cwd() / "PriceTracker.win.spec")).resolve()
if _spec_file.parent.name.lower() == "scripts":
    root = _spec_file.parent.parent
else:
    root = _spec_file.parent
app_name = os.getenv("PRICE_TRACKER_APP_NAME", "PriceTracker").strip() or "PriceTracker"
main_py = str(root / "main.py")

datas = []
hiddenimports = []
binaries = []
datas += collect_data_files("ccxt")
try:
    hiddenimports += collect_submodules("ccxt")
except Exception:
    hiddenimports += []

a = Analysis(
    [main_py],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide2", "PySide6", "PyQt6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
