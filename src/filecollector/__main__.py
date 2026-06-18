import sys

from filecollector.cli import run_cli, parse_to_engine, print_help, is_cli_mode

# 检查是否使用 Flet 版本
USE_FLET = "--flet" in sys.argv

if USE_FLET:
    # 移除 --flet 参数
    sys.argv = [arg for arg in sys.argv if arg != "--flet"]

try:
    if USE_FLET:
        import flet as ft
        from filecollector.gui_flet import main as flet_main
        FLET_AVAILABLE = True
    else:
        from PySide6.QtWidgets import QApplication
        from filecollector.gui.main_window import FileCollectorApp
        GUI_AVAILABLE = True
except ImportError:
    if USE_FLET:
        FLET_AVAILABLE = False
    else:
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

    has_cli_args = len(filtered_args) > 1

    # If there are CLI args, try to send them to a running GUI instance.
    # When connected, the running GUI applies the operations live.
    if has_cli_args:
        from filecollector.ipc import send_to_running_instance
        if send_to_running_instance(filtered_args[1:]):
            sys.exit(0)

    if not force_gui and is_cli_mode(sys.argv):
        # Pure CLI mode: no --gui, has CLI args, no running GUI
        sys.exit(run_cli())

    if USE_FLET and FLET_AVAILABLE:
        # Flet 模式
        ft.run(flet_main)
        sys.exit(0)

    if USE_FLET and not FLET_AVAILABLE:
        print("错误: 未安装 flet 依赖, 请先安装或移除 --flet 参数", file=sys.stderr)
        sys.exit(1)

    if force_gui and has_cli_args:
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
        # Normal GUI mode (no CLI args, or --gui alone)
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
