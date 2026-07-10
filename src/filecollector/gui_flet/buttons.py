"""统一按钮工厂 (规范按钮尺寸 / 圆角 / 配色 / 层级).

避免在各视图中散落硬编码的 ButtonStyle / RoundedRectangleBorder / padding /
icon_size 与魔法色值。所有按钮按语义分级:

- 主操作 (primary):   实心强调色, 如 确定 / 生成 / 发送 / 打开
- 次操作 (secondary): 文字按钮, 如 取消 / 关闭 / 清空
- 危险操作 (danger):  红色实心, 用于 删除 / 清空 等破坏性动作
- 危险文字 (danger_text): 红色文字按钮, 用于低风险删除确认
- 图标按钮 (icon_btn): 工具栏 / 行内图标
- 圆形按钮 (fab_btn): 回到底部 / 撤回等浮动圆形操作

工厂函数均保留 **kwargs 透传, 调用点可继续传入 disabled / visible /
data / width 等原生参数, 不改变既有回调逻辑.

注意: 当前 Flet 版本的按钮不接受 ``text=`` 关键字, 文字通过
``content=ft.Text(...)`` 表达 (或把字符串作为首个位置参数). 因此工厂统一
用 ``content`` 承载文字; 调用方仍按习惯传 ``text="..."``, 由工厂转换为
``content``. 若调用方已显式传入 ``content`` (如带图标+进度环的复合按钮),
则以显式 ``content`` 为准.

设计原则:
- 按钮的高度 / 图标尺寸 / 圆角 / 形状 (圆形/胶囊) 一律**不手动指定**, 跟随
  Flet 原生默认外观, 不在工厂里强加任何几何样式.
- 仅保留语义配色: 危险操作为红 (danger_btn / danger_text_btn), 生成合并文本
  按钮为蓝 (由调用方显式传 bgcolor=PRIMARY). 其余按钮颜色跟随主题默认.
"""

from __future__ import annotations

import flet as ft

# 语义配色 (集中管理, 不再散写 RED_600 / BLUE_600)
DANGER = ft.Colors.RED_600
PRIMARY = ft.Colors.BLUE_600
ON_PRIMARY = ft.Colors.WHITE


def _label(text: str, color=None) -> ft.Text:
    """把文字包装为 Text, 作为按钮 content."""
    return ft.Text(text, color=color)


def primary_btn(
    text: str,
    on_click=None,
    icon: ft.Icons | None = None,
    **kwargs,
) -> ft.ElevatedButton:
    """主操作按钮.

    默认跟随 Flet 主题外观 (高度/圆角/尺寸均为默认). 需要特定配色 (如生成按钮
    的蓝) 时由调用方显式传入 bgcolor.
    """
    if "content" not in kwargs:
        kwargs["content"] = _label(text)
    return ft.ElevatedButton(icon=icon, on_click=on_click, **kwargs)


def secondary_btn(
    text: str,
    on_click=None,
    **kwargs,
) -> ft.TextButton:
    """次操作按钮: 文字按钮 (取消 / 关闭 / 清空), 保持主题默认配色."""
    if "content" not in kwargs:
        kwargs["content"] = ft.Text(text)
    return ft.TextButton(on_click=on_click, **kwargs)


def danger_btn(
    text: str,
    on_click=None,
    icon: ft.Icons | None = None,
    **kwargs,
) -> ft.ElevatedButton:
    """危险操作按钮: 红色实心 (删除 / 清空 等破坏性动作)."""
    kwargs.setdefault("bgcolor", DANGER)
    kwargs.setdefault("color", ON_PRIMARY)
    if "content" not in kwargs:
        kwargs["content"] = _label(text)
    return ft.ElevatedButton(icon=icon, on_click=on_click, **kwargs)


def danger_text_btn(
    text: str,
    on_click=None,
    **kwargs,
) -> ft.TextButton:
    """危险文字按钮: 红色文字 (低风险删除确认)."""
    kwargs.setdefault("style", ft.ButtonStyle(color=DANGER))
    if "content" not in kwargs:
        kwargs["content"] = ft.Text(text, color=DANGER)
    return ft.TextButton(on_click=on_click, **kwargs)


def icon_btn(
    icon: ft.Icons,
    on_click=None,
    tooltip: str | None = None,
    danger: bool = False,
    **kwargs,
) -> ft.IconButton:
    """图标按钮: 工具栏 / 行内操作. danger=True 时图标显示为红色.

    图标尺寸 / 形状跟随 Flet 默认, 不手动指定.
    """
    if danger:
        kwargs.setdefault("icon_color", DANGER)
    if tooltip is not None:
        kwargs.setdefault("tooltip", tooltip)
    return ft.IconButton(icon=icon, on_click=on_click, **kwargs)


def fab_btn(
    icon: ft.Icons,
    on_click=None,
    tooltip: str | None = None,
    **kwargs,
) -> ft.IconButton:
    """浮动操作按钮: 回到底部 / 撤回等. 形状/尺寸跟随 Flet 默认."""
    if tooltip is not None:
        kwargs.setdefault("tooltip", tooltip)
    return ft.IconButton(icon=icon, on_click=on_click, **kwargs)
