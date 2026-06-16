"""Markdown → HTML 渲染 (基于 markdown-it-py + Pygments).

供 AIPanel 在生成聊天视图 HTML 时调用. 设计为无状态、可重入.
"""
from __future__ import annotations

import html as _html
import re
from typing import Optional

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound


# ---------------------------------------------------------------- 初始化
# gfm-like 启用表格 / 删除线 / 自动链接; html=False 禁用原始 HTML (XSS 防护).
# breaks=True 让单个换行变 <br>, 更接近聊天场景.
_md = MarkdownIt("gfm-like", {"html": False, "breaks": True, "linkify": True})
_md.enable("table")
_md.enable("strikethrough")

# Pygments 格式化器: 给代码块加语法高亮 span; 用 class 名而非 inline style,
# 方便我们用 CSS 控制颜色主题. 只生成内部的 span, 外层 <pre> 由我们包.
_pygments_fmt = HtmlFormatter(cssclass="md-codehilite", nowrap=False)


# ---------------------------------------------------------------- 公开 API
def render_markdown(text: str) -> str:
    """Markdown → HTML (含表格 / GFM / 链接自动识别 / 代码高亮).

    安全性: markdown-it 的 html=False 已阻止原始 HTML 标签; 链接只能走
    markdown 自己的 [text](url) 或 linkify 自动识别 (受内置白名单约束).
    """
    if not text:
        return ""
    tokens = _md.parse(text)
    _highlight_code_tokens(tokens)
    return _md.renderer.render(tokens, _md.options, {})


def sanitize_url(url: str) -> Optional[str]:
    """过滤危险 URL scheme; 安全则返回原值, 否则返回 None."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("#", "/", "./", "../")):
        return url
    if re.match(r"^(https?|ftp|file|mailto)://", url, re.IGNORECASE):
        return url
    if re.match(r"^(https?|ftp|file|mailto):", url, re.IGNORECASE):
        return url
    if url.startswith("toggle:"):
        return url  # 内部协议, 用于工具调用展开/折叠
    return None


# ---------------------------------------------------------------- 内部
def _highlight_code_tokens(tokens) -> None:
    """遍历 token 流, 把 ```lang\\n...\\n``` 的 code_block 替换为高亮 HTML."""
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == "fence" or tok.type == "code_block":
            lang = (tok.info or "").strip().split()[0] if tok.info else ""
            content = tok.content
            try:
                if lang:
                    lexer = get_lexer_by_name(lang)
                else:
                    lexer = guess_lexer(content)
            except ClassNotFound:
                lexer = None
            if lexer is not None:
                try:
                    highlighted = highlight(content, lexer, _pygments_fmt)
                except Exception:
                    highlighted = ""
            else:
                highlighted = ""
            lang_cls = _html.escape(lang or "text")
            if highlighted:
                # Pygments 输出: <div class="md-codehilite"><pre>...spans...</pre></div>
                # 改成: <pre class="md-pre md-pre-LANG"><code class="md-code">...spans...</code></pre>
                inner = re.search(
                    r'<pre>(.*?)</pre>', highlighted, re.DOTALL
                )
                span_html = inner.group(1) if inner else _html.escape(content)
                wrapped = (
                    f'<pre class="md-pre md-pre-{lang_cls}">'
                    f'<code class="md-code language-{lang_cls}">'
                    f'{span_html}</code></pre>'
                )
            else:
                wrapped = (
                    f'<pre class="md-pre md-pre-{lang_cls}">'
                    f'<code class="md-code language-{lang_cls}">'
                    f'{_html.escape(content)}</code></pre>'
                )
            tok.type = "html_block"
            tok.content = wrapped
            tok.children = []
            tok.info = ""
            tok.markup = ""
            tok.map = None
            i += 1
            continue
        i += 1
