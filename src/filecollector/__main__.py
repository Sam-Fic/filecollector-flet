import sys

from filecollector.cli import run_cli, parse_to_engine, print_help, is_cli_mode

try:
    from PySide6.QtWidgets import QApplication
    from filecollector.gui.main_window import FileCollectorApp
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False


def main():
    # Check for --gui flag: forces GUI mode even with other CLI args
    force_gui = False
    filtered_args = [sys.argv[0]]
    for arg in sys.argv[1:]:
        if arg == "--gui":
            force_gui = True
        else:
            filtered_args.append(arg)

    if not force_gui and is_cli_mode(sys.argv):
        # Pure CLI mode: no --gui, has CLI args
        sys.exit(run_cli())

    if force_gui and len(filtered_args) > 1:
        # --gui with other CLI args: parse args, then launch GUI with state
        engine, show_help, _, _ = parse_to_engine(filtered_args)
        if engine is None:
            sys.exit(1)
        if show_help:
            print_help()
            sys.exit(0)

        if not GUI_AVAILABLE:
            print("错误: 无法加载图形界面 (PySide6 未安装)", file=sys.stderr)
            sys.exit(1)

        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = FileCollectorApp()
        window.initialize_from_engine(engine)
        window.show()
        sys.exit(app.exec())

    if GUI_AVAILABLE:
        # Normal GUI mode
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
