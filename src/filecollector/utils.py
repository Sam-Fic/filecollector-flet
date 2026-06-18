import os

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
