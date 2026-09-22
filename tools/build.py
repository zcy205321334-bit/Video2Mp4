"""Video2Mp4 可重复构建流程（全新 venv，不依赖任何手工修改）。

步骤：
  1. 在 build-venv/ 创建全新虚拟环境（若存在则复用，但补丁/安装幂等）。
  2. 安装 requirements.txt（运行时）+ requirements-dev.txt（构建/自动化）。
  3. 应用 tkinterdnd2 兼容补丁（tools/patch_tkinterdnd2.py：版本检查 + 验证）。
  4. 用 Video2Mp4.spec 构建 dist/Video2Mp4.exe（默认代码页，不设 UTF-8 环境变量）。
  5. 计算并记录 dist/Video2Mp4.exe 的 SHA256。

用法：
  python tools/build.py
可选参数：
  --venv DIR   指定 venv 目录（默认 <repo>/build-venv）
  --no-install 仅构建，不替换安装目录的 EXE
"""
from __future__ import annotations
import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV_DEFAULT = REPO / "build-venv"
INSTALL_EXE = Path(r"C:\Users\Administrator\AppData\Local\Programs\Video2Mp4\Video2Mp4.exe")


def _py(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin") / "python.exe"


def _run(cmd, cwd=None, check=True):
    print("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venv", default=str(VENV_DEFAULT))
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args()

    venv = Path(args.venv)
    py = _py(venv)

    # 1. 全新 venv
    if not py.exists():
        print(f"[build] 创建全新 venv：{venv}")
        _run([sys.executable, "-m", "venv", str(venv)])
    else:
        print(f"[build] 复用 venv：{venv}")

    # 2. 安装依赖
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(py), "-m", "pip", "install", "-r", str(REPO / "requirements.txt")])
    _run([str(py), "-m", "pip", "install", "-r", str(REPO / "requirements-dev.txt")])

    # 3. 应用并验证补丁（用 venv 的 python，补的是 venv 的 site-packages）
    rc = subprocess.run([str(py), str(REPO / "tools" / "patch_tkinterdnd2.py")]).returncode
    if rc != 0:
        print(f"[build] 补丁失败，退出码 {rc}")
        return rc

    # 4. 构建（默认代码页；cwd=repo 这样 spec 内的相对路径/资源可解析）
    dist_exe = REPO / "dist" / "Video2Mp4.exe"
    if dist_exe.exists():
        dist_exe.unlink()
    _run([str(py), "-m", "PyInstaller", "Video2Mp4.spec", "--noconfirm", "--clean"],
         cwd=str(REPO))

    if not dist_exe.exists():
        print(f"[build] 错误：构建产物缺失 {dist_exe}")
        return 1

    new_hash = sha256(dist_exe)
    print(f"[build] 构建成功：{dist_exe}")
    print(f"[build] NEW_SHA256={new_hash}")

    # 5. （可选）替换安装目录
    if not args.no_install:
        if INSTALL_EXE.exists():
            bak = INSTALL_EXE.with_name(f"Video2Mp4.exe.bak-{__import__('datetime').date.today():%Y%m%d}")
            if not bak.exists():
                shutil.copy2(INSTALL_EXE, bak)
                print(f"[build] 已备份旧安装：{bak} (sha256={sha256(INSTALL_EXE)})")
        INSTALL_EXE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dist_exe, INSTALL_EXE)
        print(f"[build] 已安装到：{INSTALL_EXE} (sha256={new_hash})")
    else:
        print("[build] --no-install：未替换安装目录（仅构建）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
