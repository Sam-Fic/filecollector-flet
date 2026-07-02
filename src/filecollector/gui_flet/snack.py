"""Flet SnackBar 工具函数"""

from __future__ import annotations

import flet as ft


def show_snack(page: ft.Page, text: str, duration: int = 4000):
    snack = ft.SnackBar(content=ft.Text(text), duration=duration)
    page.overlay.append(snack)
    snack.open = True
    page.update()
