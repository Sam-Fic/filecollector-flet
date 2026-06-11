import json
import os
import sys
from pathlib import Path


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


def get_clipboard_staging_path(work_dir: Path | None) -> str:
    if work_dir is None:
        work_dir = Path(_ensure_dir())
    staging_dir = Path(work_dir) / ".fc-clipboard"
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
