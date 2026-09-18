"""
test_dpi_manifest.py - 验证 EXE 声明 DPI awareness 且源码调 SetProcessDpiAwareness

Bug: 安装版 EXE 默认 DPI Unaware，150%/200% 缩放下窗口按 96 DPI 绘制，被
系统整体拉伸 → 文字发虚。
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 构建产物位置可用环境变量 VIDEO2MP4_EXE 覆盖；默认找 dist/，不写死机器路径
EXE = Path(os.environ.get("VIDEO2MP4_EXE") or (ROOT / "dist" / "Video2Mp4.exe"))


def _has_dpi_aware_string(data: bytes) -> bool:
    needles = [b"PerMonitorV2", b"PerMonitor", b"dpiAware", b"<dpiAwareness"]
    return any(n in data for n in needles)


def test_dpi_aware_helper_exists_in_source():
    """mov2mp4.py 必须调用 SetProcessDpiAwareness，让 dev 跑（python mov2mp4.py）
    也能拿到 DPI 感知，不只是打包 EXE。"""
    src = (ROOT / "mov2mp4.py").read_text(encoding="utf-8")
    assert "SetProcessDpiAwareness" in src or "SetProcessDPIAware" in src, (
        "mov2mp4.py 没调用 SetProcessDpiAwareness —— dev 跑仍 DPI Unaware"
    )
    print("✓ mov2mp4.py 调用 SetProcessDpiAwareness")


def test_installed_exe_has_dpi_manifest():
    """安装 EXE 必须在 manifest 里声明 DPI awareness。"""
    if not EXE.exists():
        print(f"  (跳过：EXE 未构建或未安装 {EXE})")
        return
    data = EXE.read_bytes()
    assert _has_dpi_aware_string(data), (
        "安装 EXE manifest 缺 DPI awareness 标记；高 DPI 显示会拉伸/模糊"
    )
    print(f"✓ {EXE.name} 声明 DPI awareness")


if __name__ == "__main__":
    test_dpi_aware_helper_exists_in_source()
    test_installed_exe_has_dpi_manifest()
