import sys

from filecollector.cli import run_cli

try:
    from PySide6.QtWidgets import QApplication
    from filecollector.gui.main_window import FileCollectorApp
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False


def main():
    if len(sys.argv) > 1:
        sys.exit(run_cli())
    elif GUI_AVAILABLE:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = FileCollectorApp()
        window.show()
        sys.exit(app.exec())
    else:
        print("FileCollector: 请使用 --help 查看命令列表", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
