"""tkinterdnd2 兼容性补丁（可审查、可重复、带版本检查与验证）。

问题：tkinterdnd2-universal==1.7.3 仍写 `import Tkinter`（Py2 名）并
`from tkinter import tix`，而 Python 3.13 已移除 tix 模块 -> 3.13 下
`import tkinterdnd2.TkinterDnD` 直接 ImportError，导致 Video2Mp4 失去拖拽
（mov2mp4.py 用 try/except ImportError 退化为 HAS_DND=False，GUI 仍可启动但
无拖拽）。

修复：本应用只用 TkinterDnD.Tk（不用 TixTk）。补丁让 tix 导入容错，且 tix
不可用时 TixTk 退化为占位类（保持向后兼容）。补丁字节与仓库
tools/patches/tkinterdnd2/TkinterDnD.py 完全一致，便于审查。

用法：用目标 venv 的 python 运行本脚本（sys.prefix 决定补哪个 site-packages）。
  python tools/patch_tkinterdnd2.py
"""
from __future__ import annotations
import importlib.metadata as md
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATCH_SRC = REPO / "tools" / "patches" / "tkinterdnd2" / "TkinterDnD.py"
EXPECTED_DIST = "tkinterdnd2-universal"
EXPECTED_VERSION = "1.7.3"


def _dist_version() -> str | None:
    for name in (EXPECTED_DIST, "tkinterdnd2"):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            continue
    return None


def main() -> int:
    if not PATCH_SRC.exists():
        print(f"[patch] error: patch source missing {PATCH_SRC}")
        return 2

    ver = _dist_version()
    print(f"[patch] tkinterdnd2 dist version: {ver}")
    if ver is None:
        print("[patch] error: tkinterdnd2 not installed (pip install -r requirements.txt first)")
        return 2
    if ver != EXPECTED_VERSION:
        print(f"[patch] warn: version {ver} != expected {EXPECTED_VERSION}; "
              f"patch may not apply cleanly, aborting to avoid breakage.")
        return 2

    site = Path(sys.prefix) / "Lib" / "site-packages" / "tkinterdnd2" / "TkinterDnD.py"
    if not site.exists():
        print(f"[patch] error: installed file not found {site}")
        return 2

    current = site.read_bytes()
    desired = PATCH_SRC.read_bytes()
    if current == desired:
        print("[patch] already patched (bytes identical), no rewrite needed.")
    else:
        backup = site.with_suffix(".py.orig-bak")
        if not backup.exists():
            shutil.copy2(site, backup)
            print(f"[patch] backed up original: {backup}")
        shutil.copy2(PATCH_SRC, site)
        print(f"[patch] wrote patch to {site}")

    # 验证：用当前 python 重新导入 tkinterdnd2.TkinterDnD，确认 3.13 下可加载
    proc = subprocess.run(
        [sys.executable, "-c",
         "import tkinterdnd2, tkinterdnd2.TkinterDnD as T; "
         "assert hasattr(T, 'Tk'), 'missing Tk'; "
         "assert hasattr(T, 'TixTk'), 'missing TixTk'; "
         "print('IMPORT_OK', T.__name__)"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("[patch] verify FAILED: import tkinterdnd2.TkinterDnD raised:")
        print(proc.stderr)
        return 1
    print(f"[patch] verify OK: {proc.stdout.strip()}")

    # 进一步：3.13（tix 已移除）下确认 TixTk 占位路径不会在 import 阶段崩
    if sys.version_info >= (3, 13):
        chk = subprocess.run(
            [sys.executable, "-c",
             "import tkinterdnd2.TkinterDnD as T; "
             "print('TIX_NONE' if T.tix is None else 'TIX_PRESENT')"],
            capture_output=True, text=True,
        )
        print(f"[patch] tix state: {chk.stdout.strip() or chk.stderr.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
