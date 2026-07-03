"""视觉语言大模型 (VLM) 预处理流程编排 (后台线程 + UI 回调).

对齐 GNOME 版 check_and_apply_cache + start_preprocess_task:
- 先进入 CHECKING 状态, 避免"处理中..."误显示
- 计算 SHA-256 -> 查缓存 -> 命中直接 COMPLETED (from_cache=True)
- 缓存未命中 -> 调 BinaryConverter 转图片 -> MultimodalAIClient 出 Markdown
- 成功 -> 写缓存 + 状态变 COMPLETED; 失败 -> FAILED
- 全部通过 ``main_view.page.run_task`` 安全回到 UI 线程更新状态

UI 侧只关心 ``on_status(item)`` / ``on_preview(item)`` 回调, 不需要管线程细节.

VLM 预处理队列版:
- ``check_and_apply_cache`` / ``reevaluate_queue`` / ``retry`` 统一通过
  ``VLMQueueManager`` 调度, 受并发上限 / 暂停 / 取消 控制.
- 队列 executor 负责完整的 缓存检查 + VLM 转换 流程.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from filecollector.binary_converter import (
    convert_to_base64_images,
    get_output_mime_for_image,
)
from filecollector.config import load_multimodal_ai_settings
from filecollector.models import ItemData, PreprocessStatus
from filecollector.multimodal_ai_client import (
    MultimodalAIClient,
    MultimodalAIClientError,
)
from filecollector.preprocess_cache import PreprocessCache, compute_file_hash


def _get_prompt_for_item(item: ItemData, override: str = "") -> str:
    """根据文件类型生成默认系统提示词 (override 优先)."""
    if override and override.strip():
        return override

    if not item.path:
        return "请将图片中的内容转换为结构清晰的 Markdown 格式。保留标题、列表和表格。"

    lower = item.path.lower()

    if item.is_image_target():
        if any(k in lower for k in ("screenshot", "error", "bug")):
            return (
                "这是一张系统截图。请提取图中所有可见文本内容"
                "（包括错误信息、堆栈跟踪、UI 元素）。"
                "保留原始格式，使用代码块包裹命令行输出或报错信息。"
            )
        if any(k in lower for k in ("diagram", "flow", "arch")):
            return (
                "这是一张技术图表。请描述图表的结构和逻辑关系。"
                "如果可能，使用 Mermaid 语法重构此图表。"
            )
        return (
            "请提取图片中的所有文本内容，并将其转换为结构清晰的 Markdown。"
            "保留标题层级、列表结构和表格。"
        )

    if item.is_document_target():
        if any(lower.endswith(ext) for ext in (".xlsx", ".xls", ".ods")):
            return (
                "请将图片中的电子表格数据转换为标准 Markdown 表格。"
                "保留表头结构、合并单元格的语义以及数值精度。"
            )
        if any(lower.endswith(ext) for ext in (".pptx", ".ppt", ".odp")):
            return (
                "这是演示文稿的页面截图。请将每页内容提取为 Markdown，"
                "使用二级标题 (##) 分隔每页幻灯片，保留要点列表。"
            )

    return "请将图片中的内容转换为结构清晰的 Markdown 格式。保留标题、列表和表格。"


class PreprocessRunner:
    """单 main_view 范围内共用的 VLM 预处理编排器."""

    def __init__(self, main_view, get_work_dir: Callable[[], Optional[str]],
                 get_allowed_exts: Callable[[], list[str]],
                 on_status: Callable[[ItemData], None],
                 on_preview: Callable[[ItemData], None]):
        self._main_view = main_view
        self._get_work_dir = get_work_dir
        self._get_allowed_exts = get_allowed_exts
        self._on_status = on_status
        self._on_preview = on_preview
        # 跟踪在跑线程, 防止 main_view 销毁后还有 worker 持有引用
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()
        # VLM 预处理队列 (由 main_view 初始化后注入)
        self.vlm_queue: Optional[object] = None  # VLMQueueManager

    # ------------------------------------------------------------------ 公共查询
    def get_allowed_exts(self) -> list[str]:
        """返回当前 main_view 配置的允许被 VLM 转换的扩展名列表."""
        try:
            return list(self._get_allowed_exts() or [])
        except Exception:
            return []

    # ------------------------------------------------------------------ 入口
    def check_and_apply_cache(self, item: ItemData) -> None:
        """对单条 binary item 提交到队列 (由队列控制并发)."""
        if item is None or item.type != "file":
            return
        if not item.is_allowed_binary_target(self._get_allowed_exts()):
            return
        if self.vlm_queue is not None:
            self.vlm_queue.enqueue(item)
        else:
            # 降级: 无队列时直接起线程 (向后兼容)
            self._direct_check_and_apply_cache(item)

    def retry(self, item: ItemData) -> None:
        """强制重新预处理 (清掉旧缓存)."""
        if item is None or item.type != "file":
            return
        if not item.is_allowed_binary_target(self._get_allowed_exts()):
            return
        if item.preprocess_status == PreprocessStatus.PROCESSING:
            return

        work_dir = self._get_work_dir()
        if work_dir:
            try:
                cache = PreprocessCache(work_dir)
                cache.invalidate_cache(item.path or "")
            except Exception:
                pass

        item.preprocessed_content = None
        item.from_cache = False
        item.preprocess_status = PreprocessStatus.PENDING
        self._on_status(item)
        self._on_preview(item)
        self.check_and_apply_cache(item)

    def clear_workspace_cache(self) -> int:
        """清除工作目录的 .filecollector_cache. 返回清除的 item 数."""
        work_dir = self._get_work_dir()
        if not work_dir:
            return 0
        try:
            cache = PreprocessCache(work_dir)
            cache.clear_all()
        except Exception as e:
            logging.warning(f"清空缓存失败: {e}")
            return 0

        # 清空所有 item 的预处理状态
        cleared = 0
        items = getattr(self._main_view.engine, "items", [])
        for it in items:
            if it.type == "file" and it.is_allowed_binary_target(
                    self._get_allowed_exts()):
                if it.preprocess_status != PreprocessStatus.NONE:
                    it.preprocess_status = PreprocessStatus.NONE
                    it.preprocessed_content = None
                    it.from_cache = False
                    cleared += 1
        return cleared

    def reevaluate_queue(self) -> None:
        """允许扩展名列表变化后, 重新评估编排列表中各项.

        - 新进入允许列表: 触发缓存检查 (通过队列)
        - 离开允许列表: 清空预处理状态
        """
        allowed = self._get_allowed_exts()
        items = getattr(self._main_view.engine, "items", [])
        for it in items:
            if it.type != "file":
                continue
            if it.is_allowed_binary_target(allowed):
                if it.preprocess_status in (
                        PreprocessStatus.NONE, PreprocessStatus.FAILED):
                    self.check_and_apply_cache(it)
            else:
                if it.preprocess_status != PreprocessStatus.NONE:
                    it.preprocess_status = PreprocessStatus.NONE
                    it.preprocessed_content = None
                    it.from_cache = False
                    self._on_status(it)

    # ------------------------------------------------------------------ 取消回调
    def on_item_cancelled(self, item: ItemData) -> None:
        """队列取消某 item 时触发: 把状态复位为 NONE, 刷新 UI.

        由 VLMQueueManager 在独立线程中调用, 内部用 _post 切回 UI 线程.
        只复位 PENDING/CHECKING/PROCESSING — COMPLETED/FAILED/UNKNOWN 不动,
        避免抹掉已经成功或已失败的结果.
        """
        def _reset():
            if item.preprocess_status in (
                    PreprocessStatus.PENDING,
                    PreprocessStatus.CHECKING,
                    PreprocessStatus.PROCESSING):
                item.preprocess_status = PreprocessStatus.NONE
                item.preprocessed_content = None
                item.from_cache = False
                self._on_status(item)
        self._post(_reset)

    # ------------------------------------------------------------------ 队列执行器
    def vlm_task_executor(self, item: ItemData, queue_manager) -> None:
        """队列执行器: 在后台线程中完成 缓存检查 + VLM 转换.

        对齐 GNOME 版 vlm_task_executor, 所有 UI 更新通过 _post 切回主线程.
        队列的 notify_finished 也在 UI 回调中触发, 确保状态更新先于调度.
        """
        # 1. 检查缓存
        work_dir = self._get_work_dir()
        cached_md = None
        file_hash = ""

        if work_dir and item.path:
            try:
                file_hash = compute_file_hash(item.path)
                cache = PreprocessCache(work_dir)
                cached_md = cache.get_cached_markdown(item.path, file_hash)
            except Exception as e:
                logging.warning(f"Cache check failed: {e}")

        if queue_manager.check_cancelled():
            self._post(lambda: queue_manager.notify_finished(item))
            return

        if cached_md is not None:
            md = cached_md

            def _apply_cached():
                item.preprocessed_content = md
                item.preprocess_status = PreprocessStatus.COMPLETED
                item.from_cache = True
                self._on_status(item)
                self._on_preview(item)
                queue_manager.notify_finished(item)

            self._post(_apply_cached)
            return

        # 2. 调用 VLM
        def _go_processing():
            item.preprocess_status = PreprocessStatus.PROCESSING
            self._on_status(item)

        self._post(_go_processing)

        try:
            settings = load_multimodal_ai_settings()
        except Exception:
            settings = {}

        if not settings.get("enabled") or not (settings.get("api_key") or ""):
            def _fail_no_config():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
                queue_manager.notify_finished(item)
            self._post(_fail_no_config)
            return

        if queue_manager.check_cancelled():
            self._post(lambda: queue_manager.notify_finished(item))
            return

        try:
            images = convert_to_base64_images(item.path or "")
        except Exception as e:
            logging.warning(f"BinaryConverter 失败: {e}")
            images = None

        if not images:
            def _fail_convert():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
                queue_manager.notify_finished(item)
            self._post(_fail_convert)
            return

        mime_types: list[str] = []
        if item.is_image_target() and len(images) == 1:
            mime_types = [get_output_mime_for_image(item.path or "")]
        else:
            mime_types = ["image/png"] * len(images)

        prompt = _get_prompt_for_item(
            item, settings.get("system_prompt_override", "") or "")

        if queue_manager.check_cancelled():
            self._post(lambda: queue_manager.notify_finished(item))
            return

        try:
            client = MultimodalAIClient(
                base_url=settings.get("base_url", ""),
                api_key=settings.get("api_key", ""),
                model=settings.get("model", ""),
                prompt=prompt,
                timeout=float(settings.get("timeout", 120.0) or 120.0),
            )
            md = client.process_images(images, mime_types).strip()
        except MultimodalAIClientError as e:
            logging.warning(f"VLM 调用失败: {e}")
            def _fail_api():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
                queue_manager.notify_finished(item)
            self._post(_fail_api)
            return
        except Exception as e:
            logging.warning(f"VLM 任务异常: {e}")
            def _fail_exc():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
                queue_manager.notify_finished(item)
            self._post(_fail_exc)
            return

        if queue_manager.check_cancelled():
            self._post(lambda: queue_manager.notify_finished(item))
            return

        # 写缓存
        if work_dir and item.path:
            try:
                if not file_hash:
                    file_hash = compute_file_hash(item.path)
                cache = PreprocessCache(work_dir)
                cache.save_markdown(item.path, file_hash, md)
            except Exception as e:
                logging.warning(f"写缓存失败: {e}")

        def _done():
            item.preprocessed_content = md
            item.preprocess_status = PreprocessStatus.COMPLETED
            item.from_cache = False
            self._on_status(item)
            self._on_preview(item)
            queue_manager.notify_finished(item)

        self._post(_done)

    # ------------------------------------------------------------------ 降级直通
    def _direct_check_and_apply_cache(self, item: ItemData) -> None:
        """无队列时降级: 直接起后台线程 (旧行为)."""
        item.preprocess_status = PreprocessStatus.CHECKING
        self._on_status(item)

        work_dir = self._get_work_dir()
        if not work_dir:
            self._start_preprocess_direct(item)
            return

        t = threading.Thread(
            target=self._cache_check_worker,
            args=(item, work_dir),
            daemon=True,
            name="fc-cache-check",
        )
        with self._lock:
            self._threads.add(t)
        t.start()

    def _cache_check_worker(self, item: ItemData, work_dir: str) -> None:
        try:
            file_hash = compute_file_hash(item.path or "")
            cache = PreprocessCache(work_dir)
            cached = cache.get_cached_markdown(item.path or "", file_hash)
        except Exception as e:
            logging.warning(f"Cache check failed: {e}")
            cached = None

        if cached is not None:
            md = cached

            def _apply():
                item.preprocessed_content = md
                item.preprocess_status = PreprocessStatus.COMPLETED
                item.from_cache = True
                self._on_status(item)
                self._on_preview(item)

            self._post(_apply)
            return

        def _pending():
            item.preprocess_status = PreprocessStatus.PENDING
            self._on_status(item)
            self._start_preprocess_direct(item)

        self._post(_pending)

    def _start_preprocess_direct(self, item: ItemData) -> None:
        t = threading.Thread(
            target=self._vlm_worker_direct,
            args=(item,),
            daemon=True,
            name="fc-vlm-task",
        )
        with self._lock:
            self._threads.add(t)
        t.start()

    def _vlm_worker_direct(self, item: ItemData) -> None:
        def _go():
            item.preprocess_status = PreprocessStatus.PROCESSING
            self._on_status(item)
        self._post(_go)

        try:
            settings = load_multimodal_ai_settings()
        except Exception:
            settings = {}

        if not settings.get("enabled") or not (settings.get("api_key") or ""):
            def _fail():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
            self._post(_fail)
            return

        try:
            images = convert_to_base64_images(item.path or "")
        except Exception as e:
            logging.warning(f"BinaryConverter 失败: {e}")
            images = None
        if not images:
            def _fail():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
            self._post(_fail)
            return

        mime_types: list[str] = []
        if item.is_image_target() and len(images) == 1:
            mime_types = [get_output_mime_for_image(item.path or "")]
        else:
            mime_types = ["image/png"] * len(images)

        prompt = _get_prompt_for_item(
            item, settings.get("system_prompt_override", "") or "")

        try:
            client = MultimodalAIClient(
                base_url=settings.get("base_url", ""),
                api_key=settings.get("api_key", ""),
                model=settings.get("model", ""),
                prompt=prompt,
                timeout=float(settings.get("timeout", 120.0) or 120.0),
            )
            md = client.process_images(images, mime_types).strip()
        except (MultimodalAIClientError, Exception) as e:
            logging.warning(f"VLM 任务失败: {e}")
            def _fail():
                item.preprocess_status = PreprocessStatus.FAILED
                self._on_status(item)
                self._on_preview(item)
            self._post(_fail)
            return

        work_dir = self._get_work_dir()
        if work_dir and item.path:
            try:
                file_hash = compute_file_hash(item.path)
                cache = PreprocessCache(work_dir)
                cache.save_markdown(item.path, file_hash, md)
            except Exception as e:
                logging.warning(f"写缓存失败: {e}")

        def _done():
            item.preprocessed_content = md
            item.preprocess_status = PreprocessStatus.COMPLETED
            item.from_cache = False
            self._on_status(item)
            self._on_preview(item)
        self._post(_done)

    # ------------------------------------------------------------------ UI 线程桥接
    def _post(self, fn) -> None:
        """把回调安全地送到 Flet UI 线程."""
        page = getattr(self._main_view, "page", None)
        if page is None:
            try:
                fn()
            except Exception as e:
                logging.warning(f"PreprocessRunner 直接回调失败: {e}")
            return
        try:
            page.run_task(self._invoke, fn)
        except Exception as e:
            logging.warning(f"PreprocessRunner.post 失败: {e}")

    async def _invoke(self, fn) -> None:
        try:
            fn()
        except Exception as e:
            logging.warning(f"PreprocessRunner UI 回调异常: {e}")
