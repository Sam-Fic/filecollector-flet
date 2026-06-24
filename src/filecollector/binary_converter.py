"""二进制文件 -> 多张 PNG 缩略图 (base64) 转换.

对齐 GNOME 版 BinaryConverter:
- 图片: 缩放至最长边 <= 2048 px 后直接 base64
- PDF: 用 ``pdftoppm`` 把每页渲染为 PNG, 再 base64
- Office (docx/pptx/xlsx/...): 用 ``soffice`` 转 PDF, 再走 PDF 流程

Flet 端不依赖 Gdk.Pixbuf, 改用 ``Pillow`` (可选依赖) + 进程调用 ``pdftoppm`` /
``soffice``. 当工具缺失或 Pillow 不可用时, 走最朴素的"原文件 base64 上传"路径,
让纯视觉模型仍能工作 (部分 API 支持直接上传 PDF).

为避免拉入额外强依赖, 实际不强制 Pillow: 优先使用 Pillow 处理图片 (含缩放),
若失败则回退到直接 base64 编码.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from filecollector.models import IMAGE_EXTENSIONS, DOCUMENT_EXTENSIONS


MAX_IMAGE_DIMENSION = 2048


def _image_mime_for(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".bmp"):
        return "image/bmp"
    if lower.endswith((".tiff", ".tif")):
        return "image/tiff"
    return "image/png"


def _is_image(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _is_document(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS)


# ====================================================================
# 图片 -> base64
# ====================================================================
def convert_image_to_base64(path: str) -> Optional[str]:
    """读取图片 -> base64. 优先用 Pillow 缩放到 2048px 再编码, 失败则原图直传.

    返回纯 base64 字符串 (不含 ``data:...;base64,`` 前缀).
    """
    if not os.path.exists(path):
        return None
    try:
        # 优先用 Pillow 做缩放, 降低 token 消耗
        try:
            from PIL import Image
            with Image.open(path) as im:
                im = im.convert("RGBA") if im.mode in ("P", "RGBA") else im
                w, h = im.size
                longest = max(w, h)
                if longest > MAX_IMAGE_DIMENSION:
                    scale = MAX_IMAGE_DIMENSION / longest
                    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                    im = im.resize(new_size, Image.LANCZOS)
                # 输出统一转 PNG (压缩率高且 VLM 兼容性最好)
                import io
                buf = io.BytesIO()
                # JPEG 源: 直接转 PNG, 避免质量损失; 也支持直接输出原格式
                ext = os.path.splitext(path)[1].lower()
                if ext in (".jpg", ".jpeg"):
                    im.convert("RGB").save(buf, format="PNG", optimize=True)
                else:
                    im.save(buf, format="PNG", optimize=True)
                return base64.b64encode(buf.getvalue()).decode("ascii")
        except ImportError:
            # Pillow 不可用: 直接 base64 原文件
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logging.warning(f"图片读取失败 ({path}): {e}")
        return None


def get_output_mime_for_image(path: str) -> str:
    return _image_mime_for(path)


# ====================================================================
# 文档 -> base64 列表
# ====================================================================
def convert_to_base64_images(path: str) -> Optional[list[str]]:
    """把文档/图片转成 base64 列表 (每张 PNG 一项).

    图片: 列表只有 1 项, 直接走 ``convert_image_to_base64``.
    PDF: 用 ``pdftoppm`` 渲染每页为 PNG.
    Office: 先 ``soffice`` 转 PDF, 再走 PDF 流程.

    失败返回 None.
    """
    if not os.path.exists(path):
        return None

    if _is_image(path):
        b64 = convert_image_to_base64(path)
        return [b64] if b64 else None

    # PDF 走 pdftoppm; 其他 Office 文档先 soffice 转 PDF
    if path.lower().endswith(".pdf"):
        pdf_path = path
    else:
        pdf_path = _convert_office_to_pdf(path)
        if not pdf_path:
            return None

    return _render_pdf_to_base64_images(pdf_path)


def _convert_office_to_pdf(src: str) -> Optional[str]:
    """调用 ``soffice --headless --convert-to pdf`` 把 Office 文档转 PDF."""
    if not shutil.which("soffice") and not shutil.which("libreoffice"):
        logging.warning("未检测到 soffice/libreoffice, 无法转换 Office 文档。")
        return None

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    out_dir = os.path.dirname(src) or "."
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", out_dir, src],
            check=False, capture_output=True, timeout=120,
        )
    except Exception as e:
        logging.warning(f"LibreOffice 转换失败: {e}")
        return None

    base = os.path.basename(src)
    dot = base.rfind(".")
    pdf_name = (base[:dot] if dot > 0 else base) + ".pdf"
    pdf_path = os.path.join(out_dir, pdf_name)
    return pdf_path if os.path.exists(pdf_path) else None


def _render_pdf_to_base64_images(pdf_path: str) -> Optional[list[str]]:
    """用 ``pdftoppm -png -r 200`` 渲染每页为 PNG, 再 base64."""
    if not shutil.which("pdftoppm"):
        logging.warning("未检测到 pdftoppm, 无法渲染 PDF。")
        return None

    try:
        tmp_dir = tempfile.mkdtemp(prefix="fc_vlm_")
    except Exception as e:
        logging.warning(f"创建临时目录失败: {e}")
        return None

    try:
        prefix = os.path.join(tmp_dir, "page")
        try:
            result = subprocess.run(
                ["pdftoppm", "-png", "-r", "200", pdf_path, prefix],
                check=False, capture_output=True, timeout=120,
            )
        except Exception as e:
            logging.warning(f"pdftoppm 调用失败: {e}")
            return None
        if result.returncode != 0:
            logging.warning(f"pdftoppm 退出码 {result.returncode}")
            return None

        png_files = sorted(
            f for f in os.listdir(tmp_dir) if f.endswith(".png")
        )
        if not png_files:
            return None

        out: list[str] = []
        for name in png_files:
            full = os.path.join(tmp_dir, name)
            try:
                with open(full, "rb") as fh:
                    out.append(base64.b64encode(fh.read()).decode("ascii"))
            except Exception as e:
                logging.warning(f"读取渲染产物失败 ({full}): {e}")
        return out or None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
