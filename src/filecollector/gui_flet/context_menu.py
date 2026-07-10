"""共享右键上下文菜单组件.

把原先散落在 file_tree / arrangement_list / git_history 三处
各写一遍的 ``AlertDialog`` + ``Column`` 右键菜单抽成统一实现,
消除复制粘贴, 并保证菜单项渲染 / 弹窗调度风格一致.

用法::

    from filecollector.gui_flet.context_menu import build_menu_dialog, menu_item

    items = [
        menu_item(ft.Icons.COPY, "复制路径", on_click=...),
        menu_item(ft.Icons.DELETE, "删除", on_click=..., color=ft.Colors.RED),
    ]
    dlg = build_menu_dialog(items)
    page.show_dialog(dlg)
"""

from __future__ import annotations

import flet as ft


def menu_item(
    icon: str,
    text: str,
    on_click=None,
    color: str | None = None,
) -> ft.Control:
    """构建右键菜单中的一项 (图标 + 文本, 可点击行)."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(icon, size=18, color=color or ft.Colors.GREY_700),
                ft.Text(
                    text,
                    size=13,
                    expand=True,
                    color=color or None,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=8, top=6, right=8, bottom=6),
        border_radius=6,
        on_click=on_click,
        ink=True,
    )


def build_menu_dialog(items: list[ft.Control]) -> ft.AlertDialog:
    """用给定的菜单项构建一个右键菜单对话框 (以 AlertDialog 承载)."""
    return ft.AlertDialog(
        content=ft.Container(
            content=ft.Column(items, spacing=2, tight=True),
            width=280,
            padding=ft.Padding(left=24, right=24, top=24, bottom=24),
        ),
        content_padding=ft.Padding(0, 0, 0, 0),
        actions_padding=ft.Padding(0, 0, 0, 0),
        actions=[],
    )


def close_menu(page) -> None:
    """关闭当前打开的菜单对话框."""
    try:
        page.pop_dialog()
    except Exception:
        pass
