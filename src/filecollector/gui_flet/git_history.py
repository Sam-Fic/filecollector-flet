"""Git 提交历史面板 - 左侧面板 Git 模式.

对齐 GNOME 版 git_page 功能:
- 加载最近 100 条 commit 记录
- 支持按提交信息或哈希搜索
- 点击 commit 在右侧预览区渲染 Diff
- 选中 commit 后启用 "导出选中 Commit Diff" 按钮
"""

from __future__ import annotations

import threading
from typing import Optional

import flet as ft

from filecollector.i18n import _
from filecollector.git_service import GitCommit, get_log, GitError


class GitHistoryPanel:
    """Git 提交历史面板 (左栏 Git 模式)."""

    def __init__(self, main_view):
        self.main_view = main_view
        self._commits: list[GitCommit] = []
        self._filtered_commits: list[GitCommit] = []
        self._selected_commit: Optional[GitCommit] = None
        self._search_text: str = ""

        self._build_ui()

    # ============================================================== UI 构建
    def _build_ui(self):
        # 搜索框
        self.search_field = ft.TextField(
            hint_text=_("搜索提交信息…"),
            prefix_icon=ft.Icons.SEARCH,
            border_radius=8,
            content_padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            text_size=14,
            height=36,
            on_change=self._on_search_change,
        )

        # 提交列表
        self.commit_list = ft.ListView(
            expand=True,
            spacing=2,
            padding=ft.Padding(left=4, right=4, top=0, bottom=0),
        )

        # 加载状态
        self.status_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.GREY_600,
            text_align=ft.TextAlign.CENTER,
        )

        # 面板容器 (与 FileTreePanel 同级, 用于切换)
        self.container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            _("Git 提交历史"),
                            weight=ft.FontWeight.BOLD,
                            size=16,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.Padding(top=10, bottom=10, left=0, right=0),
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=self.search_field,
                        padding=ft.Padding(left=12, right=12, bottom=8, top=0),
                    ),
                    ft.Container(
                        content=ft.Column(
                            [self.commit_list],
                            spacing=0,
                            expand=True,
                        ),
                        expand=True,
                        padding=ft.Padding(left=8, right=8, top=0, bottom=0),
                    ),
                    ft.Container(
                        content=self.status_text,
                        padding=ft.Padding(left=12, right=12, top=4, bottom=8),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=12,
            padding=0,
        )

    # ============================================================== 数据加载
    def load_git_history(self, work_dir: str):
        """异步加载 Git 提交历史."""
        if not work_dir:
            self.search_field.visible = False
            self.status_text.value = _("尚未设置工作目录")
            self.status_text.color = ft.Colors.GREY_600
            self.commit_list.controls.clear()
            self._selected_commit = None
            return

        self.search_field.visible = True
        self.commit_list.controls.clear()
        self._selected_commit = None
        self.main_view.page.update()

        def _load():
            try:
                commits = get_log(work_dir, max_count=100)
                error_msg = None
            except GitError as e:
                commits = []
                error_msg = str(e)
            except Exception as e:
                commits = []
                error_msg = str(e)

            self.main_view.page.run_task(
                self._on_load_finished, commits, error_msg,
            )

        thread = threading.Thread(target=_load, daemon=True)
        thread.start()

    async def _on_load_finished(
        self, commits: list[GitCommit], error_msg: Optional[str],
    ):
        if error_msg:
            self.status_text.value = _("Git 日志加载失败: %s") % error_msg
            self.status_text.color = ft.Colors.RED_600
            self.main_view.page.update()
            return

        self._commits = commits
        self._apply_filter()
        if commits:
            self.status_text.value = _("已加载 %d 条提交记录") % len(commits)
            self.status_text.color = ft.Colors.GREEN_700
        else:
            self.status_text.value = _("暂无提交记录")
            self.status_text.color = ft.Colors.GREY_600
        self.main_view.page.update()

    # ============================================================== 搜索过滤
    def _on_search_change(self, e):
        self._search_text = (self.search_field.value or "").strip().lower()
        self._apply_filter()
        self.main_view.page.update()

    def _apply_filter(self):
        self._filtered_commits.clear()
        for c in self._commits:
            if self._search_text:
                if (self._search_text not in c.message.lower()
                        and self._search_text not in c.short_hash.lower()):
                    continue
            self._filtered_commits.append(c)
        self._rebuild_list()

    def _rebuild_list(self):
        self.commit_list.controls.clear()
        for commit in self._filtered_commits:
            self.commit_list.controls.append(self._build_commit_row(commit))

    # ============================================================== 列表项构建
    def _build_commit_row(self, commit: GitCommit) -> ft.Control:
        """构建单条 commit 行."""
        is_selected = (self._selected_commit is not None
                       and self._selected_commit.hash == commit.hash)

        hash_text = ft.Text(
            commit.short_hash,
            size=12,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.BLUE_700,
            font_family="monospace",
            no_wrap=True,
        )
        msg_text = ft.Text(
            commit.message,
            size=13,
            expand=True,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        date_text = ft.Text(
            commit.date[:10],
            size=11,
            color=ft.Colors.GREY_600,
            no_wrap=True,
        )

        row = ft.Row(
            [hash_text, msg_text, date_text],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        container = ft.Container(
            content=row,
            padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            border_radius=6,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW if is_selected else None,
            on_click=lambda e, c=commit: self._on_commit_click(c),
            ink=True,
            tooltip=f"{commit.short_hash} - {commit.message}\n{commit.author} | {commit.date}",
        )
        return container

    def _on_commit_click(self, commit: GitCommit):
        """点击 commit: 选中并触发预览."""
        self._selected_commit = commit
        self._rebuild_list()
        self.main_view.page.update()

        # 通知 main_view 预览 diff
        if hasattr(self.main_view, "on_git_commit_selected"):
            self.main_view.on_git_commit_selected(commit)

    # ============================================================== 外部 API
    @property
    def selected_commit(self) -> Optional[GitCommit]:
        return self._selected_commit

    def clear_selection(self):
        """清除选中状态."""
        self._selected_commit = None
        self._rebuild_list()
