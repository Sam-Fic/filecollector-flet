"""Flet 版本主应用入口"""

from __future__ import annotations

from pathlib import Path

import flet as ft
from filecollector.i18n import _, initialize as i18n_initialize
from filecollector.gui_flet.main_view import MainView
from filecollector.gui_flet.snack import show_snack


def main(page: ft.Page):
    """Flet 应用主入口"""
    # 在任何 _() 调用之前，先从 settings.json 加载用户语言配置
    i18n_initialize()
    page.title = _("FileCollector - 文件收集与编排工具")
    page.window.width = 1300
    page.window.height = 780
    page.window.min_width = 1100
    page.window.min_height = 560

    _icon_path = Path(__file__).resolve().parent.parent.parent.parent / "icons" / "filecollector.ico"
    if _icon_path.exists():
        page.window.icon = str(_icon_path)
        page.update()

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

    # 单实例 IPC: 让运行中的 Flet 实例接收来自 CLI 的命令.
    # 服务器线程只负责把消息通过 page.run_task 投递到 Flet 主线程,
    # 实际 engine 变更 + UI 刷新在主线程协程里完成, 跟 PySide6 端一致.
    # 进程退出时 daemon 线程自动回收, 无需显式 stop.
    def _on_ipc_message(args):
        # 跑在 IPC server 的后台线程, 唯一线程安全的 UI 调用是 run_task.
        page.run_task(_handle_ipc, args)

    async def _handle_ipc(args):
        from filecollector.cli import apply_cli_args
        if apply_cli_args(main_view.engine, args, print_feedback=False):
            main_view.initialize()
            show_snack(page, _("已从外部命令更新 (%d 项)") % len(main_view.engine.items))
        else:
            show_snack(page, _("外部命令解析失败"))

    from filecollector.ipc import start_ipc_server
    start_ipc_server(_on_ipc_message)


if __name__ == "__main__":
    ft.app(target=main)
