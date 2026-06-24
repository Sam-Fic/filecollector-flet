import json
import logging
import os
import sys
from pathlib import Path

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

# 与 GNOME 版保持一致的 Schema 域名
KEYRING_SERVICE = "com.github.samfic.filecollector"
KEYRING_API_KEY = "ai_api_key"
# VLM 单独的 keyring 用户名 (避免与侧边栏 API key 冲突)
KEYRING_MM_API_KEY = "mm_api_key"


if sys.platform == "win32":
    APP_DIR = os.path.join(
        os.environ.get(
            "APPDATA",
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming"),
        ),
        "filecollector",
    )
elif sys.platform == "darwin":
    APP_DIR = os.path.expanduser("~/Library/Application Support/filecollector")
else:
    APP_DIR = os.path.expanduser("~/.config/filecollector")
BUTTON_HEIGHT = 32

# 缓存目录名 (与 GNOME 版一致)
CACHE_DIR_NAME = ".filecollector_cache"


def _ensure_dir() -> str:
    os.makedirs(APP_DIR, exist_ok=True)
    return APP_DIR


def get_merged_txt_path() -> str:
    return os.path.join(_ensure_dir(), "merged.txt")


def get_clipboard_staging_path() -> str:
    staging_dir = Path(_ensure_dir()) / ".fc-clipboard"
    staging_dir.mkdir(parents=True, exist_ok=True)
    return str(staging_dir / "merged.txt")


def get_settings_path() -> str:
    return os.path.join(_ensure_dir(), "settings.json")


def get_common_phrases_path() -> str:
    return os.path.join(_ensure_dir(), "common_phrases.json")


def get_work_dir_cache_path(work_dir) -> str:
    """获取工作目录下 .filecollector_cache 路径."""
    if not work_dir:
        return ""
    return os.path.join(str(work_dir), CACHE_DIR_NAME)


def load_settings() -> dict:
    path = get_settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    path = get_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_common_phrases() -> list[str]:
    path = get_common_phrases_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [str(x) for x in data]
    except Exception:
        pass
    return []


def save_common_phrases(items: list[str]) -> None:
    path = get_common_phrases_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ====================================================================
# 侧边栏 AI 助手 设置
# ====================================================================
# 默认值与 GNOME 版 load_ai_settings 一致; base_url / model / timeout
# 可被 settings.json 中 ai 字段覆盖; api_key 优先存系统密钥环.

SIDEBAR_AI_DEFAULTS = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "system_prompt_override": "",
    "timeout": 60.0,
}


def load_sidebar_ai_settings() -> dict:
    """读取侧边栏 AI 助手配置.

    1. 优先从系统密钥环读取 API Key
    2. 密钥环为空但 JSON 有旧明文: 迁移到密钥环并清空 JSON
    3. 密钥环不可用 (降级): 保留 JSON 明文
    """
    settings = load_settings()
    cfg = dict(SIDEBAR_AI_DEFAULTS)
    cfg.update(settings.get("ai", {}) or {})

    keyring_key = load_api_key_from_keyring()
    if keyring_key:
        cfg["api_key"] = keyring_key
    else:
        json_key = cfg.get("api_key", "")
        if json_key:
            if store_api_key_to_keyring(json_key):
                cfg["api_key"] = json_key
                if "ai" not in settings:
                    settings["ai"] = {}
                settings["ai"]["api_key"] = ""
                save_settings(settings)
    return cfg


def save_sidebar_ai_settings(cfg: dict) -> None:
    """保存侧边栏 AI 助手配置.

    - 尝试将 API Key 存入密钥环; 成功后 JSON 中强制留空.
    - 密钥环不可用时保留 JSON 明文作为安全降级.
    """
    settings = load_settings()
    api_key = cfg.get("api_key", "")

    keyring_success = store_api_key_to_keyring(api_key)

    cfg_to_save = dict(cfg)
    if keyring_success:
        cfg_to_save["api_key"] = ""
    else:
        cfg_to_save["api_key"] = api_key

    settings["ai"] = cfg_to_save
    save_settings(settings)


# ====================================================================
# VLM 设置 (二进制文件 -> Markdown 预处理)
# ====================================================================
MULTIMODAL_AI_DEFAULTS = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o",
    "system_prompt_override": "",
    "timeout": 120.0,
}


def load_multimodal_ai_settings() -> dict:
    """读取 VLM 配置 (与侧边栏同样的密钥环优先策略)."""
    settings = load_settings()
    cfg = dict(MULTIMODAL_AI_DEFAULTS)
    cfg.update(settings.get("multimodal_ai", {}) or {})

    keyring_key = load_mm_api_key_from_keyring()
    if keyring_key:
        cfg["api_key"] = keyring_key
    else:
        json_key = cfg.get("api_key", "")
        if json_key:
            if store_mm_api_key_to_keyring(json_key):
                cfg["api_key"] = json_key
                if "multimodal_ai" not in settings:
                    settings["multimodal_ai"] = {}
                settings["multimodal_ai"]["api_key"] = ""
                save_settings(settings)
    return cfg


def save_multimodal_ai_settings(cfg: dict) -> None:
    """保存 VLM 配置 (与侧边栏同样的策略)."""
    settings = load_settings()
    api_key = cfg.get("api_key", "")

    keyring_success = store_mm_api_key_to_keyring(api_key)

    cfg_to_save = dict(cfg)
    if keyring_success:
        cfg_to_save["api_key"] = ""
    else:
        cfg_to_save["api_key"] = api_key

    settings["multimodal_ai"] = cfg_to_save
    save_settings(settings)


# ====================================================================
# 允许被 VLM 转换的二进制扩展名
# ====================================================================
def get_allowed_binary_extensions() -> list[str]:
    """读取允许转换的扩展名列表. 缺失时返回默认列表."""
    # 延迟导入避免循环引用
    from filecollector.models import DEFAULT_ALLOWED_BINARY_EXTS

    settings = load_settings()
    arr = settings.get("allowed_binary_extensions")
    if isinstance(arr, list) and len(arr) > 0:
        return [str(x) for x in arr]
    return list(DEFAULT_ALLOWED_BINARY_EXTS)


def save_allowed_binary_extensions(exts: list[str]) -> None:
    """保存允许的扩展名列表 (空数组等价于不允许任何文件)."""
    settings = load_settings()
    settings["allowed_binary_extensions"] = list(exts)
    save_settings(settings)


def parse_allowed_ext_input(raw: str) -> list[str]:
    """把 UI 输入的逗号分隔字符串解析为干净扩展名列表.

    - 自动 trim / 跳过空段
    - 大小写不敏感 (统一小写)
    - 缺前导点自动补上
    """
    result: list[str] = []
    if not raw:
        return result
    for part in raw.split(","):
        t = part.strip().lower()
        if not t:
            continue
        if not t.startswith("."):
            t = "." + t
        if t not in result:
            result.append(t)
    return result


# ====================================================================
# 系统密钥环读写
# ====================================================================
def store_api_key_to_keyring(api_key: str) -> bool:
    """将侧边栏 API Key 存入系统密钥环. 若为空则清除."""
    if not KEYRING_AVAILABLE:
        return False
    if not api_key:
        return clear_api_key_from_keyring()
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_API_KEY, api_key)
        return True
    except Exception as e:
        logging.warning(f"系统密钥环写入失败 (将降级为本地存储): {e}")
        return False


def load_api_key_from_keyring() -> str:
    """从系统密钥环读取侧边栏 API Key."""
    if not KEYRING_AVAILABLE:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY) or ""
    except Exception as e:
        logging.warning(f"系统密钥环读取失败: {e}")
        return ""


def clear_api_key_from_keyring() -> bool:
    """从系统密钥环清除侧边栏 API Key."""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_API_KEY)
        return True
    except Exception:
        return True  # 可能本来就不存在, 视为成功


def store_mm_api_key_to_keyring(api_key: str) -> bool:
    """将 VLM API Key 存入系统密钥环. 若为空则清除."""
    if not KEYRING_AVAILABLE:
        return False
    if not api_key:
        return clear_mm_api_key_from_keyring()
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_MM_API_KEY, api_key)
        return True
    except Exception as e:
        logging.warning(f"VLM API Key 写入密钥环失败: {e}")
        return False


def load_mm_api_key_from_keyring() -> str:
    """从系统密钥环读取 VLM API Key."""
    if not KEYRING_AVAILABLE:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_MM_API_KEY) or ""
    except Exception as e:
        logging.warning(f"VLM API Key 读取失败: {e}")
        return ""


def clear_mm_api_key_from_keyring() -> bool:
    """从系统密钥环清除 VLM API Key."""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_MM_API_KEY)
        return True
    except Exception:
        return True
