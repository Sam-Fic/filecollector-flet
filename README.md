# FileCollector - 文件收集与编排工具

> 🤖 本项目完全通过 **vibe coding** 方式开发完成。
>
> 📖 English version: [README-en.md](README-en.md)

FileCollector 是一款跨平台的桌面小工具，用于高效收集、编排工作目录中的文件并生成合并文本。  
它提供了可勾选的目录树、灵活的编排列表、文字插入、拖放排序和编码自动检测，非常适合将项目中的关键代码或文档快速整合成一个 TXT 文件，供后续分析或提交给大语言模型使用。

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![PySide6](https://img.shields.io/badge/GUI-PySide6-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

![FileCollector Screenshot](screenshots/screenshot.png)

---

## ✨ 功能特点

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

### 🐧 GNOME 用户

如果您使用的是 **GNOME 桌面环境**，推荐使用专为 GNOME 优化的版本，提供更原生的集成体验：

👉 [filecollector-gnome](https://github.com/Sam-Fic/filecollector-gnome)

该版本针对 GNOME 进行了适配和优化，包括：

- 原生 GNOME 风格界面
- 更好的桌面集成与交互体验
- 针对 GNOME 环境的特殊优化

<!-- ### 直接下载打包版（推荐）

前往 [Releases](https://github.com/Sam-Fic/FileCollector/releases) 页面，下载对应操作系统的可执行文件：

- `FileCollector-Windows.zip`
- `FileCollector-macOS.zip`
- `FileCollector-Linux.AppImage`
 -->

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

## 🗺️ 未来规划

目前 FileCollector 是一个独立运行的桌面工具。下一步计划是将其封装为 **MCP (Model Context Protocol) 服务** 或 **技能 (Skills)**，让编程工具（如 Cursor、VS Code + Copilot）中的大语言模型能够直接调用它完成以下工作流：

1. 用户对编程工具中的模型下达问题指令（例如“此项目有xx问题，请帮我寻找与此相关的文件并导出单个 TXT 文件”）。
2. 模型执行文件探索，利用该工具勾选出与问题相关的关键文件。
3. 模型在合适的位置插入指令（要解决的问题）。
4. 调用工具生成一份结构化的 TXT 文件。
5. 用户将此 TXT 文件上传到网页端大语言模型（如 Claude、ChatGPT 等）进行深度推理和问题解决规划。
6. 根据模型返回的规划，用户可以在编程工具使用低成本模型执行实际的问题解决操作。

这种设计将 **文件探索与代码挑选**（由编程工具内的模型完成）与 **复杂推理**（由网页端模型完成）分离，充分利用不同模型的优势，同时保持成本可控。

> 欢迎贡献想法或参与开发！

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
