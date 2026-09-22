"""
core.py - Video2Mp4 转码核心
=============================

设计要点（按用户任务书 2026-09-08 整改）：

1. 路径解析：ffmpeg / ffprobe 用绝对路径解析，绝不依赖 cwd；
   缺依赖时抛 DependencyError，UI 层捕获并禁用"开始"按钮。

2. 编码器探测：
   - 用 `-hide_banner -encoders` 静态列举
   - GPU 编码器必须经 1 秒短测确认硬件真可用（NVIDIA / AMD / Intel）
   - 失败明确回退 CPU，并在日志写明原因

3. 转码进程：
   - 用 `-progress pipe:1 -nostats` 输出结构化键值对到 stdout，**不读 stderr**
   - stderr 重定向到 .log 文件（仅记录，不阻塞）
   - 提供 stop() 方法，调用方 3 秒优雅 + 强制 kill

4. 探测：
   - probe_streams 接受路径参数，不忽略
   - can_remux_to_mp4 严格判定视频 + 音频编码
   - 选流：用户明确指定优先项，不静默"全部保留"

5. 命名 / 原子发布：
   - 输出名：先临时 .partial.mp4；ffmpeg 退出 0 + 校验通过 → 原子重命名
   - 取消 / 失败不留下"看似成功"的最终文件
   - 同名冲突自动加 (1) (2) ...
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple


# ─────────────────────────── 依赖 ───────────────────────────


class DependencyError(RuntimeError):
    """ffmpeg / ffprobe 缺失或不可执行"""


def _which_or_raise(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise DependencyError(f"找不到 {name}；请安装 ffmpeg 并加入 PATH（https://www.gyan.dev/ffmpeg/builds/）")
    # Windows 上 which 可能拿到 shim；用绝对路径校验文件存在且可执行
    if not os.path.isfile(p):
        raise DependencyError(f"{name} 解析到不存在的路径：{p}")
    return p


# 全局缓存（启动时定一次）
_FFMPEG_PATH: Optional[str] = None
_FFPROBE_PATH: Optional[str] = None


def get_ffmpeg() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH is None:
        _FFMPEG_PATH = _which_or_raise("ffmpeg")
    return _FFMPEG_PATH


def get_ffprobe() -> str:
    global _FFPROBE_PATH
    if _FFPROBE_PATH is None:
        _FFPROBE_PATH = _which_or_raise("ffprobe")
    return _FFPROBE_PATH


def verify_deps() -> dict:
    """UI 启动时调用，返回 {'ffmpeg': str|None, 'ffprobe': str|None, 'ok': bool}"""
    info = {"ffmpeg": None, "ffprobe": None, "ok": False}
    try:
        info["ffmpeg"] = get_ffmpeg()
    except DependencyError:
        pass
    try:
        info["ffprobe"] = get_ffprobe()
    except DependencyError:
        pass
    info["ok"] = bool(info["ffmpeg"] and info["ffprobe"])
    return info


# ─────────────────────────── 编码器探测 + 短测 ───────────────────────────


@dataclass
class EncoderInfo:
    name: str
    codec: str           # 'hevc' | 'h264'
    kind: str            # 'cpu' | 'nvenc' | 'amf' | 'qsv'
    available: bool
    note: str = ""
    # 短测结果
    hw_works: Optional[bool] = None  # None = 未测；True/False = 测了
    hw_reason: str = ""


def detect_encoders_static() -> dict:
    """静态列举 ffmpeg -encoders 输出。不做短测。"""
    try:
        ffmpeg = get_ffmpeg()
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, creationflags=_NO_WINDOW,
        ).stdout
    except Exception as e:
        return {"hevc": [], "h264": [], "error": str(e)}

    have = set()
    for line in out.splitlines():
        m = re.match(r"\s*\S+\s+(\S+)\s", line)
        if m:
            have.add(m.group(1))

    info = {"hevc": [], "h264": []}
    hevc_candidates = [
        ("libx265",    "hevc", "cpu",   "CPU 软编（最广兼容）"),
        ("hevc_nvenc", "hevc", "nvenc", "NVIDIA GPU"),
        ("hevc_amf",   "hevc", "amf",   "AMD GPU"),
        ("hevc_qsv",   "hevc", "qsv",   "Intel Quick Sync"),
    ]
    for name, codec, kind, note in hevc_candidates:
        if name in have:
            info["hevc"].append(EncoderInfo(name, codec, kind, True, note))
    h264_candidates = [
        ("libx264",    "h264", "cpu",   "CPU 软编"),
        ("h264_nvenc", "h264", "nvenc", "NVIDIA GPU"),
        ("h264_amf",   "h264", "amf",   "AMD GPU"),
    ]
    for name, codec, kind, note in h264_candidates:
        if name in have:
            info["h264"].append(EncoderInfo(name, codec, kind, True, note))
    return info


def _hw_smoke_test(ffmpeg: str, encoder: str, codec: str) -> Tuple[bool, str]:
    """对 GPU 编码器做 1 秒短测：生成 0.5 秒 64x64 测试源，确认能成功编码。
    返回 (ok, reason)。失败时 reason 是给用户看的中文。
    """
    # 1 秒测试源：256x256 32 帧（太小时某些硬件编码器拒收）
    # 硬件编码器要求尺寸对齐到 2 或更大，加 -s 强制 + -pix_fmt yuv420p + 显式 -r
    if codec == "hevc":
        vparams = ["-c:v", encoder, "-tag:v", "hvc1", "-t", "0.5",
                   "-s", "256x256", "-r", "30", "-pix_fmt", "yuv420p",
                   "-cq", "28", "-b:v", "0"]
    else:
        vparams = ["-c:v", encoder, "-t", "0.5",
                   "-s", "256x256", "-r", "30", "-pix_fmt", "yuv420p",
                   "-cq", "23", "-b:v", "0"]
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30",
        "-f", "lavfi", "-i", "anullsrc=r=8000",
        "-t", "0.5",
        *vparams,
        "-c:a", "aac", "-b:a", "32k",
        "-f", "mp4", "-movflags", "+faststart",
        "NUL" if sys.platform == "win32" else "/dev/null",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=8, creationflags=_NO_WINDOW)
        if r.returncode == 0:
            return True, ""
        # 抽 stderr 关键行
        err = ""
        for line in r.stderr.splitlines():
            if any(k in line for k in ("Error", "Cannot", "No NVIDIA", "Failed", "not supported", "Unknown encoder")):
                err = line.strip()
                break
        return False, err or f"ffmpeg 返回 {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "短测超时"
    except Exception as e:
        return False, str(e)


def detect_encoders_full(progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """完整探测：静态列举 + GPU 短测。CPU 跳过短测。
    progress_cb 接收 ('hevc/xxx 短测中…' / '短测通过' / '短测失败: 原因')。
    """
    info = detect_encoders_static()
    if info.get("error"):
        return info
    ffmpeg = get_ffmpeg()
    for codec in ("hevc", "h264"):
        for e in info.get(codec, []):
            if e.kind == "cpu":
                e.hw_works = True  # CPU 不测，标为可用
                continue
            if progress_cb:
                progress_cb(f"{e.name} 短测中…")
            ok, reason = _hw_smoke_test(ffmpeg, e.name, e.codec)
            e.hw_works = ok
            e.hw_reason = reason
            if progress_cb:
                progress_cb(f"{e.name} {'通过' if ok else '失败: ' + reason}")
    return info


def pick_encoder(target: str, encoders: dict, prefer_hw: bool = True) -> EncoderInfo:
    """选编码器。prefer_hw=True 时优先 GPU（nvenc > amf > qsv），失败回退 CPU。
    只考虑 hw_works=True 的。"""
    cands = [e for e in encoders.get(target, []) if e.hw_works]
    if not cands:
        raise RuntimeError(f"没有可用的 {target} 编码器")
    if prefer_hw:
        for kind in ("nvenc", "amf", "qsv"):
            for e in cands:
                if e.kind == kind:
                    return e
    for e in cands:
        if e.kind == "cpu":
            return e
    return cands[0]


# ─────────────────────────── 源文件探测 ───────────────────────────


def probe_streams(src: Path) -> dict:
    """ffprobe JSON。接受 Path；不接受字符串且不忽略。

    解码策略：subprocess 以字节捕获，显式用 UTF-8 解码 stdout（ffprobe 输出恒为
    UTF-8）。stdout 取 JSON、stderr 取错误原因，二者分离处理，避免默认 locale
    （cp936）解码失败把 r.stdout 变成 None 后 json.loads 抛 TypeError 掩盖真实错误。
    """
    if not isinstance(src, Path):
        src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"输入文件不存在：{src}")
    ffprobe = get_ffprobe()
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(src.resolve())],
            capture_output=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise

    # 退出码非零：真实失败原因在 stderr（stdout 的 JSON 可能为空/残缺）
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffprobe 失败（exit {r.returncode}）：{err[:300]}")

    raw = r.stdout or b""
    if not raw.strip():
        # 退出 0 但无 JSON：工具可能把错误写到了 stderr
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffprobe 无输出（exit {r.returncode}）：{err[:300]}")

    # 显式 UTF-8 解码；结构化数据不允许靠 errors=ignore 丢字节冒充成功
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffprobe 输出不是合法 UTF-8（需 UTF-8）：{e}；stderr={err[:200]}")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffprobe 输出不是合法 JSON：{e}；stderr={err[:200]}")


# MP4 容器原生支持的视频 / 音频编码
_MP4_VIDEO = {"h264", "hevc", "h263", "mpeg4", "vp9", "av1"}
_MP4_AUDIO = {"aac", "mp3", "ac3", "opus", "flac", "vorbis", "alac"}


@dataclass
class StreamSummary:
    video_codecs: List[str]
    audio_codecs: List[str]
    has_audio: bool
    has_video: bool
    duration: float
    raw: dict


def summarize_streams(streams: dict) -> StreamSummary:
    """整理探测结果给 UI / 决策用。"""
    vcodecs, acodecs = [], []
    for s in streams.get("streams", []):
        ct = s.get("codec_type")
        cn = s.get("codec_name", "")
        if ct == "video":
            vcodecs.append(cn)
        elif ct == "audio":
            acodecs.append(cn)
    duration = 0.0
    if streams.get("format", {}).get("duration"):
        try:
            duration = float(streams["format"]["duration"])
        except (TypeError, ValueError):
            duration = 0.0
    if duration == 0.0:
        for s in streams.get("streams", []):
            if s.get("codec_type") == "video" and s.get("duration"):
                try:
                    duration = float(s["duration"])
                    break
                except (TypeError, ValueError):
                    pass
    return StreamSummary(
        video_codecs=vcodecs,
        audio_codecs=acodecs,
        has_audio=bool(acodecs),
        has_video=bool(vcodecs),
        duration=duration,
        raw=streams,
    )


def can_remux_to_mp4(summary: StreamSummary) -> Tuple[bool, str, str]:
    """判定 remux 可行性。
    返回 (ok, reason_text, suggested_action)
    suggested_action: 'remux' | 'reencode_video_transcode_audio' | 'reencode_video_keep_audio_if_compat' | 'reencode_both'
    """
    bad_video = [c for c in summary.video_codecs if c not in _MP4_VIDEO]
    bad_audio = [c for c in summary.audio_codecs if c not in _MP4_AUDIO]

    if not summary.has_video:
        return False, "源文件没有视频流", "reencode_both"

    if bad_video and bad_audio:
        return False, f"视频 {bad_video} 和音频 {bad_audio} 都需重编码", "reencode_both"
    if bad_video and not bad_audio:
        return False, f"视频编码 {bad_video} 不在 MP4 白名单，需重编码", "reencode_video_keep_audio_if_compat"
    if bad_video and summary.has_audio:
        return False, f"视频编码 {bad_video} 不在 MP4 白名单", "reencode_video_transcode_audio"
    if not bad_video and bad_audio:
        # 视频能 remux，音频不能 → 优先"视频 copy + 音频转 AAC"，避免无谓重编码
        return True, f"视频可直接复制；音频 {bad_audio} 将转 AAC", "remux"
    if not bad_video and not bad_audio:
        return True, "视频 + 音频均在 MP4 白名单，可秒级换容器", "remux"
    return False, "未知状态", "reencode_both"


# ─────────────────────────── 转换 ───────────────────────────


@dataclass
class ConvertOptions:
    mode: str               # 'auto' | 'remux' | 'h264' | 'hevc'
    crf: int = 28
    preset: str = "medium"
    overwrite: bool = False  # 默认不允许覆盖


# 状态机常量
class Status:
    PENDING = "pending"
    PROBING = "probing"
    CONVERTING = "converting"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class TaskResult:
    src: Path
    dst: Path
    status: str
    message: str = ""
    duration_s: float = 0.0
    output_size: int = 0
    log_path: Optional[Path] = None


# ─────────────────────────── FFmpeg 子进程（结构化进度） ───────────────────────────


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
_WIN_PROCESS_FLAGS = _NO_WINDOW | _NEW_PROCESS_GROUP if sys.platform == "win32" else 0


# CPU 编码器的 preset（libx265 / libx264）
_CPU_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]
# NVENC 编码器预设（NVIDIA）
_NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
# QSV 编码器预设（Intel）
_QSV_PRESETS = ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
# AMF 编码器预设（AMD）
_AMF_PRESETS = ["speed", "balanced", "quality"]


def _map_preset(encoder_kind: str, user_preset: str) -> str:
    """把用户的 preset 翻译成该编码器接受的形态。
    用户视角的预设统一（ultrafast → veryslow 等 9 档），底层按硬件能力翻译。
    """
    if encoder_kind == "cpu":
        return user_preset if user_preset in _CPU_PRESETS else "medium"
    if encoder_kind == "nvenc":
        # 9 档 → 7 档的近似映射
        m = {"ultrafast": "p1", "superfast": "p2", "veryfast": "p3",
             "faster": "p3", "fast": "p4", "medium": "p5",
             "slow": "p6", "slower": "p6", "veryslow": "p7"}
        return m.get(user_preset, "p5")
    if encoder_kind == "qsv":
        return user_preset if user_preset in _QSV_PRESETS else "medium"
    if encoder_kind == "amf":
        m = {"ultrafast": "speed", "superfast": "speed", "veryfast": "speed",
             "faster": "speed", "fast": "balanced", "medium": "balanced",
             "slow": "quality", "slower": "quality", "veryslow": "quality"}
        return m.get(user_preset, "balanced")
    return user_preset


def _map_crf(encoder_kind: str, codec: str, user_crf: int) -> int:
    """GPU 编码器的 -cq 范围和 CPU 的 -crf 不同；统一按用户视角的 crf 处理。"""
    if encoder_kind == "cpu":
        return max(0, min(51, user_crf))
    # nvenc / amf / qsv 的 -cq 范围 0-51（与 CRF 类似）
    return max(0, min(51, user_crf))


def _build_ffmpeg_cmd(
    src: Path,
    tmp_dst: Path,
    options: ConvertOptions,
    encoder: EncoderInfo,
    audio_strategy: str,  # 'copy' | 'transcode_to_aac'
) -> List[str]:
    """根据编码器和音频策略构造 ffmpeg 命令。
    audio_strategy:
      - 'copy': 保留源音频流（仅在容器兼容时）
      - 'transcode_to_aac': 转 AAC
    """
    ffmpeg = get_ffmpeg()
    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-y",
        "-progress", "pipe:1",
        "-i", str(src.resolve()),
    ]

    # 视频编码器参数
    cmd += ["-c:v", encoder.name]
    if encoder.kind == "cpu":
        cmd += ["-crf", str(_map_crf(encoder.kind, encoder.codec, options.crf)),
                "-preset", _map_preset(encoder.kind, options.preset)]
        # x265 加个 pix_fmt 防奇怪输入
        if encoder.codec == "hevc":
            cmd += ["-pix_fmt", "yuv420p"]
    else:
        # GPU 编码器用 -cq（恒定质量模式），-b:v 0
        cmd += ["-cq", str(_map_crf(encoder.kind, encoder.codec, options.crf)),
                "-b:v", "0",
                "-preset", _map_preset(encoder.kind, options.preset)]

    # 音频策略
    if audio_strategy == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "128k"]

    cmd += ["-movflags", "+faststart", str(tmp_dst.resolve())]
    return cmd


def _parse_progress_line(line: str) -> Optional[dict]:
    """解析 ffmpeg -progress 输出。格式 key=value，每条以换行分隔，块末是 'progress=continue|end'"""
    line = line.strip()
    if not line or "=" not in line:
        return None
    k, _, v = line.partition("=")
    return {"key": k.strip(), "value": v.strip()}


def run_ffmpeg_with_progress(
    cmd: List[str],
    total_seconds: float,
    progress_cb: Callable[[float, str], None],
    is_cancelled: Callable[[], bool],
    log_path: Path,
) -> Tuple[int, str]:
    """启动 ffmpeg，实时回调进度（0.0-1.0）。
    - stdout 读 `-progress pipe:1` 输出（结构化，非阻塞读）
    - stderr 重定向到 log_path 文件（不读，ffmpeg 自己写）
    - is_cancelled() 返回 True 时优雅终止
    - 返回 (returncode, last_status)
    """
    log_file = None
    try:
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    except OSError:
        log_file = None

    # 在 Windows 上 bufsize=0 会让 stdout 变成 _io.FileIO，没有 read1。
    # 用默认 buffer（bufsize=-1）+ 单独读线程。
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=log_file if log_file else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_WIN_PROCESS_FLAGS,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        return -1, f"ffmpeg 启动失败：{e}"

    last_status = "unknown"
    out_us = 0
    state: dict = {}
    progress_queue: queue.Queue = queue.Queue()
    stop_reader = threading.Event()
    reader_error: list = []

    def _stdout_reader():
        """独立线程读 stdout，按行解析进度推到 queue。"""
        try:
            while not stop_reader.is_set():
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    break
                parsed = _parse_progress_line(line)
                if not parsed:
                    continue
                state[parsed["key"]] = parsed["value"]
                if parsed["key"] in ("out_time_us", "out_time_ms"):
                    try:
                        progress_queue.put(("time", int(parsed["value"])))
                    except ValueError:
                        pass
                if parsed["key"] == "progress":
                    progress_queue.put(("status", parsed["value"]))
        except Exception as e:
            reader_error.append(str(e))
        finally:
            progress_queue.put(("__done__", None))

    reader_thread = threading.Thread(target=_stdout_reader, daemon=True)
    reader_thread.start()

    try:
        cancel_deadline = None
        while True:
            # 取消检测
            if is_cancelled():
                _terminate_graceful(proc, deadline=3.0)
                stop_reader.set()
                _force_kill_tree(proc)
                return -2, "cancelled"

            # 拉取进度
            try:
                while True:
                    kind, val = progress_queue.get_nowait()
                    if kind == "__done__":
                        break
                    if kind == "time":
                        out_us = val
                    elif kind == "status":
                        last_status = val
                        if total_seconds > 0 and out_us > 0:
                            pct = min(out_us / (total_seconds * 1_000_000), 1.0)
                        elif last_status == "end":
                            pct = 1.0
                        else:
                            pct = -1.0
                        if pct >= 0:
                            progress_cb(pct, last_status)
            except queue.Empty:
                pass

            # 进程结束？
            if proc.poll() is not None:
                # 给 reader 一点时间消化最后几行
                reader_thread.join(timeout=0.5)
                break

            time.sleep(0.05)
    finally:
        stop_reader.set()
        if log_file:
            try:
                log_file.close()
            except Exception:
                pass

    return proc.returncode, last_status


def _terminate_graceful(proc: subprocess.Popen, deadline: float = 3.0):
    """优雅（SIGTERM/Ctrl-Break）→ 强制（kill）。Windows 用 CTRL_BREAK_EVENT。
    注意：调用前 Popen 必须带 CREATE_NEW_PROCESS_GROUP 才能收到 Ctrl-Break。
    """
    if proc.poll() is not None:
        return
    # 1. 优雅：先发 SIGINT/CTRL_BREAK 让 ffmpeg 自己 flush + 关闭输出
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except Exception:
        pass
    # 2. 等 deadline 秒
    try:
        proc.wait(timeout=deadline)
        return
    except subprocess.TimeoutExpired:
        pass
    # 3. 优雅失败：kill()（TerminateProcess on Windows）
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _force_kill_tree(proc: subprocess.Popen):
    """最后的兜底：用 taskkill 杀进程树。Windows 上 ffmpeg 可能 spawn 子进程。"""
    if proc.poll() is not None:
        return
    if sys.platform != "win32":
        return
    try:
        pid = proc.pid
        # /T 杀子树，/F 强制
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=3,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        pass


# signal 模块单独导入（CTRL_BREAK 需要）
import signal  # noqa: E402


# ─────────────────────────── 输出命名 + 原子发布 ───────────────────────────


def plan_output(src: Path, out_dir: Path, mode_tag: str, overwrite: bool = False) -> Tuple[Path, Path]:
    """规划输出路径 + 临时路径。
    - 同名文件：自动加 (1) (2) …
    - 不覆盖已有文件（除非 overwrite=True）
    - 临时文件 .partial.mp4；成功后原子 rename 为 .mp4
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 模式标签嵌入文件名，便于识别
    suffix_tag = "" if mode_tag == "remux" else f"_{mode_tag}"

    base = src.stem + suffix_tag
    candidate = out_dir / f"{base}.mp4"

    if candidate.exists() and not overwrite:
        i = 1
        while True:
            candidate = out_dir / f"{base} ({i}).mp4"
            if not candidate.exists():
                break
            i += 1

    tmp = candidate.with_suffix(".partial.mp4")
    return candidate, tmp


def atomic_publish(tmp: Path, final: Path) -> bool:
    """临时文件 → 校验 → 原子发布到 final。

    round2 行为变更：拒绝覆盖已存在的 final。

    原因：plan_output 在调用时刻检查 final 是否存在，但 ffmpeg 编码过程可能
    持续数秒到数分钟——期间其他进程或用户操作可能创建同名文件。原来的
    os.replace 永远原子覆盖，会静默销毁用户已有数据。

    新策略：
    1. final 不存在：用 O_CREAT|O_EXCL 原子占位（杜绝 TOCTOU），再 os.replace
    2. final 存在：返回 False，清理 tmp；调用方应重 plan_output 并重试一次
    """
    if not tmp.exists() or tmp.stat().st_size == 0:
        return False

    if final.exists():
        # 用户数据优先于发布：拒绝覆盖
        try:
            tmp.unlink()
        except OSError:
            pass
        return False

    # final 不存在：用 O_CREAT|O_EXCL 原子占位，杜绝 TOCTOU
    try:
        fd = os.open(str(final), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
    except FileExistsError:
        # 介于 exists() 和 open() 之间被别人抢占了
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False

    # 已成功占位 final，现在把 tmp 原子重命名过去
    try:
        os.replace(tmp, final)
    except OSError:
        # replace 失败：清理我们刚创建的占位文件
        try:
            final.unlink()
        except OSError:
            pass
        try:
            tmp.unlink()
        except OSError:
            pass
        return False

    return final.exists() and final.stat().st_size > 0


# ─────────────────────────── 单文件转换编排 ───────────────────────────


def convert_one(
    src: Path,
    options: ConvertOptions,
    encoders: dict,
    progress_cb: Callable[[float, str], None],
    is_cancelled: Callable[[], bool],
    summary: Optional[StreamSummary] = None,
    audio_strategy_override: Optional[str] = None,
    encoder_override: Optional[EncoderInfo] = None,
) -> TaskResult:
    """编排单个文件转换。返回 TaskResult（不抛异常给 UI，统一传状态）。"""
    from dataclasses import dataclass

    # 1. 探测（如未传）
    if summary is None:
        try:
            streams = probe_streams(src)
            summary = summarize_streams(streams)
        except Exception as e:
            return TaskResult(src=src, dst=Path(), status=Status.FAILED,
                              message=f"探测失败：{e}")

    # 2. 决定实际模式
    if options.mode == "auto":
        ok, reason, action = can_remux_to_mp4(summary)
        if action == "remux":
            actual_mode = "remux"
            audio_strategy = "copy" if "音频" not in reason or "可秒级" in reason else "transcode_to_aac"
            # reason 含 "音频 X 将转 AAC" → 音频需转
            if "将转 AAC" in reason:
                audio_strategy = "transcode_to_aac"
        else:
            actual_mode = "hevc"  # auto 默认 HEVC
            audio_strategy = "transcode_to_aac"
    elif options.mode == "remux":
        actual_mode = "remux"
        audio_strategy = audio_strategy_override or "copy"
    else:
        actual_mode = options.mode
        audio_strategy = "transcode_to_aac"

    # 3. 选编码器
    if encoder_override is not None:
        encoder = encoder_override
    elif actual_mode == "remux":
        encoder = EncoderInfo(name="copy", codec="copy", kind="copy", available=True,
                              hw_works=True, note="仅换容器")
    else:
        try:
            encoder = pick_encoder(actual_mode, encoders, prefer_hw=True)
        except RuntimeError as e:
            return TaskResult(src=src, dst=Path(), status=Status.FAILED,
                              message=f"无可用 {actual_mode} 编码器：{e}")

    # 4. 规划输出
    out_dir = src.parent  # 默认同目录
    candidate, tmp = plan_output(src, out_dir, actual_mode, overwrite=options.overwrite)

    # 5. 构造命令 + 执行
    cmd = _build_ffmpeg_cmd(src, tmp, options, encoder, audio_strategy)
    log_path = candidate.with_suffix(".partial.log")

    t0 = time.time()
    rc, last_status = run_ffmpeg_with_progress(
        cmd=cmd,
        total_seconds=summary.duration,
        progress_cb=progress_cb,
        is_cancelled=is_cancelled,
        log_path=log_path,
    )
    elapsed = time.time() - t0

    # 6. 取消分支
    if rc == -2 or is_cancelled():
        _cleanup(tmp)
        _cleanup(log_path)
        return TaskResult(src=src, dst=candidate, status=Status.CANCELLED,
                          message="用户取消", duration_s=elapsed, log_path=log_path)

    # 7. 失败分支
    if rc != 0 or last_status != "end":
        _cleanup(tmp)
        msg = _tail_log_for_error(log_path)
        return TaskResult(src=src, dst=candidate, status=Status.FAILED,
                          message=msg or f"ffmpeg 返回 {rc}", duration_s=elapsed,
                          log_path=log_path)

    # 8. 校验 + 原子发布
    try:
        probe = probe_streams(candidate if candidate.exists() else tmp)
        out_summary = summarize_streams(probe)
        if out_summary.duration > 0 and summary.duration > 0:
            # 时长偏差超过 5% 视为异常
            ratio = out_summary.duration / summary.duration
            if ratio < 0.95 or ratio > 1.05:
                _cleanup(tmp)
                return TaskResult(src=src, dst=candidate, status=Status.FAILED,
                                  message=f"输出时长异常：{out_summary.duration:.2f}s vs 源 {summary.duration:.2f}s",
                                  duration_s=elapsed, log_path=log_path)
    except Exception as e:
        _cleanup(tmp)
        return TaskResult(src=src, dst=candidate, status=Status.FAILED,
                          message=f"输出校验失败：{e}", duration_s=elapsed, log_path=log_path)

    if not atomic_publish(tmp, candidate):
        _cleanup(tmp)
        # round2 区分两种失败：目标被占用 vs 真磁盘/权限问题
        if candidate.exists():
            msg = f"输出路径 {candidate.name} 已被占用，未覆盖"
        else:
            msg = "原子发布失败（磁盘？权限？）"
        return TaskResult(src=src, dst=candidate, status=Status.FAILED,
                          message=msg, duration_s=elapsed,
                          log_path=log_path)

    # partial.log 也清理；成功不保留日志
    _cleanup(log_path)

    return TaskResult(
        src=src, dst=candidate, status=Status.SUCCESS,
        message=f"{actual_mode} → {candidate.name}", duration_s=elapsed,
        output_size=candidate.stat().st_size,
    )


def _cleanup(p: Path):
    try:
        if p and p.exists():
            p.unlink()
    except OSError:
        pass


def _tail_log_for_error(log_path: Path, lines: int = 8) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = text.splitlines()[-lines:]
    # 优先找含 Error 的行
    for line in reversed(tail):
        if any(k in line for k in ("Error", "Invalid", "Conversion failed", "Permission")):
            return line.strip()
    return tail[-1] if tail else ""


# ─────────────────────────── 取消信号对象 ───────────────────────────


class CancelToken:
    """线程安全的取消令牌。Worker 用 stop() 触发，ffmpeg 进程通过 is_cancelled() 回调查询。"""
    def __init__(self):
        self._evt = threading.Event()

    def cancel(self):
        self._evt.set()

    def is_cancelled(self) -> bool:
        return self._evt.is_set()

    def reset(self):
        self._evt.clear()
