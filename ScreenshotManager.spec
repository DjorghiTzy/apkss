# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm --clean ScreenshotManager.spec
# Hasil: dist/ScreenshotManager/ScreenshotManager.exe (mode folder: start cepat & stabil)
import sys

block_cipher = None

EXCLUDES = [
    # modul Qt besar yang tidak dipakai -> ukuran lebih kecil
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "unittest", "pytest",
]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets")],
    hiddenimports=["watchdog.observers.read_directory_changes", "watchdog.observers.polling"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenshotManager",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version="version_info.txt" if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
               name="ScreenshotManager")
