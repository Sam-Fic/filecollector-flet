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


def store_api_key_to_keyring(api_key: str) -> bool:
    """将 API Key 存入系统密钥环。若为空则清除。"""
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
    """从系统密钥环读取 API Key。"""
    if not KEYRING_AVAILABLE:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY) or ""
    except Exception as e:
        logging.warning(f"系统密钥环读取失败: {e}")
        return ""


def clear_api_key_from_keyring() -> bool:
    """从系统密钥环清除 API Key。"""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_API_KEY)
        return True
    except Exception:
        return True  # 可能本来就不存在，视为成功
