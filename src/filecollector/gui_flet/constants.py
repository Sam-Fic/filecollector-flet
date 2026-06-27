"""共享常量 (避免多处重复定义)."""

from __future__ import annotations

# 通用忽略目录: 文件树 / 搜索 / AI 文件扫描 共用
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode",
    "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".cache",
    "venv", ".venv", "env",
    "build", "dist",
    ".next", ".nuxt", "target", ".gradle",
    # VLM 缓存目录
    ".filecollector_cache",
}

# AI 文件扫描额外跳过的隐藏目录 (以 . 开头)
AI_SKIP_HIDDEN: bool = True
