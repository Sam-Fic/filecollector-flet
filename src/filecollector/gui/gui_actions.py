import os
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt

from filecollector.engine import FileCollectorEngine


def generate_txt(window, engine):
    if not engine.items:
        QMessageBox.warning(window, "警告", "编排列表为空，无法生成。")
        return

    file_path, _selected = QFileDialog.getSaveFileName(
        window, "保存合并文本", "",
        "Text files (*.txt);;All files (*)"
    )
    if not file_path:
        return
    if not file_path.lower().endswith('.txt'):
        file_path += '.txt'

    try:
        engine.export(file_path)

        window.status_bar.showMessage(f"TXT 已生成: {file_path}")
        QMessageBox.information(window, "成功", f"文件已保存到:\n{file_path}")

        reply = QMessageBox.question(
            window, "打开位置", "是否打开文件所在文件夹？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            _open_file_location(file_path)

    except Exception as e:
        QMessageBox.critical(window, "错误", f"生成 TXT 失败:\n{e}")


def generate_to_clipboard(window, engine):
    if not engine.items:
        QMessageBox.warning(window, "警告", "编排列表为空，无法生成。")
        return
    try:
        import subprocess
        from filecollector.config import get_clipboard_staging_path

        file_path = get_clipboard_staging_path(engine.work_dir)
        engine.export(file_path)

        if sys.platform == "win32":
            subprocess.run(
                ["clip"],
                input=open(file_path, "rb").read(),
                check=False
            )
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard", file_path],
                check=False
            )
        window.status_bar.showMessage("合并文本已复制到剪贴板")
    except Exception as e:
        QMessageBox.critical(window, "错误", f"复制到剪贴板失败:\n{e}")


def _open_file_location(path):
    try:
        import subprocess

        if sys.platform == "win32":
            subprocess.Popen(
                ['explorer', '/select,', path.replace('/', '\\')]
            )
        elif sys.platform == "darwin":
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(path)])
    except Exception:
        pass


def open_folder(window, engine):
    directory = QFileDialog.getExistingDirectory(window, "选择工作文件夹")
    if directory:
        engine.work_dir = Path(directory).resolve()
        window.work_dir_label.setText(f"当前工作目录: {engine.work_dir}")
        window._refresh_tree()
        window._refresh_list()
        window.status_bar.showMessage(f"已设置工作目录: {engine.work_dir}")


_SAVE_FILTER = "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)"
_OPEN_FILTER = "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)"


def _pick_save_path(window, engine):
    file_path, _selected = QFileDialog.getSaveFileName(
        window, "保存项目", engine.project_file or "",
        _SAVE_FILTER,
        selectedFilter="Project (*.project.json *.fcol *.fcol.json)"
    )
    if file_path:
        if not (file_path.endswith(".project.json") or file_path.endswith(".fcol") or file_path.endswith(".fcol.json")):
            file_path += ".project.json"
    return file_path


def save_project(window, engine):
    if not engine.project_file:
        return save_project_as(window, engine)
    _write_project(window, engine, engine.project_file)


def save_project_as(window, engine):
    file_path = _pick_save_path(window, engine)
    if file_path:
        _write_project(window, engine, file_path)


def _write_project(window, engine, file_path):
    try:
        engine.common_phrases = list(getattr(window, "common_phrases", []) or [])
        engine.save(file_path)
        engine.project_file = file_path
        _show_toast(window, f"项目已保存: {Path(file_path).name}")
    except Exception as e:
        QMessageBox.critical(window, "保存失败", str(e))


def load_project(window, engine):
    file_path, _selected = QFileDialog.getOpenFileName(
        window, "打开项目", "",
        _OPEN_FILTER,
        selectedFilter="Project (*.project.json *.fcol *.fcol.json)"
    )
    if not file_path:
        return
    try:
        engine.load(file_path)
        _sync_project_state(window, engine)

        engine.project_file = file_path
        _show_toast(window, f"项目已加载: {Path(file_path).name}")
    except Exception as e:
        QMessageBox.critical(
            window, "加载失败",
            f"项目文件损坏或格式不正确:\n{e}"
        )
        traceback.print_exc()


def _sync_project_state(window, engine, restore_selection=False):
    if hasattr(window, "work_dir_label"):
        window.work_dir_label.setText(f"当前工作目录: {engine.work_dir}" if engine.work_dir else "当前工作目录: 未设置")

    if hasattr(window, "_refresh_tree"):
        window._refresh_tree()

    if hasattr(window, "_restore_tree_checks"):
        window._restore_tree_checks(engine.checked_paths)
    else:
        from PySide6.QtCore import Qt
        for p_str in engine.checked_paths:
            window._set_tree_item_check(p_str, Qt.Checked)

    if hasattr(window, "radio_abs"):
        window.radio_abs.setChecked(engine.use_absolute)
        window.radio_rel.setChecked(not engine.use_absolute)
        window.check_header.setChecked(engine.show_header)
        if hasattr(window, "_update_path_mode_ui"):
            window._update_path_mode_ui()

    if hasattr(window, "_refresh_list"):
        window._refresh_list()

    if restore_selection and hasattr(window, "_restore_list_selection"):
        window._restore_list_selection()

    if hasattr(window, "common_phrases"):
        window.common_phrases = list(engine.common_phrases)


def reload_project(window, engine):
    if not engine.project_file or not Path(engine.project_file).exists():
        return
    try:
        engine.load(engine.project_file)
        _sync_project_state(window, engine, restore_selection=True)
        _show_toast(window, "项目文件已重新加载")
    except Exception as e:
        _show_toast(window, f"重新加载失败: {e}")


def show_about(window):
    QMessageBox.about(
        window, "关于 FileCollector",
        "文件收集与编排工具 v2.0 (PySide6)\n"
        "跨平台支持 Windows / macOS / Linux\n"
        "高清屏适配，现代字体渲染\n\n"
        "功能：目录树勾选、拖放排序、文字编排、编码检测、项目保存"
    )
