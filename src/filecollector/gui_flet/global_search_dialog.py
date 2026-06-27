"""全局内容搜索对话框.

对齐 GNOME 版 global_search_dialog.vala:
- 搜索框 + 大小写切换
- 后台异步扫描, 实时更新结果列表
- 结果行: 文件路径 + 行号 + 匹配内容
- 全选/全不选 + 添加选中文件 / 添加全部
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.i18n import _
from filecollector.gui_flet.search_service import SearchService


class GlobalSearchDialog(ft.AlertDialog):
    """全局内容搜索对话框."""

    def __init__(self, main_view):
        self.main_view = main_view
        self._search_service: Optional[SearchService] = None
        self._cancel_event: Optional[threading.Event] = None
        # 文件路径 -> checkbox 控件映射 (全选/全不选时同步)
        self._checkboxes: dict[str, ft.Checkbox] = {}
        self._matched_files: set[str] = set()
        self._selected_files: set[str] = set()

        # 搜索框
        self._search_field = ft.TextField(
            hint_text=_("输入要搜索的代码内容… (按 Enter 搜索)"),
            expand=True,
            on_submit=lambda e: self._trigger_search(),
        )
        self._case_toggle = ft.IconButton(
            icon=ft.Icons.TEXT_FIELDS,
            tooltip=_("区分大小写"),
            selected=False,
            on_click=self._on_case_toggle,
        )

        # 状态标签
        self._status_label = ft.Text(
            "", size=12, color=ft.Colors.GREY_600, visible=False)
        self._spinner = ft.ProgressRing(
            width=16, height=16, stroke_width=2, visible=False)

        # 结果列表
        self._result_list = ft.ListView(
            expand=True,
            spacing=2,
        )

        # 按钮
        self._btn_toggle_select = ft.ElevatedButton(
            _("全选"), on_click=self._on_toggle_select, disabled=True)
        self._btn_add_selected = ft.ElevatedButton(
            _("添加选中文件到编排列表 (0)"),
            icon=ft.Icons.ADD,
            on_click=self._on_add_selected,
            disabled=True,
        )
        self._btn_add_all = ft.ElevatedButton(
            _("添加全部 (0)"),
            icon=ft.Icons.ADD_TASK,
            on_click=self._on_add_all,
            disabled=True,
        )

        super().__init__(
            title=ft.Text(_("全局内容搜索")),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                self._search_field,
                                self._case_toggle,
                                ft.IconButton(
                                    icon=ft.Icons.SEARCH,
                                    tooltip=_("搜索"),
                                    on_click=lambda e: self._trigger_search(),
                                ),
                            ],
                            spacing=4,
                        ),
                        ft.Row(
                            [self._spinner, self._status_label],
                            spacing=8,
                        ),
                        ft.Container(
                            content=self._result_list,
                            expand=True,
                            height=350,
                        ),
                        ft.Row(
                            [
                                self._btn_toggle_select,
                                ft.Container(expand=True),
                                self._btn_add_selected,
                                self._btn_add_all,
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=8,
                        ),
                    ],
                    spacing=8,
                    expand=True,
                ),
                width=650,
                height=500,
            ),
            actions=[
                ft.TextButton(_("关闭"), on_click=self._on_close),
            ],
        )

    def _on_case_toggle(self, e):
        self._case_toggle.selected = not self._case_toggle.selected
        self._case_toggle.icon = (
            ft.Icons.TEXT_FIELDS if not self._case_toggle.selected
            else ft.Icons.FORMAT_SIZE
        )
        self.main_view.page.update()

    def _trigger_search(self):
        keyword = (self._search_field.value or "").strip()
        if not keyword:
            return

        work_dir = self.main_view.engine.work_dir
        if not work_dir:
            return

        # 取消前一次搜索
        if self._cancel_event:
            self._cancel_event.set()

        self._cancel_event = threading.Event()
        self._result_list.controls.clear()
        self._checkboxes.clear()
        self._matched_files.clear()
        self._selected_files.clear()

        self._spinner.visible = True
        self._status_label.visible = True
        self._status_label.value = _("正在扫描文件树...")
        self._btn_add_selected.disabled = True
        self._btn_add_all.disabled = True
        self._btn_toggle_select.disabled = True
        self.main_view.page.update()

        self._search_service = SearchService(
            root_dir=str(work_dir),
            query=keyword,
            case_sensitive=self._case_toggle.selected,
            cancel_event=self._cancel_event,
            on_result=self._on_result,
            on_progress=self._on_progress,
            on_finished=self._on_finished,
        )
        self._search_service.start()

    # ── 搜索回调 (来自后台线程, 只收集数据, 不操作 UI) ──────────

    def _on_result(self, file_path: str, rel_path: str,
                   line_number: int, line_content: str):
        """单条搜索结果回调 (后台线程)."""
        self._matched_files.add(file_path)
        # 传递数据到 UI 线程创建控件
        async def _add():
            check = ft.Checkbox(value=False)
            self._checkboxes[file_path] = check

            def _on_check(e):
                if check.value:
                    self._selected_files.add(file_path)
                else:
                    self._selected_files.discard(file_path)
                self._sync_button_labels()

            check.on_change = _on_check

            row = ft.Container(
                content=ft.Row(
                    [
                        check,
                        ft.Column(
                            [
                                ft.Text(
                                    f"{rel_path} : {line_number}",
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                                ft.Text(
                                    line_content.strip()[:200],
                                    size=12,
                                    font_family="monospace",
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                            tight=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding(left=8, top=6, right=8, bottom=6),
                border_radius=6,
            )
            self._result_list.controls.append(row)
            self._sync_button_labels()
            self.main_view.page.update()

        self._post(_add)

    def _on_progress(self, scanned: int, matched: int):
        async def _update():
            self._status_label.value = _(
                "已扫描 %d 个文件，找到 %d 个匹配项...") % (scanned, matched)
            self.main_view.page.update()
        self._post(_update)

    def _on_finished(self, total_scanned: int, total_matched: int):
        async def _update():
            self._spinner.visible = False
            self._status_label.value = _(
                "搜索完成：扫描 %d 个文件，找到 %d 个匹配项（涉及 %d 个独立文件）"
            ) % (total_scanned, total_matched, len(self._matched_files))
            has = len(self._matched_files) > 0
            self._btn_add_selected.disabled = not has
            self._btn_add_all.disabled = not has
            self._btn_toggle_select.disabled = not has
            self._sync_button_labels()
            self.main_view.page.update()
        self._post(_update)

    def _post(self, async_fn) -> None:
        """把 async 回调安全地送到 Flet UI 线程."""
        page = getattr(self.main_view, "page", None)
        if page is None:
            return
        try:
            page.run_task(async_fn)
        except Exception:
            pass

    # ── 按钮交互 (UI 线程) ──────────────────────────────────

    def _sync_button_labels(self):
        """同步按钮文字 (根据 _matched_files / _selected_files)."""
        n_sel = len(self._selected_files)
        n_all = len(self._matched_files)
        all_selected = n_all > 0 and n_sel >= n_all
        self._btn_toggle_select.text = _("全不选") if all_selected else _("全选")
        self._btn_add_selected.text = _("添加选中文件到编排列表 (%d)") % n_sel
        self._btn_add_all.text = _("添加全部 (%d)") % n_all

    def _on_toggle_select(self, e):
        all_selected = (len(self._matched_files) > 0
                        and len(self._selected_files) >= len(self._matched_files))
        if all_selected:
            self._selected_files.clear()
            for fp, cb in self._checkboxes.items():
                cb.value = False
        else:
            self._selected_files = set(self._matched_files)
            for fp, cb in self._checkboxes.items():
                cb.value = True
        self._sync_button_labels()
        self.main_view.page.update()

    def _on_add_selected(self, e):
        if not self._selected_files:
            return
        self._add_files_to_list(list(self._selected_files))

    def _on_add_all(self, e):
        if not self._matched_files:
            return
        self._add_files_to_list(list(self._matched_files))

    def _add_files_to_list(self, paths: list[str]):
        """将搜索结果中的文件添加到编排列表."""
        self.main_view._push_undo()
        added = 0
        for p in paths:
            if not self.main_view._path_in_items(p):
                from filecollector.models import ItemData
                self.main_view.engine.items.append(
                    ItemData("file", path=p, force_absolute=False))
                self.main_view.file_tree_panel.checked_paths.add(p)
                added += 1
        self.main_view.file_tree_panel.refresh()
        self.main_view.arrangement_panel.refresh()
        runner = getattr(self.main_view, "preprocess_runner", None)
        if runner:
            try:
                runner.reevaluate_queue()
            except Exception:
                pass
        self._on_close(None)
        from filecollector.gui_flet.snack import show_snack
        show_snack(self.main_view.page,
                   _("已从搜索结果添加 %d 个文件") % added)

    def _on_close(self, e):
        if self._cancel_event:
            self._cancel_event.set()
        try:
            self.main_view.page.pop_dialog()
        except Exception:
            pass
