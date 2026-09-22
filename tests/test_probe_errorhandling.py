"""
test_probe_errorhandling.py — probe_streams 错误处理与批次行为（证据分类清晰）

分类：
  A. 真实子进程工具定位失败（集成）：当前进程 PATH 不含 ffprobe → 抛 DependencyError 且提示可操作。
     这模拟"普通桌面找不到依赖"的真实情况，不是 monkeypatch。
  B. 故障注入（monkeypatch）：get_ffprobe 抛 DependencyError → 验证异常被传播。
     明确标注为故障注入，不与 A 混淆。
  C. 非法 JSON：用真实（但假的）ffprobe 可执行文件输出乱码 → 应抛"非法 JSON"明确错误。
  D. 非法 UTF-8：注入返回非法 UTF-8 字节 → 应抛"解码失败"明确错误（非 NoneType/丢字节冒充成功）。
  E. 超时：注入 subprocess.run 抛 TimeoutExpired → 应传播。
  F. 批次坏文件居中部：真实文件列表中坏文件在中间 → 坏明确失败、好继续、状态不串位。

运行：python tests/test_probe_errorhandling.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
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


def _dummy_existing_file(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    p = base / "dummy.mkv"
    p.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00" + b"x" * 64)
    return p


def case_real_missing_dep(rep: Report, base: Path):
    """A. 真实集成：进程 PATH 无 ffprobe → DependencyError 且提示可操作。"""
    saved = os.environ.get("PATH", "")
    newp = ";".join(d for d in saved.split(";")
                    if "WinGet" not in d and "ffmpeg" not in d.lower())
    os.environ["PATH"] = newp
    core._FFMPEG_PATH = None
    core._FFPROBE_PATH = None
    dummy = _dummy_existing_file(base / "real_missing")
    try:
        raised = None
        try:
            core.probe_streams(dummy)
        except core.DependencyError as e:
            raised = e
        except Exception as e:  # pragma: no cover
            raised = e
        ok = isinstance(raised, core.DependencyError) and (
            "PATH" in str(raised) or "ffmpeg" in str(raised).lower())
        rep.case("A 真实缺依赖→DependencyError 且提示 PATH/安装",
                 ok, str(raised)[:120] if raised else "未抛异常")
    finally:
        os.environ["PATH"] = saved
        core._FFMPEG_PATH = None
        core._FFPROBE_PATH = None


def case_monkeypatch_missing_dep(rep: Report, base: Path):
    """B. 故障注入：monkeypatch get_ffprobe → 仍抛 DependencyError（与 A 区分）。"""
    dummy = _dummy_existing_file(base / "mp_missing")
    orig = core.get_ffprobe

    def _boom():
        raise core.DependencyError("mock: 找不到 ffprobe")

    core.get_ffprobe = _boom
    try:
        raised = None
        try:
            core.probe_streams(dummy)
        except core.DependencyError:
            raised = True
        except Exception:  # pragma: no cover
            raised = False
        rep.case("[故障注入] B monkeypatch get_ffprobe→仍抛 DependencyError",
                 raised is True)
    finally:
        core.get_ffprobe = orig


def case_illegal_json(rep: Report, base: Path):
    """C. 真实（假）ffprobe：输出非 JSON → 明确'非法 JSON'错误。"""
    fake_dir = base / "fakejson"
    fake_dir.mkdir(parents=True, exist_ok=True)
    fake = fake_dir / "ffprobe.cmd"
    fake.write_text("@echo off\r\necho this is not json\r\nexit /b 0\r\n", encoding="utf-8")
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = str(fake_dir) + os.pathsep + saved
    core._FFPROBE_PATH = None
    dummy = _dummy_existing_file(base / "illegal_json")
    try:
        raised = None
        try:
            core.probe_streams(dummy)
        except Exception as e:
            raised = e
        ok = raised is not None and "JSON" in str(raised)
        rep.case("C 非法 JSON→明确'非法 JSON'错误（真实假 ffprobe）",
                 ok, str(raised)[:120] if raised else "未抛异常")
    finally:
        os.environ["PATH"] = saved
        core._FFPROBE_PATH = None


def case_illegal_utf8(rep: Report, base: Path):
    """D. 故障注入：返回非法 UTF-8 字节 → 明确'解码失败'（非 NoneType/丢字节冒充成功）。"""
    dummy = _dummy_existing_file(base / "illegal_utf8")
    real_run = subprocess.run

    def _fake(*a, **k):
        if a and "ffprobe" in str(a[0]):
            return subprocess.CompletedProcess(a[0], 0,
                                               stdout=b"\xff\xfe\x80not_utf8",
                                               stderr=b"")
        return real_run(*a, **k)

    with mock.patch.object(subprocess, "run", _fake):
        raised = None
        try:
            core.probe_streams(dummy)
        except Exception as e:
            raised = e
    msg = str(raised).lower()
    ok = raised is not None and ("utf" in msg or "decode" in msg or "解码" in str(raised))
    rep.case("[故障注入] D 非法 UTF-8→明确解码错误（非 NoneType/丢字节）",
             ok, str(raised)[:120] if raised else "未抛异常")


def case_timeout(rep: Report, base: Path):
    """E. 故障注入：超时 → TimeoutExpired 传播。"""
    dummy = _dummy_existing_file(base / "timeout")
    real_run = subprocess.run

    def _fake(*a, **k):
        if a and "ffprobe" in str(a[0]):
            raise subprocess.TimeoutExpired(a[0], k.get("timeout", 30))
        return real_run(*a, **k)

    with mock.patch.object(subprocess, "run", _fake):
        raised = None
        try:
            core.probe_streams(dummy)
        except subprocess.TimeoutExpired as e:
            raised = e
        except Exception as e:  # pragma: no cover
            raised = e
    rep.case("[故障注入] E 超时→TimeoutExpired 传播",
             isinstance(raised, subprocess.TimeoutExpired), str(raised)[:80])


def case_batch_middle_bad(rep: Report, base: Path):
    """F. 批次：坏文件在中间 → 坏明确失败、好继续、状态不串位。"""
    os.environ["PATH"] = FF_BIN + os.pathsep + os.environ.get("PATH", "")
    core._FFMPEG_PATH = None
    core._FFPROBE_PATH = None

    files = [
        base / "b1" / "a.mkv",
        base / "b2" / "bad.mkv",   # 中间坏文件
        base / "b3" / "c.mkv",
    ]
    for f in (files[0], files[2]):
        _make_h264(f)
    files[1].parent.mkdir(parents=True, exist_ok=True)
    files[1].write_bytes(b"garbage" * 40)

    statuses = []
    for f in files:
        try:
            core.probe_streams(f)
            statuses.append(("ok", f.name))
        except Exception as e:
            statuses.append(("fail", f.name))
    good = [s for s in statuses if s[0] == "ok"]
    bad = [s for s in statuses if s[0] == "fail"]
    rep.case("F 批次：两侧好文件成功", len(good) == 2, str(good))
    rep.case("F 批次：中间坏文件明确失败", len(bad) == 1 and bad[0][1] == "bad.mkv",
             str(bad))


def _make_h264(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = [core.get_ffmpeg(), "-hide_banner", "-y",
           "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", str(p.resolve())]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       timeout=60, creationflags=core._NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"造样本失败: {r.stderr[-200:]}")


def main():
    print("Video2Mp4 — probe_streams 错误处理/批次回归")
    base = Path(tempfile.gettempdir()) / "v2mp4_err_tests"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    rep = Report()
    case_real_missing_dep(rep, base)
    case_monkeypatch_missing_dep(rep, base)
    case_illegal_json(rep, base)
    case_illegal_utf8(rep, base)
    case_timeout(rep, base)
    case_batch_middle_bad(rep, base)

    ok = rep.summary()
    out = ROOT / "tests" / "probe_errorhandling_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"passed": ok,
                   "results": [{"name": n, "ok": o, "detail": d} for n, o, d in rep.results]},
                  f, ensure_ascii=False, indent=2)
    print(f"报告: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
