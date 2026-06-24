"""Flet build 入口文件。

flet build 期望项目根目录下存在 main.py（或通过 --module-name 指定的 .py 文件），
本项目使用 src/ 布局，因此在这里将 src/ 加入 sys.path 并调用真正的 Flet 应用入口。
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import flet as ft  # noqa: E402
from filecollector.gui_flet import main as flet_main  # noqa: E402

ft.app(target=flet_main)
