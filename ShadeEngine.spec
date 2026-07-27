# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Shade Engine.
# Produces ONE self-contained file:  dist/Shade Engine.exe
#
# Build with:   pyinstaller --noconfirm --clean ShadeEngine.spec
#
from PyInstaller.utils.hooks import collect_all

# Bundle the pydivert package together with the WinDivert.dll / WinDivert64.sys
# driver files it needs (PyInstaller does not grab these automatically).
pd_datas, pd_binaries, pd_hiddenimports = collect_all('pydivert')

datas = pd_datas + [
    ('config.json', '.'),
    ('assets/icon.png', 'assets'),
    ('assets/icon.ico', 'assets'),
]

hiddenimports = pd_hiddenimports + [
    'engine_core',
    'gui',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
]

a = Analysis(
    ['shade_engine.py'],
    pathex=[],
    binaries=pd_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Shade Engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed GUI app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,         # always request Administrator (WinDivert needs it)
    icon='assets/icon.ico',
    version='version_info.txt',
)
