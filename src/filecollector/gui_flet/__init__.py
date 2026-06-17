"""Flet 版本主应用入口"""

from __future__ import annotations

import flet as ft
from filecollector.engine import FileCollectorEngine
from filecollector.i18n import _
from filecollector.gui_flet.main_view import MainView


def main(page: ft.Page):
    """Flet 应用主入口"""
    page.title = _("FileCollector - 文件收集与编排工具")
    page.window.width = 1300
    page.window.height = 780
    page.window.min_width = 960
    page.window.min_height = 560

    # Material 3 主题
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        color_scheme_seed="blue",
        use_material3=True,
    )

    # 创建主视图
    main_view = MainView(page)
    page.add(main_view.container)

    # 初始化
    main_view.initialize()


if __name__ == "__main__":
    ft.app(target=main)
