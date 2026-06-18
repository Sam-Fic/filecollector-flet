# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配置 for FileCollector.

显式打包 ``chardet`` 依赖, 防止在纯净运行环境中丢失编码检测能力
(否则 ``utils.safe_read_file`` 会回退到 ``latin-1`` 静默吞下乱码).
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 显式收集 chardet 全部子模块, 避免 PyInstaller 静态分析遗漏动态导入
hiddenimports = [
    'chardet',
    'charset_normalizer',
]
hiddenimports += collect_submodules('chardet')

a = Analysis(
    ['file_collector.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FileCollector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='../icons/filecollector.ico' if sys.platform == 'win32' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FileCollector',
)
