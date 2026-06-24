"""视觉语言大模型 (VLM) 预处理缓存.

对齐 GNOME 版 PreprocessCache:
- 目录: ``<work_dir>/.filecollector_cache/``
- 结构:
    .filecollector_cache/
        manifest.json
        markdown/<hash>.md
- key: 相对 work_dir 的相对路径 (若文件在 work_dir 外则用绝对路径)
- value: { "hash": sha256, "md_file": "<hash>.md", "timestamp": ... }
- 命中条件: 路径与当前 SHA-256 一致, 且 markdown 文件存在
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Optional


CACHE_SUBDIR = ".filecollector_cache"
CACHE_MD_SUBDIR = "markdown"
MANIFEST_NAME = "manifest.json"


def compute_file_hash(path: str) -> str:
    """计算文件 SHA-256, 8KB 分块读, 适合大文件."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class PreprocessCache:
    """单 work_dir 范围的本地预处理缓存."""

    def __init__(self, work_dir: str):
        self.work_dir = os.path.abspath(work_dir) if work_dir else ""
        if not self.work_dir:
            raise ValueError("work_dir 不能为空")
        self.cache_dir = os.path.join(self.work_dir, CACHE_SUBDIR)
        self.md_dir = os.path.join(self.cache_dir, CACHE_MD_SUBDIR)
        self.manifest_path = os.path.join(self.cache_dir, MANIFEST_NAME)
        self._mutex = threading.Lock()
        self._manifest: dict = self._load_manifest()

    # ------------------------------------------------------------------ 路径工具
    def _rel_path(self, abs_path: str) -> str:
        try:
            rel = os.path.relpath(abs_path, self.work_dir)
        except ValueError:
            rel = abs_path
        return rel.replace("\\", "/")

    # ------------------------------------------------------------------ manifest
    def _load_manifest(self) -> dict:
        if not os.path.exists(self.manifest_path):
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as e:
            logging.warning(f"读取 manifest 失败: {e}")
            return {}

    def _save_manifest(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = self.manifest_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.manifest_path)
        except Exception as e:
            logging.warning(f"写入 manifest 失败: {e}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ------------------------------------------------------------------ 公开 API
    def get_cached_markdown(self, abs_path: str,
                            current_hash: str) -> Optional[str]:
        """命中缓存则返回 markdown 文本, 否则 None."""
        with self._mutex:
            rel = self._rel_path(abs_path)
            entry = self._manifest.get(rel)
            if not isinstance(entry, dict):
                return None
            cached_hash = entry.get("hash", "")
            if cached_hash != current_hash:
                return None
            md_filename = entry.get("md_file", "")
            if not md_filename:
                return None
            md_path = os.path.join(self.md_dir, md_filename)
            if not os.path.exists(md_path):
                return None
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                logging.warning(f"读取缓存 markdown 失败: {e}")
                return None

    def save_markdown(self, abs_path: str, current_hash: str,
                      markdown_content: str) -> None:
        """写入缓存 (创建目录, 更新 manifest)."""
        rel = self._rel_path(abs_path)
        md_filename = f"{current_hash}.md"
        md_path = os.path.join(self.md_dir, md_filename)
        with self._mutex:
            try:
                os.makedirs(self.md_dir, exist_ok=True)
                tmp = md_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                os.replace(tmp, md_path)
            except Exception as e:
                logging.warning(f"写缓存 markdown 失败: {e}")
                return
            self._manifest[rel] = {
                "hash": current_hash,
                "md_file": md_filename,
                "timestamp": int(time.time()),
            }
            self._save_manifest()

    def invalidate_cache(self, abs_path: str) -> None:
        """移除单条缓存 (用于强制重新转换)."""
        rel = self._rel_path(abs_path)
        with self._mutex:
            entry = self._manifest.pop(rel, None)
            if isinstance(entry, dict):
                md_filename = entry.get("md_file", "")
                if md_filename:
                    md_path = os.path.join(self.md_dir, md_filename)
                    if os.path.exists(md_path):
                        try:
                            os.remove(md_path)
                        except OSError:
                            pass
                self._save_manifest()

    def clear_all(self) -> None:
        """清空整个 .filecollector_cache 目录."""
        with self._mutex:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir, ignore_errors=True)
            self._manifest = {}
            try:
                os.makedirs(self.md_dir, exist_ok=True)
            except OSError:
                pass
            self._save_manifest()
