"""Flet 启动入口 - 由 flet build 调用"""

from filecollector.gui_flet import main

if __name__ == "__main__":
    import flet as ft
    ft.app(target=main)
