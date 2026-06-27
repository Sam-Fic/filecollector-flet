from __future__ import annotations

import json
from pathlib import Path

from filecollector.models import ItemData
from filecollector.utils import safe_read_file
from filecollector.config import get_settings_path, load_settings, save_settings, get_common_phrases_path, load_common_phrases, save_common_phrases, get_merged_txt_path


class FileCollectorEngine:
    def __init__(self):
        self.work_dir: Path | None = None
        self.items: list[ItemData] = []
        self.checked_paths: set[str] = set()
        self.use_absolute: bool = False
        self.show_header: bool = False
        self.common_phrases: list[str] = []
        self.project_file: str | None = None

    # ------------------------------------------------------------------ Items
    def add_file(self, abs_path_str: str, force_absolute: bool = False) -> None:
        # 去重: 同一文件不重复添加, 避免导出时出现重复内容
        for it in self.items:
            if it.type == "file" and it.path == abs_path_str:
                return
        self.items.append(ItemData(type_="file", path=abs_path_str, force_absolute=force_absolute))
        if not force_absolute:
            self.checked_paths.add(abs_path_str)

    def add_text(self, content: str, index: int | None = None) -> None:
        item_data = ItemData(type_="text", content=content)
        if index is None or index >= len(self.items):
            self.items.append(item_data)
        else:
            self.items.insert(index, item_data)

    def move_item(self, from_idx: int, to_idx: int) -> None:
        if 0 <= from_idx < len(self.items) and 0 <= to_idx < len(self.items):
            item = self.items.pop(from_idx)
            self.items.insert(to_idx, item)

    def remove_item(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def remove_items_by_path(self, abs_path_str: str) -> None:
        self.items = [it for it in self.items if not (it.type == "file" and it.path == abs_path_str)]

    def clear(self) -> None:
        self.items.clear()
        self.checked_paths.clear()

    def list_items(self):
        result = []
        for i, data in enumerate(self.items):
            if data.type == "file":
                p = Path(data.path)
                tag = "绝对路径" if data.force_absolute else "相对路径"
                result.append((i, "文件", f"{p.name} ({tag})"))
            else:
                preview = data.content[:50] + ("..." if len(data.content) > 50 else "")
                result.append((i, "文字", preview))
        return result

    # ------------------------------------------------------------------ Undo helpers
    def snapshot(self) -> dict:
        return {
            "items": [ItemData(type_=it.type, path=it.path, content=it.content, force_absolute=it.force_absolute) for it in self.items],  # deep copy
            "checked_paths": set(self.checked_paths),
            "use_absolute": self.use_absolute,
            "show_header": self.show_header,
        }

    def restore(self, state: dict) -> None:
        self.items = list(state["items"])
        self.checked_paths = set(state["checked_paths"])
        self.use_absolute = bool(state["use_absolute"])
        self.show_header = bool(state["show_header"])

    # ------------------------------------------------------------------ Export / clipboard target file
    def generate_text(self) -> str:
        """生成合并文本并返回字符串 (供剪贴板等场景复用)."""
        import io
        buf = io.StringIO()
        self._write_export(buf)
        return buf.getvalue()

    def export(self, file_path: str) -> None:
        out_path = Path(file_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8", errors="replace") as f:
                self._write_export(f)
            tmp_path.replace(out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _write_export(self, f) -> None:
        """将合并内容写入 file-like 对象 (文件或 StringIO)."""
        if not self.use_absolute and self.show_header and self.work_dir:
            f.write(f"# 工作目录绝对路径: {self.work_dir}\n\n")

        for i, data in enumerate(self.items):
            if i > 0:
                f.write("\n\n")
            if data.type == "file":
                file_p = Path(data.path)
                if not file_p.exists():
                    f.write(f"[文件不存在: {data.path}]\n")
                    continue
                if data.force_absolute or self.use_absolute or not self.work_dir:
                    display = str(file_p.resolve())
                else:
                    try:
                        display = str(file_p.resolve().relative_to(self.work_dir))
                    except ValueError:
                        display = str(file_p.resolve())
                f.write(f"{display}:\n")
                pre_md = getattr(data, "preprocessed_content", None)
                if pre_md:
                    f.write(pre_md)
                    continue
                try:
                    content, _ = safe_read_file(data.path)
                    f.write(content)
                except Exception as e:
                    f.write(f"[读取错误: {e}]")
            else:
                f.write(data.content)

    # ------------------------------------------------------------------ Project I/O (Qt default: .project.json / GNOME: .fcol)
    def _normalize_project_path(self, file_path: str) -> str:
        if file_path.endswith(".project.json"):
            return file_path
        if not (file_path.endswith(".fcol") or file_path.endswith(".fcol.json")):
            file_path += ".project.json" if not file_path.endswith(".json") else ""
        return file_path

    def save_project(self, file_path: str) -> None:
        file_path = self._normalize_project_path(file_path)
        data = {
            "work_dir": str(self.work_dir) if self.work_dir else None,
            "use_absolute": self.use_absolute,
            "show_header": self.show_header,
            "checked_entries": sorted(self.checked_paths),  # GNOME 联调用名
            "items": [
                {"type": "file", "path": it.path, "force_absolute": it.force_absolute}
                if it.type == "file"
                else {"type": "text", "content": it.content}
                for it in self.items
            ],
            "common_phrases": self.common_phrases,  # 随项目保存，GNOME 兼容
        }
        # 原子写入: 先写临时文件, 再 rename, 避免中途崩溃导致项目文件损坏
        out_path = Path(file_path)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        try:
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        self.project_file = file_path

    def load_project(self, file_path: str) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._apply_project_dict(data)
        self.project_file = file_path

    def _apply_project_dict(self, data: dict) -> None:
        wd = data.get("work_dir") or data.get("work_directory")  # GNOME v3 兼容字段
        self.work_dir = Path(wd).resolve() if wd and Path(wd).exists() else None
        # 保留所有勾选路径, 即使文件暂时不可用 (如网络挂载未就绪),
        # 避免状态丢失; 导出时再按需处理缺失文件.
        self.checked_paths = set(data.get("checked_entries", data.get("checked_files", [])))  # GNOME 兼容字段名
        self.use_absolute = bool(data.get("use_absolute", False))
        self.show_header = bool(data.get("show_header", False))
        self.items = []
        for item_dict in data.get("items", []):
            if item_dict["type"] == "file":
                p = item_dict["path"]
                # 保留文件条目 (含路径), 即使文件暂时缺失; 导出时会标注
                self.items.append(ItemData("file", path=p, force_absolute=item_dict.get("force_absolute", False)))
            else:
                self.items.append(ItemData("text", content=item_dict["content"]))
        phrases = data.get("common_phrases")
        self.common_phrases = list(phrases) if isinstance(phrases, list) else []

    # ------------------------------------------------------------------ Persistence helpers (not project file)
    def save_settings(self, payload: dict | None = None) -> None:
        if payload is not None:
            save_settings(payload)

    def load_settings(self) -> dict:
        return load_settings()

    def save_common_phrases_to_disk(self) -> None:
        save_common_phrases(self.common_phrases)

    def load_common_phrases_from_disk(self) -> None:
        self.common_phrases = load_common_phrases()
