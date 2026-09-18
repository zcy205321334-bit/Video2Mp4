<div align="center">

[中文](./README.md) · **English**

# 🎬 Video2Mp4

#### Drop any video in. Get MP4 out.

[![License](https://img.shields.io/badge/License-MIT-3B82F6?style=for-the-badge)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-10B981?style=for-the-badge)](#-install)
[![Python](https://img.shields.io/badge/Python-3.11-8B5CF6?style=for-the-badge)](#-tech-stack)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-D97706?style=for-the-badge)](#-install)

![GUI](https://img.shields.io/badge/GUI-Tkinter%20%2B%20ttk-FF6F00?style=flat-square&logo=python&logoColor=white)
![Drag](https://img.shields.io/badge/Drag%20%26%20Drop-tkinterdnd2-3B82F6?style=flat-square)
![H.264](https://img.shields.io/badge/H.264-NVENC%20%2F%20AMF%20%2F%20QSV-10B981?style=flat-square)
![H.265](https://img.shields.io/badge/H.265-libx265-8B5CF6?style=flat-square)

</div>

> **Status**: this repository is currently a **front page** — README, license and issue templates are in place;
> **source code and binaries are coming next**. Star or watch to get notified.

---

## 📋 Contents

| | |
|---|---|
| 🎬 [**What it does**](#-what-it-does) | Four conversion modes + twelve capabilities at a glance |
| 📦 [**Install**](#-install) | **Install FFmpeg first**, then grab the exe — order matters |
| 🚀 [**Usage**](#-usage) | Drop in, pick a mode, hit start |
| 🛠️ [**Tech stack**](#-tech-stack) | Python 3.11 + Tkinter + FFmpeg |
| 🔨 [**Build**](#-build) | How to build your own once the source is public |
| 📝 [**Roadmap**](#-roadmap) | What's done, what's next |
| ❓ [**FAQ**](#-faq) | "Missing dependency" on startup? |

---

## 🎬 What it does

### Four conversion modes

This is the heart of it. Picking the wrong mode is the #1 beginner mistake, so each one spells out when to use it:

| Mode | What it does | When to use |
|---|---|---|
| ⚡ **Auto** | Remux if the container allows it, otherwise encode to H.265 | You don't want to choose |
| 📦 **Remux only** | No re-encoding, finishes in seconds, file size unchanged (**lossless**) | You just want mkv / ts inside an mp4 shell |
| 🎬 **H.264 compatible** | Re-encode to H.264, plays on everything | Old TVs, old phones, presentations |
| 🗜️ **H.265 compact** | Re-encode to H.265, roughly **50% smaller** | Archiving; some old devices won't decode it |

> 💡 **Just changing container? Pick "Remux only"** — it never touches quality and finishes in seconds.
> Pick a re-encoding mode by mistake and a 2-hour video can take half an hour.

### Everything else

| Capability | Details |
|---|---|
| 🖱️ **Drag & drop** | Drop videos straight into the window (tkinterdnd2); `+ Add files` button also there |
| 📁 **Folder recursion** | Drop a folder — it walks subdirectories for you |
| 🎞️ **10 input formats** | `.mov` `.mp4` `.mkv` `.avi` `.m4v` `.flv` `.wmv` `.ts` `.webm` `.3gp` |
| 🧠 **Hardware encoder detection** | Probes NVIDIA(NVENC) / AMD(AMF) / Intel(QSV), falls back to CPU |
| 🎚️ **Advanced controls** | Quality (CRF) / speed preset (nine steps) / encoder, tucked into an "Advanced" panel |
| 📂 **Optional output dir** | Leave empty to write next to the source, or pick a folder |
| 🛑 **Cancellable** | A single CancelToken runs end to end — cancel and it stops cleanly |
| 📋 **Five-column file list** | File / size / mode / status / full path |
| 📜 **Collapsible log** | Failure summary plus per-file detail |
| 🌗 **Follows system theme** | Live light/dark switching with Windows, no restart |
| 🖥️ **High-DPI aware** | PerMonitorV2 — no blur on 2K/4K displays |
| 🟢 **Green single binary** | One exe; no registry writes, no services, no leftovers |

---

## 📦 Install

### Step 1 — Install FFmpeg (**required**)

Video2Mp4 **does not bundle FFmpeg**. All transcoding and stream probing is delegated to it.
Without it the app shows `✗ missing dependency: ffmpeg not found` on startup and the **Start button stays greyed out**.

Grab `ffmpeg-release-essentials.zip` from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/),
extract it (say to `C:\ffmpeg`), then add its `bin` folder to PATH:

```powershell
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\ffmpeg\bin",
  "User"
)
```

Verify in a **freshly opened** terminal — both must print a version:

```powershell
ffmpeg -version
ffprobe -version
```

> ⚠️ PATH changes only apply to **new** terminals (and a restarted app). This is the most common one-time snag.

### Step 2 — Get Video2Mp4.exe

Download from [Releases](https://github.com/zcy205321334-bit/Video2Mp4/releases) and double-click.

**No release published yet** — binaries and source are coming together (see [roadmap](#-roadmap)).

---

## 🚀 Usage

1. Launch `Video2Mp4.exe`
2. Drag in video files (or a whole folder)
3. Pick a conversion mode — choose **"Remux only"** if you just need the container changed
4. Optionally expand "Advanced" to tune quality / speed / encoder
5. Hit **Start** and wait for the progress bar
6. Output appears next to the source (or in your chosen folder)

A summary line at the bottom reports `Done: N succeeded, M failed`. Expand the log for per-file detail.

### Notes

- **H.264 has the widest compatibility**; H.265 saves space but older devices may refuse it
- Hardware encoding needs a supported GPU and reasonably current drivers — detection failure just means CPU
- Try one short clip before batching a whole library
- Duplicate output names get an auto-incremented suffix; **existing files are never overwritten**

---

## 🛠️ Tech stack

| Component | Role |
|---|---|
| Python 3.11 | Primary language |
| Tkinter + ttk | GUI (`clam` theme) |
| tkinterdnd2 | Drag & drop (bundles win-x64 / win-arm64 natives) |
| FFmpeg / ffprobe | Transcoder + stream probing (**external dependency**) |
| NVENC / AMF / QSV | NVIDIA / AMD / Intel hardware encoders |
| libx264 / libx265 | CPU software encoders |
| PyInstaller | Single-file packaging |

---

## 🔨 Build

Once the source is public (see [roadmap](#-roadmap)) — a placeholder for now:

```bash
uv venv
uv sync --extra dev
scripts\build.cmd
```

Expected artifact: `output\dist\Video2Mp4.exe`.

---

## 📝 Roadmap

- [x] 10 input formats → MP4
- [x] Four conversion modes (Auto / Remux only / H.264 / H.265)
- [x] Automatic hardware encoder detection (NVENC / AMF / QSV) with CPU fallback
- [x] Lossless remux
- [x] Drag & drop + folder recursion
- [x] Live system theme following
- [x] High-DPI awareness
- [ ] **Publish the source code**
- [ ] **First release (with the exe)**
- [ ] Batch queue
- [ ] Pause / resume (only cancel today)

---

## ❓ FAQ

**Startup says `missing dependency: ffmpeg not found` and Start is greyed out?**

FFmpeg isn't installed, or isn't on PATH. Follow [step 1](#step-1--install-ffmpeg-required),
verify in a **new** terminal, and restart the app so it picks up the new PATH.

**Why is the output file bigger than the input?**

You picked a re-encoding mode (H.264 / H.265). If you only wanted the mp4 container,
switch to **"Remux only"** — no re-encoding, no size change.

**Why isn't hardware acceleration available?**

The app probes for it. If detection fails, it's usually an old GPU driver or an unsupported encoder
on your card. Either way it falls back to CPU and keeps working.

**Does it upload my videos anywhere?**

No. It's a purely local GUI with no networking code; transcoding is done by your own FFmpeg.

---

## 📄 License

[MIT](./LICENSE) · © 2026 zcy205321334-bit

---

<div align="center">

A small tool for people who, like me, can't be bothered installing codec packs on Windows.

Made by [@zcy205321334-bit](https://github.com/zcy205321334-bit)

</div>
