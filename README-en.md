# FileCollector - File Collection & Organization Tool

> 🤖 This project was developed entirely through **vibe coding**.
>
> 📖 中文版本：[README.md](README.md)

FileCollector is a cross-platform desktop utility for efficiently collecting and organizing files from a working directory into a merged text file.  
It features a checkable directory tree, flexible organization list, text insertion, drag-and-drop sorting, and automatic encoding detection — perfect for quickly consolidating key code or documents from a project into a single TXT file for analysis or submission to a large language model.

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![PySide6](https://img.shields.io/badge/GUI-PySide6-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

![FileCollector Screenshot](screenshots/screenshot.png)

---

## ✨ Features

- 📂 **Lazy-loaded Directory Tree**: Automatically displays an expandable file tree when opening a folder, with easy file checkbox selection.
- 📋 **Visual Organization List**: Checked files automatically appear in the list, freely reorderable via drag-and-drop, move up/down, or delete.
- ✏️ **Custom Text Insertion**: Insert explanatory text at any position, double-click to edit.
- 🔍 **Instant Preview**: Select a list item to preview file content or full text in the right panel.
- 🧲 **External File Support**: Manually add external files using absolute paths.
- 🧠 **Smart Encoding Detection**: Automatically identifies `utf-8`, `gbk`, and other encodings for seamless Chinese file handling.
- 📄 **Flexible Output**: Choose absolute or relative paths, with optional working directory annotation at file header.
- 💾 **Project Save/Load**: Save current workspace state as `.project.json` and restore it with one click.
- 🚀 **Cross-Platform**: Built on PySide6, supporting Windows, macOS, and Linux with crisp high-DPI fonts.

---

## 🤔 Why Use This Tool?

1. **Solving the Context Dilemma in Coding Tools**: In coding tools, models need to make numerous tool calls to explore the workspace, which can easily get sidetracked by irrelevant files and lose focus. Large projects are prone to context compression. Additionally, the large system prompts in coding tools consume significant tokens. Use this tool to manually select important files, then pass the curated context to a web-side model (with relatively lighter system prompts) for bug analysis and other deep reasoning tasks, maximizing model reasoning performance.

2. **Cost Control**: Web-side models are mostly free (or come with credits), aren't they?

---

## 🛠️ Installation & Usage

### Run from Source

**Requirements**: Python 3.8+.

1. Clone the repository
   ```bash
   git clone https://github.com/Sam-Fic/FileCollector.git
   cd FileCollector
   ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Run the program
   ```bash
   python file_collector.py
   ```

### 🐧 GNOME Users

If you are using the **GNOME desktop environment**, we recommend using the GNOME-optimized version for a more native integration experience:

👉 [filecollector-gnome](https://github.com/Sam-Fic/filecollector-gnome)

This version is adapted and optimized for GNOME, including:
- Native GNOME-style interface
- Better desktop integration and interaction experience
- Special optimizations for the GNOME environment

<!-- ### Download Pre-built Packages (Recommended)

Visit the [Releases](https://github.com/Sam-Fic/FileCollector/releases) page to download the executable for your OS:

- `FileCollector-Windows.zip`
- `FileCollector-macOS.zip`
- `FileCollector-Linux.AppImage`
 -->
---

## 📖 User Guide

1. **Open Working Directory**  
   Click `📂 Open Folder`, select your project root, and the file tree will appear on the left.
2. **Check Files**  
   Check files in the tree to add them to the organization list in order.
3. **Organize Content**
   - Drag list items to freely reorder;
   - Use `Insert Text ↑/↓` to add comments before or after selected items;
   - Double-click text items to edit;
   - Click `Add External File` to include files outside the working directory.
4. **Preview & Adjust**  
   Select any item to preview the first 50 lines of a file or full text content in the right panel.
5. **Set Output Options**  
   Choose **Relative Path** (recommended) or **Absolute Path**; if using relative paths, you can check "Annotate working directory absolute path at file header" for readability.
6. **Generate TXT**  
   Click `📄 Generate TXT`, choose a save location, and get a merged text file in order.
7. **Save/Restore Workspace**  
   Use `💾 Save Project` to store the current selection and organization as `.project.json`, then restore it later via `📂 Load Project`.

---

## 🗺️ Future Roadmap

Currently, FileCollector is a standalone desktop application. The next step is to package it as an **MCP (Model Context Protocol) service** or **Skill**, enabling large language models in coding tools (like Cursor, VS Code + Copilot) to directly invoke it for the following workflow:

1. User gives an instruction to the model in the coding tool (e.g., "This project has an xx issue, help me find related files and export them as a single TXT file").
2. The model explores files and uses this tool to check and select key files related to the issue.
3. The model inserts the instruction (the problem to solve) at an appropriate position.
4. Invokes the tool to generate a structured TXT file.
5. User uploads this TXT file to a web-side LLM (like Claude, ChatGPT, etc.) for deep reasoning and problem-solving.
6. Based on the model's response, users can execute actual problem-solving operations using low-cost models in the coding tool.

This design separates **file exploration and code selection** (handled by the coding tool's model) from **complex reasoning** (handled by the web-side model), leveraging the strengths of different models while keeping costs manageable.

> Contributions and MCP interface development ideas are welcome!

---

## 📦 Build Your Own Package

To package as a standalone executable using PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "FileCollector" file_collector.py
```

Ensure all dependencies (`requirements.txt`) are installed before packaging.

---

## 🤝 Contributing

This project is in its early stages. Issues and Pull Requests are welcome.  
If you're interested in MCP integration, feature enhancements, or cross-platform testing, please start a discussion.

---

## 📄 License

This project uses the **MIT License**, see the [LICENSE](LICENSE) file for details.  
The MIT license is permissive and flexible, allowing commercial use and closed-source modifications with only the requirement to retain copyright notices.

---

## 🙏 Acknowledgments

- [PySide6](https://wiki.qt.io/Qt_for_Python) - Modern GUI framework
- [chardet](https://github.com/chardet/chardet) - Encoding detection library
- TRAE / opencode
- Deepseek v4 Flash / Gemini 3.5 Flash
