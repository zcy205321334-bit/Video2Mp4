"""
test_probe_utf8.py — probe_streams 真实 ffprobe 回归（中文/空格/「」路径 + 非 ASCII 元数据）

设计：调用真实 ffprobe（命令级临时把 WinGet 的 ffmpeg bin 加入 PATH，仅用于开发/诊断，
不作为安装证据）。覆盖：
  - ASCII 路径（旧/新均成功，作为健全性基线）
  - 中文 + 空格 路径（ffprobe 在 JSON 回显含中文的文件名 → 老代码 r.stdout=None → 失败）
  - 中文「」路径（同上）
  - 非 ASCII 元数据（emoji + 中文 title，必然产生 GBK 不可解码字节 → 老代码失败；新代码保留 UTF-8）

证明"旧实现失败、修复后成功"：本文件在打补丁前运行会看到中文/「」/元数据用例失败，
打补丁后全部通过。仅 mock subprocess 不算根因验证，这里全部走真实 ffprobe 子进程。

运行：python tests/test_probe_utf8.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 仅 Windows cp936 控制台需要
    pass

import core  # noqa: E402

FF_BIN = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0-full_build\bin"


class Report:
    def __init__(self):
        self.results = []

    def case(self, name, ok, detail=""):
        self.results.append((name, ok, detail))
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {name}" + (f" — {detail}" if detail else ""))

    def summary(self):
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\n=== {passed}/{total} 通过 ===")
        for name, ok, detail in self.results:
            if not ok:
                print(f"  FAIL {name}: {detail}")
        return passed == total


def _make_sample(path: Path, *, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        core.get_ffmpeg(), "-hide_banner", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
    ]
    if metadata:
        for k, v in metadata.items():
            cmd += ["-metadata", f"{k}={v}"]
    cmd.append(str(path.resolve()))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       timeout=60, creationflags=core._NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"造样本失败: {r.stderr[-300:]}")
    return path


def case_ascii_path(rep: Report, base: Path):
    p = base / "ascii" / "sample.mkv"
    _make_sample(p)
    try:
        info = core.probe_streams(p)
        rep.case("ASCII 路径探测成功", isinstance(info, dict) and "streams" in info,
                 f"streams={len(info.get('streams', []))}")
    except Exception as e:
        rep.case("ASCII 路径探测成功", False, str(e)[:120])


def case_chinese_space_path(rep: Report, base: Path):
    # ffprobe -show_format 会在 JSON 的 format.filename 回显含中文的路径
    p = base / "中文 目录 test" / "源文件 名字.mkv"
    _make_sample(p)
    try:
        info = core.probe_streams(p)
        rep.case("中文+空格 路径探测成功（文件名进入 JSON）",
                 isinstance(info, dict) and "streams" in info,
                 f"streams={len(info.get('streams', []))}")
    except Exception as e:
        rep.case("中文+空格 路径探测成功（文件名进入 JSON）", False, str(e)[:120])


def case_chinese_brackets_path(rep: Report, base: Path):
    p = base / "「双语」测试" / "片.mkv"
    _make_sample(p)
    try:
        info = core.probe_streams(p)
        rep.case("中文「」路径探测成功", isinstance(info, dict) and "streams" in info,
                 f"streams={len(info.get('streams', []))}")
    except Exception as e:
        rep.case("中文「」路径探测成功", False, str(e)[:120])


def case_nonascii_metadata(rep: Report, base: Path):
    # emoji 的 UTF-8 字节在 GBK 下必然不可解码 → 冻结为"确实复现"的样本
    p = base / "meta" / "sample.mkv"
    _make_sample(p, metadata={"title": "🎬测试标题", "comment": "朋友 双语"})
    try:
        info = core.probe_streams(p)
        tags = info.get("format", {}).get("tags", {}) or {}
        title = tags.get("title", "")
        rep.case("非 ASCII 元数据探测成功", isinstance(info, dict) and "streams" in info)
        rep.case("非 ASCII 元数据保留（UTF-8 未丢字节）",
                 "🎬" in title and "测试标题" in title, f"title={title!r}")
    except Exception as e:
        rep.case("非 ASCII 元数据探测成功", False, str(e)[:120])
        rep.case("非 ASCII 元数据保留（UTF-8 未丢字节）", False, str(e)[:120])


def case_batch_mixed_real(rep: Report, base: Path):
    good = base / "batch" / "good.mkv"
    bad = base / "batch" / "bad.mkv"
    _make_sample(good)
    bad.write_bytes(b"not a video file at all" * 50)

    good_ok = False
    bad_err = None
    try:
        core.probe_streams(good)
        good_ok = True
    except Exception as e:
        good_ok = False
        bad_err = f"好文件竟失败: {e}"
    try:
        core.probe_streams(bad)
        bad_err = "坏文件未被判定失败"
    except Exception as e:
        bad_err = None if bad_err is None else bad_err
        bad_err = str(e) if bad_err is None else bad_err
    rep.case("批次好文件成功", good_ok)
    rep.case("批次坏文件明确失败（状态不串位）", bad_err is not None and good_ok,
             (bad_err or "")[:80])


def main():
    print("Video2Mp4 — probe_streams 真实 ffprobe 回归")
    os.environ["PATH"] = FF_BIN + os.pathsep + os.environ.get("PATH", "")
    core._FFMPEG_PATH = None
    core._FFPROBE_PATH = None
    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        print("ERROR: ffprobe/ffmpeg 不在 PATH，无法跑真实集成用例")
        return 2

    base = Path(tempfile.gettempdir()) / "v2mp4_probe_tests"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    rep = Report()
    case_ascii_path(rep, base)
    case_chinese_space_path(rep, base)
    case_chinese_brackets_path(rep, base)
    case_nonascii_metadata(rep, base)
    case_batch_mixed_real(rep, base)

    ok = rep.summary()
    out = ROOT / "tests" / "probe_utf8_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"passed": ok,
                   "results": [{"name": n, "ok": o, "detail": d} for n, o, d in rep.results]},
                  f, ensure_ascii=False, indent=2)
    print(f"报告: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
