"""Flet 版本主应用入口"""

from __future__ import annotations

from pathlib import Path

import flet as ft
from filecollector.i18n import _, initialize as i18n_initialize
from filecollector.gui_flet.main_view import MainView
from filecollector.gui_flet.snack import show_snack
from filecollector.config import get_color_scheme


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
    # 跨平台系统字体栈：Windows 用微软雅黑 UI / Segoe UI，
    # macOS 用苹方，Linux 用 Noto Sans CJK SC，最后落到 sans-serif。
    # 注意：必须用单个 CSS 风格字符串，flet.Theme.font_family 不支持元组，
    # 否则会被序列化为 "('...', '...')" 查不到任何字体导致渲染挂起。
    _SYSTEM_FONT_FAMILY = (
        "MiWithJBMono, Microsoft YaHei UI, Segoe UI, PingFang SC, "
        "Noto Sans CJK SC, Helvetica Neue, Arial, sans-serif"
    )
    # 外观主题: 跟随配置 (system / light / dark), 默认 LIGHT 保底
    _scheme = get_color_scheme()
    if _scheme == "dark":
        page.theme_mode = ft.ThemeMode.DARK
    elif _scheme == "light":
        page.theme_mode = ft.ThemeMode.LIGHT
    else:  # system
        page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(
        color_scheme_seed="blue",
        use_material3=True,
        font_family=_SYSTEM_FONT_FAMILY,
    )

    # 创建主视图
    main_view = MainView(page)
    page.add(main_view.container)

    # 初始化
    main_view.initialize()

    # --gui 模式: 应用启动时透传的 CLI 初始化参数 (对齐 gnome 的 CLI 参数注入 GUI)
    from filecollector.__main__ import _PENDING_CLI_ARGS
    if _PENDING_CLI_ARGS:
        from filecollector.cli import apply_cli_args
        if apply_cli_args(main_view.engine, _PENDING_CLI_ARGS, print_feedback=False):
            main_view.initialize()
            # 清空, 避免后续 IPC 等路径重复应用
            _PENDING_CLI_ARGS.clear()

    # 单实例 IPC: 让运行中的 Flet 实例接收来自 CLI 的命令.
    # 服务器线程只负责把消息通过 page.run_task 投递到 Flet 主线程,
    # 实际 engine 变更 + UI 刷新在主线程协程里完成.
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
