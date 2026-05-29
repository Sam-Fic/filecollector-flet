# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['file_collector.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['filecollector.models', 'filecollector.utils', 'filecollector.engine',
                   'filecollector.cli', 'filecollector.gui.dialogs', 'filecollector.gui.main_window'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FileCollector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
