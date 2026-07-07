"""预览面板 - 右侧面板.

设计原则 (按用户要求简化):
- 不显示文件名, 不显示状态徽标/分割线/独立按钮区
- 仅在内容区右上角悬浮一个"重新进行 AI 转换"按钮 (仅 binary 条目可见)
- 内容渲染:
  - 普通文本/文本条目: ft.Text
  - 视觉语言大模型 (VLM) 预处理过的二进制: ft.Markdown 渲染 preprocessed_content
  - 其他状态: 显示简洁的状态文字
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.models import ItemData, PreprocessStatus
from filecollector.utils import safe_read_file
from filecollector.i18n import _

# Markdown 预览内容长度上限，避免超大内容导致 Flutter 渲染/同步卡顿
_MAX_MD_PREVIEW_CHARS = 100_000


class PreviewPanel:
    """右侧预览面板"""

    def __init__(self, main_view):
        self.main_view = main_view
        self._current_item: Optional[ItemData] = None
        self._build_ui()

    # ============================================================== UI 构建
    def _build_ui(self):
        # 内容显示
        self.content_md = ft.Markdown(
            value="",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.GITHUB,
            expand=True,
        )
        self.content_text = ft.Text(
            "",
            size=13,
            no_wrap=False,
            selectable=True,
        )

        # 悬浮按钮: 重新进行 AI 转换 (仅 binary 条目可见)
        self.btn_retry = ft.ElevatedButton(
            _("重新进行 AI 转换"),
            icon=ft.Icons.REFRESH,
            on_click=self._on_retry_preprocess,
            visible=False,
            tooltip=_("重新进行 AI 转换"),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=20),
                padding=ft.Padding(left=14, top=8, right=14, bottom=8),
                bgcolor=ft.Colors.with_opacity(0.92, ft.Colors.SURFACE),
                side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                elevation=2,
            ),
        )

        # 内容区: Stack 让按钮悬浮在内容右上角.
        # fit=EXPAND 让 Stack 占满整个预览卡片内容区, 而不是随内部文字宽度收缩,
        # 这样 right=12 才会相对于卡片右上角对齐, 避免内容窄时按钮被裁切.
        self.content_stack = ft.Stack(
            [
                ft.Column(
                    [self.content_md, self.content_text],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    spacing=0,
                ),
                ft.Container(
                    content=self.btn_retry,
                    right=12,
                    top=8,
                ),
            ],
            expand=True,
            fit=ft.StackFit.EXPAND,
        )

        # 面板容器
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
                        content=self.content_stack,
                        expand=True,
                        padding=ft.Padding(left=12, right=12, bottom=8, top=0),
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

    # ============================================================== 内容控制
    def _set_md_visible(self, visible: bool) -> None:
        try:
            self.content_md.visible = visible
        except Exception:
            pass

    def _set_text_visible(self, visible: bool) -> None:
        try:
            self.content_text.visible = visible
        except Exception:
            pass

    def _set_retry_visible(self, visible: bool) -> None:
        try:
            self.btn_retry.visible = visible
        except Exception:
            pass

    def _set_retry_enabled(self, enabled: bool) -> None:
        try:
            self.btn_retry.disabled = not enabled
        except Exception:
            pass

    # ============================================================== 主入口
    def show_preview(self, data: ItemData):
        self._current_item = data

        if data.type == "text":
            self._show_text(data.content or "")
            self._set_retry_visible(False)
            return

        if data.type != "file":
            self._show_text(str(data.content or ""))
            self._set_retry_visible(False)
            return

        # 文件: 判断是否 binary (走 VLM 预览) 或普通文本
        runner = getattr(self.main_view, "preprocess_runner", None)
        allowed = runner.get_allowed_exts() if runner else []
        is_binary = data.is_allowed_binary_target(allowed)

        if is_binary:
            self._show_binary(data)
        else:
            self._show_text_file(data)

    # ============================================================== 文本文件
    def _show_text_file(self, data: ItemData) -> None:
        if not data.path or not os.path.exists(data.path):
            self._show_text(_("[文件不存在]"))
            self._set_retry_visible(False)
            return
        try:
            # 片段条目需要读取完整内容以提取指定行范围
            full = data.is_snippet()
            content, enc = safe_read_file(
                data.path, max_preview_lines=None if full else 80)
            # 片段条目: 仅提取指定行范围 (1-based) 预览
            if data.is_snippet():
                lines = content.split("\n")
                s = max(0, data.start_line - 1)
                e = min(len(lines), data.end_line)
                snippet = "\n".join(lines[s:e])
                self._show_text(
                    _("--- 片段预览 %s [L%d-L%d] (编码: %s) ---\n%s")
                    % (Path(data.path).name, data.start_line, data.end_line, enc, snippet)
                )
                return
            if Path(data.path).suffix.lower() in {".md", ".markdown"}:
                self.content_md.value = content
                self._set_md_visible(True)
                self._set_text_visible(False)
            else:
                self._show_text(
                    _("--- 文件预览 (编码: %s) ---\n%s") % (enc, content)
                )
        except Exception as e:
            self._show_text(_("读取错误: %s") % e)
        self._set_retry_visible(False)

    # ============================================================== 文本条目
    def _show_text(self, text: str) -> None:
        self._set_md_visible(False)
        self._set_text_visible(True)
        self.content_text.value = text

    # ============================================================== 二进制 + VLM
    def _show_binary(self, data: ItemData) -> None:
        st = data.preprocess_status
        # 转换进行中 (PENDING/CHECKING/PROCESSING) 时不显示按钮
        # 其余状态 (NONE/COMPLETED/FAILED) 显示按钮
        in_progress = st in (
            PreprocessStatus.PENDING,
            PreprocessStatus.CHECKING,
            PreprocessStatus.PROCESSING,
        )
        if in_progress:
            self._set_retry_visible(False)
        else:
            self._set_retry_visible(True)
            self._set_retry_enabled(True)

        # 内容: 若已完成, 渲染 markdown; 否则给提示
        if data.preprocessed_content and st == PreprocessStatus.COMPLETED:
            md = data.preprocessed_content
            if len(md) > _MAX_MD_PREVIEW_CHARS:
                md = md[:_MAX_MD_PREVIEW_CHARS] + _(
                    "\n\n---\n\n*（内容过长，已截断显示前 %d 个字符）*"
                ) % _MAX_MD_PREVIEW_CHARS
            # 先赋值再显示, 避免 Markdown 控件在空值与显示状态切换时 Flutter 侧卡顿
            self.content_md.value = md
            self._set_md_visible(True)
            self._set_text_visible(False)
        else:
            self._set_md_visible(False)
            self._set_text_visible(True)
            if st == PreprocessStatus.FAILED:
                self.content_text.value = _(
                    "AI 转换失败。\n\n可点击右上角 '重新进行 AI 转换' 按钮重试。")
            elif st == PreprocessStatus.PROCESSING:
                self.content_text.value = _("AI 正在转换中, 请稍候…")
            elif st == PreprocessStatus.CHECKING:
                self.content_text.value = _("正在检查本地缓存…")
            elif st == PreprocessStatus.PENDING:
                self.content_text.value = _("等待处理 (排队中)…")
            else:
                self.content_text.value = _("尚未开始处理。")

        try:
            self.preview_container.update()
        except Exception:
            try:
                self.main_view.page.update()
            except Exception:
                pass

    # ============================================================== 按钮事件
    def _on_retry_preprocess(self, e):
        item = self._current_item
        if item is None:
            return
        runner = getattr(self.main_view, "preprocess_runner", None)
        if runner is None:
            return
        if item.type != "file":
            return
        try:
            runner.retry(item)
            self._show_binary(item)
        except Exception:
            pass

    # ============================================================== Diff 预览
    def show_diff(self, title: str, diff_text: str):
        """渲染 diff 内容到预览区 (按文件分段 + 紫色分隔线)."""
        self._current_item = None
        self._set_retry_visible(False)

        sections = self._split_diff_by_file(diff_text)
        parts = [f"**{title}**\n"]
        for fname, body in sections:
            if fname:
                parts.append(f"\n---\n\n##### `{fname}`\n")
            parts.append(f"\n```diff\n{body}\n```")

        md_content = "\n".join(parts)
        # 先赋值再显示, 避免 Markdown 控件空值切换时 Flutter 侧卡顿
        self.content_md.value = md_content
        self._set_md_visible(True)
        self._set_text_visible(False)

        try:
            self.preview_container.update()
        except Exception:
            try:
                self.main_view.page.update()
            except Exception:
                pass

    @staticmethod
    def _split_diff_by_file(diff_text: str) -> list[tuple[str, str]]:
        """将 diff 按 'diff --git' 行切分为 [(filename, body), ...]."""
        import re
        chunks: list[tuple[str, str]] = []
        current_file = ""
        current_lines: list[str] = []

        for line in diff_text.split("\n"):
            if line.startswith("diff --git"):
                if current_lines:
                    chunks.append((current_file, "\n".join(current_lines)))
                current_lines = [line]
                m = re.search(r" b/(.+)$", line)
                current_file = m.group(1) if m else ""
            else:
                current_lines.append(line)

        if current_lines:
            chunks.append((current_file, "\n".join(current_lines)))

        return chunks if chunks else [("", diff_text)]

    def show_raw_text(self, text: str):
        """显示纯文本 (无 Markdown), 用于加载中提示等."""
        self._set_md_visible(False)
        self._set_text_visible(True)
        self.content_text.value = text

    # ============================================================== 清空
    def clear(self):
        self._current_item = None
        self.content_text.value = ""
        try:
            self.content_md.value = ""
        except Exception:
            pass
        self._set_md_visible(False)
        self._set_text_visible(True)
        self._set_retry_visible(False)
        try:
            self.preview_container.update()
        except Exception:
            try:
                self.main_view.page.update()
            except Exception:
                pass
