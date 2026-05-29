import os
import json
from pathlib import Path

from filecollector.models import ItemData
from filecollector.utils import safe_read_file


class FileCollectorEngine:
    def __init__(self):
        self.work_dir = None
        self.items = []
        self.checked_paths = set()
        self.use_absolute = False
        self.show_header = False
        self.project_file = None

    def add_file(self, abs_path_str, force_absolute=False):
        self.items.append(ItemData(type_="file", path=abs_path_str, force_absolute=force_absolute))

    def add_text(self, content, index=None):
        item_data = ItemData(type_="text", content=content)
        if index is None or index >= len(self.items):
            self.items.append(item_data)
        else:
            self.items.insert(index, item_data)

    def move_item(self, from_idx, to_idx):
        if 0 <= from_idx < len(self.items) and 0 <= to_idx < len(self.items):
            item = self.items.pop(from_idx)
            self.items.insert(to_idx, item)

    def remove_item(self, index):
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def remove_items_by_path(self, abs_path_str):
        self.items = [it for it in self.items if not (it.type == "file" and it.path == abs_path_str)]

    def clear(self):
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
                preview = data.content[:50] + ('...' if len(data.content) > 50 else '')
                result.append((i, "文字", preview))
        return result

    def export(self, file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
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
                    try:
                        content, _ = safe_read_file(data.path)
                        f.write(content)
                    except Exception as e:
                        f.write(f"[读取错误: {e}]")
                else:
                    f.write(data.content)

    def save(self, file_path):
        data = {
            "work_dir": str(self.work_dir) if self.work_dir else None,
            "use_absolute": self.use_absolute,
            "show_header": self.show_header,
            "checked_files": list(self.checked_paths),
            "items": []
        }
        for item_data in self.items:
            if item_data.type == "file":
                data["items"].append({
                    "type": "file",
                    "path": item_data.path,
                    "force_absolute": item_data.force_absolute
                })
            else:
                data["items"].append({
                    "type": "text",
                    "content": item_data.content
                })
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        wd = data.get("work_dir")
        self.work_dir = Path(wd).resolve() if wd and Path(wd).exists() else None

        self.checked_paths = set()
        for p_str in data.get("checked_files", []):
            if os.path.exists(p_str):
                self.checked_paths.add(p_str)

        self.use_absolute = data.get("use_absolute", False)
        self.show_header = data.get("show_header", False)

        self.items.clear()
        for item_dict in data.get("items", []):
            if item_dict["type"] == "file":
                p = item_dict["path"]
                if not os.path.exists(p):
                    it = ItemData("text", content=f"[缺失文件: {p}]")
                else:
                    it = ItemData("file", path=p, force_absolute=item_dict.get("force_absolute", False))
                self.items.append(it)
            else:
                self.items.append(ItemData("text", content=item_dict["content"]))
