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
        # 多选: 用 set 存 commit.hash; 单选时此 set 仅含一个元素
        self._selected_hashes: set[str] = set()
        self._anchor_hash: Optional[str] = None  # shift+click 范围选的锚点
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
            on_blur=lambda e: self._ensure_keyboard_focus(),
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

        # 面板内容 (Column) 用 KeyboardListener 包装, 用于追踪 Ctrl/Shift 状态.
        panel_content = ft.Column(
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
        )
        self.keyboard_listener = ft.KeyboardListener(
            content=panel_content,
            autofocus=True,
            on_key_down=self._on_key_down,
            on_key_up=self._on_key_up,
        )

        # 面板容器 (与 FileTreePanel 同级, 用于切换)
        self.container = ft.Container(
            content=self.keyboard_listener,
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
            self._selected_hashes.clear()
            self._anchor_hash = None
            return

        self.search_field.visible = True
        self.commit_list.controls.clear()
        self._selected_hashes.clear()
        self._anchor_hash = None
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
        is_selected = commit.hash in self._selected_hashes

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
            bgcolor=ft.Colors.PRIMARY_CONTAINER if is_selected else None,
            on_click=lambda e, c=commit: self._on_commit_row_click(c),
            ink=True,
            tooltip=f"{commit.short_hash} - {commit.message}\n{commit.author} | {commit.date}",
        )
        return ft.GestureDetector(
            content=container,
            on_secondary_tap=lambda e, c=commit: self._on_commit_right_click(c, e),
        )

    def _on_commit_right_click(self, commit: GitCommit, e):
        """右键 commit: 弹出上下文菜单."""
        from filecollector.gui_flet.snack import show_snack

        def _copy_short_hash(ev):
            self.main_view.page.set_clipboard(commit.short_hash)
            show_snack(self.main_view.page,
                       _("已复制短哈希: %s") % commit.short_hash)
            self.main_view.page.pop_dialog()

        def _copy_full_hash(ev):
            self.main_view.page.set_clipboard(commit.hash)
            show_snack(self.main_view.page,
                       _("已复制完整哈希: %s") % commit.hash)
            self.main_view.page.pop_dialog()

        def _copy_message(ev):
            self.main_view.page.set_clipboard(commit.message)
            show_snack(self.main_view.page, _("已复制提交信息"))
            self.main_view.page.pop_dialog()

        items = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Text(commit.short_hash, size=13,
                                weight=ft.FontWeight.BOLD,
                                font_family="monospace"),
                        ft.Text(commit.message[:40], size=12,
                                color=ft.Colors.GREY_600,
                                expand=True, no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=8,
                ),
                padding=ft.Padding(left=8, top=4, right=8, bottom=4),
            ),
            ft.Divider(height=8, thickness=1),
            self._ctx_menu_item(
                ft.Icons.CONTENT_COPY, _("复制短哈希 (%s)") % commit.short_hash,
                _copy_short_hash),
            self._ctx_menu_item(
                ft.Icons.TAG, _("复制完整哈希"),
                _copy_full_hash),
            self._ctx_menu_item(
                ft.Icons.MESSAGE, _("复制提交信息"),
                _copy_message),
        ]

        dlg = ft.AlertDialog(
            content=ft.Container(
                content=ft.Column(items, spacing=2, tight=True),
                width=280,
                padding=ft.Padding(left=24, right=24, top=20, bottom=20),
            ),
            content_padding=ft.Padding(0, 0, 0, 0),
            actions_padding=ft.Padding(0, 0, 0, 0),
            actions=[],
        )
        self.main_view.page.show_dialog(dlg)

    @staticmethod
    def _ctx_menu_item(icon: str, text: str, on_click) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=18, color=ft.Colors.GREY_700),
                    ft.Text(text, size=13, expand=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            border_radius=6,
            on_click=on_click,
            ink=True,
        )

    def _on_commit_row_click(self, commit: GitCommit):
        """Commit 行点击包装: 确保键盘焦点后再走多选逻辑."""
        self._ensure_keyboard_focus()
        self._on_commit_click(commit)

    def _on_commit_click(self, commit: GitCommit):
        """点击 commit: 支持 Ctrl/Shift 多选.

        - 普通点击: 单选 (清空其他)
        - Ctrl+点击: 切换该 commit 选中状态
        - Shift+点击: 从锚点到该 commit 范围全选

        注意: Flet 的 ControlEvent 不暴露 ctrl/shift 修饰键,
        必须通过 main_view 全局跟踪的 _ctrl_held / _shift_held 读取.
        """
        ctrl = bool(getattr(self.main_view, "_ctrl_held", False))
        shift = bool(getattr(self.main_view, "_shift_held", False))

        if shift and self._anchor_hash is not None:
            # 范围选: 在 _filtered_commits 中找到锚点和当前, 全选中间
            idx_anchor = next((i for i, c in enumerate(self._filtered_commits)
                               if c.hash == self._anchor_hash), None)
            idx_cur = next((i for i, c in enumerate(self._filtered_commits)
                            if c.hash == commit.hash), None)
            if idx_anchor is not None and idx_cur is not None:
                lo, hi = min(idx_anchor, idx_cur), max(idx_anchor, idx_cur)
                self._selected_hashes = {
                    c.hash for c in self._filtered_commits[lo:hi + 1]
                }
        elif ctrl:
            if commit.hash in self._selected_hashes:
                self._selected_hashes.discard(commit.hash)
            else:
                self._selected_hashes.add(commit.hash)
            self._anchor_hash = commit.hash
        else:
            # 普通点击: 单选
            self._selected_hashes = {commit.hash}
            self._anchor_hash = commit.hash

        self._rebuild_list()
        self.main_view.page.update()

        # 通知 main_view 预览首个选中 commit 的 diff
        first = self.first_selected_commit
        if first and hasattr(self.main_view, "on_git_commit_selected"):
            self.main_view.on_git_commit_selected(first)

    def _on_key_down(self, e: ft.KeyDownEvent):
        """键盘按下: 跟踪 Ctrl / Shift 修饰键."""
        key = e.key.upper()
        if "CONTROL" in key or "CTRL" in key:
            self.main_view._ctrl_held = True
        elif "SHIFT" in key:
            self.main_view._shift_held = True

    def _on_key_up(self, e: ft.KeyUpEvent):
        """键盘释放: 跟踪 Ctrl / Shift 修饰键."""
        key = e.key.upper()
        if "CONTROL" in key or "CTRL" in key:
            self.main_view._ctrl_held = False
        elif "SHIFT" in key:
            self.main_view._shift_held = False

    def _ensure_keyboard_focus(self):
        """确保 KeyboardListener 持有焦点, 以便持续接收按键事件."""
        try:
            self.main_view.page.run_task(self.keyboard_listener.focus())
        except Exception:
            pass

    # ============================================================== 外部 API
    @property
    def selected_commit(self) -> Optional[GitCommit]:
        """向后兼容: 返回首个选中 commit (无选中返回 None)."""
        return self.first_selected_commit

    @property
    def first_selected_commit(self) -> Optional[GitCommit]:
        """返回 _filtered_commits 中第一个被选中的 commit."""
        for c in self._filtered_commits:
            if c.hash in self._selected_hashes:
                return c
        return None

    @property
    def selected_commits(self) -> list[GitCommit]:
        """返回所有选中 commit, 按 _filtered_commits 显示顺序 (最新在前)."""
        return [c for c in self._filtered_commits if c.hash in self._selected_hashes]

    def clear_selection(self):
        """清除选中状态."""
        self._selected_hashes.clear()
        self._anchor_hash = None
        self._rebuild_list()
