# -*- mode: python ; coding: utf-8 -*-
# Video2Mp4.spec - PyInstaller spec
#
# 打包时需要：
#   - tkinterdnd2 的 tkdnd 二进制资源（Windows 是 tkdnd2.9.2/）
#   - clam 主题需要的额外 tcl/tk 文件
#
# 单独 EXE 包含 tkinterdnd2 的运行时；用户机器上仍需 ffmpeg / ffprobe 在 PATH。
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# tkinterdnd2 的数据文件（tkdnd 运行时二进制 + tcl 文件）
datas = []
hiddenimports = []

try:
    import tkinterdnd2
    tkd2_dir = Path(tkinterdnd2.__file__).parent
    # 把整个 tkinterdnd2 包下非 .py 文件都打包
    for f in tkd2_dir.rglob("*"):
        if f.is_file() and not f.suffix == ".py":
            rel = f.relative_to(tkd2_dir.parent)
            datas.append((str(f), str(rel.parent)))
    hiddenimports += ["tkinterdnd2"]
    print(f"[Video2Mp4.spec] tkinterdnd2 资源：{len([d for d in datas if 'tkinterdnd2' in d[0]])} 项")
except ImportError:
    print("[Video2Mp4.spec] WARNING: tkinterdnd2 未安装；打包后无拖拽")

# 隐藏导入（PyInstaller 有时漏掉）
hiddenimports += [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
]

a = Analysis(
    ['mov2mp4.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Video2Mp4',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # GUI 不弹 console
    manifest='assets/Video2Mp4.manifest',   # round2 #1: DPI PerMonitorV2
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
