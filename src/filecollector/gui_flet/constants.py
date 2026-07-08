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


def get_effective_skip_dirs() -> set[str]:
    """内置跳过目录与用户偏好设置的忽略目录合并后的有效集合.

    文件树扫描 / 全局搜索 / AI 扫描均应使用此集合, 使偏好设置里的
    "扫描忽略目录" 真正生效 (用户目录在 SKIP_DIRS 基础上追加跳过).
    """
    from filecollector.config import get_ignored_dirs
    return SKIP_DIRS | set(get_ignored_dirs())
