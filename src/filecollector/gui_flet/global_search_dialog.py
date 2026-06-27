"""全局内容搜索对话框."""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
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
        self._checkboxes: dict[str, list[ft.Checkbox]] = defaultdict(list)
        self._matched_files: set[str] = set()
        self._selected_files: set[str] = set()
        self._pending_results: list[tuple[str, str, int, str]] = []
        self._file_count: int = 0

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

        self._status_label = ft.Text(
            "", size=12, color=ft.Colors.GREY_600, visible=False)
        self._spinner = ft.ProgressRing(
            width=16, height=16, stroke_width=2, visible=False)

        self._result_list = ft.ListView(expand=True, spacing=2)

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

        if self._cancel_event:
            self._cancel_event.set()

        self._cancel_event = threading.Event()
        self._result_list.controls.clear()
        self._checkboxes.clear()
        self._matched_files.clear()
        self._selected_files.clear()
        self._pending_results.clear()
        self._file_count = 0

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

    # ── 后台线程回调 ──────────────────────────────────────────

    def _on_result(self, file_path: str, rel_path: str,
                   line_number: int, line_content: str):
        self._matched_files.add(file_path)
        self._pending_results.append(
            (file_path, rel_path, line_number, line_content))

    def _on_progress(self, scanned: int, matched: int):
        self._safe_update_ui(
            self._status_label,
            _("已扫描 %d 个文件，找到 %d 个匹配项...") % (scanned, matched))

    def _on_finished(self, total_scanned: int, total_matched: int):
        results = list(self._pending_results)
        n_files = len(self._matched_files)
        self._file_count = n_files

        def _build():
            self._spinner.visible = False
            self._status_label.value = _(
                "搜索完成：扫描 %d 个文件，找到 %d 个匹配项（涉及 %d 个独立文件）"
            ) % (total_scanned, total_matched, n_files)

            self._result_list.controls.clear()
            self._checkboxes.clear()
            self._selected_files.clear()

            for file_path, rel_path, line_number, line_content in results:
                self._add_result_row(file_path, rel_path,
                                     line_number, line_content)

            has = n_files > 0
            self._btn_add_selected.disabled = not has
            self._btn_add_all.disabled = not has
            self._btn_toggle_select.disabled = not has
            self._apply_labels()
            self.main_view.page.update()

        self._run_on_ui(_build)

    # ── 线程安全 UI 调度 ──────────────────────────────────────

    def _run_on_ui(self, fn) -> None:
        """把回调安全地送到 UI 线程 (asyncio 线程安全调度)."""
        page = self.main_view.page
        if page is None:
            return
        try:
            loop = page.loop
            if loop and loop.is_running():
                loop.call_soon_threadsafe(fn)
                return
        except Exception:
            pass
        # fallback: 直接调用
        try:
            fn()
        except Exception:
            pass

    def _safe_update_ui(self, control, value) -> None:
        """后台线程安全更新单个控件属性."""
        def _do():
            control.value = value
            self.main_view.page.update()
        self._run_on_ui(_do)

    # ── 结果行构建 (UI 线程) ──────────────────────────────────

    def _add_result_row(self, file_path, rel_path, line_number, line_content):
        check = ft.Checkbox(value=(file_path in self._selected_files))

        def _on_change(e):
            if check.value:
                self._selected_files.add(file_path)
            else:
                self._selected_files.discard(file_path)
            for cb in self._checkboxes.get(file_path, []):
                if cb is not check:
                    cb.value = check.value
            self._apply_labels()
            self.main_view.page.update()

        check.on_change = _on_change
        self._checkboxes[file_path].append(check)

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

    # ── 按钮交互 (UI 线程) ──────────────────────────────────

    def _apply_labels(self):
        n_sel = len(self._selected_files)
        n_all = self._file_count
        all_sel = n_all > 0 and n_sel >= n_all
        self._btn_toggle_select.text = _("全不选") if all_sel else _("全选")
        self._btn_add_selected.text = _("添加选中文件到编排列表 (%d)") % n_sel
        self._btn_add_all.text = _("添加全部 (%d)") % n_all

    def _on_toggle_select(self, e):
        all_sel = (self._file_count > 0
                   and len(self._selected_files) >= self._file_count)
        if all_sel:
            self._selected_files.clear()
            for cbs in self._checkboxes.values():
                for cb in cbs:
                    cb.value = False
        else:
            self._selected_files = set(self._matched_files)
            for fp, cbs in self._checkboxes.items():
                for cb in cbs:
                    cb.value = True
        self._apply_labels()
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
