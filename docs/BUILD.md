# FileCollector 打包说明（flet build · Linux）

本文档说明如何使用 `flet build` 把 FileCollector 打包成 Linux 桌面应用，以及本次适配过程中踩过的坑与修复方式。

> 仅适用 Linux 桌面打包。其它平台（macOS / Windows / Web / Android / iOS）的命令与依赖请参考 [flet 官方文档](https://flet.dev/docs/publish)。

## 1. 环境前置

`flet build linux` 会在本机调用 Flutter + Clang 完成链接。当前系统（Ubuntu 26.04 + clang-21）需要先补齐工具链：

```bash
# 必需：lld-21，Flutter Linux 构建要求 /usr/lib/llvm-21/bin/ld.lld
sudo apt install -y lld-21
```

> 不装 `lld-21` 时构建会在「Building Linux application」阶段失败：
> `Failed to find any of [ld.lld, ld] in LocalDirectory: '/usr/lib/llvm-21/bin'`。

其它常规依赖（通常已自带）：

- `clang` / `cmake` / `ninja-build` / `pkg-config` / `libgtk-3-dev`

## 2. 项目入口约定

`flet build` 默认在项目根目录寻找 `main.py`，**不会**读取 `flet.yaml` 的 `app_path` 去定位 `src/` 下的入口。本项目使用 `src/` 布局，因此需要新增根目录入口 [main.py](../main.py)：

```python
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import flet as ft  # noqa: E402
from filecollector.gui_flet import main as flet_main  # noqa: E402

ft.app(target=flet_main)
```

> 如果未来把入口上移到根目录，可删除该文件并让 flet 直接使用根目录的 `main.py`。

## 3. 执行打包

```bash
cd /home/sam/Desktop/filecollector

# 必须带上 CFLAGS / CXXFLAGS，否则会因 pyconfig.h 宏重定义而失败
CFLAGS="-Wno-error=macro-redefined" \
CXXFLAGS="-Wno-error=macro-redefined -Wno-implicit-fallthrough" \
flet build linux -v
```

### 为什么需要 `-Wno-error=macro-redefined`

Python 3.12 的 `pyconfig.h` 会 `#define _POSIX_C_SOURCE 200809L` 和 `#define _XOPEN_SOURCE 700`，而 glib / GTK 头文件已经先定义过同名宏。clang-21 起 `-Wmacro-redefined` 升级为 `-Werror`，导致构建失败。上面这条 flag 把它降级回 warning，构建即可通过。

## 4. 产物位置

构建完成后，产物位于 `build/linux/` 目录：

```
build/linux/
├── filecollector          # 24KB 的 ELF 启动器
├── data/                  # 242MB  Flutter 资源（字体、图标、AOT 字节码）
├── lib/                   # 88MB   Flutter / Python / 插件 .so
├── python3.12/            # 13MB   Python 标准库
└── site-packages/         # 31MB   第三方包：flet / chardet / markdown-it-py / pygments / keyring
```

整体约 373MB。直接运行：

```bash
./build/linux/filecollector
```

## 5. 二次封装为 AppImage / deb / rpm

`flet build linux` 暂不直接生成 AppImage，可把 `build/linux/` 目录作为输入，用 [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy) 进一步打包：

```bash
# 示例：生成 AppImage
wget https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
wget https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage
chmod +x linuxdeploy*.AppImage

./linuxdeploy-x86_64.AppImage \
    --appdir build/linux \
    --executable build/linux/filecollector \
    --desktop-file <(cat <<EOF
[Desktop Entry]
Type=Application
Name=FileCollector
Exec=filecollector %F
Icon=filecollector
Categories=Utility;
EOF
) \
    --icon icons/filecollector.png \
    --output appimage
```

## 6. 常见问题速查

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| `main.py not found in the root of Flet app directory` | 项目用 `src/` 布局，根目录缺 `main.py` | 新增 [main.py](../main.py) 桥接 `filecollector.gui_flet.main` |
| `Failed to find any of [ld.lld, ld] in LocalDirectory: '/usr/lib/llvm-21/bin'` | 缺 LLVM 链接器 | `sudo apt install lld-21` |
| `error: '_POSIX_C_SOURCE' macro redefined [-Werror,-Wmacro-redefined]` | clang-21 + Python 3.12 头冲突 | 设置 `CFLAGS` / `CXXFLAGS`（见第 3 节） |
| `flutter doctor` 报 Android toolchain / Network resources 异常 | 与 Linux 桌面打包无关 | 可忽略，不影响本次构建 |
