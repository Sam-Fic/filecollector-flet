"""预览面板 - 右侧面板"""

from __future__ import annotations

import os

import flet as ft

from filecollector.models import ItemData
from filecollector.utils import safe_read_file
from filecollector.i18n import _


class PreviewPanel:
    """右侧预览面板"""

    def __init__(self, main_view):
        self.main_view = main_view

        self._build_ui()

    def _build_ui(self):
        """构建预览面板 UI"""
        # 预览文本
        self.preview_text = ft.Text(
            "",
            size=13,
            no_wrap=False,
            selectable=True,
        )

        # 预览容器
        self.preview_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            _("预览"),
                            weight=ft.FontWeight.BOLD,
                            size=16,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.Padding(top=10, bottom=10, left=0, right=0),
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=ft.Column(
                            [self.preview_text],
                            scroll=ft.ScrollMode.AUTO,
                            expand=True,
                        ),
                        expand=True,
                        padding=ft.Padding(
                            left=12, right=12, bottom=8, top=0),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=1,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=12,
            padding=0,
        )

    @property
    def container(self):
        return self.preview_container

    def show_preview(self, data: ItemData):
        """显示预览内容"""
        if data.type == "file":
            if not os.path.exists(data.path):
                self.preview_text.value = _("[文件不存在]")
            else:
                try:
                    content, enc = safe_read_file(
                        data.path, max_preview_lines=50)
                    self.preview_text.value = _(
                        "--- 文件预览 (编码: %s) ---\n%s") % (enc, content)
                except Exception as e:
                    self.preview_text.value = _("读取错误: %s") % e
        else:
            self.preview_text.value = data.content

        self.main_view.page.update()

    def clear(self):
        """清空预览"""
        self.preview_text.value = ""
        self.main_view.page.update()
