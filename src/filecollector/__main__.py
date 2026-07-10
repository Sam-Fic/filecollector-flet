import sys

from filecollector.cli import run_cli, parse_to_engine, print_help, is_cli_mode

try:
    import flet as ft
    from filecollector.gui_flet import main as flet_main
    FLET_AVAILABLE = True
except ImportError:
    FLET_AVAILABLE = False

# 当通过 --gui 启动时, 把 CLI 初始化参数暂存于此, 供 flet_main 启动时应用
# (对齐 gnome: 先用 CLI 参数构建状态, 再注入 GUI 实例).
_PENDING_CLI_ARGS: list[str] = []


def main():
    # Check for --gui flag: forces GUI mode even with other CLI args
    force_gui = False
    no_ipc = False
    filtered_args = [sys.argv[0]]
    for arg in sys.argv[1:]:
        if arg == "--gui":
            force_gui = True
        elif arg == "--no-ipc":
            no_ipc = True
        else:
            filtered_args.append(arg)

    has_cli_args = len(filtered_args) > 1

    # If there are CLI args, try to send them to a running GUI instance.
    # When connected, the running GUI applies the operations live.
    # --no-ipc bypasses forwarding for scripted/CLI use where the caller
    # needs a deterministic exit code instead of async GUI handling.
    if has_cli_args and not no_ipc:
        from filecollector.ipc import send_to_running_instance
        if send_to_running_instance(filtered_args[1:]):
            sys.exit(0)

    if not force_gui and is_cli_mode(sys.argv):
        # Pure CLI mode: no --gui, has CLI args, no running GUI
        sys.exit(run_cli())

    # --gui 模式: 把 CLI 初始化参数暂存, 待 GUI 启动后应用 (而非开空白界面)
    if force_gui and has_cli_args:
        global _PENDING_CLI_ARGS
        _PENDING_CLI_ARGS = filtered_args[1:]

    # 默认使用 Flet 模式
    if FLET_AVAILABLE:
        ft.run(flet_main)
        sys.exit(0)

    # Flet 不可用时提示错误
    print("错误: Flet 未安装，请运行: pip install flet", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
