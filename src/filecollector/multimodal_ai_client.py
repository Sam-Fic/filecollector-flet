"""多模态 AI 客户端 (二进制文件 -> Markdown).

对齐 GNOME 版 MultimodalAIClient:
- 调用 OpenAI 兼容 Chat Completions 端点
- 上传 base64 编码的图片 (image_url data URL)
- 返回模型产出的 Markdown 文本

与侧边栏 ai_client.AIClient 区别:
- 走同步 send_and_read (单次大请求, 后台线程跑, 不需要工具循环)
- 走 image_url content parts (而非纯文本)
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any


class MultimodalAIClientError(Exception):
    """多模态 AI 调用失败的对外异常 (消息已面向用户)."""


class MultimodalAIClient:
    """OpenAI 兼容 Chat Completions (含 vision)."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 prompt: str = "", timeout: float = 120.0):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.prompt = prompt or ""
        self.timeout = float(timeout)

    def process_images(self, base64_images: list[str],
                       mime_types: list[str] | None = None) -> str:
        """上传一组图片 (已 base64 编码) 给 VLM, 返回模型产出的 Markdown.

        :param base64_images: 不含 ``data:...;base64,`` 前缀的纯 base64 串
        :param mime_types: 与图片一一对应的 MIME, 默认全 ``image/png``
        """
        if not self.base_url:
            raise MultimodalAIClientError("API 基础地址未配置。")
        if not self.api_key:
            raise MultimodalAIClientError("API 密钥未配置。")
        if not self.model:
            raise MultimodalAIClientError("模型名称未配置。")
        if not base64_images:
            raise MultimodalAIClientError("无可处理的图片数据。")

        url = f"{self.base_url}/chat/completions"

        # 构造 messages: 单条 user, content = [text, image, image, ...]
        content_parts: list[dict] = [
            {"type": "text", "text": self.prompt or
             "请将图片中的内容转换为结构清晰的 Markdown 格式。"}
        ]
        for i, b64 in enumerate(base64_images):
            mime = "image/png"
            if mime_types and i < len(mime_types) and mime_types[i]:
                mime = mime_types[i]
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content_parts}],
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        max_retries = 2
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                # 429 / 5xx 走指数退避重试
                if attempt < max_retries and (e.code == 429 or 500 <= e.code < 600):
                    time.sleep(2 ** attempt)
                    last_err = MultimodalAIClientError(
                        f"HTTP {e.code}: {detail[:200]}")
                    continue
                raise MultimodalAIClientError(
                    f"HTTP {e.code} {e.reason}: {detail[:500]}".strip()) from e
            except urllib.error.URLError as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    last_err = MultimodalAIClientError(f"网络错误: {e.reason}")
                    continue
                raise MultimodalAIClientError(f"网络错误: {e.reason}") from e
            except TimeoutError as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    last_err = MultimodalAIClientError("请求超时。")
                    continue
                raise MultimodalAIClientError(
                    "请求超时, 请检查网络或增大超时时间。") from e
            except Exception as e:  # noqa: BLE001
                raise MultimodalAIClientError(f"调用失败: {e}") from e

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as e:
                raise MultimodalAIClientError(
                    f"响应不是合法 JSON: {e}") from e
            return self._extract_content(parsed)

        if last_err:
            raise last_err
        raise MultimodalAIClientError("请求失败: 已达最大重试次数")

    @staticmethod
    def _extract_content(payload: dict) -> str:
        try:
            choices = payload.get("choices") or []
            if not choices:
                raise MultimodalAIClientError("响应 choices 为空")
            msg = choices[0].get("message") or {}
            content = (msg.get("content") or "").strip()
        except MultimodalAIClientError:
            raise
        except Exception as e:  # noqa: BLE001
            raise MultimodalAIClientError(
                f"响应解析失败: {e}") from e
        if not content:
            raise MultimodalAIClientError("模型返回了空内容")
        return content


def encode_file_to_base64(path: str) -> str:
    """读取本地文件, 返回纯 base64 字符串 (不含 data URL 前缀)."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")
