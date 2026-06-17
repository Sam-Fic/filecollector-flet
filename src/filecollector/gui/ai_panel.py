"""AI 助手聊天面板.

UI 布局与现有三栏卡片保持一致 (同 LeftPanel/MiddlePanel/RightPanel 风格):
- 顶部标题: "AI 助手" + 模型名标签
- 中部: QTextBrowser 渲染聊天气泡 (用户右对齐, 助手左对齐)
- 底部: 多行输入框 + 发送按钮
- 状态行: 模型名称 / 当前状态

API 调用走 QThread + Worker, 不阻塞主线程; 工具调用由 main_window
注入的 tool_executor 回调执行, 此处只负责消息展示和对话循环.
"""

from __future__ import annotations

import html
import json
from typing import Callable

from PySide6.QtCore import Qt, QThread, QObject, Signal, QUrl, QSize, QEvent, QPoint, QTimer, QRectF
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QTextBrowser, QScrollArea, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from filecollector.i18n import _
from filecollector.config import BUTTON_HEIGHT
from filecollector.ai_client import (
    AIClient, AIClientError, TOOL_SCHEMA, build_system_prompt,
)
from filecollector.gui.ai_markdown import render_markdown


# tool_executor(name: str, arguments: dict) -> str
ToolExecutor = Callable[[str, dict], str]


# ----------------------------------------------------------------
# QTextBrowser 回退模式用的简化样式 (QTextBrowser 不支持 flexbox / 阴影)
# 用 table 实现左右气泡对齐
# ----------------------------------------------------------------
_CHAT_CSS_SIMPLE = """
body {
    margin: 0;
    padding: 8px 10px;
    font-family: -apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
    line-height: 1.5;
    color: #1f2328;
    background: transparent;
}
.row-left { width: 100%; margin: 10px 0; }
.row-left td { vertical-align: top; }
.row-right { width: 100%; margin: 10px 0; }
.row-right td { vertical-align: top; text-align: right; }
.row-center { width: 100%; margin: 8px 0; }
.row-center td { text-align: center; }

.bubble {
    display: inline-block;
    padding: 10px 14px;
    border-radius: 12px;
    word-wrap: break-word;
    line-height: 1.55;
    font-size: 14px;
    max-width: 360px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
}
.bubble-user {
    background: #2b7fff;
    background-image: linear-gradient(135deg, #2b7fff 0%, #0969da 100%);
    color: #ffffff;
    box-shadow: 0 1px 2px rgba(9,105,218,0.18), 0 2px 6px rgba(9,105,218,0.10);
}
.bubble-assistant {
    background: #ffffff;
    color: #1f2328;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.bubble-system {
    background: #fff8c5;
    color: #9a6700;
    border: 1px solid #d4a72c;
    font-size: 12px;
    padding: 6px 14px;
    border-radius: 12px;
    max-width: 100%;
}
.bubble-tool {
    background: #fdf6e3;
    color: #586e75;
    border: 1px solid #eee8d5;
    padding: 0;
    border-radius: 8px;
    max-width: 100%;
    display: block;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}

.bubble-content p { margin: 0 0 4px 0; }
.bubble-content p:last-child { margin: 0; }
.bubble-content h1, .bubble-content h2, .bubble-content h3 { margin: 6px 0 4px 0; font-weight: bold; }
.bubble-content ul, .bubble-content ol { margin: 4px 0 4px 18px; padding: 0; }
.bubble-content blockquote { margin: 4px 0; padding: 2px 8px; border-left: 3px solid #c5c5c5; color: #555; }
.bubble-content code { background: rgba(0,0,0,0.08); padding: 1px 4px; border-radius: 3px; font-family: "Consolas", monospace; font-size: 12px; }
.bubble-content pre.md-pre { background: rgba(0,0,0,0.08); padding: 6px 8px; border-radius: 4px; overflow-x: auto; margin: 4px 0; }
.bubble-content pre.md-pre code { background: transparent; padding: 0; }
.bubble-content a { color: #0969da; text-decoration: none; }
.bubble-content a:hover { text-decoration: underline; }
.bubble-content table { border-collapse: collapse; margin: 4px 0; }
.bubble-content th, .bubble-content td { border: 1px solid #d0d7de; padding: 4px 8px; }

/* 用户气泡内的元素在深色背景上的对比度 */
.bubble-user .bubble-content a { color: #cfe2ff; }
.bubble-user .bubble-content code { background: rgba(255,255,255,0.18); color: #ffffff; }
.bubble-user .bubble-content pre.md-pre { background: rgba(255,255,255,0.12); }
.bubble-user .bubble-content blockquote { border-left-color: rgba(255,255,255,0.4); color: rgba(255,255,255,0.85); background: rgba(255,255,255,0.08); }
.bubble-user .bubble-content table th, .bubble-user .bubble-content table td { border-color: rgba(255,255,255,0.3); color: #ffffff; }

.tool-header {
    display: block;
    padding: 8px 12px;
    color: inherit;
    text-decoration: none;
    cursor: pointer;
}
.tool-header:hover { background: rgba(0,0,0,0.04); }
.tool-arrow { color: #b58900; font-size: 11px; margin-right: 4px; }
.tool-icon { background: #b58900; color: #fff; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: bold; margin-right: 6px; }
.tool-name { font-weight: bold; }
.tool-args { color: #657b83; font-size: 11px; }
.tool-action { color: #b58900; font-size: 11px; margin-left: 8px; }
.tool-body { padding: 0 12px 8px 12px; border-top: 1px dashed #eee8d5; }
.tool-result { background: #fff; padding: 6px 8px; border-radius: 4px; margin: 6px 0 0 0; white-space: pre-wrap; word-wrap: break-word; font-family: "Consolas", monospace; font-size: 11px; color: #073642; max-height: 300px; overflow-y: auto; }
.tool-body-preview { font-style: italic; color: #657b83; font-size: 11px; padding-top: 6px; }
"""


class _LinkAwareWebEnginePage(QWebEnginePage):
    """自定义 QWebEnginePage, 拦截 toggle:// 链接点击.

    旧版 PySide6 没有 setLinkDelegationPolicy, 改用 acceptNavigationRequest
    拦截导航请求实现相同效果.
    """

    toggleRequested = Signal(int)

    # type: ignore[override]
    # type: ignore[override]
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # 兼容旧版 PySide6: nav_type 在某些版本是 int 而非 NavigationType 枚举
        from PySide6.QtWebEngineCore import QWebEnginePage
        if url.scheme() == "toggle":
            raw = url.path().lstrip("/") or url.toString().split(":", 1)[-1]
            try:
                tool_id = int(raw)
            except ValueError:
                return False
            self.toggleRequested.emit(tool_id)
            return False  # 不实际导航
        # 不是 toggle 链接, 委托给父类 (QDesktopServices 不在浏览器中打开外链
        # 的话, 浏览器会自己处理)
        try:
            if isinstance(nav_type, int):
                nav_type = QWebEnginePage.NavigationType(nav_type)
        except Exception:
            pass
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


# 聊天气泡 / 工具调用卡片 的局部样式 (注入到 QWebEngineView 的 HTML 中).
# 主题: 浅色现代风格, 类似 ChatGPT / 现代 IDE.
_CHAT_CSS = """
:root {
    color-scheme: light;
    --bg: #ffffff;
    --fg: #1f2328;
    --muted: #57606a;
    --border: #d0d7de;
    --user-bg: linear-gradient(135deg, #2b7fff 0%, #0969da 100%);
    --user-fg: #ffffff;
    --user-border: rgba(9, 105, 218, 0.0);
    --assistant-bg: #ffffff;
    --assistant-fg: #1f2328;
    --assistant-border: #d0d7de;
    --system-bg: #fff8c5;
    --system-fg: #9a6700;
    --system-border: #d4a72c;
    --tool-bg: #fdf6e3;
    --tool-fg: #586e75;
    --tool-border: #eee8d5;
    --tool-result-bg: #fbf2d4;
    --code-bg: #f6f8fa;
    --code-fg: #1f2328;
    --link: #0969da;
    --row-alt: #f6f8fa;
    --shadow-user: 0 1px 2px rgba(9, 105, 218, 0.15),
                   0 2px 6px rgba(9, 105, 218, 0.10);
    --shadow: 0 1px 2px rgba(31, 35, 40, 0.04),
              0 3px 6px rgba(31, 35, 40, 0.06);
}

* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 12px 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei",
                 sans-serif;
    font-size: 14px;
    line-height: 1.55;
    color: var(--fg);
    background: transparent;
}

.chat-container {
    max-width: 820px;
    margin: 0 auto;
}

/* ---- 气泡行 ---- */
.bubble-row {
    margin: 10px 0;
    width: 100%;
}
/* 用户消息: 右对齐 */
.bubble-row-user { text-align: right; }
.bubble-row-user .bubble { display: inline-block; text-align: left; }
/* AI 消息: 左对齐 */
.bubble-row-assistant { text-align: left; }
.bubble-row-assistant .bubble { display: inline-block; text-align: left; }
/* 系统消息 / 工具调用: 居中 */
.bubble-row-system,
.bubble-row-tool { text-align: center; }
.bubble-row-system .bubble,
.bubble-row-tool > div { display: inline-block; text-align: left; }

.bubble {
    padding: 10px 14px;
    word-wrap: break-word;
    word-break: break-word;
    overflow-wrap: anywhere;
    line-height: 1.55;
    position: relative;
    font-size: 14px;
}

/* ---- 用户气泡 (右对齐, 蓝色填充) ---- */
.bubble-user {
    background: var(--user-bg);
    color: var(--user-fg);
    border-radius: 12px;
    max-width: 80%;
    box-shadow: var(--shadow-user);
}
.bubble-user .bubble-content a { color: #cfe2ff; }
.bubble-user .bubble-content a:hover { color: #ffffff; }
.bubble-user .bubble-content code {
    background: rgba(255, 255, 255, 0.18);
    color: #ffffff;
}
.bubble-user .bubble-content pre.md-pre {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.2);
    color: #ffffff;
}
.bubble-user .bubble-content pre.md-pre code { color: #ffffff; }
.bubble-user .bubble-content blockquote {
    border-left-color: rgba(255, 255, 255, 0.4);
    color: rgba(255, 255, 255, 0.85);
    background: rgba(255, 255, 255, 0.08);
}
.bubble-user .bubble-content table th,
.bubble-user .bubble-content table td {
    border-color: rgba(255, 255, 255, 0.3);
    color: #ffffff;
}
.bubble-user .bubble-content th { background: rgba(255, 255, 255, 0.1); }
.bubble-user .bubble-content hr { border-top-color: rgba(255, 255, 255, 0.3); }

/* ---- AI 气泡 (左对齐, 纯白) ---- */
.bubble-assistant {
    background: var(--assistant-bg);
    color: var(--assistant-fg);
    border-radius: 12px;
    max-width: 85%;
    box-shadow: var(--shadow);
}

/* ---- 系统提示 (居中, 短文字) ---- */
.bubble-system {
    background: var(--system-bg);
    color: var(--system-fg);
    border: 1px solid var(--system-border);
    border-radius: 12px;
    font-size: 12px;
    text-align: center;
    max-width: 100%;
    padding: 6px 14px;
}

/* ---- markdown 内部元素 (助手气泡) ---- */
.bubble-assistant .bubble-content > *:first-child { margin-top: 0; }
.bubble-assistant .bubble-content > *:last-child  { margin-bottom: 0; }
.bubble-content p { margin: 0 0 8px 0; }
.bubble-content h1, .bubble-content h2, .bubble-content h3,
.bubble-content h4, .bubble-content h5, .bubble-content h6 {
    margin: 14px 0 6px 0;
    font-weight: 600;
    line-height: 1.3;
}
.bubble-content h1 { font-size: 22px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.bubble-content h2 { font-size: 19px; padding-bottom: 5px; border-bottom: 1px solid var(--border); }
.bubble-content h3 { font-size: 17px; }
.bubble-content h4 { font-size: 15px; }
.bubble-content ul, .bubble-content ol {
    margin: 6px 0 8px 0;
    padding-left: 24px;
}
.bubble-content li { margin: 2px 0; }
.bubble-content li > p { margin: 2px 0; }
.bubble-content blockquote {
    margin: 8px 0;
    padding: 0 12px;
    border-left: 3px solid var(--border);
    color: var(--muted);
    background: rgba(175, 184, 193, 0.1);
    border-radius: 0 4px 4px 0;
}
.bubble-content hr {
    border: 0;
    border-top: 1px solid var(--border);
    margin: 14px 0;
}
.bubble-content a {
    color: var(--link);
    text-decoration: none;
}
.bubble-content a:hover { text-decoration: underline; }

.bubble-content code {
    background: rgba(175, 184, 193, 0.2);
    padding: 1px 5px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas,
                 "Liberation Mono", Menlo, monospace;
    font-size: 0.88em;
}
.bubble-content pre.md-pre {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 14px;
    overflow-x: auto;
    margin: 8px 0;
    line-height: 1.5;
}
.bubble-content pre.md-pre code.md-code {
    background: transparent;
    padding: 0;
    border-radius: 0;
    font-size: 13px;
    color: var(--code-fg);
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas,
                 "Liberation Mono", Menlo, monospace;
}

/* Pygments 语法高亮 - GitHub Light 主题配色 */
.md-codehilite .hll { background-color: #ffffcc; }
.md-codehilite .c, .md-codehilite .c1, .md-codehilite .cm,
.md-codehilite .cs, .md-codehilite .cd { color: #6e7781; font-style: italic; }
.md-codehilite .err { color: #cf222e; }
.md-codehilite .k, .md-codehilite .kc, .md-codehilite .kd,
.md-codehilite .kn, .md-codehilite .kp, .md-codehilite .kr,
.md-codehilite .kt { color: #cf222e; }
.md-codehilite .n  { color: #1f2328; }
.md-codehilite .na { color: #8250df; }
.md-codehilite .nb { color: #0550ae; }
.md-codehilite .bp { color: #0550ae; }
.md-codehilite .nc { color: #953800; }
.md-codehilite .ne { color: #cf222e; }
.md-codehilite .nf { color: #8250df; }
.md-codehilite .nl { color: #953800; }
.md-codehilite .nn { color: #1f2328; }
.md-codehilite .nv, .md-codehilite .vc, .md-codehilite .vg,
.md-codehilite .vi { color: #953800; }
.md-codehilite .o, .md-codehilite .ow { color: #cf222e; }
.md-codehilite .s, .md-codehilite .s1, .md-codehilite .s2,
.md-codehilite .sa, .md-codehilite .sb, .md-codehilite .sc,
.md-codehilite .dl, .md-codehilite .sd, .md-codehilite .se,
.md-codehilite .sh, .md-codehilite .si, .md-codehilite .sx,
.md-codehilite .sr, .md-codehilite .ss { color: #0a3069; }
.md-codehilite .m, .md-codehilite .mb, .md-codehilite .mf,
.md-codehilite .mh, .md-codehilite .mi, .md-codehilite .il,
.md-codehilite .mo { color: #0550ae; }
.md-codehilite .w  { color: #6e7781; }
.md-codehilite .ge { font-style: italic; }
.md-codehilite .gs { font-weight: bold; }
.md-codehilite .gh { color: #0550ae; font-weight: bold; }
.md-codehilite .go { color: #6e7781; }
.md-codehilite .gp { color: #0550ae; font-weight: bold; }
.md-codehilite .gu { color: #0550ae; font-weight: bold; }
.md-codehilite .gi { color: #0550ae; font-weight: bold; }
.md-codehilite .gd { color: #cf222e; }
.md-codehilite .gt { color: #cf222e; }
.md-codehilite .gi, .md-codehilite .gd { background: rgba(0,0,0,0.04); }
.md-codehilite .kc, .md-codehilite .kn, .md-codehilite .kp,
.md-codehilite .kr, .md-codehilite .kt { color: #cf222e; }
.md-codehilite .kd { color: #cf222e; }
.md-codehilite .nt { color: #116329; }

/* ---- 表格 ---- */
.bubble-content table {
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 13px;
    width: 100%;
}
.bubble-content table-wrap {
    overflow-x: auto;
    max-width: 100%;
}
.bubble-content thead { background: var(--row-alt); }
.bubble-content th, .bubble-content td {
    border: 1px solid var(--border);
    padding: 6px 12px;
    text-align: left;
}
.bubble-content th { font-weight: 600; background: var(--row-alt); }
.bubble-content tbody tr:nth-child(even) { background: var(--row-alt); }

/* ---- 任务列表 ---- */
.bubble-content input[type="checkbox"] {
    margin-right: 6px;
    vertical-align: middle;
}

/* ---- 工具调用卡片 ---- */
.bubble-tool {
    background: var(--tool-bg);
    color: var(--tool-fg);
    border: 1px solid var(--tool-border);
    border-radius: 8px;
    padding: 0;
    overflow: hidden;
    box-shadow: var(--shadow);
    max-width: 100%;
}
.tool-header {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    cursor: pointer;
    user-select: none;
    gap: 8px;
    background: rgba(0, 0, 0, 0.02);
    border-bottom: 1px solid transparent;
    transition: background 0.12s;
    color: inherit;
    text-decoration: none;
}
.tool-header:visited { color: inherit; }
.tool-header:hover { background: rgba(0, 0, 0, 0.05); text-decoration: none; }
.tool-arrow {
    display: inline-block;
    width: 12px;
    text-align: center;
    font-size: 10px;
    color: #b58900;
    transition: transform 0.15s;
}
.tool-card.expanded .tool-arrow { transform: rotate(90deg); }
.tool-icon {
    width: 18px; height: 18px;
    border-radius: 4px;
    background: #b58900;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 600;
}
.tool-name { font-weight: 600; }
.tool-args {
    color: #657b83;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas, monospace;
    font-size: 12px;
    opacity: 0.85;
    word-break: break-all;
    flex: 1;
}
.tool-action {
    color: #b58900;
    font-size: 11px;
    font-weight: 500;
}
.tool-body {
    display: none;
    padding: 10px 14px 12px 14px;
    border-top: 1px dashed var(--tool-border);
    background: var(--tool-result-bg);
}
.tool-card.expanded .tool-body { display: block; }
.tool-result {
    background: #fff;
    border: 1px solid var(--tool-border);
    padding: 8px 10px;
    border-radius: 4px;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas, monospace;
    font-size: 12px;
    color: #073642;
    max-height: 300px;
    overflow-y: auto;
    margin: 0;
}
.tool-card:not(.expanded) .tool-body-preview {
    display: block;
    padding-top: 0;
    border-top: none;
    background: transparent;
    color: #657b83;
    font-style: italic;
    font-size: 12px;
    margin-left: 28px;
    padding-bottom: 0;
}

/* ---- 滚动条 ---- */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.18);
    border-radius: 5px;
    border: 2px solid var(--bg);
}
::-webkit-scrollbar-thumb:hover { background: rgba(0, 0, 0, 0.3); }
"""


class _AIWorker(QObject):
    """后台执行单次 chat 请求的 worker."""

    finished = Signal(object)  # dict
    failed = Signal(str)

    def __init__(self, client: AIClient, messages: list[dict], tools: list[dict] | None):
        super().__init__()
        self._client = client
        self._messages = messages
        self._tools = tools
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            data = self._client.chat(self._messages, self._tools)
        except AIClientError as e:
            if not self._cancelled:
                self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            if not self._cancelled:
                self.failed.emit(str(e))
        else:
            if not self._cancelled:
                self.finished.emit(data)


class MessageBubble(QWidget):
    """聊天气泡控件: 自定义 QPainter 画圆角矩形, 内部嵌 QTextBrowser 显示内容.

    设计动机: QTextBrowser 不支持 CSS3 border-radius, 想要真正的圆角矩形
    必须自己用 QPainter 画. 这样还能避开 QWebEngineView 在某些 GPU 环境
    (Vulkan 缺失) 下崩溃 X server 的问题.
    """

    # role -> (背景色, 前景色, 边框色)
    ROLE_STYLES = {
        "user":      (QColor("#2b7fff"), QColor("#ffffff"), QColor("#0969da")),
        "assistant": (QColor("#ffffff"), QColor("#1f2328"), QColor("#d0d7de")),
        "system":    (QColor("#fff8c5"), QColor("#9a6700"), QColor("#d4a72c")),
        "tool":      (QColor("#fdf6e3"), QColor("#586e75"), QColor("#eee8d5")),
    }

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self._role = role
        bg, fg, _ = self.ROLE_STYLES[role]
        self._padding_x = 12
        self._padding_y = 8
        self._radius = 12
        self._max_width_ratio = 0.80  # 气泡最大占父容器宽度的 80%
        self._alignment = "left"
        self._natural_w = 1  # 内容自然宽度 (不换行时)
        self._min_bubble_w = 40  # 气泡最小宽度, 保证极短内容也能显示

        # 内容视图: QTextBrowser 渲染 HTML (markdown 转换结果)
        self._browser = QTextBrowser(self)
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.setFrameShape(QFrame.NoFrame)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._browser.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none; color: {fg.name()}; }}"
            f" a {{ color: {fg.name()}; }}"
        )
        # Document margin = 0 避免内容跟边框有间距
        doc = self._browser.document()
        doc.setDocumentMargin(0)

        # 大小策略: Preferred - layout 可以给比 sizeHint 小的宽度
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Preferred)
        sp.setVerticalPolicy(QSizePolicy.Fixed)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

        # 监听父容器 resize: 父容器变窄时重新排版
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        # 监听任何祖先 resize: 父容器/祖父容器变窄时都重新排版
        if event.type() == QEvent.Resize:
            self._reflow()
        return super().eventFilter(obj, event)

    def set_content(self, html_content: str) -> None:
        """设置气泡内的 HTML 内容 (markdown 已经渲染好的)."""
        self._browser.setHtml(html_content)
        # 用 setTextWidth(-1) 测自然宽度 (不换行时)
        doc = self._browser.document()
        doc.setTextWidth(-1)
        self._natural_w = max(
            1, int(doc.documentLayout().documentSize().width()))
        self._reflow()

    def set_alignment(self, alignment: str) -> None:
        """alignment: "left" | "right" | "center" - 决定气泡在父布局中的位置."""
        self._alignment = alignment
        self._reflow()

    def _reflow(self) -> None:
        """根据父容器宽度 + 内容自然宽度, 决定气泡实际宽高."""
        parent_w = self.parentWidget().width() if self.parentWidget() else 360
        if self._role == "tool":
            side_gap = self._tool_side_gap()
            max_w = max(self._min_bubble_w, parent_w - 2 * side_gap)
        else:
            max_w = max(self._min_bubble_w, int(parent_w * self._max_width_ratio))
        max_text_w = max(1, max_w - 2 * self._padding_x)
        # 实际排版宽度 = min(自然宽度, max_text_w)
        actual_text_w = min(self._natural_w, max_text_w)
        if self._role == "tool":
            actual_text_w = max_text_w
        # 用实际宽度让文档重新排版, 得到真实高度
        doc = self._browser.document()
        doc.setTextWidth(actual_text_w)
        self._browser.setFixedWidth(actual_text_w)
        # 强制文档重新布局, 防止长内容时高度读取得不准确
        text_h = max(1, int(doc.documentLayout().documentSize().height()))
        bubble_h = text_h + 2 * self._padding_y
        # 气泡宽度 = 内容宽 + padding, 但不超过 max_w, 不小于 min_bubble_w
        bubble_w = max(self._min_bubble_w, min(
            max_w, actual_text_w + 2 * self._padding_x))
        # 定位 QTextBrowser 在气泡内 (带 padding)
        self._browser.setFixedHeight(text_h)
        self._browser.move(self._padding_x, self._padding_y)
        # 关键: 用 sizeHint + min/max, 不用 setFixedSize
        # 这样父容器变窄时 layout 可以把气泡缩到 min/max 范围内
        self.setMinimumSize(self._min_bubble_w, bubble_h)
        self.setMaximumSize(max_w, bubble_h)
        self.resize(bubble_w, bubble_h)
        self._pref_size = QSize(bubble_w, bubble_h)

    def _tool_side_gap(self) -> int:
        parent = self.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is None:
            return 8
        margins = layout.contentsMargins()
        left, right = margins.left(), margins.right()
        return left if left == right else min(left, right)

    def sizeHint(self) -> QSize:
        return getattr(self, "_pref_size", QSize(200, 40))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        """layout 用 heightForWidth 决定气泡高度 - 跟实际宽度同步."""
        max_w = max(self._min_bubble_w, int(self._max_width_ratio *
                    (self.parentWidget().width() if self.parentWidget() else 360)))
        if self._role == "tool":
            parent_w = self.parentWidget().width() if self.parentWidget() else 360
            max_w = max(
                self._min_bubble_w,
                parent_w - 2 * self._tool_side_gap(),
            )
        actual_w = max(self._min_bubble_w, min(max_w, width))
        actual_text_w = max(1, actual_w - 2 * self._padding_x)
        doc = self._browser.document()
        doc.setTextWidth(actual_text_w)
        text_h = max(1, int(doc.documentLayout().documentSize().height()))
        return text_h + 2 * self._padding_y

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 实际宽度变化时同步 browser 尺寸 + 气泡自身高度 (跟内容文本同步)
        text_w = max(1, self.width() - 2 * self._padding_x)
        doc = self._browser.document()
        doc.setTextWidth(text_w)
        self._browser.setFixedWidth(text_w)
        text_h = max(1, int(doc.documentLayout().documentSize().height()))
        self._browser.setFixedHeight(text_h)
        self._browser.move(self._padding_x, self._padding_y)
        # 同步气泡高度 (layout 给的宽度可能让文本换行增多)
        new_h = text_h + 2 * self._padding_y
        if self.height() != new_h:
            # 用 setMaximumSize 限制高度, 然后 resize
            self.setMaximumSize(self.maximumWidth(), new_h)
            self.resize(self.width(), new_h)
            self._pref_size = QSize(self.width(), new_h)

    def paintEvent(self, event) -> None:
        """在 QTextBrowser 下面画一个圆角矩形作为气泡背景."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg, _, border = self.ROLE_STYLES[self._role]
        r = self._radius
        # 背景: 内缩 1px 避免与边框重叠产生模糊
        bg_rect = self.rect().adjusted(1, 1, -1, -1)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(bg_rect), r, r)
        painter.fillPath(bg_path, bg)
        # 工具/系统/AI 气泡加 1px 边框, 用户气泡纯填充 (深色边沿由 box-shadow 替代)
        if self._role in ("assistant", "system", "tool"):
            border_path = QPainterPath()
            border_path.addRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), r, r)
            pen = QPen(border, 1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(border_path)
        # 不调 super().paintEvent(): QTextBrowser 自己在 paintEvent 里画自己


# 旧的 chat_view 标识, 保留避免破坏其他模块引用
_AIChatViewBase = QTextBrowser


class AIPanel(QFrame):
    """可嵌入主窗口 splitter 的 AI 边栏."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIPanel")

        self._messages: list[dict] = []
        self._system_prompt_override: str = ""
        self._client: AIClient | None = None
        self._tool_executor: ToolExecutor | None = None
        self._state_provider: Callable[[], tuple] | None = None
        self._thread: QThread | None = None
        self._worker: _AIWorker | None = None
        self._scroll_bottom_btn: QPushButton | None = None
        self._busy = False
        self._pending_welcome = True
        self._stop_requested = False
        # 渲染层消息列表 + 工具调用折叠状态
        self._rendered_messages: list[dict] = []
        self._tool_counter: int = 0

        self._build_ui()

    # ------------------------------------------------------------------ 公共 API
    def configure(
        self,
        ai_settings: dict,
        tool_executor: ToolExecutor,
        state_provider: Callable[[], tuple],
    ) -> None:
        """由 main_window 在初始化或设置变更时调用.

        ai_settings  : 从 settings.json["ai"] 读取的字典
        tool_executor: 工具调用回调 (name, args) -> result_str
        state_provider: () -> (work_dir, items, use_absolute, show_header)
        """
        self._tool_executor = tool_executor
        self._state_provider = state_provider
        self._system_prompt_override = (ai_settings.get(
            "system_prompt_override") or "").strip()

        base = (ai_settings.get("base_url") or "").strip()
        key = (ai_settings.get("api_key") or "").strip()
        model = (ai_settings.get("model") or "").strip()
        timeout = float(ai_settings.get("timeout", 60.0) or 60.0)

        self.model_label.setText(model or _("未配置模型"))
        if base and key and model:
            self._client = AIClient(base, key, model, timeout)
        else:
            self._client = None

        enabled = bool(ai_settings.get("enabled"))
        self._update_status()

        if enabled and self._pending_welcome:
            self._pending_welcome = False
            self._render_assistant(
                _("你好, 我是 AI 编排助手。告诉我你想收集哪些文件, 我来帮你编排。\n"
                  "例如: \"把 src 目录下所有 Python 文件加进去, 然后在开头插入一段任务说明。\"")
            )

    def shutdown(self) -> None:
        """主窗口关闭时清理后台线程."""
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    # ------------------------------------------------------------------ UI 构建
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title = QLabel(_("AI 助手"))
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        # 聊天区: 用 QScrollArea + 自定义气泡控件 (MessageBubble) 实现
        # - QWebEngineView 需要 GPU/Vulkan, 在某些 Linux 环境会拖垮 X server
        # - QTextBrowser 不支持 CSS3 border-radius, 圆角无法画出
        # - MessageBubble 用 QPainter 画圆角矩形, 不依赖任何 GPU/CSS3
        self._use_webengine = False
        self.chat_view = self._create_chat_view()

        chat_outer = QFrame()
        chat_outer.setObjectName("AIChatOuter")
        outer_layout = QVBoxLayout(chat_outer)
        outer_layout.setContentsMargins(10, 0, 10, 6)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.chat_view)

        self._scroll_bottom_btn = QPushButton(_("回到底部"), chat_outer)
        self._scroll_bottom_btn.setObjectName("AIScrollBottomButton")
        self._scroll_bottom_btn.setFixedHeight(32)
        self._scroll_bottom_btn.setCursor(Qt.PointingHandCursor)
        self._scroll_bottom_btn.clicked.connect(self._scroll_chat_to_bottom_now)
        self._scroll_bottom_btn.setStyleSheet(
            "QPushButton#AIScrollBottomButton {"
            " background: #ffffff;"
            " border: 1px solid #d0d7de;"
            " border-radius: 16px;"
            " padding: 6px 10px;"
            " color: #57606a;"
            " font-size: 12px;"
            "}"
            "QPushButton#AIScrollBottomButton:hover {"
            " background: #f6f8fa;"
            " border-color: #afb8c1;"
            "}"
        )
        self._scroll_bottom_btn.hide()
        self.chat_view.verticalScrollBar().valueChanged.connect(
            self._update_scroll_bottom_button)
        self.chat_view.verticalScrollBar().rangeChanged.connect(
            self._update_scroll_bottom_button)
        root.addWidget(chat_outer, 1)

        # 输入区
        input_frame = QFrame()
        input_frame.setObjectName("AIInputFrame")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(6)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("AIInput")
        self.input_edit.setPlaceholderText(_("输入指令, Enter 发送, Ctrl+Enter 换行"))
        self.input_edit.setFixedHeight(90)
        self.input_edit.installEventFilter(self)
        input_layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_clear = QPushButton(_("清空对话"))
        self.btn_clear.setFixedHeight(BUTTON_HEIGHT)
        self.btn_clear.clicked.connect(self._on_clear_chat)
        self.btn_send = QPushButton(_("发送"))
        self.btn_send.setObjectName("SuggestedAction")
        self.btn_send.setFixedHeight(BUTTON_HEIGHT)
        self.btn_send.clicked.connect(self._on_send_or_stop)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_send)
        input_layout.addLayout(btn_row)

        root.addWidget(input_frame)

        # 状态行
        status_row = QHBoxLayout()
        status_row.setContentsMargins(12, 0, 12, 8)
        self.status_label = QLabel("")
        self.status_label.setObjectName("AIStatusLabel")
        self.model_label = QLabel("")
        self.model_label.setObjectName("AIModelLabel")
        self.model_label.setAlignment(Qt.AlignRight)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.model_label)
        root.addLayout(status_row)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumWidth(280)

    def _create_chat_view(self) -> QWidget:
        """构造 chat_view: 用 QScrollArea + 内部 container 容纳 MessageBubble.

        始终使用自定义气泡 (QPainter 画圆角), 不再用 QWebEngineView/QTextBrowser:
        - QWebEngineView 在缺少 GPU/Vulkan 的环境会拖垮 X server
        - QTextBrowser 不支持 CSS3 border-radius
        """
        scroll = QScrollArea()
        scroll.setObjectName("AIChatView")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        # 内部 container: 放所有气泡
        container = QWidget()
        container.setObjectName("AIChatContainer")
        container.setStyleSheet(
            "QWidget#AIChatContainer { background: transparent; }"
        )
        v = QVBoxLayout(container)
        v.setContentsMargins(8, 0, 8, 8)
        v.setSpacing(8)
        # 尾部 stretch: 当内容不足一屏时把多余空间留在底部, 让气泡靠顶部
        v.addStretch(1)

        scroll.setWidget(container)
        # 暴露 container 方便后续添加气泡
        scroll._container_layout = v   # type: ignore[attr-defined]
        return scroll

    # ------------------------------------------------------------------ 事件
    def _on_toggle_requested(self, tool_id: int) -> None:
        """通过自定义 WebEnginePage 收到 toggle 链接点击, 翻转对应 tool 的展开态."""
        for msg in self._rendered_messages:
            if msg["type"] == "tool" and msg["id"] == tool_id:
                msg["expanded"] = not msg["expanded"]
                break
        self._render_chat(preserve_tool_id=tool_id)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """处理 chat_view 中的链接点击 (兼容旧 signal API)."""
        if url.scheme() == "toggle":
            self._on_toggle_requested(
                int(url.path().lstrip("/") or url.toString().split(":", 1)[-1])
            )
            return
        # 外部链接: 用系统浏览器打开
        if url.scheme() in ("http", "https", "file", "ftp"):
            QDesktopServices.openUrl(url)

    def _on_send_or_stop(self) -> None:
        """发送按钮在 busy 时变成停止, 点击后中断当前请求."""
        if self._busy:
            self._request_stop()
            return
        self._on_send()

    def _request_stop(self) -> None:
        """标记停止, 让 worker 完成后不处理结果."""
        self._stop_requested = True
        if self._worker is not None:
            self._worker.cancel()
        self.status_label.setText(_("已停止"))
        self._set_busy(False)
        self._stop_requested = False

    def eventFilter(self, obj, event):
        if obj is self.input_edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier:
                    return False
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll_bottom_button_position()

    # ------------------------------------------------------------------ 渲染
    def _render_user(self, text: str) -> None:
        self._rendered_messages.append({"type": "user", "content": text})
        self._render_chat()

    def _render_assistant(self, text: str) -> None:
        self._rendered_messages.append({"type": "assistant", "content": text})
        self._render_chat()

    def _render_system(self, text: str) -> None:
        self._rendered_messages.append({"type": "system", "content": text})
        self._render_chat()

    def _render_tool(self, name: str, args: dict, result: str) -> None:
        self._tool_counter += 1
        self._rendered_messages.append({
            "type": "tool",
            "id": self._tool_counter,
            "name": name,
            "args": args,
            "result": result or "OK",
            "expanded": False,
        })
        self._render_chat()

    def _render_chat(self, preserve_tool_id: int | None = None) -> None:
        """从 _rendered_messages 整体重建聊天视图 (MessageBubble 列表)."""
        scroll_anchor = None
        if preserve_tool_id is not None:
            scroll_anchor = self._record_tool_scroll_anchor(preserve_tool_id)
        should_scroll_bottom = self._is_chat_at_bottom()
        # 清空旧气泡 (保留顶部的 stretch)
        layout = self.chat_view._container_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        for msg in self._rendered_messages:
            t = msg["type"]
            if t == "user":
                self._add_bubble("user", msg["content"], "right")
            elif t == "assistant":
                self._add_bubble("assistant", msg["content"], "left")
            elif t == "system":
                self._add_bubble("system", msg["content"], "center")
            elif t == "tool":
                self._add_tool_bubble(msg)
        # 触发布局更新
        QApplication.processEvents()
        if scroll_anchor is not None and self._restore_tool_scroll_anchor(scroll_anchor):
            self._update_scroll_bottom_button()
            return
        if should_scroll_bottom:
            self._scroll_chat_to_bottom()
        else:
            self._update_scroll_bottom_button()

    def _find_message_row(self, message_type: str, message_id: int | None = None) -> QWidget | None:
        layout = self.chat_view._container_layout
        for index in range(layout.count()):
            row = layout.itemAt(index).widget()
            if row is None:
                continue
            if getattr(row, "_ai_message_type", None) != message_type:
                continue
            if message_id is not None and getattr(row, "_ai_message_id", None) != message_id:
                continue
            return row
        return None

    def _record_tool_scroll_anchor(self, tool_id: int) -> dict:
        row = self._find_message_row("tool", tool_id)
        if row is None:
            return {"tool_id": tool_id, "view_y": 0}
        return {
            "tool_id": tool_id,
            "view_y": row.mapTo(self.chat_view.viewport(), QPoint(0, 0)).y(),
        }

    def _restore_tool_scroll_anchor(self, anchor: dict) -> bool:
        row = self._find_message_row("tool", anchor["tool_id"])
        if row is None:
            return False
        container = self.chat_view.widget()
        row_y = row.mapTo(container, QPoint(0, 0)).y()
        value = max(0, row_y - anchor["view_y"])
        self.chat_view.verticalScrollBar().setValue(value)
        return True

    def _add_bubble(self, role: str, content: str, alignment: str) -> None:
        """添加一条普通消息气泡."""
        from filecollector.gui.ai_markdown import render_markdown
        html_content = render_markdown(content) if content else ""
        bubble = MessageBubble(role, parent=self.chat_view.widget())
        bubble.set_alignment(alignment)
        bubble.set_content(html_content)
        # 用一个水平布局行把气泡推到对应位置
        row = QWidget()
        row._ai_message_type = "user"  # type: ignore[attr-defined]
        row._ai_message_id = None  # type: ignore[attr-defined]
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        if alignment == "right":
            h.addStretch(1)
            h.addWidget(bubble)
        elif alignment == "left":
            h.addWidget(bubble)
            h.addStretch(1)
        else:  # center
            h.addStretch(1)
            h.addWidget(bubble)
            h.addStretch(1)
        # 插在 stretch 之前
        layout = self.chat_view._container_layout
        layout.insertWidget(layout.count() - 1, row)

    def _add_tool_bubble(self, msg: dict) -> None:
        """工具调用: 居中卡片, 头部可点击展开, 内部直接显示结果 (默认折叠)."""
        name = html.escape(msg["name"])
        args_repr = self._format_tool_args(msg["name"], msg["args"])
        if len(args_repr) > 1200:
            args_repr = args_repr[:1200] + "…"
        args_esc = html.escape(args_repr)
        expanded = msg["expanded"]
        action = _("收起") if expanded else _("查看结果")
        tool_id = msg["id"]
        if expanded:
            body_html = (
                '<pre class="tool-result">'
                f'{html.escape(msg["result"])}</pre>'
            )
        else:
            preview = msg["result"] or ""
            if len(preview) > 80:
                preview = preview[:80] + "…"
            preview = html.escape(preview)
            body_html = f'<div class="tool-body-preview">{preview or "—"}</div>'

        full_html = (
            f'<div class="tool-card">'
            f'<a class="tool-header" href="toggle:{tool_id}">'
            f'<span class="tool-arrow">{("▼" if expanded else "▶")}</span>'
            f'<span class="tool-name">{name}</span>'
            f'<span class="tool-args">{args_esc}</span>'
            f'<span class="tool-action">{action}</span>'
            f'</a>'
            f'<div class="tool-body">{body_html}</div>'
            f'</div>'
        )

        bubble = MessageBubble("tool", parent=self.chat_view.widget())
        bubble.set_alignment("center")
        bubble.set_content(full_html)
        # 监听 toggle 链接: 连接到内嵌 QTextBrowser 的 anchorClicked 信号
        bubble._browser.anchorClicked.connect(self._on_anchor_clicked)
        # 居中
        row = QWidget()
        row._ai_message_type = "tool"  # type: ignore[attr-defined]
        row._ai_message_id = msg["id"]  # type: ignore[attr-defined]
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addStretch(1)
        h.addWidget(bubble)
        h.addStretch(1)
        layout = self.chat_view._container_layout
        layout.insertWidget(layout.count() - 1, row)

    # 旧的 _render_chat_webengine / _render_chat_textbrowser 已废弃, 保留以防旧引用
    def _render_chat_webengine(self) -> None:  # pragma: no cover
        self._render_chat()

    def _render_chat_textbrowser(self) -> None:  # pragma: no cover
        self._render_chat()

    def _is_chat_at_bottom(self) -> bool:
        sb = self.chat_view.verticalScrollBar()
        return sb.maximum() - sb.value() <= 4

    def _scroll_chat_to_bottom(self) -> None:
        """把 chat_view 滚动条拉到最底. 在内容更新后异步调用."""
        QTimer.singleShot(0, self._do_scroll_bottom)

    def _do_scroll_bottom(self) -> None:
        # QScrollArea 的滚动条
        sb = self.chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._update_scroll_bottom_button()

    def _scroll_chat_to_bottom_now(self) -> None:
        self._do_scroll_bottom()

    def _update_scroll_bottom_button(self) -> None:
        if self._scroll_bottom_btn is None:
            return
        sb = self.chat_view.verticalScrollBar()
        visible = sb.maximum() > 0 and not self._is_chat_at_bottom()
        self._scroll_bottom_btn.setVisible(visible)
        self._update_scroll_bottom_button_position()

    def _update_scroll_bottom_button_position(self) -> None:
        if self._scroll_bottom_btn is None:
            return
        chat_view = self.chat_view
        cx = chat_view.x() + (chat_view.width() - self._scroll_bottom_btn.width()) // 2
        bottom = chat_view.y() + chat_view.height() - 16
        self._scroll_bottom_btn.move(cx, bottom - self._scroll_bottom_btn.height())

    # ---- 各类型气泡 HTML (旧 webengine/textbrowser 模式保留, 已不调用) ----
    def _user_bubble_html(self, content: str) -> str:
        return (
            '<div class="bubble-row bubble-row-user">'
            '<div class="bubble bubble-user">'
            f'<div class="bubble-content">{render_markdown(content)}</div>'
            '</div></div>'
        )

    def _assistant_bubble_html(self, content: str) -> str:
        return (
            '<div class="bubble-row bubble-row-assistant">'
            '<div class="bubble bubble-assistant">'
            f'<div class="bubble-content">{render_markdown(content)}</div>'
            '</div></div>'
        )

    def _system_bubble_html(self, content: str) -> str:
        return (
            '<div class="bubble-row bubble-row-system">'
            '<div class="bubble bubble-system">'
            f'{html.escape(content)}'
            '</div></div>'
        )

    def _tool_bubble_html(self, msg: dict) -> str:
        tool_id = msg["id"]
        name = html.escape(msg["name"])
        args_repr = self._format_tool_args(msg["name"], msg["args"])
        if len(args_repr) > 1200:
            args_repr = args_repr[:1200] + "…"
        args_esc = html.escape(args_repr)
        expanded = msg["expanded"]
        action = _("收起") if expanded else _("查看结果")
        if expanded:
            body = (
                '<div class="tool-body">'
                f'<pre class="tool-result">{html.escape(msg["result"])}</pre>'
                '</div>'
            )
        else:
            preview = msg["result"] or ""
            if len(preview) > 80:
                preview = preview[:80] + "…"
            preview = html.escape(preview)
            # 把 preview 放在 tool-body 里, 折叠态用 CSS 显示
            body = (
                '<div class="tool-body tool-body-preview">'
                f'{preview or "—"}'
                '</div>'
            )
        return (
            '<table class="row-center" cellspacing="0" cellpadding="0">'
            '<tr><td>'
            f'<div class="{cls}" data-tool-id="{tool_id}">'
            f'<a class="tool-header" href="toggle:{tool_id}">'
            f'<span class="tool-arrow">▶</span>'
            f'<span class="tool-name">{name}</span>'
            f'<span class="tool-args">{args_esc}</span>'
            f'<span class="tool-action">{action}</span>'
            f'</a>'
            f'{body}'
            f'</div>'
            f'</div>'
        )

    # ---- QTextBrowser 回退模式下的简化气泡 (用 table 实现对齐) ----
    def _user_bubble_html_simple(self, content: str) -> str:
        return (
            '<table class="row-right" cellspacing="0" cellpadding="0">'
            '<tr><td>'
            f'<div class="bubble bubble-user">'
            f'<div class="bubble-content">{render_markdown(content)}</div>'
            f'</div>'
            '</td></tr></table>'
        )

    def _assistant_bubble_html_simple(self, content: str) -> str:
        return (
            '<table class="row-left" cellspacing="0" cellpadding="0">'
            '<tr><td>'
            f'<div class="bubble bubble-assistant">'
            f'<div class="bubble-content">{render_markdown(content)}</div>'
            f'</div>'
            '</td></tr></table>'
        )

    def _tool_bubble_html_simple(self, msg: dict) -> str:
        tool_id = msg["id"]
        name = html.escape(msg["name"])
        args_repr = self._format_tool_args(msg["name"], msg["args"])
        if len(args_repr) > 1200:
            args_repr = args_repr[:1200] + "…"
        args_esc = html.escape(args_repr)
        expanded = msg["expanded"]
        action = _("收起") if expanded else _("查看结果")
        icon = (name[:2] or "FX").upper()
        if expanded:
            body = (
                '<div class="tool-body">'
                f'<pre class="tool-result">{html.escape(msg["result"])}</pre>'
                '</div>'
            )
        else:
            preview = msg["result"] or ""
            if len(preview) > 80:
                preview = preview[:80] + "…"
            preview = html.escape(preview)
            body = (
                '<div class="tool-body tool-body-preview">'
                f'{preview or "—"}'
                '</div>'
            )
        return (
            '<div class="bubble bubble-tool">'
            f'<a class="tool-header" href="toggle:{tool_id}">'
            f'<span class="tool-arrow">▶</span>'
            f'<span class="tool-icon">{icon}</span>'
            f'<span class="tool-name">{name}</span>'
            f'<span class="tool-args">{args_esc}</span>'
            f'<span class="tool-action">{action}</span>'
            f'</a>'
            f'{body}'
            f'</div>'
        )

    @staticmethod
    def _format_tool_args(name: str, args: dict) -> str:
        """为常见工具生成更易读的 args 展示. 其他工具仍走 JSON."""
        if name == "add_files" and isinstance(args.get("paths"), list):
            paths = args["paths"]
            if len(paths) <= 8:
                inner = ", ".join(f'"{p}"' for p in paths)
            else:
                # 路径多时按文件夹分组, 列出前几个再总结
                inner = ", ".join(f'"{p}"' for p in paths[:5])
                inner += f", … (+{len(paths) - 5} more)"
            return f"paths=[{inner}]"
        if name == "read_file":
            p = args.get("path", "")
            extras = []
            if "start_line" in args:
                extras.append(f"start_line={args['start_line']}")
            if "max_lines" in args:
                extras.append(f"max_lines={args['max_lines']}")
            if "max_bytes" in args:
                extras.append(f"max_bytes={args['max_bytes']}")
            extra = f", {', '.join(extras)}" if extras else ""
            return f'"{p}"{extra}'
        if name == "list_files":
            parts = []
            if "pattern" in args:
                parts.append(f"pattern='{args['pattern']}'")
            if "directory" in args:
                parts.append(f"directory='{args['directory']}'")
            if "max_depth" in args:
                parts.append(f"max_depth={args['max_depth']}")
            if "max_results" in args:
                parts.append(f"max_results={args['max_results']}")
            return ", ".join(parts) if parts else "(no filter)"
        if name == "list_items":
            parts = []
            if "kind" in args:
                parts.append(f"kind='{args['kind']}'")
            if "max_items" in args:
                parts.append(f"max_items={args['max_items']}")
            return ", ".join(parts) if parts else "(all items)"
        return json.dumps(args, ensure_ascii=False)

    def _append_html(self, html_fragment: str) -> None:
        """[DEPRECATED] 旧接口, 现在所有渲染都走 _render_chat."""
        # 为兼容性保留; 实际不再使用
        pass

    @staticmethod
    def _md_to_html(text: str) -> str:
        """[DEPRECATED] 已被 ai_markdown.render_markdown 替代."""
        from filecollector.gui.ai_markdown import render_markdown as _rm
        return _rm(text)

    @staticmethod
    def _md_inline_to_html(text: str) -> str:
        """[DEPRECATED] 已被 ai_markdown.render_markdown 替代."""
        return html.escape(text)

    # ------------------------------------------------------------------ 对话循环

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if self._client is None:
            self._render_system(_("请先在 设置 → AI 设置 中启用并配置 API。"))
            return

        self._render_user(text)
        self.input_edit.clear()
        self._send_user_message(text)

    def _on_clear_chat(self) -> None:
        # 清空气泡: 移除 container 布局里除尾部 stretch 之外的所有子项
        layout = self.chat_view._container_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._messages = []
        self._rendered_messages = []
        self._tool_counter = 0
        self._pending_welcome = True

    def _send_user_message(self, text: str) -> None:
        # 重新构建 system prompt, 反映最新 engine 状态
        self._rebuild_system_message()
        self._messages.append({"role": "user", "content": text})
        self._next_turn()

    def _rebuild_system_message(self) -> None:
        # 移除旧的 system 消息
        self._messages = [
            m for m in self._messages if m.get("role") != "system"]
        if self._state_provider is None:
            return
        work_dir, items, use_abs, show_header = self._state_provider()
        if self._system_prompt_override:
            content = self._system_prompt_override + "\n\n" + build_system_prompt(
                work_dir, items, use_abs, show_header,
            )
        else:
            content = build_system_prompt(
                work_dir, items, use_abs, show_header)
        self._messages.insert(0, {"role": "system", "content": content})

    def _next_turn(self) -> None:
        assert self._client is not None
        self._set_busy(True)
        self._thread = QThread(self)
        self._worker = _AIWorker(self._client, self._messages, TOOL_SCHEMA)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_api_finished)
        self._worker.failed.connect(self._on_api_failed)
        self._thread.start()

    def _on_api_finished(self, data: dict) -> None:
        self._cleanup_thread()
        # 如果用户点了停止, 忽略结果
        if self._stop_requested:
            return
        try:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []
        except Exception as e:  # noqa: BLE001
            self._set_busy(False)
            self._render_system(_("响应解析失败: %s") % e)
            return

        # 把 assistant 消息写入历史 (即使 content 为空, 也要保留 tool_calls)
        assistant_msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        self._messages.append(assistant_msg)

        if content:
            self._render_assistant(content)

        if tool_calls:
            for tc in tool_calls:
                name = (tc.get("function") or {}).get("name", "")
                raw_args = (tc.get("function") or {}).get(
                    "arguments", "") or ""
                tc_id = tc.get("id", "")
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                result_str = self._run_tool(name, args)
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str,
                })
            # 继续下一轮, 让 LLM 基于工具结果回复
            self._next_turn()
        else:
            self._set_busy(False)

    def _on_api_failed(self, err: str) -> None:
        self._cleanup_thread()
        self._set_busy(False)
        self._render_system(_("调用失败: %s") % err)

    def _run_tool(self, name: str, args: dict) -> str:
        if self._tool_executor is None:
            return _("未配置工具执行器")
        try:
            result = self._tool_executor(name, args)
        except Exception as e:  # noqa: BLE001
            return _("执行出错: %s") % e
        # 简短展示一次工具调用 (用淡气泡)
        try:
            self._render_tool(name, args, result or "OK")
        except Exception:
            pass
        return result or "OK"

    # ------------------------------------------------------------------ 状态
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.btn_send.setText(_("停止"))
            self.btn_send.setObjectName("StopAction")
            self.btn_send.setStyleSheet("")  # 清除 SuggestedAction 样式
            self.btn_send.update()
            self.status_label.setText(_("正在思考..."))
        else:
            self.btn_send.setText(_("发送"))
            self.btn_send.setObjectName("SuggestedAction")
            self.btn_send.setStyleSheet("")
            self.btn_send.update()
            self._update_status()
        self.input_edit.setReadOnly(busy)
        self.btn_clear.setEnabled(not busy)

    def _update_status(self) -> None:
        if self._client is None:
            self.status_label.setText(_("未配置"))
            self.status_label.setStyleSheet("color: #c01c28;")
        else:
            self.status_label.setText(_("就绪"))
            self.status_label.setStyleSheet("color: #5e5c64;")

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(3000)
            except Exception:
                pass
            self._thread = None
            self._worker = None
