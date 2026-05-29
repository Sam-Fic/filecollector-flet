import sys
from pathlib import Path

from filecollector.engine import FileCollectorEngine


def run_cli():
    engine = FileCollectorEngine()
    show_help = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        if arg in ("--help", "-h"):
            show_help = True
            i += 1
        elif arg == "--work-dir":
            i += 1
            if i >= len(sys.argv):
                print("--work-dir 需要参数", file=sys.stderr)
                return 1
            engine.work_dir = Path(sys.argv[i]).resolve()
            print(f"工作目录: {engine.work_dir}")
            i += 1
        elif arg == "--select-file":
            i += 1
            if i >= len(sys.argv):
                print("--select-file 需要参数", file=sys.stderr)
                return 1
            abs_path = str(Path(sys.argv[i]).resolve())
            engine.add_file(abs_path)
            print(f"已添加文件: {abs_path}")
            i += 1
        elif arg == "--add-text":
            i += 1
            if i >= len(sys.argv):
                print("--add-text 需要参数", file=sys.stderr)
                return 1
            text = sys.argv[i]
            engine.add_text(text)
            preview = text[:40] + ('...' if len(text) > 40 else '')
            print(f"已添加文字: {preview}")
            i += 1
        elif arg == "--move":
            i += 1
            if i + 1 >= len(sys.argv):
                print("--move 需要两个参数", file=sys.stderr)
                return 1
            from_idx = int(sys.argv[i])
            to_idx = int(sys.argv[i + 1])
            engine.move_item(from_idx, to_idx)
            print(f"已将 [{from_idx}] 移动到 [{to_idx}]")
            i += 2
        elif arg == "--remove":
            i += 1
            if i >= len(sys.argv):
                print("--remove 需要参数", file=sys.stderr)
                return 1
            idx = int(sys.argv[i])
            engine.remove_item(idx)
            print(f"已删除索引 [{idx}]")
            i += 1
        elif arg == "--clear":
            engine.clear()
            print("已清空编排列表")
            i += 1
        elif arg == "--list-items":
            items = engine.list_items()
            if not items:
                print("编排列表为空")
            else:
                print(f"\n编排列表 ({len(items)} 项):")
                print("-" * 50)
                for idx, typ, desc in items:
                    print(f"  [{idx}] [{typ}] {desc}")
            print()
            i += 1
        elif arg == "--export":
            i += 1
            if i >= len(sys.argv):
                print("--export 需要参数", file=sys.stderr)
                return 1
            try:
                engine.export(sys.argv[i])
                print(f"已导出到: {sys.argv[i]}")
            except Exception as e:
                print(f"导出失败: {e}", file=sys.stderr)
                return 1
            i += 1
        elif arg == "--absolute":
            engine.use_absolute = True
            print("路径模式: 绝对路径")
            i += 1
        elif arg == "--header":
            engine.show_header = True
            print("头部信息: 已启用")
            i += 1
        elif arg == "--load":
            i += 1
            if i >= len(sys.argv):
                print("--load 需要参数", file=sys.stderr)
                return 1
            try:
                engine.load(sys.argv[i])
                print(f"已加载项目: {sys.argv[i]}")
            except Exception as e:
                print(f"加载项目失败: {e}", file=sys.stderr)
                return 1
            i += 1
        elif arg == "--save":
            i += 1
            if i >= len(sys.argv):
                print("--save 需要参数", file=sys.stderr)
                return 1
            try:
                engine.save(sys.argv[i])
                print(f"项目已保存: {sys.argv[i]}")
            except Exception as e:
                print(f"保存项目失败: {e}", file=sys.stderr)
                return 1
            i += 1
        else:
            print(f"未知选项: {arg}", file=sys.stderr)
            print(f"使用 --help 查看帮助", file=sys.stderr)
            return 1

    if show_help:
        print("用法: filecollector [选项...]")
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
        print("  --help, -h                 显示帮助信息")
        return 0

    return 0
