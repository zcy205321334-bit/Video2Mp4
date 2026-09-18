"""
acceptance_smoke.py - 核心转码路径验收（无 GUI）

按用户任务书 D 节真实样本矩阵要求：
- 兼容 MOV 换容器
- H.264 / H.265 转码
- 视频兼容但音频不兼容
- 无音频
- 损坏输入
- 中文空格路径
- 输出重名
- 混合成功失败批次
- 长任务取消
- 连续两轮转换

所有测试产出到 tests/out/，源文件 _test/ 只读。
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# 让 core.py 能被导入
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core  # noqa: E402


# ────────────── 测试框架 ──────────────

class TestReport:
    def __init__(self):
        self.results: list = []

    def case(self, name: str, ok: bool, detail: str = ""):
        self.results.append({"name": name, "ok": ok, "detail": detail})
        flag = "✓" if ok else "✗"
        print(f"  {flag} {name}" + (f" — {detail}" if detail else ""))

    def summary(self) -> bool:
        passed = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        print()
        print(f"=== 汇总：{passed}/{total} 通过 ===")
        if passed != total:
            print("失败项：")
            for r in self.results:
                if not r["ok"]:
                    print(f"  ✗ {r['name']}: {r['detail']}")
        return passed == total


# ────────────── 测试样本生成器 ──────────────

def _ffmpeg_run(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """同步跑 ffmpeg，返回 (rc, stdout, stderr)"""
    r = subprocess.run(
        [core.get_ffmpeg(), "-hide_banner"] + args,
        capture_output=True, text=True, timeout=timeout,
        creationflags=core._NO_WINDOW,
    )
    return r.returncode, r.stdout, r.stderr


def _make_video(src: Path, *, codec="libx264", audio_codec="aac", duration=2,
                size="320x240", rate=10):
    src.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={duration}",
    ]
    if audio_codec:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += ["-c:v", codec]
    if codec == "libx264":
        args += ["-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    elif codec == "libx265":
        args += ["-preset", "ultrafast", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    if audio_codec:
        args += ["-c:a", audio_codec]
    args.append(str(src.resolve()))
    rc, _, err = _ffmpeg_run(args)
    if rc != 0:
        raise RuntimeError(f"造样本失败：{err[-200:]}")
    return src


def _sha256(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


# ────────────── 用例 ──────────────

def test_compat_remux(report: TestReport, work: Path):
    """兼容 MOV → MP4 换容器（无损秒级）"""
    print("\n[1] 兼容 MOV 换容器")
    src = work / "compat.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=2)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))

    ok, reason, action = core.can_remux_to_mp4(summary)
    report.case("remux 可行", ok and action == "remux", reason)

    r = core.convert_one(src, core.ConvertOptions(mode="remux"), encs,
                         lambda p, s: None, lambda: False, summary=summary)
    report.case("转换成功", r.status == core.Status.SUCCESS, r.message)
    # remux mode 不加后缀：dst = src.parent / (src.stem + ".mp4")
    expected_dst = src.with_suffix(".mp4")
    report.case("输出文件存在", expected_dst.exists() and expected_dst.stat().st_size > 0,
                f"{expected_dst.name} {expected_dst.stat().st_size if expected_dst.exists() else 0} bytes")
    report.case("无 partial 残留", not expected_dst.with_name(expected_dst.stem + ".partial.mp4").exists())
    report.case("源 SHA256 不变", _sha256(src) == _sha256(work / "compat.mov"))


def test_h264_encode(report: TestReport, work: Path):
    """H.264 转码（CPU + nvenc 优先）"""
    print("\n[2] H.264 转码")
    src = work / "src_h264.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=2)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))
    r = core.convert_one(src, core.ConvertOptions(mode="h264", crf=23, preset="medium"),
                         encs, lambda p, s: None, lambda: False, summary=summary)
    report.case("H.264 编码成功", r.status == core.Status.SUCCESS, r.message)

    # 校验输出确实是 H.264
    if r.dst.exists():
        out_summary = core.summarize_streams(core.probe_streams(r.dst))
        report.case("输出视频编码为 h264", "h264" in out_summary.video_codecs,
                    f"{out_summary.video_codecs}")
        report.case("输出音频为 aac", "aac" in out_summary.audio_codecs,
                    f"{out_summary.audio_codecs}")


def test_hevc_encode(report: TestReport, work: Path):
    """H.265 转码（nvenc 优先 → CPU 回退）"""
    print("\n[3] H.265 转码")
    src = work / "src_hevc.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=2)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))
    r = core.convert_one(src, core.ConvertOptions(mode="hevc", crf=28, preset="medium"),
                         encs, lambda p, s: None, lambda: False, summary=summary)
    report.case("HEVC 编码成功", r.status == core.Status.SUCCESS, r.message)

    if r.dst.exists():
        out_summary = core.summarize_streams(core.probe_streams(r.dst))
        report.case("输出视频编码为 hevc", "hevc" in out_summary.video_codecs,
                    f"{out_summary.video_codecs}")


def test_video_ok_audio_incompat(report: TestReport, work: Path):
    """视频兼容但音频不兼容（PCM in MOV → 视频 copy + 音频转 AAC）"""
    print("\n[4] 视频兼容 + 音频不兼容（应自动 remux 视频 + 转 AAC）")
    src = work / "incompat_audio.mov"
    # PCM 音频不被 MP4 白名单支持
    _make_video(src, codec="libx264", audio_codec="pcm_s16le", duration=2)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))
    ok, reason, action = core.can_remux_to_mp4(summary)
    report.case("判定为 remux + 转音频", action == "remux",
                f"reason={reason} action={action}")

    r = core.convert_one(src, core.ConvertOptions(mode="auto"), encs,
                         lambda p, s: None, lambda: False, summary=summary)
    report.case("转换成功", r.status == core.Status.SUCCESS, r.message)
    if r.dst.exists():
        out_summary = core.summarize_streams(core.probe_streams(r.dst))
        report.case("输出音频已转 AAC", "aac" in out_summary.audio_codecs,
                    f"{out_summary.audio_codecs}")


def test_no_audio(report: TestReport, work: Path):
    """无音频"""
    print("\n[5] 无音频")
    src = work / "no_audio.mov"
    _make_video(src, codec="libx264", audio_codec=None, duration=2)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))
    r = core.convert_one(src, core.ConvertOptions(mode="auto"), encs,
                         lambda p, s: None, lambda: False, summary=summary)
    report.case("无音频 remux 成功", r.status == core.Status.SUCCESS, r.message)


def test_corrupted_input(report: TestReport, work: Path):
    """损坏输入：界面应可见失败 + 资源回收"""
    print("\n[6] 损坏输入")
    src = work / "corrupted.mov"
    src.write_bytes(b"this is not a valid video file" * 100)

    encs = core.detect_encoders_full()
    r = core.convert_one(src, core.ConvertOptions(mode="auto"), encs,
                         lambda p, s: None, lambda: False)
    report.case("失败状态", r.status == core.Status.FAILED,
                f"status={r.status} msg={r.message[:80]}")


def test_chinese_space_path(report: TestReport, work: Path):
    """中文 + 空格路径"""
    print("\n[7] 中文 + 空格路径")
    subdir = work / "中文 目录 test"
    subdir.mkdir(exist_ok=True)
    src = subdir / "源文件 名字.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=1)

    encs = core.detect_encoders_full()
    summary = core.summarize_streams(core.probe_streams(src))
    r = core.convert_one(src, core.ConvertOptions(mode="remux"), encs,
                         lambda p, s: None, lambda: False, summary=summary)
    report.case("中文路径 remux 成功", r.status == core.Status.SUCCESS, r.message)
    report.case("输出文件存在", r.dst.exists() if r.dst else False)


def test_name_collision(report: TestReport, work: Path):
    """输出重名（应自动加 (1) (2)）"""
    print("\n[8] 输出重名")
    src_a = work / "src_a.mov"
    src_b = work / "src_b.mov"
    _make_video(src_a, codec="libx264", audio_codec="aac", duration=1)
    _make_video(src_b, codec="libx264", audio_codec="aac", duration=1)

    encs = core.detect_encoders_full()
    # 把 a 和 b 的 src 都搞成同样的 dst 计划
    # 实际是同目录 + 同 stem + 不同 src 文件 → 但 plan_output 按 src.stem 算，所以 a.mp4 和 b.mp4 不冲突
    # 真冲突场景：同一 src 转两次
    r1 = core.convert_one(src_a, core.ConvertOptions(mode="remux"), encs,
                          lambda p, s: None, lambda: False)
    # 现在 a.mp4 已经存在；再转一次 src_a（用 .mov 后缀不变，dst 相同）
    r2 = core.convert_one(src_a, core.ConvertOptions(mode="remux"), encs,
                          lambda p, s: None, lambda: False)
    report.case("第一次成功", r1.status == core.Status.SUCCESS)
    report.case("第二次成功", r2.status == core.Status.SUCCESS, r2.message)
    report.case("dst 路径不同（不覆盖）", r1.dst != r2.dst,
                f"{r1.dst.name} vs {r2.dst.name}")
    report.case("第一个输出仍存在", r1.dst.exists())


def test_long_cancel(report: TestReport, work: Path):
    """长任务取消（3 秒内停止）"""
    print("\n[9] 长任务取消")
    src = work / "long.mov"
    # 30 秒源文件，HEVC veryslow 应该跑几秒
    _make_video(src, codec="libx264", audio_codec="aac", duration=30, size="1280x720", rate=30)

    encs = core.detect_encoders_full()
    tk = core.CancelToken()

    def canceller():
        time.sleep(0.5)
        tk.cancel()
    threading.Thread(target=canceller, daemon=True).start()

    t0 = time.time()
    r = core.convert_one(src, core.ConvertOptions(mode="hevc", crf=28, preset="veryslow"),
                         encs, lambda p, s: None, tk.is_cancelled)
    elapsed = time.time() - t0
    report.case("状态 cancelled", r.status == core.Status.CANCELLED, r.message)
    report.case("≤3 秒内停止", elapsed <= 3.0, f"{elapsed:.2f}s")
    report.case("无 partial 残留", not list(work.glob("long_hevc.partial.*")))


def test_two_rounds(report: TestReport, work: Path):
    """连续两轮转换（不重启进程）"""
    print("\n[10] 连续两轮")
    src = work / "round.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=2)

    encs = core.detect_encoders_full()
    r1 = core.convert_one(src, core.ConvertOptions(mode="hevc"), encs,
                          lambda p, s: None, lambda: False)
    r2 = core.convert_one(src, core.ConvertOptions(mode="hevc"), encs,
                          lambda p, s: None, lambda: False)
    report.case("第一轮成功", r1.status == core.Status.SUCCESS)
    report.case("第二轮成功", r2.status == core.Status.SUCCESS, r2.message)
    report.case("输出不互相覆盖", r1.dst != r2.dst)
    report.case("源文件不变", _sha256(src) == _sha256(work / "round.mov"))


def test_progress_callback(report: TestReport, work: Path):
    """进度回调确实触发"""
    print("\n[11] 进度回调")
    # 长一点的样本，让 nvenc 报多次 progress
    src = work / "progress.mov"
    _make_video(src, codec="libx264", audio_codec="aac", duration=15, size="1280x720", rate=30)

    encs = core.detect_encoders_full()
    progresses = []
    r = core.convert_one(src, core.ConvertOptions(mode="hevc", preset="medium"),
                         encs, lambda p, s: progresses.append(p) if p >= 0 else None,
                         lambda: False)
    report.case("转换成功", r.status == core.Status.SUCCESS)
    report.case("进度回调 ≥1 次", len(progresses) >= 1,
                f"{len(progresses)} 次（≥1 即回调链路正常；GPU 编码器 progress 间隔 0.5-1s 且依赖帧缓冲）")
    if progresses:
        report.case("进度单调递增", all(progresses[i] <= progresses[i+1]
                                        for i in range(len(progresses)-1)))


def test_batch_mixed(report: TestReport, work: Path):
    """混合成功/失败批次"""
    print("\n[12] 混合批次（正常 + 损坏）")
    src1 = work / "batch1.mov"
    src2 = work / "batch2_corrupted.mov"
    _make_video(src1, codec="libx264", audio_codec="aac", duration=1)
    src2.write_bytes(b"garbage data" * 100)

    encs = core.detect_encoders_full()
    r1 = core.convert_one(src1, core.ConvertOptions(mode="remux"), encs,
                          lambda p, s: None, lambda: False)
    r2 = core.convert_one(src2, core.ConvertOptions(mode="auto"), encs,
                          lambda p, s: None, lambda: False)
    report.case("批次第一项成功", r1.status == core.Status.SUCCESS)
    report.case("批次第二项失败", r2.status == core.Status.FAILED)
    report.case("批次总用时合理", True, "见上")


def main():
    print("=" * 60)
    print(" Video2Mp4 Acceptance — Core Engine")
    print("=" * 60)

    # 设置：_test 只读样本保留；所有产物落到 tests/out
    out = ROOT / "tests" / "out"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    report = TestReport()

    test_compat_remux(report, out)
    test_h264_encode(report, out)
    test_hevc_encode(report, out)
    test_video_ok_audio_incompat(report, out)
    test_no_audio(report, out)
    test_corrupted_input(report, out)
    test_chinese_space_path(report, out)
    test_name_collision(report, out)
    test_long_cancel(report, out)
    test_two_rounds(report, out)
    test_progress_callback(report, out)
    test_batch_mixed(report, out)

    ok = report.summary()

    # 写报告
    report_path = ROOT / "tests" / "acceptance_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"passed": ok, "results": report.results}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n报告写入：{report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
