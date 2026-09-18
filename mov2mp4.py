"""
mov2mp4.py - Video2Mp4 GUI（tkinter + ttk + tkinterdnd2）

按用户任务书 C 节重写：
- 顶部：标题 + 副标题 + 状态
- 主区：可拖拽的文件列表（含文件夹）
- 设置：4 个模式卡片（自动 / 仅换容器 / H.264 / H.265），明确说明
- 高级折叠：质量 / 速度 / 编码器
- 底部：开始 / 取消 / 进度 / 计数
- 日志折叠：失败摘要 + 详情
- 全局：跟随 Windows 主题切换（实时）
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

# 拖拽：tkinterdnd2 必须先于 tkinter 导入
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

import core
from theme import ThemeManager


# ────────── DPI awareness（Win 10 1703+）──────────
def _enable_dpi_awareness() -> None:
    """声明进程 DPI 感知。必须在任何 tk widget 创建之前调用，否则位图已被
    系统按 96 DPI 拉伸。Windows Vista+ 全可用；PerMonitorV2 是 Win10 1703+。

    失败 best-effort：若都失败，OS 默认 DPI Unaware 仍能渲染（仅高 DPI 模糊）。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Win10 1703+: SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
            return
        except (AttributeError, OSError):
            pass
        # Win8.1+: SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE = 2)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except (AttributeError, OSError):
            pass
        # Vista+: SetProcessDPIAware() = system aware
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


APP_TITLE = "Video2Mp4"
APP_SUBTITLE = "本地 MOV → MP4 转码（H.264 / H.265 / 仅换容器）"
SUPPORTED_EXTS = {".mov", ".mp4", ".mkv", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".webm", ".3gp"}


# ────────────── 后台 Worker ──────────────

class Worker(threading.Thread):
    """后台线程跑转换。完全不用 Thread 内部名字（避免 _stop 冲突）。

    round2 fix: 单一 CancelToken，取消事件一个源头。Worker.cancel() 翻转
    token，convert_one 通过 is_cancelled=token.is_cancelled 闭包轮询同一状态。
    """

    def __init__(self, items, options, encoders, out_dir,
                 progress_q, log_q, done_q):
        super().__init__(daemon=True)
        self.items = items           # List[(src_path, summary_or_None)]
        self.options = options
        self.encoders = encoders
        self.out_dir = out_dir       # None = 同源目录
        self.progress_q = progress_q
        self.log_q = log_q
        self.done_q = done_q
        # 单一取消源：用户点取消 → cancel() → token 翻转 →
        # convert_one.is_cancelled() 看到 True → ffmpeg 终止
        self._cancel_token = core.CancelToken()

    def cancel(self):
        self._cancel_token.cancel()

    def run(self):
        for idx, (src, summary) in enumerate(self.items):
            if self._cancel_token.is_cancelled():
                self.log_q.put((src, "cancelled", "用户取消"))
                continue

            self.progress_q.put((idx, "start", src.name))
            self.log_q.put((src, "info", f"开始：{src.name}"))

            try:
                # 决定输出目录
                out_dir = self.out_dir if self.out_dir else src.parent
                out_dir = Path(out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)

                src_for_convert = src
                r = core.convert_one(
                    src=src_for_convert,
                    options=self.options,
                    encoders=self.encoders,
                    progress_cb=lambda p, s, i=idx: self.progress_q.put((i, "progress", p, s)),
                    is_cancelled=self._cancel_token.is_cancelled,
                    summary=summary,
                )

                # 如果指定了 out_dir，把产物移过去
                if r.status == core.Status.SUCCESS and self.out_dir and r.dst.parent != out_dir:
                    target = self._unique_dst(out_dir, r.dst.name)
                    try:
                        os.replace(r.dst, target)
                        r.dst = target
                    except OSError:
                        try:
                            import shutil
                            shutil.copy2(r.dst, target)
                            r.dst.unlink()
                            r.dst = target
                        except Exception as e:
                            r = core.TaskResult(src=src, dst=r.dst,
                                                status=core.Status.FAILED,
                                                message=f"移动到 {out_dir} 失败：{e}")

                # round2: log_q 载荷用 src 路径，不用 idx（解决索引错位）
                self.log_q.put((src, r.status, r.message))

            except Exception as e:
                self.log_q.put((src, "failed", f"未捕获异常：{e}"))
                continue

        self.done_q.put("done")

    def _unique_dst(self, out_dir: Path, name: str) -> Path:
        """避免覆盖，必要时加 (1)。"""
        candidate = out_dir / name
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        i = 1
        while True:
            candidate = out_dir / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                return candidate
            i += 1


# ────────────── 文件列表行 ──────────────

class FileListTree(ttk.Treeview):
    """5 列：文件 / 大小 / 处理方式 / 状态 / 路径"""

    COLS = ("size", "mode", "status", "path")

    def __init__(self, master, **kw):
        super().__init__(master, columns=self.COLS, show="tree headings",
                         selectmode="extended", **kw)
        self.heading("#0", text="文件", anchor="w")
        self.heading("size", text="大小", anchor="e")
        self.heading("mode", text="处理方式", anchor="center")
        self.heading("status", text="状态", anchor="center")
        self.heading("path", text="完整路径", anchor="w")
        self.column("#0", width=220, minwidth=120)
        self.column("size", width=80, minwidth=60, anchor="e")
        self.column("mode", width=110, minwidth=80, anchor="center")
        self.column("status", width=110, minwidth=80, anchor="center")
        self.column("path", width=300, minwidth=120, anchor="w")
        self.tag_configure("ok", foreground="#107c10")
        self.tag_configure("fail", foreground="#d13438")
        self.tag_configure("warn", foreground="#ca5010")
        self.tag_configure("muted", foreground="#888888")

    def add(self, src: Path):
        size = src.stat().st_size if src.exists() else 0
        size_str = _human_size(size)
        self.insert("", "end", iid=str(src), text=src.name,
                    values=(size_str, "待命", "已加入", str(src)),
                    tags=("muted",))

    def set_mode(self, src: Path, mode_text: str):
        if self.exists(str(src)):
            self.set(str(src), "mode", mode_text)

    def set_status(self, src: Path, text: str, tag: str = ""):
        if self.exists(str(src)):
            self.set(str(src), "status", text)
            if tag:
                self.item(str(src), tags=(tag,))


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ────────────── 主窗口 ──────────────

class App(TkinterDnD.Tk if HAS_DND else tk.Tk):
    def __init__(self):
        _enable_dpi_awareness()  # 必须在 super().__init__() 完成布局之前
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("960x700")
        self.minsize(820, 600)

        # 状态
        self.theme = ThemeManager(self)
        self.style = ttk.Style(self)
        # 强制 clam 主题：原生 vista/xpnative 主题按钮文字不可控（白字看不见等）
        # clam 是纯 ttk 渲染，foreground / background / bordercolor 全部按我们的样式生效
        self.style.theme_use("clam")
        self.theme.apply_to_root(self)
        self.theme.apply_to_ttk_style(self.style)
        self.theme.on_change(self._on_theme_change)

        self.items: List[Path] = []
        self.item_summaries: Dict[str, dict] = {}  # src_str -> {summary, src}
        self.encoders: dict = core.detect_encoders_full(
            lambda m: self._log_system(m)
        )
        self.progress_q: queue.Queue = queue.Queue()
        self.log_q: queue.Queue = queue.Queue()
        self.done_q: queue.Queue = queue.Queue()
        self.worker: Optional[Worker] = None
        self.success_count = 0
        self.fail_count = 0

        self._build_ui()
        self._bind_dnd()
        self._poll_queues()

        # 依赖检查
        deps = core.verify_deps()
        if not deps["ok"]:
            self._log_system("✗ 缺少依赖：")
            for name, path in (("ffmpeg", deps["ffmpeg"]), ("ffprobe", deps["ffprobe"])):
                if not path:
                    self._log_system(f"    - {name}：未找到")
            self._log_system("  请安装 ffmpeg 并加入 PATH：https://www.gyan.dev/ffmpeg/builds/")
            self.start_btn.config(state="disabled")
            self.status_var.set("缺依赖，无法启动")
        else:
            self._log_initial()

    # ────────── 主题切换 ──────────

    def _on_theme_change(self, pal, is_dark):
        self.theme.apply_to_root(self)
        self.theme.apply_to_ttk_style(self.style)
        # 重建 Treeview 标签颜色
        if hasattr(self, "file_tree"):
            self.file_tree.tag_configure("ok", foreground=pal["success"])
            self.file_tree.tag_configure("fail", foreground=pal["error"])
            self.file_tree.tag_configure("warn", foreground=pal["warning"])
            self.file_tree.tag_configure("muted", foreground=pal["fg_muted"])
        # Text widget 配色
        if hasattr(self, "log_text"):
            self.log_text.configure(
                background=pal["log_bg"], foreground=pal["log_fg"],
                insertbackground=pal["fg"]
            )

    # ────────── UI 构建 ──────────

    def _build_ui(self):
        # ── 顶部 ──
        top = ttk.Frame(self, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text=APP_SUBTITLE, style="Muted.TLabel").pack(side="left", padx=(10, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(top, textvariable=self.status_var, style="Muted.TLabel").pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        # ── 主区（左右） ──
        body = ttk.Frame(self, padding=(16, 8))
        body.pack(fill="both", expand=True)

        # 左：文件区
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        file_header = ttk.Frame(left)
        file_header.pack(fill="x", pady=(0, 4))
        ttk.Label(file_header, text="文件", style="Card.Title.TLabel" if False else "TLabel",
                  font=("", 11, "bold")).pack(side="left")
        self.file_count_var = tk.StringVar(value="0 个文件")
        ttk.Label(file_header, textvariable=self.file_count_var,
                  style="Muted.TLabel").pack(side="left", padx=(8, 0))

        # 拖拽提示
        ttk.Button(file_header, text="+ 添加文件", command=self._add_files).pack(side="right")
        ttk.Button(file_header, text="+ 添加文件夹", command=self._add_dir).pack(side="right", padx=(4, 0))
        ttk.Button(file_header, text="清空", command=self._clear).pack(side="right", padx=(4, 0))

        # Treeview 容器
        tree_frame = ttk.Frame(left, relief="solid", borderwidth=1)
        tree_frame.pack(fill="both", expand=True)

        self.file_tree = FileListTree(tree_frame)
        self.file_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_frame, command=self.file_tree.yview)
        sb.pack(side="right", fill="y")
        self.file_tree.config(yscrollcommand=sb.set)

        # 拖入提示（空状态）
        self.empty_label = ttk.Label(self.file_tree,
                                     text="把视频文件拖到这里\n或点上面 + 添加",
                                     style="Muted.TLabel", justify="center")

        # 右：设置
        right = ttk.Frame(body, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # 设置卡片
        settings = ttk.LabelFrame(right, text="转换模式", padding=12)
        settings.pack(fill="x", pady=(0, 8))

        self.mode_var = tk.StringVar(value="auto")
        # 4 个 radio + 描述
        mode_descs = [
            ("auto", "自动", "源能换容器就换容器，否则 H.265 编码"),
            ("remux", "仅换容器", "不重编码，秒级完成，文件大小不变（无损）"),
            ("h264", "H.264 兼容", "重编码为 H.264，所有设备都能播放"),
            ("hevc", "H.265 压缩", "重编码为 H.265，文件更小（约 50%）"),
        ]
        for val, label, desc in mode_descs:
            rb_frame = ttk.Frame(settings)
            rb_frame.pack(fill="x", pady=2)
            rb = ttk.Radiobutton(rb_frame, text=label, value=val, variable=self.mode_var,
                                 command=self._on_mode_change)
            rb.pack(side="left", anchor="n")
            ttk.Label(rb_frame, text=desc, style="Muted.TLabel", wraplength=200,
                      justify="left").pack(side="left", padx=(8, 0), fill="x", expand=True)

        # 输出位置
        out_frame = ttk.LabelFrame(right, text="输出位置", padding=12)
        out_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(out_frame, text="留空 = 与源同目录", style="Muted.TLabel").pack(anchor="w")
        path_row = ttk.Frame(out_frame)
        path_row.pack(fill="x", pady=(6, 0))
        self.outdir_var = tk.StringVar()
        self.outdir_entry = ttk.Entry(path_row, textvariable=self.outdir_var)
        self.outdir_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="…", width=3, command=self._pick_outdir).pack(side="left", padx=(4, 0))

        # 高级折叠
        adv_frame = ttk.LabelFrame(right, text="高级", padding=12)
        adv_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(adv_frame, text="质量（CRF）").grid(row=0, column=0, sticky="w", pady=2)
        self.crf_var = tk.IntVar(value=28)
        ttk.Spinbox(adv_frame, from_=0, to=51, textvariable=self.crf_var, width=6).grid(
            row=0, column=1, sticky="e", pady=2)

        ttk.Label(adv_frame, text="编码速度").grid(row=1, column=0, sticky="w", pady=2)
        self.preset_var = tk.StringVar(value="medium")
        ttk.Combobox(adv_frame, textvariable=self.preset_var, width=10, state="readonly",
                     values=["ultrafast", "superfast", "veryfast", "faster", "fast",
                             "medium", "slow", "slower", "veryslow"]).grid(
            row=1, column=1, sticky="e", pady=2)

        # 编码器显示
        ttk.Label(adv_frame, text="编码器").grid(row=2, column=0, sticky="w", pady=2)
        self.encoder_var = tk.StringVar()
        self._refresh_encoder_label()
        ttk.Label(adv_frame, textvariable=self.encoder_var, style="Muted.TLabel",
                  wraplength=180, justify="right").grid(row=2, column=1, sticky="e", pady=2)

        # ── 底部 ──
        bot = ttk.Frame(self, padding=(16, 4, 16, 12))
        bot.pack(fill="x", side="bottom")

        # 进度条 + 计数
        prog_row = ttk.Frame(bot)
        prog_row.pack(fill="x", pady=(4, 4))
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(prog_row, variable=self.progress_var, maximum=100).pack(side="left", fill="x", expand=True)
        self.progress_text_var = tk.StringVar(value="0 / 0")
        ttk.Label(prog_row, textvariable=self.progress_text_var,
                  style="Muted.TLabel").pack(side="right", padx=(8, 0))

        # 操作按钮
        btn_row = ttk.Frame(bot)
        btn_row.pack(fill="x")
        self.start_btn = ttk.Button(btn_row, text="开始转换", style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_row, text="取消", style="Danger.TButton",
                                   command=self._cancel, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.summary_var = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self.summary_var,
                  style="Muted.TLabel").pack(side="right")

        # 日志折叠
        log_toggle_row = ttk.Frame(self, padding=(16, 0, 16, 0))
        log_toggle_row.pack(fill="x")
        self.log_expanded = tk.BooleanVar(value=False)
        self.log_toggle_btn = ttk.Button(log_toggle_row, text="▶ 显示日志",
                                         command=self._toggle_log)
        self.log_toggle_btn.pack(side="left")

        self.log_container = ttk.Frame(self, padding=(16, 0, 16, 12))
        # 默认隐藏
        self.log_text = tk.Text(self.log_container, height=8, wrap="word", state="disabled",
                                bg=self.theme.pal["log_bg"], fg=self.theme.pal["log_fg"],
                                insertbackground=self.theme.pal["fg"],
                                font=("Consolas", 9), relief="solid", borderwidth=1,
                                padx=8, pady=6)

    # ────────── 拖拽 ──────────

    def _bind_dnd(self):
        if not HAS_DND:
            self._log_system("（拖拽需要 tkinterdnd2；当前未启用，请用 + 按钮添加）")
            return
        self.file_tree.drop_target_register(DND_FILES)
        self.file_tree.dnd_bind('<<Drop>>', self._on_drop)
        # 整个窗口也接（拖到空白也行）
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self._on_drop)

    def _on_drop(self, event):
        # 解析拖入路径（可能有 {} 包裹的空格路径）
        data = event.data
        paths = self._parse_drop_data(data)
        for p in paths:
            if p.is_dir():
                self._add_dir_path(p)
            elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self._add_path(p)
        return event.action if hasattr(event, 'action') else None

    def _parse_drop_data(self, data: str) -> List[Path]:
        """tkinterdnd2 拖入数据：空格分隔，路径含空格时用 {} 包裹。"""
        import re
        paths = []
        for token in re.findall(r"\{[^}]*\}|\S+", data):
            token = token.strip("{}")
            if token:
                paths.append(Path(token))
        return paths

    # ────────── 队列轮询 ──────────

    def _poll_queues(self):
        # 进度
        try:
            while True:
                item = self.progress_q.get_nowait()
                self._handle_progress(item)
        except queue.Empty:
            pass

        # 日志
        try:
            while True:
                item = self.log_q.get_nowait()
                self._handle_log(item)
        except queue.Empty:
            pass

        # 完成
        try:
            while True:
                self.done_q.get_nowait()
                self._on_worker_done()
        except queue.Empty:
            pass

        self.after(100, self._poll_queues)

    def _handle_progress(self, item):
        if len(item) == 3:
            idx, kind, name = item
            if kind == "start":
                self.status_var.set(f"正在转换 {idx + 1}/{len(self.items)}：{name}")
                # 行状态
                for src in self.items:
                    if src.name == name:
                        self.file_tree.set_status(src, "转换中…", "warn")
                        break
        elif len(item) == 4:
            idx, kind, pct, status = item
            if kind == "progress" and pct >= 0:
                # 单文件进度按队列位置算（简化：直接显示 pct）
                self.progress_var.set(pct * 100)
                self.progress_text_var.set(f"{(idx + 1)}/{len(self.items)} · {pct * 100:.0f}%")

    def _handle_log(self, item):
        # round2: payload 是 (src_path: Path, status, msg)，不再用 idx
        # 用 src 直接定位 Treeview 行，索引错位自然消失
        src, status, msg = item
        if status == "info":
            self._log_text(f"  → {msg}")
            return
        # 状态结果
        text_map = {
            core.Status.SUCCESS: ("✓ 完成", "ok"),
            core.Status.FAILED: ("✗ 失败", "fail"),
            core.Status.CANCELLED: ("— 取消", "muted"),
            "cancelled": ("— 取消", "muted"),
            "failed": ("✗ 失败", "fail"),
        }
        text, tag = text_map.get(status, (str(status), "muted"))
        self.file_tree.set_status(src, text, tag)
        self._log_text(f"  [{text}] {src.name} — {msg}")
        # 计数
        if status == core.Status.SUCCESS:
            self.success_count += 1
        elif status in (core.Status.FAILED, "failed"):
            self.fail_count += 1
        self._update_summary()

    def _on_worker_done(self):
        self.worker = None
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress_var.set(100)
        self.status_var.set(
            f"完成：{self.success_count} 成功，{self.fail_count} 失败"
        )
        # 自动展开日志（如果有失败）
        if self.fail_count > 0 and not self.log_expanded.get():
            self._toggle_log()
        self._log_text(f"=== 全部完成：{self.success_count} 成功 / {self.fail_count} 失败 ===")

    # ────────── 文件管理 ──────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择视频",
            filetypes=[("视频文件", "*.mov *.mp4 *.mkv *.avi *.m4v *.flv *.wmv *.ts *.webm *.3gp"),
                       ("全部", "*.*")],
        )
        for p in paths:
            self._add_path(Path(p))

    def _add_dir(self):
        d = filedialog.askdirectory(title="选择文件夹（递归扫描）")
        if d:
            self._add_dir_path(Path(d))

    def _add_dir_path(self, d: Path):
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self._add_path(p)

    def _add_path(self, p: Path):
        if p in self.items or not p.exists():
            return
        self.items.append(p)
        self.file_tree.add(p)
        self._update_file_count()
        self._update_empty_state()

    def _clear(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("运行中", "请先取消当前转换")
            return
        self.items.clear()
        self.item_summaries.clear()
        self.success_count = 0
        self.fail_count = 0
        for iid in self.file_tree.get_children():
            self.file_tree.delete(iid)
        self._update_file_count()
        self._update_empty_state()
        self._update_summary()
        self.progress_var.set(0)
        self.progress_text_var.set("0 / 0")
        self.status_var.set("就绪")

    def _pick_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir_var.set(d)

    def _update_file_count(self):
        n = len(self.items)
        self.file_count_var.set(f"{n} 个文件")

    def _update_empty_state(self):
        if len(self.items) == 0:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty_label.place_forget()

    def _update_summary(self):
        total = self.success_count + self.fail_count
        if total == 0:
            self.summary_var.set("")
        else:
            self.summary_var.set(f"成功 {self.success_count} · 失败 {self.fail_count}")

    def _refresh_encoder_label(self):
        """根据当前探测结果更新编码器标签。"""
        hevc = self.encoders.get("hevc", [])
        if not hevc:
            self.encoder_var.set("（无可用）")
            return
        avail = [e for e in hevc if e.hw_works]
        if not avail:
            self.encoder_var.set("（无可用）")
            return
        # 第一个 GPU（如果可用）
        gpu = next((e for e in avail if e.kind in ("nvenc", "amf", "qsv")), None)
        if gpu:
            label_map = {"nvenc": "NVIDIA", "amf": "AMD", "qsv": "Intel"}
            self.encoder_var.set(f"{label_map[gpu.kind]} {gpu.name}")
        else:
            self.encoder_var.set("CPU libx265")

    # ────────── 模式切换 ──────────

    def _on_mode_change(self):
        # remux 模式下质量/preset 不起作用，给用户提示
        if self.mode_var.get() == "remux":
            self.crf_var.set(0)
            # 不禁用控件，避免改回时还要重新启用
        self._log_text(f"模式切换：{self.mode_var.get()}")

    # ────────── 日志折叠 ──────────

    def _toggle_log(self):
        if self.log_expanded.get():
            self.log_container.pack_forget()
            self.log_expanded.set(False)
            self.log_toggle_btn.config(text="▶ 显示日志")
        else:
            self.log_container.pack(fill="both", expand=False, before=self.log_toggle_btn.master)
            self.log_text.pack(fill="both", expand=True)
            self.log_expanded.set(True)
            self.log_toggle_btn.config(text="▼ 隐藏日志")

    def _log_text(self, line: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _log_system(self, line: str):
        # 系统消息 → 也写到日志（不阻塞 UI）
        try:
            if hasattr(self, "log_text"):
                self._log_text(line)
        except (tk.TclError, AttributeError):
            pass  # 日志 widget 还没建好或已销毁

    def _log_initial(self):
        self._log_system(f"=== {APP_TITLE} ===")
        self._log_system(f"输出：{'与源同目录' if not self.outdir_var.get() else self.outdir_var.get()}")
        self._log_system("可用编码器：")
        for codec in ("hevc", "h264"):
            lst = self.encoders.get(codec, [])
            if lst:
                avail = [e.name + ("(GPU)" if e.hw_works and e.kind != "cpu" else "")
                         for e in lst if e.hw_works]
                self._log_system(f"  {codec.upper()}: {', '.join(avail) if avail else '（无可用）'}")

    # ────────── 启动 / 取消 ──────────

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.items:
            messagebox.showinfo("提示", "请先添加视频文件")
            return

        # 探测 + 决策（后台跑）
        def prepare():
            prepared = []
            for src in self.items:
                try:
                    streams = core.probe_streams(src)
                    summary = core.summarize_streams(streams)
                    # 决定每个文件的 mode 显示
                    if self.mode_var.get() == "auto":
                        ok, reason, action = core.can_remux_to_mp4(summary)
                        if action == "remux":
                            display_mode = "仅换容器"
                        else:
                            display_mode = f"H.265 {action}"
                    else:
                        mode_map = {"remux": "仅换容器", "h264": "H.264", "hevc": "H.265"}
                        display_mode = mode_map[self.mode_var.get()]
                    self.after(0, lambda s=src, m=display_mode: self.file_tree.set_mode(s, m))
                    prepared.append((src, summary))
                except Exception as e:
                    self.log_q.put((len(prepared), core.Status.FAILED, f"探测失败：{e}"))
            return prepared

        # 同步探测（避免后台线程改 UI；这里文件数不会太多，先这样）
        prepared = []
        for src in list(self.items):
            try:
                streams = core.probe_streams(src)
                summary = core.summarize_streams(streams)
                if self.mode_var.get() == "auto":
                    ok, reason, action = core.can_remux_to_mp4(summary)
                    display_mode = "仅换容器" if action == "remux" else f"H.265 ({action})"
                else:
                    mode_map = {"remux": "仅换容器", "h264": "H.264", "hevc": "H.265"}
                    display_mode = mode_map[self.mode_var.get()]
                self.file_tree.set_mode(src, display_mode)
                prepared.append((src, summary))
            except Exception as e:
                self.file_tree.set_status(src, "✗ 探测失败", "fail")
                self._log_text(f"  ✗ 探测失败 {src.name}: {e}")

        if not prepared:
            messagebox.showwarning("无可用文件", "所有文件都探测失败")
            return

        # 构造 options
        opts = core.ConvertOptions(
            mode=self.mode_var.get(),
            crf=self.crf_var.get(),
            preset=self.preset_var.get(),
        )
        out_dir = Path(self.outdir_var.get()) if self.outdir_var.get().strip() else None

        self.success_count = 0
        self.fail_count = 0
        self._update_summary()
        self.progress_var.set(0)
        self.progress_text_var.set(f"0 / {len(prepared)}")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set(f"开始 {len(prepared)} 个任务…")

        self.worker = Worker(prepared, opts, self.encoders, out_dir,
                             self.progress_q, self.log_q, self.done_q)
        self.worker.start()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
            self.status_var.set("正在取消…")
            self.stop_btn.config(state="disabled")

    def on_closing(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("退出", "转换进行中，确定取消并退出？"):
                return
            self.worker.cancel()
            self.worker.join(timeout=5)
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
