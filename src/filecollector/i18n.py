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
# 用 RLock 防止 _() 内部调 set_language 时重入死锁
_lock = threading.RLock()

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
    "导出合并文本": "Export Merged Text",
    "文本文件 (*.txt)": "Text File (*.txt)",
    "Markdown (*.md)": "Markdown (*.md)",
    "JSON (*.json)": "JSON (*.json)",
    "JSONL (*.jsonl)": "JSONL (*.jsonl)",
    "Jupyter Notebook (*.ipynb)": "Jupyter Notebook (*.ipynb)",
    "所有文件 (*)": "All Files (*)",
    "Markdown": "Markdown",
    "JSONL": "JSONL",
    "JSON": "JSON",
    "Jupyter Notebook": "Jupyter Notebook",
    "合并文本": "Merged Text",
    "%s 已保存": "%s saved",
    "预估上下文: %d / %d Tokens (%.1f%%)":
        "Estimated context: %d / %d Tokens (%.1f%%)",
    "上下文窗口设置": "Context Window Settings",
    "模型上下文限制": "Model Context Limit",
    "设置目标 LLM 的最大 Token 窗口，用于进度条预警。":
        "Set the target LLM's max token window for progress bar warnings.",
    "上下文窗口大小 (Tokens)": "Context Window Size (Tokens)",
    "已将 %d 个 Commit Diff 插入编排列表":
        "Inserted %d commit diff(s) into the arrangement list",
    "Token 警告: 当前内容超过上下文窗口":
        "Token warning: content exceeds context window",
    "打开项目": "Open Project",
    "保存项目到": "Save Project to",
    "项目": "Project",
    "项目文件 (*.project.json)": "Project Files (*.project.json)",
    "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)": "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)",
    "Text files (*.txt);;All files (*)": "Text files (*.txt);;All files (*)",
    "已勾选 %d 个文件": "%d file(s) checked",
    "确定": "OK",
    "设置界面语言": "Set Interface Language",
    "语言": "Language",
    "界面语言": "Interface Language",
    "切换语言后需要重启应用才能生效。": "A restart is required for the language change to take effect.",
    "应用语言设置": "Apply Language Setting",
    "保存语言设置并重启应用": "Save the language setting and restart the app",
    "应用": "Apply",
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
    "目录树浏览 + 多选勾选": "Directory tree browsing with multi-select",
    "拖放排序 + 撤销 / 重做": "Drag & drop reordering with undo/redo",
    "文字插入 + 常用语管理": "Text insertion + phrase management",
    "智能编码检测 (UTF-8 / GBK / 拉丁系)": "Smart encoding detection (UTF-8 / GBK / Latin)",
    "项目保存 / 加载 (.project.json / .fcol)": "Project save/load (.project.json / .fcol)",
    "中英文切换 (跟随系统 / 中文 / English)": "English / 中文 switch (Follow System / 中文 / English)",
    "完整键盘快捷键支持": "Full keyboard shortcut support",
    "开发者：Sam-Fic | License: MIT": "Developer: Sam-Fic | License: MIT",
    "访问 GitHub 仓库": "Visit GitHub Repository",
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
    "↶": "↶",
    "↷": "↷",
    "%d. %s": "%d. %s",
    # ---- AI 助手 ----
    "AI 助手": "AI Assistant",
    "AI 助手设置": "AI Assistant Settings",
    "AI 设置": "AI Settings",
    "启用 AI 助手": "Enable AI Assistant",
    "API 基础地址:": "API Base URL:",
    "API 密钥:": "API Key:",
    "模型名称:": "Model Name:",
    "请求超时:": "Request Timeout:",
    "自定义提示词:": "Custom System Prompt:",
    "留空则使用默认系统提示词": "Leave empty to use the default system prompt",
    "测试连接": "Test Connection",
    "正在测试...": "Testing...",
    "✓ 连接成功": "✓ Connected",
    "✗ 失败: %s": "✗ Failed: %s",
    "请先填写 API 基础地址、密钥和模型名称。": "Please fill in API base URL, key, and model name first.",
    "配置 OpenAI 兼容 API, 即可在右侧 AI 边栏使用自然语言编排文件。\n"
    "支持 OpenAI、Azure OpenAI、Microsoft Foundry 上的 Fast Context 等特化模型, "
    "以及任何兼容端点 (例如本地 Ollama)。":
        "Configure an OpenAI-compatible API to drive the AI sidebar.\n"
        "Works with OpenAI, Azure OpenAI, Microsoft Foundry models (e.g. Fast Context), "
        "and any compatible endpoint (e.g. local Ollama).",
    "请先在 设置 → AI 设置 中启用并配置 API。":
        "Please enable and configure the API in Settings → AI Settings first.",
    "你好, 我是 AI 编排助手。告诉我你想收集哪些文件, 我来帮你编排。\n"
    "例如: \"把 src 目录下所有 Python 文件加进去, 然后在开头插入一段任务说明。\"":
        "Hi! I'm your AI arrangement assistant. Tell me which files you want to collect and I'll handle the orchestration.\n"
        "Example: \"Add all Python files under src to the list, and prepend a task description.\"",
    "输入指令, Enter 发送, Shift+Enter 换行": "Type a request. Press Enter to send, Shift+Enter to insert a new line.",
    "发送": "Send",
    "回到底部": "Scroll to bottom",
    "清空对话": "Clear Chat",
    "正在思考...": "Thinking...",
    "未配置": "Not configured",
    "未配置模型": "No model configured",
    "调用失败: %s": "API call failed: %s",
    "响应解析失败: %s": "Failed to parse response: %s",
    "执行出错: %s": "Tool execution error: %s",
    "未配置工具执行器": "Tool executor not configured",
    "已添加 %d 个文件 (跳过 %d 个无效路径)": "Added %d file(s), skipped %d invalid path(s)",
    "已跳过所有 %d 个路径 (文件不存在)": "Skipped all %d path(s) (files do not exist)",
    "错误: 尚未设置工作目录, 也未提供 directory 参数":
        "Error: no work directory set and no 'directory' argument provided",
    "错误: 目录不存在: %s": "Error: directory does not exist: %s",
    "在 %s 下未找到匹配 '%s' 的文件":
        "No files matching '%s' were found under %s",
    "%s 下没有可列出的文件": "No files to list under %s",
    "错误: path 不能为空": "Error: 'path' must not be empty",
    "错误: 文件不存在: %s": "Error: file does not exist: %s",
    "错误: 不是普通文件: %s": "Error: not a regular file: %s",
    "错误: 读取失败: %s": "Error: failed to read: %s",
    "错误: 文件看起来是二进制, 不支持读取: %s":
        "Error: file looks binary, reading is not supported: %s",
    "更多行请用 start_line / max_lines 分段读取":
        "Read further in chunks via start_line / max_lines",
    "内容被 max_bytes 截断": "content truncated by max_bytes",
    "编排列表为空 (0 项)": "Orchestration list is empty (0 items)",
    "错误: kind 必须是 'file' 或 'text', 得到: %s":
        "Error: kind must be 'file' or 'text', got: %s",
    "(无匹配项)": "(no matching items)",
    "… 仅显示前 %d 项, 完整列表请用 kind 过滤":
        "… showing the first %d item(s); use kind to filter for a complete view",
    "停止": "Stop",
    "已停止": "Stopped",
    # ---- 视觉语言大模型 (VLM) 预处理 ----
    "AI 助手 (侧边栏)": "AI Assistant (Sidebar)",
    "启用视觉语言大模型 (VLM)": "Enable Vision-Language Model (VLM)",
    "视觉语言大模型 (二进制文件预处理)": "Vision-Language Model (Binary File Preprocessing)",
    "自定义系统提示词 (可选)": "Custom System Prompt (Optional)",
    "配置视觉语言大模型 (VLM) API, 用于将 PDF、Word、PPT、图片等转为 Markdown。":
        "Configure a Vision-Language Model (VLM) API to convert PDF, Word, PPT, images, etc. into Markdown.",
    "验证侧边栏 AI 配置是否可用": "Verify sidebar AI configuration",
    "验证视觉语言大模型 (VLM) 配置是否可用":
        "Verify Vision-Language Model (VLM) configuration",
    "关闭后二进制文件将不会自动转换":
        "Binary files will not be auto-converted when disabled",
    "⚠ %s (缺失)": "⚠ %s (missing)",
    "已添加 %d 个文件": "Added %d file(s)",
    "已添加 %d 个文件，跳过 %d 个重复文件":
        "Added %d file(s), skipped %d duplicate(s)",
    "所选文件已全部存在，跳过 %d 个重复文件":
        "All selected files already exist, skipped %d duplicate(s)",
    "来自外部文件": "External file",
    "AI 转换失败": "AI conversion failed",
    "AI 转换完成": "AI conversion complete",
    "已读取本地缓存": "Loaded from local cache",
    "强制重新调用 VLM 转换": "Force re-run VLM conversion",
    "正在处理中...": "Processing...",
    "等待处理": "Pending",
    "重试转换": "Retry conversion",
    "重新进行 AI 转换": "Re-run AI conversion",
    "清除工作区缓存": "Clear Workspace Cache",
    "确认清除缓存？": "Confirm Cache Deletion?",
    "这将删除当前工作目录下的 .filecollector_cache 隐藏文件夹。\n"
    "下次处理相同文件时，将重新调用视觉语言大模型（VLM）并消耗 API Token。":
        "This will delete the .filecollector_cache hidden folder in the current working directory.\n"
        "The next time the same files are processed, the Vision-Language Model will be called again, consuming API tokens.",
    "清除": "Clear",
    "工作区缓存已清除": "Workspace cache cleared",
    "尚未设置工作目录": "No working directory set yet",
    "编辑文本": "Edit Text",
    "在上方插入文本": "Insert Text Above",
    "在下方插入文本": "Insert Text Below",
    "路径已复制到剪贴板": "Path copied to clipboard",
    "在文件管理器中显示": "Show in File Manager",
    "复制路径": "Copy Path",
    "复制文件内容": "Copy File Content",
    "文件过大，无法复制内容": "File too large to copy content",
    "读取文件失败": "Failed to read file",
    "无法打开文件管理器": "Cannot open file manager",
    "操作失败: %s": "Operation failed: %s",
    "文件为二进制格式, 不支持复制内容":
        "File is binary, content copy not supported",
    "内容已复制到剪贴板": "Content copied to clipboard",
    "刷新子树": "Refresh Subtree",
    "检查缓存…": "Checking cache…",
    "AI 转换中…": "AI converting…",
    "已转换": "Converted",
    "转换失败": "Conversion failed",
    "AI 预处理状态: %s": "AI preprocess status: %s",
    "正在检查本地缓存…": "Checking local cache…",
    "AI 转换失败。\n\n可点击右上角 '重新进行 AI 转换' 按钮重试。":
        "AI conversion failed.\n\nClick the 'Re-run AI conversion' button at the top right to retry.",
    "AI 正在转换中, 请稍候…":
        "AI is converting, please wait…",
    "等待处理 (排队中)…": "Pending (queued)…",
    "尚未开始处理。": "Not yet started.",
    "AI 转换失败, 可点击重试":
        "AI conversion failed, click to retry",
    "已重新触发 AI 转换": "AI conversion re-triggered",
    "AI 助手未启用": "AI assistant is not enabled",
    "AI 设置已保存": "AI settings saved",
    "默认": "Default",
    # ---- Git 模式 ----
    "切换到 Git 提交历史": "Switch to Git Commit History",
    "切换到文件树": "Switch to File Tree",
    "Git 提交历史": "Git Commit History",
    "搜索提交信息…": "Search commit messages…",
    "正在加载 Git 日志…": "Loading Git log…",
    "Git 日志加载失败: %s": "Git log load failed: %s",
    "已加载 %d 条提交记录": "Loaded %d commit(s)",
    "暂无提交记录": "No commits yet",
    "一键添加所有改动文件": "Add All Changed Files",
    "导出工作区 Diff": "Export Working Tree Diff",
    "导出选中 Commit Diff": "Export Selected Commit Diff",
    "正在加载 Diff...": "Loading Diff...",
    "加载 Diff 失败: %s": "Failed to load Diff: %s",
    "已将 Diff 插入编排列表": "Diff inserted into arrangement list",
    "已添加 %d 个改动文件到编排列表": "Added %d changed file(s) to arrangement list",
    "当前工作区没有未提交的改动": "No uncommitted changes in the working tree",
    "没有可添加的文件": "No files to add",
    "Git 错误: %s": "Git error: %s",
    "尚未设置工作目录": "No working directory set yet",
    "恢复为默认扩展名列表":
        "Restore to default extension list",
    "允许转换的二进制扩展名 (逗号分隔, 如 .pdf, .docx)":
        "Allowed binary extensions to convert (comma separated, e.g. .pdf, .docx)",
    "留空则不允许任何文件被自动转换":
        "Leave empty to disallow auto-conversion of any file",
    "打开缓存": "Open cache",
    "尚未设置工作目录": "No working directory set yet",
    "复制失败: %s": "Copy failed: %s",
    "⚠ 配置 API 时请确保使用可信网络与 HTTPS, 避免密钥泄露。":
        "⚠ When configuring the API, please ensure a trusted network and HTTPS to avoid key leakage.",
    "启用 AI 助手": "Enable AI Assistant",
    "侧边栏": "Sidebar",
    "多模态": "VLM",  # 旧 key, 兼容旧调用, 推荐使用 "VLM"
    "VLM": "VLM",
    "API 基础地址": "API Base URL",
    "API 密钥": "API Key",
    "模型名称": "Model Name",
    "请求超时 (秒)": "Request Timeout (sec)",
    "留空则使用默认系统提示词":
        "Leave empty to use the default system prompt",
    "测试连接": "Test Connection",
    "正在测试...": "Testing...",
    "✓ 连接成功": "✓ Connected",
    "✗ 失败: %s": "✗ Failed: %s",
    "✗ 请先填写 API 基础地址、密钥和模型名称。":
        "✗ Please fill in API base URL, key, and model name first.",
    "扫描忽略目录 (逗号分隔)":
        "Ignored scan directories (comma separated)",
    "扫描忽略目录": "Ignored Scan Directories",
    "这些目录不会出现在文件树中, 也不会被自动收集。":
        "These directories won't appear in the file tree and won't be auto-collected.",
    "安全警告": "Security Warning",
    "取消": "Cancel",
    "保存": "Save",
    "AI 助手设置": "AI Assistant Settings",
    "AI 设置": "AI Settings",
    # ---- 补充遗漏 ----
    "使用相对路径": "Use Relative Path",
    "保存失败: %s": "Save failed: %s",
    "加载失败: %s": "Load failed: %s",
    "复制到剪贴板失败: %s": "Copy to clipboard failed: %s",
    "头部信息: %s": "Header info: %s",
    "工作目录已切换到 %s": "Working directory changed to %s",
    "已关闭": "Off",
    "已开启": "On",
    "已删除索引 %d": "Deleted index %d",
    "已将 [%d] 移动到 [%d]": "Moved [%d] to [%d]",
    "已清空编排列表": "Arrangement list cleared",
    "未知工具: %s": "Unknown tool: %s",
    "源与目标相同, 无需移动": "Source and destination are the same; no move needed",
    "生成失败: %s": "Generation failed: %s",
    "请先选择一个条目": "Please select an item first",
    "路径模式: %s": "Path mode: %s",
    "无法打开文件管理器: %s": "Cannot open file manager: %s",
    "项目保存 / 加载 (.fcol)": "Project save/load (.fcol)",
    "错误: text 必须是字符串": "Error: 'text' must be a string",
    "错误: index 必须是整数": "Error: 'index' must be an integer",
    "错误: index %d 超出范围 (0..%d)": "Error: index %d out of range (0..%d)",
    "错误: paths 必须是非空数组": "Error: 'paths' must be a non-empty array",
    "错误: from_index / to_index 必须是整数": "Error: 'from_index' / 'to_index' must be integers",
    "错误: 索引超出范围 (0..%d)": "Error: index out of range (0..%d)",
    "配置 OpenAI 兼容 API, 在 AI 边栏使用自然语言编排文件。":
        "Configure an OpenAI-compatible API to drive the AI sidebar.",
    "配置视觉语言大模型（VLM）API, 用于将 PDF、Word、PPT、图片等转为 Markdown。":
        "Configure a Vision-Language Model (VLM) API to convert PDF, Word, PPT, images, etc. into Markdown.",
    # ---- 文件树加载进度 ----
    "正在加载 %d 个项目...": "Loading %d item(s)...",
    "已加载 %d / %d": "Loaded %d / %d",
    # ---- 文件片段 (snippet) ----
    "已添加片段: %s [L%d-L%d]": "Added snippet: %s [L%d-L%d]",
    "--- 片段预览 %s [L%d-L%d] (编码: %s) ---\n%s":
        "--- Snippet Preview %s [L%d-L%d] (Encoding: %s) ---\n%s",
    # ---- 文件树 "选择行" ----
    "选择行...": "Select Lines…",
    "选择行": "Select Lines",
    "行范围": "Line Range",
    "输入行范围，用逗号分隔，用连字符表示区间。\n例如：1-10,15,20-25":
        "Enter line ranges, comma-separated, hyphen for intervals.\n"
        "e.g. 1-10,15,20-25",
    "无效的行范围: %s": "Invalid line range: %s",
    "无效的行号: %s": "Invalid line number: %s",
    "未输入有效的行范围": "No valid line range entered",
    "已添加 %d 个行范围": "Added %d line range(s)",
    # ---- 偏好设置 (上下文 / 外观) ----
    "外观与上下文": "Appearance & Context",
    "设置模型上下文窗口用于进度条预警；外观主题立即生效。":
        "Set the model context window for progress warnings; the appearance theme applies instantly.",
    "上下文窗口大小 (Tokens)": "Context Window Size (Tokens)",
    "外观主题": "Appearance Theme",
    "跟随系统": "Follow System",
    "浅色": "Light",
    "深色": "Dark",
    "偏好设置": "Preferences",
    # ---- 空状态引导 ----
    "未选择工作目录": "No working directory selected",
    "打开一个文件夹作为工作目录，即可开始收集与编排文件。":
        "Open a folder as the working directory to start collecting and arranging files.",
    "打开工作目录": "Open Working Directory",
    # ---- Git 空状态引导 ----
    "未检测到 Git 仓库": "No Git Repository Detected",
    "当前工作目录不是一个 Git 仓库，无法读取提交历史。请在该目录下执行 git init 进行初始化，或在包含版本库的工作目录中打开本应用。":
        "The current working directory is not a Git repository, so commit history cannot be read. Run git init here, or open the app in a directory that contains a repository.",
    "暂无提交记录": "No Commits Yet",
    "当前 Git 仓库中还没有任何提交。完成首次 git commit 后，提交历史将显示在此处。":
        "This Git repository does not have any commits yet. After your first git commit, the history will appear here.",
    # ---- 通用操作 / 弹窗 ----
    "暂停": "Pause",
    "继续": "Resume",
    "取消全部": "Cancel All",
    "展开": "Expand",
    "收起": "Collapse",
    "全选": "Select All",
    "全不选": "Select None",
    "搜索": "Search",
    "恢复": "Restore",
    "丢弃": "Discard",
    "确认清空": "Confirm Clear",
    "删除 (%d 项)": "Delete (%d item(s))",
    "请先设置工作目录": "Please set a working directory first",
    "编排列表为空，请先添加文件": "The arrangement list is empty; add files first",
    "请先在 AI 设置中配置 API": "Please configure the API in AI Settings first",
    # ---- AI 阅读指南 / 模板 ----
    "AI 生成阅读指南": "AI Reading Guide",
    "AI 生成阅读指南失败": "Failed to generate AI reading guide",
    "正在让 AI 生成阅读指南...": "Asking AI to generate a reading guide...",
    "AI 阅读指南已插入编排列表顶部": "AI reading guide inserted at the top of the arrangement list",
    "场景模板管理": "Scenario Template Manager",
    "提示词模板管理": "Prompt Template Manager",
    "暂无模板": "No templates yet",
    "新增模板": "Add Template",
    "编辑模板": "Edit Template",
    "删除选中模板？": "Delete the selected template?",
    "可用模板:": "Available templates:",
    "请输入模板 ID，例如: /t bug": "Enter a template ID, e.g. /t bug",
    "未找到模板: %s": "Template not found: %s",
    "撤回此消息及后续所有 AI 回复与操作": "Undo this message and all following AI replies and actions",
    "确认撤回": "Confirm Undo",
    "这将撤销此消息之后 AI 的所有回复以及对文件列表的修改。是否继续？":
        "This will undo all of the AI's replies after this message and the changes it made to the file list. Continue?",
    "撤回": "Undo",
    "已撤销 AI 的操作": "AI actions undone",
    # ---- AI 文件操作结果 ----
    "AI 添加了 %d 个文件": "AI added %d file(s)",
    "，跳过 %d 个": ", skipped %d",
    "AI 插入了自定义文本": "AI inserted custom text",
    "AI 清空了编排列表": "AI cleared the arrangement list",
    # ---- Git Diff 注入结果 ----
    "当前工作区没有未提交的改动。": "There are no uncommitted changes in the working tree.",
    "当前没有已暂存的改动。": "There are no staged changes.",
    "已成功将 Git Diff 注入编排列表 (%d 行)": "Git diff injected into the arrangement list (%d lines)",
    "已成功将 Git Diff 注入编排列表 (%d 行)。": "Git diff injected into the arrangement list (%d lines).",
    "未找到该 Commit 的 Diff 或 Commit 不存在。":
        "No diff found for that commit, or the commit does not exist.",
    "已成功将 Commit %s 的 Diff 注入编排列表 (%d 行)":
        "Commit %s diff injected into the arrangement list (%d lines)",
    "已成功将 Commit %s 的 Diff 注入编排列表 (%d 行)。":
        "Commit %s diff injected into the arrangement list (%d lines).",
    "从 %s 到 %s 没有代码差异。": "No code difference between %s and %s.",
    "已成功将 %s..%s 的 Diff 注入编排列表 (%d commits, %d 行)":
        "Diff of %s..%s injected into the arrangement list (%d commits, %d lines)",
    "已成功将 %s..%s 的 Diff 注入编排列表 (%d commits, %d 行)。":
        "Diff of %s..%s injected into the arrangement list (%d commits, %d lines).",
    "当前工作目录不是一个 Git 仓库，无法读取提交历史。":
        "The current working directory is not a Git repository, so commit history cannot be read.",
    # ---- 未保存会话恢复 ----
    "发现未保存的会话": "Unsaved session found",
    "已恢复未保存的会话": "Unsaved session restored",
    "上次运行存在未保存的更改 (%d 个项目)。是否恢复？":
        "The last run left %d unsaved item(s). Restore them?",
    "恢复失败: %s": "Restore failed: %s",
    # ---- 预处理进度 ----
    "正在预处理 0/0 个文件...": "Preprocessing 0/0 files...",
    "正在预处理 %d/%d 个文件...": "Preprocessing %d/%d files...",
    # ---- 编排列表批量操作 ----
    "已选择 %d 个项目": "%d item(s) selected",
    "已重新触发 %d 个文件的 AI 转换": "Re-triggered AI conversion for %d file(s)",
    "已切换 %d 个文件的路径模式": "Switched path mode for %d file(s)",
    "已删除 %d 个条目": "Deleted %d item(s)",
    "重新进行 AI 转换 (%d 项)": "Re-run AI conversion (%d item(s))",
    "切换绝对/相对路径 (%d 项)": "Toggle absolute/relative path (%d item(s))",
    "确定要清空编排列表中的所有 %d 个项目吗？":
        "Clear all %d item(s) from the arrangement list?",
    # ---- Git 历史复制 ----
    "已复制提交信息": "Commit message copied",
    "复制完整哈希": "Copy Full Hash",
    "复制提交信息": "Copy Commit Message",
    "已复制短哈希: %s": "Short hash copied: %s",
    "已复制完整哈希: %s": "Full hash copied: %s",
    "复制短哈希 (%s)": "Copy Short Hash (%s)",
    # ---- 全局内容搜索 ----
    "全局内容搜索": "Global Content Search",
    "输入要搜索的代码内容… (按 Enter 搜索)": "Enter code to search… (Press Enter to search)",
    "区分大小写": "Case Sensitive",
    "正在扫描文件树...": "Scanning file tree...",
    "已扫描 %d 个文件，找到 %d 个匹配项...": "Scanned %d files, found %d match(es)...",
    "搜索完成：扫描 %d 个文件，找到 %d 个匹配项（涉及 %d 个独立文件）":
        "Search complete: scanned %d files, found %d match(es) across %d distinct file(s)",
    "添加选中文件到编排列表 (0)": "Add selected files to arrangement list (0)",
    "添加全部 (0)": "Add All (0)",
    "添加选中文件到编排列表 (%d)": "Add selected files to arrangement list (%d)",
    "添加全部 (%d)": "Add All (%d)",
    # ---- 预览截断提示 ----
    "\n\n---\n\n*（内容过长，已截断显示前 %d 个字符）*":
        "\n\n---\n\n*(Content too long; truncated to the first %d characters)*",
}

_LISTENERS: list[Callable[[str], None]] = []


def detect_system_language() -> str:
    """探测系统语言并返回支持的语言代码."""
    try:
        lang_env = os.environ.get("FILECOLLECTOR_LANG") or os.environ.get(
            "LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
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
