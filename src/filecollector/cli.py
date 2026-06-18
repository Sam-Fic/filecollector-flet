import sys
from pathlib import Path

from filecollector.engine import FileCollectorEngine


def apply_cli_args(engine, args, print_feedback=True):
    """Apply CLI operations to an existing engine in-place.

    Handles all state-modifying args: --work-dir, --select-file, --add-text,
    --move, --remove, --clear, --absolute, --header, --load, --list-items.
    Skips --help, --export, --save (those are handled by CLI mode only).

    Returns True on success, False on error.
    """
    i = 0
    while i < len(args):
        arg = args[i]

        if arg in ("--help", "-h", "--gui", "--no-ipc"):
            pass
        elif arg == "--work-dir":
            i += 1
            if i >= len(args):
                if print_feedback:
                    print("--work-dir 需要参数", file=sys.stderr)
                return False
            engine.work_dir = Path(args[i]).resolve()
            if print_feedback:
                print(f"工作目录: {engine.work_dir}")
        elif arg == "--select-file":
            i += 1
            if i >= len(args):
                if print_feedback:
                    print("--select-file 需要参数", file=sys.stderr)
                return False
            abs_path = str(Path(args[i]).resolve())
            engine.add_file(abs_path)
            engine.checked_paths.add(abs_path)
            if print_feedback:
                print(f"已添加文件: {abs_path}")
        elif arg == "--add-text":
            i += 1
            if i >= len(args):
                if print_feedback:
                    print("--add-text 需要参数", file=sys.stderr)
                return False
            text = args[i]
            engine.add_text(text)
            if print_feedback:
                preview = text[:40] + ('...' if len(text) > 40 else '')
                print(f"已添加文字: {preview}")
        elif arg == "--move":
            if i + 2 >= len(args):
                if print_feedback:
                    print("--move 需要两个参数", file=sys.stderr)
                return False
            try:
                from_idx = int(args[i + 1])
                to_idx = int(args[i + 2])
            except ValueError:
                if print_feedback:
                    print("--move 参数必须是整数", file=sys.stderr)
                return False
            engine.move_item(from_idx, to_idx)
            if print_feedback:
                print(f"已将 [{from_idx}] 移动到 [{to_idx}]")
            i += 2
        elif arg == "--remove":
            i += 1
            if i >= len(args):
                if print_feedback:
                    print("--remove 需要参数", file=sys.stderr)
                return False
            try:
                idx = int(args[i])
            except ValueError:
                if print_feedback:
                    print("--remove 参数必须是整数", file=sys.stderr)
                return False
            if 0 <= idx < len(engine.items):
                data = engine.items[idx]
                if data.type == "file" and not data.force_absolute:
                    engine.checked_paths.discard(data.path)
            engine.remove_item(idx)
            if print_feedback:
                print(f"已删除索引 [{idx}]")
        elif arg == "--clear":
            engine.clear()
            engine.checked_paths.clear()
            if print_feedback:
                print("已清空编排列表")
        elif arg == "--list-items":
            items = engine.list_items()
            if not items:
                if print_feedback:
                    print("编排列表为空")
            elif print_feedback:
                print(f"\n编排列表 ({len(items)} 项):")
                print("-" * 50)
                for idx, typ, desc in items:
                    print(f"  [{idx}] [{typ}] {desc}")
                print()
        elif arg == "--absolute":
            engine.use_absolute = True
            if print_feedback:
                print("路径模式: 绝对路径")
        elif arg == "--header":
            engine.show_header = True
            if print_feedback:
                print("头部信息: 已启用")
        elif arg == "--load":
            i += 1
            if i >= len(args):
                if print_feedback:
                    print("--load 需要参数", file=sys.stderr)
                return False
            try:
                engine.load_project(args[i])
                if print_feedback:
                    print(f"已加载项目: {args[i]}")
            except Exception as e:
                if print_feedback:
                    print(f"加载项目失败: {e}", file=sys.stderr)
                return False
        elif arg in ("--export", "--save"):
            i += 1
            if i >= len(args):
                return False
        else:
            if print_feedback:
                print(f"未知选项: {arg}", file=sys.stderr)
                if print_feedback:
                    print("使用 --help 查看帮助", file=sys.stderr)
            return False

        i += 1
    return True


def parse_to_engine(argv):
    """Parse CLI args into a new FileCollectorEngine.

    Returns (engine, show_help, save_path, export_path).
    Returns (None, False, None, None) on error.
    """
    engine = FileCollectorEngine()
    show_help = False
    save_path = None
    export_path = None

    # First pass: extract special flags that are not engine state.
    filtered = []
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            show_help = True
            filtered.append(argv[i])
        elif arg == "--export":
            i += 1
            if i >= len(argv):
                print("--export 需要参数", file=sys.stderr)
                return None, False, None, None
            export_path = argv[i]
        elif arg == "--save":
            i += 1
            if i >= len(argv):
                print("--save 需要参数", file=sys.stderr)
                return None, False, None, None
            save_path = argv[i]
        else:
            filtered.append(argv[i])
        i += 1

    if not apply_cli_args(engine, filtered):
        return None, False, None, None

    return engine, show_help, save_path, export_path


def print_help():
    print("用法: filecollector [选项...]")
    print()
    print("CLI 命令行模式 — 无需图形界面即可完成所有核心操作")
    print()
    print("选项:")
    print("  --work-dir DIR             设置工作目录")
    print("  --select-file PATH         添加文件到编排列表（可多次使用）")
    print('  --add-text "TEXT"          添加自定义文字（可多次使用）')
    print("  --move FROM TO             将索引 FROM 处的项目移动到索引 TO")
    print("  --remove INDEX             删除索引 INDEX 处的项目")
    print("  --clear                    清空编排列表")
    print("  --list-items               列出当前编排列表")
    print("  --export PATH              导出合并文本到文件")
    print("  --absolute                 使用绝对路径")
    print("  --header                   添加头部信息（工作目录路径）")
    print("  --load FILE                从项目文件加载状态")
    print("  --save FILE                将当前状态保存到项目文件")
    print("  --gui                      使用 CLI 参数初始化后打开图形界面")
    print("  --no-ipc                   不转发到已运行的 GUI 实例 (CLI 脚本模式)")
    print("  --help, -h                 显示帮助信息")


def run_cli():
    engine, show_help, save_path, export_path = parse_to_engine(sys.argv)
    if engine is None:
        return 1

    if show_help:
        print_help()
        return 0

    if save_path:
        try:
            engine.save_project(save_path)
            print(f"项目已保存: {save_path}")
        except Exception as e:
            print(f"保存项目失败: {e}", file=sys.stderr)
            return 1

    if export_path:
        if not engine.items:
            print("错误: 编排列表为空，无法导出", file=sys.stderr)
            return 1
        try:
            engine.export(export_path)
            print(f"已导出到: {export_path}")
        except Exception as e:
            print(f"导出失败: {e}", file=sys.stderr)
            return 1

    return 0


def is_cli_mode(argv):
    """Check if argv contains CLI mode arguments (excluding --gui)."""
    for arg in argv:
        if arg in ("--work-dir", "--select-file", "--add-text",
                   "--move", "--remove", "--clear",
                   "--export", "--load", "--save",
                   "--absolute", "--header", "--help",
                   "-h", "--list-items"):
            return True
    return False
