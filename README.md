# FileCollector - 文件收集与编排工具

> 🤖 本项目完全通过 **vibe coding** 方式开发完成。
>
> 📖 English version: [README-en.md](README-en.md)

FileCollector 是一款跨平台的桌面小工具，用于高效收集、编排工作目录中的文件并生成合并文本。  
它提供了可勾选的目录树、灵活的编排列表、文字插入、拖放排序和编码自动检测，非常适合将项目中的关键代码或文档快速整合成一个 TXT 文件，供后续分析或提交给大语言模型使用。

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![PySide6](https://img.shields.io/badge/GUI-PySide6-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

![FileCollector Screenshot](screenshots/screenshot.png)

---

## 📖 使用说明

图形界面使用流程与 Tips，请参阅 [使用说明文档](docs/USAGE.md)。

## ✨ 功能特点

- 💻 **命令行模式 (CLI)**：支持通过终端命令完成所有核心操作，便于脚本化和自动化。
- 🤖 **MCP 服务**：封装为 MCP (Model Context Protocol) 服务，可直接被 Cursor、VS Code + Copilot 等编程工具调用。
- 🔄 **渐进式体验**：CLI 处理与 GUI 微调无缝衔接，AI 后台自动探索编排后，可随时用图形界面人工接管调整。
- 📂 **懒加载目录树**：打开文件夹后自动展示可展开的文件树，轻松勾选文件。
- 📋 **可视化编排列表**：勾选的文件自动进入列表，可自由拖拽排序、上移下移、删除。
- ✏️ **自定义文字插入**：在任意位置插入自己的说明文字，双击即可编辑。
- 🔍 **即时预览**：选中列表条目，右侧预览区显示文件内容或文字全文。
- 🧲 **外部文件支持**：手动添加外部文件，强制使用绝对路径。
- 🧠 **智能编码检测**：自动识别 `utf-8`、`gbk` 等编码，轻松处理中文文件。
- 📄 **灵活输出**：可选择绝对路径或相对路径，并可选在文件头部标注工作目录绝对路径。
- 💾 **项目保存/加载**：将当前工作状态保存为 `.project.json`，下次一键恢复。
- 🚀 **跨平台**：基于 PySide6，支持 Windows、macOS、Linux，高分屏字体清晰。

---

## 🤔 为什么使用此工具？

1. **解决编程工具的上下文困境**：在编程工具中，模型为了探索工作区需要进行大量工具调用，很容易被无关文件干扰而偏离主题。超大项目还容易触发上下文压缩。此外，编程工具中大量的系统提示词会消耗大量 Token。使用此工具人工挑选重要文件，将整理好的上下文交给网页端模型（系统提示词相对较少）进行 bug 分析等深度推理，以最大化模型推理性能。

2. **成本控制**：网页端模型大多是免费（或有额度）的，不是吗？

---

## 🛠️ 安装与运行

### 🐧 GNOME 用户

如果您使用的是 **GNOME 桌面环境**，推荐使用专为 GNOME 优化的版本，提供更原生的集成体验：

👉 [filecollector-gnome](https://github.com/Sam-Fic/filecollector-gnome)

该版本针对 GNOME 进行了适配和优化，包括：

- 原生 GNOME 风格界面
- 更好的桌面集成与交互体验
- 针对 GNOME 环境的特殊优化

### 从源码运行

**要求**：Python 3.8 及以上。

1. 克隆仓库
   ```bash
   git clone https://github.com/Sam-Fic/FileCollector.git
   cd FileCollector
   ```
2. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```
3. 运行程序
   ```bash
   cd src
   python file_collector.py
   ```

<!-- ### 直接下载打包版（推荐）

前往 [Releases](https://github.com/Sam-Fic/FileCollector/releases) 页面，下载对应操作系统的可执行文件：

- `FileCollector-Windows.zip`
- `FileCollector-macOS.zip`
- `FileCollector-Linux.AppImage`
 -->

---

## 📁 项目结构

```
src/
├── file_collector.py          # 向后兼容入口（薄封装 → 委托到包）
├── FileCollector.spec         # PyInstaller 构建配置
└── filecollector/             # 核心 Python 包
    ├── __init__.py            # 包声明，导出 ItemData / FileCollectorEngine
    ├── __main__.py            # python -m filecollector 入口，分发 CLI/GUI
    ├── models.py              # 数据模型（ItemData：文件/文字条目）
    ├── utils.py               # 工具函数（编码检测、安全读取）
    ├── engine.py              # 业务引擎（所有核心逻辑，不依赖 Qt）
    ├── cli.py                 # CLI 模式（按序参数解析与执行）
    └── gui/
        ├── __init__.py
        ├── dialogs.py         # 文字编辑对话框（TextEditDialog）
        └── main_window.py     # 主窗口（FileCollectorApp，依赖 PySide6）
```

---

## 📖 使用指南

1. **打开工作目录**  
   点击 `📂 打开文件夹`，选择项目根目录，左侧将显示文件树。
2. **勾选文件**  
   在树中勾选需要加入的文件，它们会按顺序进入中间的编排列表。
3. **编排内容**
   - 拖拽列表项可自由排序；
   - 使用 `插入文字 ↑/↓` 在选中条目前后添加注释；
   - 双击文字条目进行编辑；
   - 点击 `添加外部文件` 可加入工作目录以外的文件。
4. **预览与调整**  
   选中任意条目，右侧预览区会显示文件前 50 行或文字内容。
5. **设置输出选项**  
   选择 **相对路径**（建议）或 **绝对路径**；若选相对路径，可勾选“在文件头部标注工作目录绝对路径”以便阅读。
6. **生成 TXT**  
   点击 `📄 生成 TXT`，选择保存位置，即可得到按顺序合并的文本文件。
7. **保存/恢复工作区**  
   使用 `💾 保存项目` 将当前勾选状态和编排列表存储为 `.project.json`，下次通过 `📂 加载项目` 恢复。

---

## 🖥️ CLI 命令行模式

FileCollector 内置命令行模式，无需启动图形界面即可通过终端完成所有核心操作，适合脚本化和自动化集成。

### 使用方式

在终端中运行 `filecollector` 并附加 CLI 参数即可进入命令行模式。若未检测到 CLI 参数，则正常启动图形界面。

```bash
filecollector [选项...]
```

### 命令列表

| 选项                 | 说明                              |
| -------------------- | --------------------------------- |
| `--work-dir DIR`     | 设置工作目录                      |
| `--select-file PATH` | 添加文件到编排列表（可多次使用）  |
| `--add-text "TEXT"`  | 添加自定义文字（可多次使用）      |
| `--move FROM TO`     | 将索引 FROM 处的项目移动到索引 TO |
| `--remove INDEX`     | 删除索引 INDEX 处的项目           |
| `--clear`            | 清空编排列表                      |
| `--list-items`       | 列出当前编排列表                  |
| `--export PATH`      | 导出合并文本到文件                |
| `--absolute`         | 使用绝对路径                      |
| `--header`           | 添加头部信息（工作目录路径）      |
| `--load FILE`        | 从项目文件加载状态                |
| `--save FILE`        | 将当前状态保存到项目文件          |
| `--gui`              | 使用 CLI 参数初始化后打开图形界面 |
| `--help`, `-h`       | 显示帮助信息                      |

### 完整工作流示例

**构建并导出：**

```bash
filecollector --work-dir ./project \
    --select-file src/main.vala \
    --select-file src/utils/helper.vala \
    --add-text "=== 以下为配置文件 ===" \
    --select-file config.ini \
    --move 3 2 \
    --header \
    --export output.txt
```

**从项目文件导出：**

```bash
filecollector --load my.project.json --export output.txt
```

**构建并保存项目（供 GUI 使用）：**

```bash
filecollector --work-dir ./project \
    --select-file file1.txt --select-file file2.txt \
    --save my.project.json
```

**查看编排列表：**

```bash
filecollector --load my.project.json --list-items
```

**加载项目后用 GUI 手动调整：**

```bash
filecollector --load my.project.json --gui
```

**用 CLI 参数初始化状态后打开 GUI：**

```bash
filecollector --work-dir ./project --select-file src/main.vala --gui
```

> CLI 模式与 GUI 模式共享同一套数据模型和业务逻辑，`.project.json` 文件可在两者之间互通使用。添加 `--gui` 参数可在 CLI 参数初始化状态后直接弹出图形界面供人工微调，实现自动化与人工审查的无缝切换。

---

## 🗺️ MCP (Model Context Protocol) 服务

FileCollector 已经封装为 MCP 服务，现在编程工具（如 Cursor、VS Code + Copilot）中的大语言模型可以直接调用它完成以下工作流：

1. 用户对编程工具中的模型下达问题指令（例如"此项目有 xx 问题，请帮我寻找与此相关的文件并导出单个 TXT 文件"）。
2. 模型执行文件探索，利用该工具勾选出与问题相关的关键文件。
3. 模型在合适的位置插入指令（要解决的问题）。
4. 调用工具生成一份结构化的 TXT 文件。
5. 用户将此 TXT 文件上传到网页端大语言模型（如 Claude、ChatGPT 等）进行深度推理和问题解决规划。
6. 根据模型返回的规划，用户可以在编程工具使用低成本模型执行实际的问题解决操作。

这种设计将 **文件探索与代码挑选**（由编程工具内的模型完成）与 **复杂推理**（由网页端模型完成）分离，充分利用不同模型的优势，同时保持成本可控。

> 查看 [filecollector-mcp-server](https://github.com/Sam-Fic/filecollector-mcp-server) 了解更多详情和安装使用方法。

---

## 🔄 渐进式体验

GUI 与 CLI 结合，实现了无缝的人机协同工作流：

1. 在 Cursor 中通过 MCP 服务让大模型自动探索和编排项目文件。
2. 当生成的文件列表需要人工微调时，在终端运行：
   ```bash
   filecollector --load ~/.config/filecollector/mcp_state.json --gui
   ```
   `--gui` 参数确保打开图形界面（不带 `--gui` 则仅执行 CLI 命令）。
3. 弹出图形界面，展示模型选定的文件列表。可继续勾选、排序、保存。
4. 回到 Cursor 中，模型继续后续工作。

---

## 📦 自行打包

如需打包为独立可执行文件，可使用 PyInstaller：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "FileCollector" file_collector.py
```

打包前请确保已安装所有依赖（`requirements.txt`）。

---

## 🤝 贡献

项目处于早期阶段，欢迎 Issue 和 Pull Request。  

---

## 📄 开源许可

本项目采用 **MIT 许可证**，详情见 [LICENSE](LICENSE) 文件。  

---

## 🙏 致谢

- [PySide6](https://wiki.qt.io/Qt_for_Python) - 提供现代 GUI 框架
- [chardet](https://github.com/chardet/chardet) - 编码检测库
