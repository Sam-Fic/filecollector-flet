"""文件树面板 - 左侧面板.

Flet 版本 - 懒加载 + 三态复选框:

懒加载
------
- 每个目录节点初始无 children, 首次展开时通过 ``on_change`` 回调加载.
- 已加载过的目录会被缓存, 折叠后再展开不会重新扫描.
- 通过 ``IGNORE_DIRS`` 跳过常见构建 / VCS / 缓存目录, 避免不必要扫描.

三态复选框
----------
- 目录使用自定义 ``TreeCheckbox`` 实现 0/1/2 三态:
    0 = 未选 (空白方框)
    1 = 部分选 (方框带横线)
    2 = 全选 (方框带勾)
- 文件夹点击 = 级联: 0/1 → 2 (勾选所有后代文件), 2 → 0 (取消所有后代).
- 每次级联后刷新所有祖先目录的视觉状态.
- 文件状态: 仅维护 ``checked_paths`` 集合, 显示用普通二态.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.i18n import _


# 三态枚举
UNCHECKED = 0
PARTIAL = 1
CHECKED = 2

# 行高 / 缩进 / 箭头占位常量
_ROW_HEIGHT = 36
_INDENT_STEP = 16
_ARROW_WIDTH = 32


class TreeCheckbox(ft.Container):
    """树形复选框控件：同时支持二态/三态，避免 Flet tristate Checkbox 渲染异常."""

    def __init__(self, on_click=None, size: int = 20):
        super().__init__()
        self._state = UNCHECKED
        self._on_click = on_click
        self._size = size
        self._toggling = False
        self.icon_ctrl = ft.Icon(
            icon=ft.Icons.CHECK_BOX_OUTLINE_BLANK, size=size)
        self.content = self.icon_ctrl
        self.width = size + 8
        self.height = size + 8
        self.alignment = ft.alignment.Alignment(0, 0)
        self.border_radius = 4
        self.ink = True
        self.on_click = self._handle_click
        # 记录反向引用 (供父容器刷新)
        self._path_str: Optional[str] = None
        self.set_state(UNCHECKED)

    def bind_path(self, path_str: str) -> None:
        self._path_str = path_str

    def _handle_click(self, e):
        self.toggle()

    def toggle(self) -> None:
        """触发一次点击回调，并防止父容器重复触发导致二次切换."""
        if self._toggling:
            return
        self._toggling = True
        try:
            if self._on_click is not None:
                self._on_click(self._path_str, self._state)
        finally:
            self._toggling = False

    def set_state(self, state: int) -> None:
        self._state = state
        if state == UNCHECKED:
            self.icon_ctrl.icon = ft.Icons.CHECK_BOX_OUTLINE_BLANK
            self.icon_ctrl.color = ft.Colors.GREY_500
        elif state == PARTIAL:
            self.icon_ctrl.icon = ft.Icons.INDETERMINATE_CHECK_BOX
            self.icon_ctrl.color = ft.Colors.BLUE_600
        else:  # CHECKED
            self.icon_ctrl.icon = ft.Icons.CHECK_BOX
            self.icon_ctrl.color = ft.Colors.BLUE_600
        try:
            self.icon_ctrl.update()
        except Exception:
            pass

    @property
    def state(self) -> int:
        return self._state


class _DirNode:
    """目录节点的模型层 - 与 Flet 控件解耦, 支持懒加载."""

    __slots__ = ("path", "children", "loaded")

    def __init__(self, path: Path):
        self.path = path
        self.children: list = []  # list[_DirNode | _FileNode]
        self.loaded = False


class _FileNode:
    __slots__ = ("path",)

    def __init__(self, path: Path):
        self.path = path


class FileTreePanel:
    """左侧文件树面板"""

    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".svn", ".hg",
        "venv", ".idea", ".vscode", "build", "dist", ".cache",
        ".mypy_cache", ".pytest_cache", ".next", ".nuxt", "target",
        ".gradle", ".venv", "env",
    }

    def __init__(self, main_view):
        self.main_view = main_view
        self.work_dir: Optional[Path] = None
        self.checked_paths: set[str] = set()

        # UI 引用
        self._dir_widgets: dict[str, TreeCheckbox] = {}
        self._file_widgets: dict[str, TreeCheckbox] = {}
        self._dir_tiles: dict[str, ft.Column] = {}  # path -> children column
        self._dir_nodes: dict[str, _DirNode] = {}  # path -> model node
        self._dir_arrows: dict[str, ft.Icon] = {}  # path -> arrow icon

        self._build_ui()

    # ============================================================== UI 构建
    def _build_ui(self):
        """构建树面板 UI"""
        # 搜索框
        self.search_field = ft.TextField(
            hint_text=_("搜索…"),
            prefix_icon=ft.Icons.SEARCH,
            border_radius=8,
            content_padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            text_size=14,
            visible=False,
            on_change=self._on_search_change,
            height=_ROW_HEIGHT,
        )

        # 根内容容器（动态填充）
        self.tree_content = ft.Column(
            [],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 面板容器
        self.container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            _("资源管理器"),
                            weight=ft.FontWeight.BOLD,
                            size=16,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.Padding(
                            top=10, bottom=10, left=0, right=0),
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=self.search_field,
                        padding=ft.Padding(
                            left=12, right=12, bottom=8, top=0),
                    ),
                    ft.Container(
                        content=self.tree_content,
                        expand=True,
                        padding=ft.Padding(
                            left=12, right=12, top=0, bottom=0),
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

    # ====================================================== 工作目录 / 刷新
    def set_work_dir(self, work_dir: Path):
        """设置工作目录并刷新树 (根节点不展开, 由用户决定是否展开)."""
        self.work_dir = work_dir
        self.checked_paths.clear()
        self._dir_widgets.clear()
        self._file_widgets.clear()
        self._dir_tiles.clear()
        self._dir_nodes.clear()
        self._dir_arrows.clear()
        self.search_field.visible = True

        # 清空树
        self.tree_content.controls.clear()

        if work_dir and work_dir.exists():
            # 注册根节点
            root_node = _DirNode(work_dir)
            self._dir_nodes[str(work_dir)] = root_node
            # 立即加载根的直接子项, 显示一级文件 (避免空根节点)
            self._load_children(root_node)
            root_node_col = self._build_dir_node(root_node, indent=0)
            self.tree_content.controls.append(root_node_col)
            self._populate_dir_children(root_node)

        self.main_view.page.update()

    def refresh(self):
        """外部调用: 刷新所有 checkbox 显示状态."""
        # 刷新所有文件 checkbox
        for path_str, cb in self._file_widgets.items():
            cb.set_state(
                CHECKED if path_str in self.checked_paths else UNCHECKED)
        # 刷新所有目录三态
        self._refresh_all_dir_displays()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    # ====================================================== 懒加载: 子项加载
    def _load_children(self, node: _DirNode) -> None:
        """扫描目录, 填充 node.children, 跳过忽略目录."""
        if node.loaded:
            return
        node.loaded = True
        try:
            entries = sorted(
                node.path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except (PermissionError, FileNotFoundError, OSError):
            entries = []

        for entry in entries:
            # 隐藏目录跳过
            if entry.name.startswith(".") and entry.is_dir():
                continue
            if entry.name in self.IGNORE_DIRS:
                continue
            if entry.is_dir():
                child = _DirNode(entry)
                self._dir_nodes[str(entry)] = child
                node.children.append(child)
            elif entry.is_file():
                node.children.append(_FileNode(entry))

    def _ensure_dir_loaded(self, dir_path: Path) -> _DirNode:
        """确保某目录已加载, 返回其节点 (若不存在则创建)."""
        path_str = str(dir_path)
        node = self._dir_nodes.get(path_str)
        if node is not None:
            if not node.loaded:
                self._load_children(node)
            return node
        node = _DirNode(dir_path)
        self._dir_nodes[path_str] = node
        self._load_children(node)
        return node

    def _node_indent(self, node: _DirNode) -> int:
        """计算节点在文件树中的层级 (根节点为 0, 直接子节点为 1, 依此类推).

        层级直接决定左侧缩进像素: left_padding = indent * _INDENT_STEP.
        """
        if node.path == self.work_dir:
            return 0
        indent = 0
        current = node.path
        while current != self.work_dir and current != current.parent:
            indent += 1
            current = current.parent
        return indent

    # ====================================================== 构建 UI 节点
    def _build_dir_node(self, node: _DirNode, indent: int) -> ft.Column:
        """为目录节点创建自定义展开节点 (header + children_col)."""
        path_str = str(node.path)
        is_root = self.work_dir is not None and node.path == self.work_dir

        # 自定义箭头（放在最左侧，跟随缩进）
        arrow = ft.Icon(
            ft.Icons.EXPAND_MORE if is_root else ft.Icons.CHEVRON_RIGHT,
            size=18,
            color=ft.Colors.GREY_600,
        )
        self._dir_arrows[path_str] = arrow

        # 三态 checkbox
        cb = TreeCheckbox(
            on_click=self._on_dir_checkbox_click, size=20)
        cb.bind_path(path_str)
        cb.set_state(self._dir_state(node.path))
        self._dir_widgets[path_str] = cb

        # 子节点容器：默认根目录展开，其他折叠
        # 子节点自身会携带 (indent + 1) 的左缩进，因此容器本身不需要额外缩进
        children_col = ft.Column(
            [], spacing=0, visible=is_root)
        self._dir_tiles[path_str] = children_col

        # 标题行：与文件行保持完全一致的高度和结构
        # left_padding = indent * _INDENT_STEP：层级越深，缩进越大
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=arrow,
                        width=_ARROW_WIDTH,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    cb,
                    ft.Icon(ft.Icons.FOLDER, size=18,
                            color=ft.Colors.AMBER_600),
                    ft.Text(node.path.name, size=14,
                            weight=ft.FontWeight.W_500),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=_ROW_HEIGHT,
            padding=ft.Padding(
                left=indent * _INDENT_STEP, top=0, right=12, bottom=0),
            on_click=lambda e, n=node, a=arrow, col=children_col: self._on_dir_expand(
                n, a, col, e),
            ink=True,
            border_radius=4,
        )

        return ft.Column([header, children_col], spacing=0)

    def _populate_dir_children(self, node: _DirNode) -> None:
        """把 node.children 转为实际控件, 填充到目录的子节点容器."""
        path_str = str(node.path)
        children_col = self._dir_tiles.get(path_str)
        if children_col is None:
            return

        # 当前节点层级; 子节点层级 = indent + 1
        indent = self._node_indent(node)

        new_controls: list[ft.Control] = []
        for child in node.children:
            if isinstance(child, _DirNode):
                new_controls.append(self._build_dir_node(child, indent + 1))
            else:
                new_controls.append(
                    self._build_file_row(child.path, indent + 1))
        children_col.controls = new_controls

    def _on_dir_expand(
        self,
        node: _DirNode,
        arrow: ft.Icon,
        children_col: ft.Column,
        e: ft.ControlEvent,
    ) -> None:
        """用户展开/折叠目录时, 懒加载子项并旋转箭头."""
        is_expanded = not children_col.visible
        children_col.visible = is_expanded
        if is_expanded and not node.loaded:
            self._load_children(node)
            self._populate_dir_children(node)
            # 展开后立刻按当前 checked_paths 刷新一次三态
            self._refresh_dir_display(node)
        # 更新箭头方向
        arrow.icon = (
            ft.Icons.EXPAND_MORE if is_expanded else ft.Icons.CHEVRON_RIGHT
        )
        try:
            arrow.update()
            self.main_view.page.update()
        except Exception:
            pass

    def _build_file_row(self, file_path: Path, indent: int) -> ft.Container:
        """创建文件行 (含二态 checkbox)."""
        path_str = str(file_path)
        # 注册到文件 widget 字典 (供 refresh 同步状态)
        # 避免重复创建: 若已存在则不重建
        if path_str in self._file_widgets:
            cb = self._file_widgets[path_str]
        else:
            cb = TreeCheckbox(
                on_click=self._on_file_checkbox_click, size=20)
            cb.bind_path(path_str)
            cb.set_state(
                CHECKED if path_str in self.checked_paths else UNCHECKED)
            self._file_widgets[path_str] = cb

        # 根据扩展名选图标
        ext = file_path.suffix.lower()
        icon_name = ft.Icons.INSERT_DRIVE_FILE
        icon_color = ft.Colors.GREY_500
        if ext in {".py", ".pyi"}:
            icon_name = ft.Icons.CODE
            icon_color = ft.Colors.BLUE_600
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            icon_name = ft.Icons.JAVASCRIPT
            icon_color = ft.Colors.AMBER_600
        elif ext in {".json", ".yaml", ".yml", ".toml", ".xml"}:
            icon_name = ft.Icons.DATA_OBJECT
            icon_color = ft.Colors.TEAL_600
        elif ext in {".md", ".txt", ".rst"}:
            icon_name = ft.Icons.DESCRIPTION
            icon_color = ft.Colors.GREEN_600
        elif ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp",
                     ".svg", ".webp"}:
            icon_name = ft.Icons.IMAGE
            icon_color = ft.Colors.PURPLE_600
        elif ext in {".zip", ".tar", ".gz", ".7z", ".rar"}:
            icon_name = ft.Icons.ARCHIVE
            icon_color = ft.Colors.BROWN_600

        # 文件行：箭头占位 + checkbox + 图标 + 名称
        # 占位宽度与目录箭头一致，保证同层级 checkbox 对齐
        # left_padding = indent * _INDENT_STEP：与目录 header 使用同一套层级缩进
        row = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=_ARROW_WIDTH),
                    cb,
                    ft.Icon(icon_name, size=18, color=icon_color),
                    ft.Text(file_path.name, size=14),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=_ROW_HEIGHT,
            padding=ft.Padding(
                left=indent * _INDENT_STEP, top=0, right=12, bottom=0),
            on_click=lambda e, c=cb: c.toggle(),
            ink=True,
            border_radius=4,
        )
        return row

    # ====================================================== 状态计算
    def _walk_files(self, dir_path: Path):
        """递归生成 dir_path 下所有文件路径 (跳过忽略目录)."""
        try:
            for entry in dir_path.iterdir():
                if entry.name in self.IGNORE_DIRS:
                    continue
                if entry.name.startswith(".") and entry.is_dir():
                    continue
                if entry.is_file():
                    yield entry
                elif entry.is_dir():
                    yield from self._walk_files(entry)
        except (PermissionError, FileNotFoundError, OSError):
            return

    def _dir_state(self, dir_path: Path) -> int:
        """0=未选, 1=部分, 2=全选. 文件总数 0 时返回 0."""
        total = 0
        checked = 0
        for f in self._walk_files(dir_path):
            total += 1
            if str(f.resolve()) in self.checked_paths:
                checked += 1
        if total == 0:
            return UNCHECKED
        if checked == 0:
            return UNCHECKED
        if checked == total:
            return CHECKED
        return PARTIAL

    def _refresh_dir_display(self, node: _DirNode) -> None:
        """刷新单个目录节点的三态显示."""
        cb = self._dir_widgets.get(str(node.path))
        if cb is None:
            return
        cb.set_state(self._dir_state(node.path))

    def _refresh_all_dir_displays(self) -> None:
        """刷新所有已注册目录的三态显示 (按路径从浅到深, 让祖先计算正确)."""
        # 按路径段数排序: 浅的目录先算
        paths = sorted(self._dir_widgets.keys(),
                       key=lambda p: p.count(os.sep))
        for p in paths:
            node = self._dir_nodes.get(p)
            if node is not None:
                self._refresh_dir_display(node)
            else:
                # 根目录等简单路径: 直接用 path 计算
                cb = self._dir_widgets[p]
                cb.set_state(self._dir_state(Path(p)))

    # ====================================================== 点击事件
    def _on_dir_checkbox_click(self, path_str: str, old_state: int) -> None:
        """目录三态点击: 级联设置所有后代文件."""
        dir_path = Path(path_str)
        files = list(self._walk_files(dir_path))
        # 单击: 0/1 -> 2 (全选), 2 -> 0 (取消全选)
        if old_state == CHECKED:
            for f in files:
                self.checked_paths.discard(str(f.resolve()))
        else:
            for f in files:
                self.checked_paths.add(str(f.resolve()))
        # 刷新所有可见的文件 checkbox
        for p, cb in self._file_widgets.items():
            cb.set_state(CHECKED if p in self.checked_paths else UNCHECKED)
        # 刷新所有目录三态 (浅 → 深, 浅的先算才会反映深层修改)
        self._refresh_all_dir_displays()
        # 推送到 engine + 编排列表
        self._sync_to_engine()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    def _on_file_checkbox_click(self, path_str: str, old_state: int) -> None:
        """点击文件 checkbox 切换勾选状态."""
        new_state = CHECKED if old_state == UNCHECKED else UNCHECKED
        if new_state == CHECKED:
            self.checked_paths.add(path_str)
        else:
            self.checked_paths.discard(path_str)
        # 刷新对应文件 checkbox 视觉
        cb = self._file_widgets.get(path_str)
        if cb is not None:
            cb.set_state(new_state)
        # 刷新所有目录三态
        self._refresh_all_dir_displays()
        self._sync_to_engine()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    # ====================================================== 同步到 engine
    def _sync_to_engine(self):
        """同步到 engine 和编排列表."""
        self.main_view.engine.checked_paths = self.checked_paths.copy()
        self.main_view.arrangement_panel.sync_from_tree()
        self.main_view.arrangement_panel.refresh()

    # ====================================================== 搜索
    def _on_search_change(self, e):
        """搜索框变化: 仅过滤已加载节点."""
        query = self.search_field.value.strip().lower()
        self._filter_tree(self.tree_content.controls, query)
        try:
            self.main_view.page.update()
        except Exception:
            pass

    def _filter_tree(self, controls, query: str) -> bool:
        """过滤树节点, 返回是否有可见内容."""
        has_visible = False
        for ctrl in controls:
            if isinstance(ctrl, ft.Column) and len(ctrl.controls) >= 2:
                # 目录节点: [header Container, children Column]
                header, children_col = ctrl.controls[0], ctrl.controls[1]
                header_visible = self._row_matches(header, query)
                child_visible = self._filter_tree(children_col.controls, query)
                ctrl.visible = header_visible or child_visible or (not query)
                if ctrl.visible:
                    has_visible = True
            elif isinstance(ctrl, ft.Container):
                if self._row_matches(ctrl, query):
                    ctrl.visible = True
                    has_visible = True
                else:
                    ctrl.visible = False
        return has_visible

    @staticmethod
    def _row_matches(ctrl: ft.Container, query: str) -> bool:
        """判断某行 (目录/文件) 的名称是否匹配搜索关键词."""
        if not query:
            return True
        row = ctrl.content
        if isinstance(row, ft.Row) and len(row.controls) >= 4:
            name_text = row.controls[3]
            if isinstance(name_text, ft.Text):
                return query in name_text.value.lower()
        return False

    # ====================================================== 外部 API
    def get_checked_paths(self) -> set[str]:
        return self.checked_paths.copy()
