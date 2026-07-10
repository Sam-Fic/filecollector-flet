"""ZIP 打包导出服务 (对齐 GNOME 版 zip_exporter.vala).

把编排列表 (engine.items) 导出为一个保留目录结构的 ZIP 包:

- ``type == "file"`` 的条目: 按相对工作目录的路径复制到 staging 目录 (保留目录结构);
  文件不存在则记入缺失列表并跳过; 工作目录外的文件隔离到 ``_external/<basename>``.
- 非 file 的自定义文本条目: 收集为文本段, 写入 README.md.
- 自动生成 ``README.md`` 清单 (文件序号 / 相对路径 / 大小 / 类型 + 缺失提示 + 总大小).
- 用 Python 标准库 ``zipfile`` 打包, 完成后清理 staging 目录.

实现风格: 原生标准库 (zipfile + shutil), 不依赖系统 ``zip`` 命令, 跨平台稳定.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# 单文件大小上限 (100 MB): 超过仍会复制, 但 README 中标注, 避免超大文件拖慢压缩
MAX_FILE_SIZE = 100 * 1024 * 1024


def compute_relative_path(abs_path: str, work_dir: str | None) -> str:
    """计算文件在 ZIP 中的相对归档路径 (对齐 gnome compute_relative_path)."""
    file_p = Path(abs_path)
    if not work_dir:
        # 没有工作目录: 去掉前导 /, 避免同名冲突
        return file_p.as_posix().lstrip("/")
    try:
        return str(file_p.resolve().relative_to(Path(work_dir).resolve()))
    except ValueError:
        # 文件在工作目录外: 用 _external/<basename> 隔离
        return os.path.join("_external", file_p.name)


def detect_kind(path: str) -> str:
    """根据扩展名推断语言 / 类型名 (对齐 gnome detect_kind)."""
    lower = path.lower()
    table = {
        ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript",
        ".ts": "TypeScript", ".vala": "Vala",
        ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cc": "C++",
        ".rs": "Rust", ".go": "Go", ".java": "Java",
        ".md": "Markdown", ".json": "JSON",
        ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
        ".xml": "XML", ".html": "HTML", ".htm": "HTML",
        ".css": "CSS", ".sh": "Shell", ".sql": "SQL",
        ".png": "Image", ".jpg": "Image", ".jpeg": "Image",
        ".webp": "Image", ".gif": "Image", ".bmp": "Image",
        ".pdf": "PDF",
    }
    for ext, name in table.items():
        if lower.endswith(ext):
            return name
    base, dot, ext = lower.rpartition(".")
    if not dot or not ext:
        return "Text"
    return ext.upper()


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _write_readme(readme_path: str, now: datetime, work_dir: str | None,
                  text_blocks: list[str], copied: list[dict], missing: list[str],
                  total_size: int) -> None:
    """生成 README.md 清单 (对齐 gnome write_readme)."""
    sb: list[str] = []
    sb.append("# FileCollector Export\n\n")
    sb.append(f"> 由 FileCollector 生成于 {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    if work_dir:
        sb.append("## 工作目录\n\n")
        sb.append(f"`{work_dir}`\n\n")
    else:
        sb.append("## 工作目录\n\n")
        sb.append("未设置工作目录, 文件按其绝对路径归档\n\n")

    if text_blocks:
        sb.append("## 用户自定义文本\n\n")
        for block in text_blocks:
            if block.startswith("#") or block.startswith("```") or block.startswith("> "):
                sb.append(block)
            else:
                sb.append("> ")
                sb.append(block.replace("\n", "\n> "))
            sb.append("\n\n")

    sb.append("## 文件索引\n\n")
    sb.append(f"共 {len(copied)} 个文件, 总大小 {_format_size(total_size)}\n\n")
    if copied:
        sb.append("| # | 相对路径 | 大小 | 类型 |\n")
        sb.append("|---|---------|------|------|\n")
        for e in copied:
            flag = " ⚠超大" if e["size"] > MAX_FILE_SIZE else ""
            sb.append(
                f"| {e['index']} | `{e['rel_path']}` | "
                f"{_format_size(e['size'])}{flag} | {e['kind']} |\n"
            )
        sb.append("\n")

    if missing:
        sb.append("## 缺失文件\n\n")
        sb.append("以下文件在导出时不存在, 已被跳过:\n\n")
        for p in missing:
            sb.append(f"- `{p}`\n")
        sb.append("\n")

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("".join(sb))


def export_to_zip(zip_path: str, items: list, show_header: bool,
                  work_dir: str | None) -> tuple[list[str], int]:
    """将编排列表导出为 ZIP 包.

    Args:
        zip_path: 目标 .zip 路径.
        items: ``ItemData`` 列表 (engine.items).
        show_header: 是否把 header 信息写入 README (当前仅影响 README 标题区语义,
                     gnome 一致保留该参数位).
        work_dir: 当前工作目录绝对路径, 用于计算相对归档路径; 可空.

    Returns:
        (missing_files, total_size)
    """
    staging = tempfile.mkdtemp(prefix="filecollector-zip-")
    try:
        now = datetime.now()
        copied: list[dict] = []
        missing: list[str] = []
        text_blocks: list[str] = []
        total_size = 0
        file_index = 0

        for data in items:
            if getattr(data, "type", None) == "file":
                src = getattr(data, "path", None)
                if not src or not os.path.exists(src):
                    if src:
                        missing.append(src)
                    continue
                rel = compute_relative_path(src, work_dir)
                dest = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(dest) or staging, exist_ok=True)
                # 字面复制 (不跟随符号链接指向的真文件), 强制覆盖
                if os.path.islink(src):
                    shutil.copyfile(src, dest)
                else:
                    shutil.copy2(src, dest)
                try:
                    sz = os.path.getsize(dest)
                except OSError:
                    sz = 0
                total_size += sz
                file_index += 1
                copied.append({
                    "index": file_index,
                    "rel_path": rel,
                    "size": sz,
                    "kind": detect_kind(src),
                })
            else:
                content = getattr(data, "content", None) or ""
                stripped = content.strip()
                if stripped:
                    text_blocks.append(stripped)

        _write_readme(
            os.path.join(staging, "README.md"), now, work_dir,
            text_blocks, copied, missing, total_size,
        )

        # 若目标已存在则先删除, 避免 zipfile 追加到旧文件
        if os.path.exists(zip_path):
            os.remove(zip_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(staging):
                for name in files:
                    full = os.path.join(root, name)
                    arcname = os.path.relpath(full, staging)
                    zf.write(full, arcname)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return missing, total_size
