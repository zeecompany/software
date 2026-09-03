# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — AURCO Inventory Manager (Windows .EXE).

Build:  pyinstaller packaging\aurco.spec --noconfirm --clean
Output: dist\AURCO Inventory Manager\AURCO Inventory Manager.exe
"""
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.getcwd())

hidden = (collect_submodules("reportlab") + collect_submodules("openpyxl") +
          ["PySide6.QtSvg", "PySide6.QtPrintSupport", "sqlite3", "PIL", "pypdf",
           "arabic_reshaper", "bidi", "bidi.algorithm",
           # barcode symbologies used by the Barcode & Label Designer
           "reportlab.graphics.barcode.code128", "reportlab.graphics.barcode.code39",
           "reportlab.graphics.barcode.eanbc", "reportlab.graphics.barcode.qr",
           "reportlab.graphics.renderPDF", "reportlab.graphics.renderPM",
           # v2.4 modules
           "aurco.core.adminstation", "aurco.core.barcodes", "aurco.core.gdn",
           "aurco.ui.admin_station", "aurco.ui.barcode_designer", "aurco.ui.general_dn",
           "aurco.ui.user_manual", "aurco.ui.calculator",
           "aurco.core.issuance", "aurco.ui.issuance_page",
           "aurco.core.protection",
           "aurco.core.library", "aurco.ui.library_page",
           # v2.18 Tool Station (PDF handover custody register)
           "aurco.core.toolstation", "aurco.ui.tool_station",
           "pypdf"])

datas = []
if os.path.exists(os.path.join(ROOT, "assets")):
    datas.append((os.path.join(ROOT, "assets"), "assets"))

icon_file = os.path.join(ROOT, "assets", "aurco.ico")
version_file = os.path.join(ROOT, "packaging", "version_info.txt")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # keep the bundle lean & fast to start.
    # NOTE: do NOT exclude PIL — reportlab imports it for image support.
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtNetworkAuth", "PySide6.QtPositioning",
              "PySide6.QtBluetooth", "PySide6.QtSerialPort", "PySide6.QtTest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AURCO Inventory Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                      # GUI app: no console window
    disable_windowed_traceback=False,
    icon=icon_file if os.path.exists(icon_file) else None,
    version=version_file if os.path.exists(version_file) else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="AURCO Inventory Manager",
)
