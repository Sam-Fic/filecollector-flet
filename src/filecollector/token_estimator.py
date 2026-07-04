"""Token 估算 (对齐 GNOME 版 token_estimator.vala).

提供 estimate_tokens_fast(text): 基于字符类别的快速 token 估算,
不依赖外部库, 适合实时进度条预警.

权重规则 (与 Vala 版一致):
- CJK (中日韩) 字符: 1.0 token
- 连续数字组 (含小数点/逗号): 1.0 token
- 标点: 0.5 token
- 带重音拉丁字符: 0.33 token
- 其他字符: 0.25 token
最终结果向上取整并乘 1.05 安全系数.
"""

from __future__ import annotations

import math
import unicodedata


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK 统一表意文字
        or 0x3400 <= cp <= 0x4DBF   # CJK 扩展 A
        or 0x3040 <= cp <= 0x30FF   # 平假名 + 片假名
        or 0xAC00 <= cp <= 0xD7AF   # 韩文音节
        or 0xF900 <= cp <= 0xFAFF   # CJK 兼容表意文字
    )


def _is_punctuation(ch: str) -> bool:
    if ch in ("`", "~", "|", "\\"):
        return True
    cat = unicodedata.category(ch)
    return cat.startswith("P")


def _is_accented_latin(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x00C0 <= cp <= 0x00FF      # Latin-1 Supplement (带重音)
        or 0x0100 <= cp <= 0x017F   # Latin Extended-A
        or 0x1E00 <= cp <= 0x1EFF   # Latin Extended Additional
    )


def estimate_tokens_fast(text: str | None) -> int:
    """快速估算字符串的 token 数量.

    空字符串返回 0. 否则按字符类别累加权重, 最后乘 1.05 安全系数并向上取整.
    """
    if not text:
        return 0

    tokens = 0.0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        i += 1

        if ch.isspace():
            continue

        if _is_cjk(ch):
            tokens += 1.0
        elif ch.isdigit():
            # 消耗连续数字 / 小数点 / 千分位逗号
            while i < n and (text[i].isdigit() or text[i] in (".", ",")):
                i += 1
            tokens += 1.0
        elif _is_punctuation(ch):
            tokens += 0.5
        elif _is_accented_latin(ch):
            tokens += 0.33
        else:
            tokens += 0.25

    return int(math.ceil(tokens * 1.05))
