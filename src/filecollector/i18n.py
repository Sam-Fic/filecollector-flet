"""轻量级国际化 (i18n) 基础设施.

参考 GNOME 版本使用 gettext 的方式, 此处结合 Python 内置 gettext 与
内置字典翻译表, 优先使用本地化字典, 缺失时回退到 gettext,
最终回退到源字符串. 这样在无 .mo 文件环境下仍可正常工作.

默认提供中文 (zh_CN) 与英文 (en) 两种语言.
"""

from __future__ import annotations

import gettext
import locale
import os
import threading
from typing import Callable, Optional

APP_NAME = "filecollector"
SUPPORTED_LANGS = ("en", "zh_CN")
DEFAULT_LANG = ""

_translator: Optional[gettext.NullTranslations] = None
_current_lang: str = ""
_lock = threading.Lock()

内置_中文翻译 = {
    "FileCollector - 文件收集与编排工具": "FileCollector - File Collection & Arrangement Tool",
    "FileCollector": "FileCollector",
    "未设置工作目录": "No working directory set",
    "当前工作目录: 未设置": "Working directory: not set",
    "当前工作目录: %s": "Working directory: %s",
    "资源管理器": "Files",
    "搜索…": "Search…",
    "输出编排列表": "Arrangement List",
    "预览": "Preview",
    "添加外部文件": "Add External File",
    "上方插入文本": "Insert Text Above",
    "下方插入文本": "Insert Text Below",
    "上移": "Move Up",
    "下移": "Move Down",
    "删除": "Delete",
    "清空": "Clear",
    "清空列表": "Clear List",
    "使用绝对路径": "Use Absolute Path",
    "在文件头部标注工作目录信息": "Write working directory at the top of the file",
    "生成合并文本": "Generate Merged Text",
    "生成合并文本到剪贴板": "Generate to Clipboard",
    "生成到剪贴板": "Copy to Clipboard",
    "保存项目": "Save Project",
    "项目另存为...": "Save Project As…",
    "加载项目": "Load Project",
    "打开项目...": "Open Project…",
    "语言设置": "Language",
    "常用语管理": "Manage Phrases",
    "键盘快捷键": "Keyboard Shortcuts",
    "关于": "About",
    "退出": "Quit",
    "确认退出": "Confirm Exit",
    "撤销": "Undo",
    "重做": "Redo",
    "打开文件夹": "Open Folder",
    "打开工作目录": "Open Working Directory",
    "选择工作目录，左侧加载目录树": "Select a working directory; the tree loads on the left",
    "主工具栏": "Main Toolbar",
    "就绪": "Ready",
    "警告": "Warning",
    "错误": "Error",
    "确认": "Confirm",
    "取消": "Cancel",
    "应用": "Apply",
    "关闭": "Close",
    "添加": "Add",
    "编辑": "Edit",
    "保存": "Save",
    "删除选中常用语？": "Delete the selected phrase?",
    "暂无常用语": "No phrases yet",
    "新增常用语": "Add Phrase",
    "编辑常用语": "Edit Phrase",
    "编辑文字": "Edit Text",
    "插入自定义文字": "Insert Custom Text",
    "请输入文字:": "Enter text:",
    "使用常用语": "Use Phrase",
    "直接插入": "Insert Directly",
    "插入常用语": "Insert Phrase",
    "已插入文字": "Text inserted",
    "文字已更新": "Text updated",
    "条目已删除": "Item deleted",
    "编排列表已清空": "Arrangement list cleared",
    "编排列表为空": "Arrangement list is empty",
    "编排列表为空，无法生成。": "Arrangement list is empty; nothing to generate.",
    "编排列表不为空，确定退出吗？": "The arrangement list is not empty. Quit anyway?",
    "TXT 已生成: %s": "TXT generated: %s",
    "合并文本已复制到剪贴板": "Merged text copied to clipboard",
    "已设置工作目录: %s": "Working directory set: %s",
    "已添加 %d 个外部文件": "Added %d external file(s)",
    "已添加 %d 个项目": "Added %d item(s)",
    "项目已保存: %s": "Project saved: %s",
    "项目已加载: %s": "Project loaded: %s",
    "已从 CLI 参数加载 %d 个项目": "Loaded %d item(s) from CLI args",
    "已从外部命令更新 (%d 项)": "Updated from external command (%d item(s))",
    "外部命令解析失败": "Failed to parse external command",
    "生成 TXT 失败:\n%s": "Failed to generate TXT:\n%s",
    "复制到剪贴板失败:\n%s": "Failed to copy to clipboard:\n%s",
    "项目文件损坏或格式不正确:\n%s": "Project file is corrupt or invalid:\n%s",
    "文件已保存到:\n%s": "File saved to:\n%s",
    "保存失败": "Save failed",
    "加载失败": "Load failed",
    "文件不存在": "File does not exist",
    "[文件不存在]": "[File does not exist]",
    "读取错误: %s": "Read error: %s",
    "确定清空编排列表吗？": "Clear the arrangement list?",
    "选择工作文件夹": "Select Working Folder",
    "选择外部文件": "Select External Files",
    "保存合并文本": "Save Merged Text",
    "打开项目": "Open Project",
    "保存项目到": "Save Project to",
    "项目": "Project",
    "项目文件 (*.project.json)": "Project Files (*.project.json)",
    "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)": "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)",
    "Text files (*.txt);;All files (*)": "Text files (*.txt);;All files (*)",
    "已勾选 %d 个文件": "%d file(s) checked",
    "确定": "OK",
    "设置界面语言": "Set Interface Language",
    "跟随系统": "Follow System",
    "选择后立即生效。": "Takes effect immediately.",
    "中文": "中文",
    "English": "English",
    "提示": "Notice",
    "语言设置已保存，重启应用后生效。是否现在重启？": "Language setting saved. Restart to apply. Restart now?",
    "稍后": "Later",
    "立即重启": "Restart Now",
    "语言设置已保存，重启生效。\n\n当前支持：跟随系统 / 中文 / English": "Language setting saved. Restart to apply.\n\nSupported: Follow System / 中文 / English",
    "关于 FileCollector": "About FileCollector",
    "文件收集与编排工具": "File collection & arrangement tool",
    "跨平台支持 Windows / macOS / Linux。":
        "Cross-platform: Windows / macOS / Linux.",
    "主要功能：": "Key features:",
    "📂 目录树浏览 + 多选勾选": "📂 Directory tree browsing with multi-select",
    "📋 拖放排序 + 撤销 / 重做": "📋 Drag & drop reordering with undo/redo",
    "✏️ 文字插入 + 常用语管理": "✏️ Text insertion + phrase management",
    "🧠 智能编码检测 (UTF-8 / GBK / 拉丁系)": "🧠 Smart encoding detection (UTF-8 / GBK / Latin)",
    "💾 项目保存 / 加载 (.project.json / .fcol)": "💾 Project save/load (.project.json / .fcol)",
    "🌐 中英文切换 (跟随系统 / 中文 / English)": "🌐 English / 中文 switch (Follow System / 中文 / English)",
    "⌨️ 完整键盘快捷键支持": "⌨️ Full keyboard shortcut support",
    "开发者：Sam-Fic | License: MIT": "Developer: Sam-Fic | License: MIT",
    "请查看菜单栏 键盘快捷键 或关于对话框中查看所有快捷键。": "See all shortcuts in the menu bar or About dialog.",
    "常用操作": "Common Operations",
    "列表操作": "List Operations",
    "应用程序": "Application",
    "保存中...": "Saving...",
    "加载中...": "Loading...",
    "(绝对)": "(Absolute)",
    "(相对)": "(Relative)",
    "(绝对路径)": "(Absolute Path)",
    "相对路径": "Relative Path",
    "--- 文件预览 (编码: %s) ---": "--- File Preview (Encoding: %s) ---",
    "--- 文件预览 (编码: %s) ---\n%s": "--- File Preview (Encoding: %s) ---\n%s",
    "未设置": "Not set",
    "工具栏": "Toolbar",
    "状态": "Status",
    "项目(&P)": "&Project",
    "设置(&S)": "&Settings",
    "帮助(&H)": "&Help",
    "退出(&X)": "E&xit",
    "常用语管理(&M)": "&Manage Phrases",
    "常用语": "Phrases",
    "尚未打开工作目录": "No working directory opened",
    "📌": "📌",
    "📄": "📄",
    "📝": "📝",
    "📂": "📂",
    "📋": "📋",
    "↶": "↶",
    "↷": "↷",
    "%d. %s": "%d. %s",
}

_LISTENERS: list[Callable[[str], None]] = []


def detect_system_language() -> str:
    """探测系统语言并返回支持的语言代码."""
    try:
        lang_env = os.environ.get("FILECOLLECTOR_LANG") or os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
        if lang_env:
            code = lang_env.split(":")[0].split(".")[0].strip()
            if code.startswith("zh"):
                return "zh_CN"
            if code.startswith("en"):
                return "en"
        try:
            loc = locale.getlocale()[0] or ""
        except Exception:
            loc = ""
        if loc.startswith("zh"):
            return "zh_CN"
        if loc.startswith("en"):
            return "en"
    except Exception:
        pass
    return ""


def _resolve_locale_dir() -> str:
    """定位翻译 .mo 文件所在目录."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, "locales"),
        os.path.join(os.path.dirname(base), "locales"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def _translate_dict(text: str) -> str:
    """使用内置字典进行翻译 (zh_CN -> en)."""
    if _current_lang == "en":
        return 内置_中文翻译.get(text, text)
    return text


def _build_translator(lang: str) -> gettext.NullTranslations:
    """根据语言代码构造 gettext 翻译器对象 (作为字典翻译的补充)."""
    if not lang or lang == "zh_CN":
        return gettext.NullTranslations()
    try:
        localedir = _resolve_locale_dir()
        return gettext.translation(APP_NAME, localedir, languages=[lang], fallback=True)
    except Exception:
        return gettext.NullTranslations()


def set_language(lang: str, *, notify: bool = True) -> None:
    """设置当前语言, 可选是否通知监听器.

    lang: 语言代码, '' 表示跟随系统 (使用中文作为默认).
    """
    with _lock:
        global _translator, _current_lang
        if lang not in ("", "en", "zh_CN"):
            lang = "zh_CN"
        if not lang:
            lang = detect_system_language() or "zh_CN"
        prev = _current_lang
        _current_lang = lang
        _translator = _build_translator(lang)
    if notify and prev != lang:
        for cb in list(_LISTENERS):
            try:
                cb(lang)
            except Exception:
                pass


def get_language() -> str:
    """返回当前语言代码."""
    return _current_lang


def is_english() -> bool:
    return _current_lang == "en"


def add_listener(cb: Callable[[str], None]) -> None:
    """注册语言切换监听器 (用于动态刷新 UI 文案)."""
    if cb not in _LISTENERS:
        _LISTENERS.append(cb)


def remove_listener(cb: Callable[[str], None]) -> None:
    """注销语言切换监听器."""
    try:
        _LISTENERS.remove(cb)
    except ValueError:
        pass


def notify_listeners() -> None:
    """通知所有监听器语言已变化 (供 UI 主动重新翻译)."""
    for cb in list(_LISTENERS):
        try:
            cb(_current_lang)
        except Exception:
            pass


def _(text: str) -> str:
    """翻译函数简写."""
    with _lock:
        if _translator is None:
            set_language("", notify=False)
        dict_result = _translate_dict(text)
        if dict_result != text:
            return dict_result
        try:
            return _translator.gettext(text)
        except Exception:
            return text


def initialize() -> str:
    """初始化 i18n, 返回最终生效的语言代码."""
    try:
        from filecollector.config import load_settings
        settings = load_settings()
        lang = settings.get("language", "")
    except Exception:
        lang = ""
    if not lang:
        env_lang = os.environ.get("FILECOLLECTOR_LANG", "")
        if env_lang in ("en", "zh_CN"):
            lang = env_lang
        else:
            lang = detect_system_language()
    if not lang:
        lang = "zh_CN"
    set_language(lang, notify=False)
    return lang
