import logging
import os
import threading
from pathlib import Path

try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False


def detect_encoding(file_path, num_bytes=10000):
    if not CHARDET_AVAILABLE:
        return None
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(num_bytes)
    except Exception:
        return None
    # BOM 检测 (优先于 chardet, 置信度最高)
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    if raw.startswith(b'\xff\xfe\x00\x00') or raw.startswith(b'\x00\x00\xfe\xff'):
        return 'utf-32'
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return 'utf-16'
    try:
        result = chardet.detect(raw)
        if result and result['confidence'] > 0.5:
            return result['encoding']
    except Exception:
        pass
    return None


def display_path(path, *, force_absolute=False, use_absolute=False, work_dir=None) -> str:
    """计算文件的显示路径: 优先相对 work_dir, 否则回退绝对路径。

    统一替代原先散落在 engine / arrangement_list / multi_format_exporter
    中三处各写的字符串相对化逻辑, 避免跨平台不一致。
    """
    file_p = Path(path)
    if force_absolute or use_absolute or not work_dir:
        return str(file_p.resolve())
    try:
        return str(file_p.resolve().relative_to(Path(work_dir).resolve()))
    except ValueError:
        return str(file_p.resolve())


def run_on_ui(page, fn) -> None:
    """把同步回调安全地调度到 Flet UI 线程 (统一跨线程 UI 更新通道).

    统一替代原先散落在 preprocess_runner / global_search_dialog /
    vlm_queue 中三套各不相同的调度机制 (run_task / call_soon_threadsafe /
    另起 Thread), 全部收敛到 Flet 官方推荐的 ``page.run_task`` 通道。

    ``page`` 为 None (未挂载) 时退化为直接调用并吞掉异常, 便于单测。
    """
    if page is None:
        try:
            fn()
        except Exception:
            pass
        return
    try:
        async def _invoke():
            try:
                fn()
            except Exception as e:
                logging.warning(f"run_on_ui 回调异常: {e}")
        page.run_task(_invoke)
    except Exception as e:
        logging.warning(f"run_on_ui 调度失败: {e}")


def debounce(wait: float):
    """简单的防抖装饰器: 在最后一次调用后 wait 秒内无新调用才触发。

    统一替代原先散落在 auto_save / 状态刷新 / resize 中各自手写的
    ``threading.Timer`` 防抖逻辑。
    """
    def decorator(fn):
        timer = None
        lock = threading.Lock()

        def wrapped(*args, **kwargs):
            nonlocal timer
            with lock:
                if timer is not None:
                    timer.cancel()
                timer = threading.Timer(wait, lambda: fn(*args, **kwargs))
                timer.daemon = True
                timer.start()
        return wrapped
    return decorator


def is_binary_file(file_path, sniff_bytes: int = 8192) -> bool:
    """通过嗅探前 sniff_bytes 字节是否含 NUL (\\x00) 判断二进制文件。

    统一替代原先散落在 search_service / file_tree / multi_format_exporter /
    main_view 中四份各写一遍且阈值不一致 (2048 / 8192) 的实现。
    读取失败按二进制处理 (更安全, 避免把错误内容当文本)。
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def safe_read_file(file_path, max_preview_lines=None):
    encodings_to_try = ['utf-8', 'gbk', 'latin-1']
    detected = detect_encoding(file_path)
    if detected and detected.lower() not in [e.lower() for e in encodings_to_try]:
        encodings_to_try.insert(0, detected)

    for enc in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                if max_preview_lines is None:
                    content = f.read()
                else:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_preview_lines:
                            break
                        lines.append(line)
                    content = ''.join(lines)
            return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue
    raise RuntimeError(f"无法解码文件: {file_path}")


def read_file_snippet(file_path, start_line: int, end_line: int):
    """流式读取文件片段 (1-based 行号范围), 避免大文件 OOM.

    仅按行迭代, 跳过 start_line 之前的行, 收集 [start_line, end_line] 区间,
    读到 end_line 即停止 (不再遍历/加载文件剩余内容). 内存中只保留片段本身,
    适合从超大文件中截取少量行的场景 (如编排列表中的文件片段条目).

    返回 (片段文本, 使用的编码). 行号非法或越界时返回可用范围内的内容.
    """
    if end_line < 1:
        return "", None
    # 归一化: 1-based -> 0-based 索引区间
    start_idx = max(0, start_line - 1)
    end_idx = max(start_idx, end_line - 1)

    encodings_to_try = ['utf-8', 'gbk', 'latin-1']
    detected = detect_encoding(file_path)
    if detected and detected.lower() not in [e.lower() for e in encodings_to_try]:
        encodings_to_try.insert(0, detected)

    for enc in encodings_to_try:
        try:
            collected: list[str] = []
            with open(file_path, 'r', encoding=enc) as f:
                for idx, line in enumerate(f):
                    if idx > end_idx:
                        break  # 已抵达片段末尾, 立即停止, 不读剩余文件
                    if idx >= start_idx:
                        collected.append(line)
            return ''.join(collected), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue
    raise RuntimeError(f"无法解码文件: {file_path}")
