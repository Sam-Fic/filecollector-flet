"""编排列表条目数据模型 + 视觉语言大模型 (VLM) 预处理状态.

对齐 GNOME 版本 ItemData:
- 新增 ``preprocess_status`` / ``preprocessed_content`` / ``from_cache``:
  用于记录 VLM 预处理流程中的瞬时状态与最终产物.
- 新增 ``is_document_target`` / ``is_image_target`` / ``is_binary_target`` /
  ``is_allowed_binary_target`` / ``get_image_mime_type``: 文件类型识别.
"""

from __future__ import annotations

import enum
from typing import Optional


# 默认允许被 VLM 转换的二进制扩展名 (与 GNOME 版 DEFAULT_ALLOWED_BINARY_EXTS 对齐)
DEFAULT_ALLOWED_BINARY_EXTS = (
    ".pdf", ".docx", ".pptx", ".doc", ".ppt",
    ".xlsx", ".xls", ".ods", ".odt", ".odp", ".rtf", ".wps",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
)

# 文档类扩展名 (用于图标 / 区分于纯图片)
DOCUMENT_EXTENSIONS = (
    ".pdf", ".docx", ".pptx", ".doc", ".ppt",
    ".xlsx", ".xls", ".ods", ".odt", ".odp", ".rtf", ".wps",
)

# 图片类扩展名
IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
)


class PreprocessStatus(enum.IntEnum):
    """VLM 预处理状态机 (与 GNOME 版 PreprocessStatus 一致)."""
    NONE = 0          # 未进入处理流程 (普通文本条目 / 不在允许列表)
    PENDING = 1       # 等待处理
    CHECKING = 2      # 正在检查本地缓存
    PROCESSING = 3    # 真正在调用 VLM
    COMPLETED = 4     # 成功
    FAILED = 5        # 失败


class ItemData:
    def __init__(self, type_, path=None, content=None, force_absolute=False):
        self.type = type_
        self.path = path
        self.force_absolute = force_absolute
        self.content = content
        # VLM 预处理相关字段
        self.preprocess_status: PreprocessStatus = PreprocessStatus.NONE
        self._preprocessed_content: Optional[str] = None
        self.from_cache: bool = False
        # Token 估算缓存 (preprocessed_content 优先, 否则用 content)
        self.cached_tokens: int = 0
        self.update_token_stats()

    # ---------------------------------------------------------------- Token 估算
    @property
    def preprocessed_content(self) -> Optional[str]:
        return self._preprocessed_content

    @preprocessed_content.setter
    def preprocessed_content(self, value: Optional[str]) -> None:
        self._preprocessed_content = value
        # 赋值时自动刷新 cached_tokens, 避免遗漏调用点导致估算为 0
        # (对齐 GNOME 版 notify["preprocessed-content"].connect)
        self.update_token_stats()

    def get_effective_content(self) -> str:
        """返回用于 token 估算 / 导出的有效内容.

        preprocessed_content (VLM 转写) 优先; 否则用 content (text 条目 / 文件读取结果).
        """
        if self.preprocessed_content:
            return self.preprocessed_content
        return self.content or ""

    def update_token_stats(self) -> None:
        """基于 get_effective_content() 刷新 cached_tokens.

        在 __init__ / preprocessed_content 赋值 / 文本编辑后调用.
        """
        from filecollector.token_estimator import estimate_tokens_fast
        self.cached_tokens = estimate_tokens_fast(self.get_effective_content())

    # ---------------------------------------------------------------- 文件类型判断
    def is_document_target(self) -> bool:
        if self.type != "file" or not self.path:
            return False
        lower = self.path.lower()
        return any(lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS)

    def is_image_target(self) -> bool:
        if self.type != "file" or not self.path:
            return False
        lower = self.path.lower()
        return any(lower.endswith(ext) for ext in IMAGE_EXTENSIONS)

    def is_binary_target(self) -> bool:
        """默认判断: 文档类或图片类扩展名即视为二进制文件."""
        return self.is_document_target() or self.is_image_target()

    def is_allowed_binary_target(self, allowed_extensions) -> bool:
        """用户可配置的"允许被 VLM 转换的扩展名"判断.

        传入空数组相当于不允许任何文件被转换.
        自动为缺少前导点的扩展名补上, 兼容 ".pdf" 与 "pdf" 两种写法.
        """
        if self.type != "file" or not self.path:
            return False
        if not allowed_extensions:
            return False
        lower = self.path.lower()
        for ext in allowed_extensions:
            if not ext:
                continue
            e = ext.lower()
            if not e.startswith("."):
                e = "." + e
            if lower.endswith(e):
                return True
        return False

    def get_image_mime_type(self) -> str:
        if not self.path:
            return "image/png"
        lower = self.path.lower()
        if lower.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".bmp"):
            return "image/bmp"
        if lower.endswith((".tiff", ".tif")):
            return "image/tiff"
        return "image/png"

    def make_snapshot_dict(self) -> dict:
        """生成可被 json.dumps 序列化的快照 (供 undo / project save)."""
        return {
            "type": self.type,
            "path": self.path,
            "content": self.content,
            "force_absolute": self.force_absolute,
            # 预处理状态/内容不持久化: 项目保存只关心编排结构, 缓存会重建
        }

    @classmethod
    def from_snapshot_dict(cls, d: dict) -> "ItemData":
        return cls(
            type_=d.get("type", "file"),
            path=d.get("path"),
            content=d.get("content"),
            force_absolute=bool(d.get("force_absolute", False)),
        )
