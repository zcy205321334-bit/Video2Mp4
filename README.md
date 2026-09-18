<div align="center">

**中文** · [English](./README.en.md)

# 🎬 Video2Mp4

#### 把一堆格式乱七八糟的视频，拖进去，出来就是 MP4

[![License](https://img.shields.io/badge/License-MIT-3B82F6?style=for-the-badge)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-10B981?style=for-the-badge)](#-安装)
[![Python](https://img.shields.io/badge/Python-3.11-8B5CF6?style=for-the-badge)](#-技术栈)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-需自备-D97706?style=for-the-badge)](#-安装)

![GUI](https://img.shields.io/badge/GUI-Tkinter%20%2B%20ttk-FF6F00?style=flat-square&logo=python&logoColor=white)
![Drag](https://img.shields.io/badge/%E6%8B%96%E6%8B%BD-tkinterdnd2-3B82F6?style=flat-square)
![H.264](https://img.shields.io/badge/H.264-NVENC%20%2F%20AMF%20%2F%20QSV-10B981?style=flat-square)
![H.265](https://img.shields.io/badge/H.265-libx265-8B5CF6?style=flat-square)

</div>

> **当前状态**：这个仓库目前是**门面页** —— README、许可证、Issue 模板都已经就位，**源码和可执行文件随后补上**。
> 想第一时间拿到，点个 ⭐ 或 Watch 就行。

---

## 📋 目录

| 名字 | 一句话 |
|---|---|
| 🎬 [**它能做什么**](#-它能做什么) | 四种转换模式 + 十二项能力，一眼看完 |
| 📦 [**安装**](#-安装) | **先装 FFmpeg**，再拿 exe —— 顺序别反 |
| 🚀 [**使用**](#-使用) | 拖进去、选模式、点开始 |
| 🛠️ [**技术栈**](#-技术栈) | Python 3.11 + Tkinter + FFmpeg |
| 🔨 [**构建**](#-构建) | 源码公开后怎么自己打一个 |
| 📝 [**路线图**](#-路线图) | 已做了什么、接下来做什么 |
| ❓ [**常见问题**](#-常见问题) | 启动提示「缺少依赖」怎么办 |

---

## 🎬 它能做什么

### 四种转换模式

这是它的核心。选错模式是新手最常踩的坑，所以每个模式都写清适用场景：

| 模式 | 干什么 | 什么时候用 |
|---|---|---|
| ⚡ **自动** | 源能换容器就换容器，否则 H.265 编码 | 懒得挑，交给它自己判断 |
| 📦 **仅换容器** | 不重编码，秒级完成，文件大小不变（**无损**） | 只是想把 mkv / ts 换个壳成 mp4 |
| 🎬 **H.264 兼容** | 重编码为 H.264，所有设备都能播放 | 要丢给老电视、老手机、PPT 用 |
| 🗜️ **H.265 压缩** | 重编码为 H.265，文件更小（**约 50%**） | 存档、省硬盘，接受部分老设备不认 |

> 💡 **只想换格式别重编码，就选「仅换容器」** —— 它不碰画质、几秒钟完事。
> 选错成重编码，2 小时视频可能要跑半小时。

### 其它

| 能力 | 说明 |
|---|---|
| 🖱️ **拖拽添加** | 视频直接拖进窗口（tkinterdnd2），也保留 `+ 添加文件` 按钮 |
| 📁 **文件夹递归** | 拖一个文件夹进来，自动递归子目录找出所有视频 |
| 🎞️ **10 种输入格式** | `.mov` `.mp4` `.mkv` `.avi` `.m4v` `.flv` `.wmv` `.ts` `.webm` `.3gp` |
| 🧠 **硬件编码自动探测** | 探测 NVIDIA(NVENC) / AMD(AMF) / Intel(QSV)，有就用，没有回落 CPU |
| 🎚️ **高级参数可调** | 质量（CRF）/ 编码速度（preset 九档）/ 编码器，折在「高级」面板里 |
| 📂 **输出位置可选** | 留空 = 与源文件同目录，也可另外指定 |
| 🛑 **随时取消** | 单个 CancelToken 贯穿全程，点了就停，不会留下半个文件 |
| 📋 **五列文件列表** | 文件 / 大小 / 处理方式 / 状态 / 完整路径 |
| 📜 **可折叠日志** | 失败摘要 + 逐条详情，出问题时有据可查 |
| 🌗 **跟随系统主题** | 实时跟随 Windows 浅色 / 深色切换，不用重启 |
| 🖥️ **高 DPI 感知** | PerMonitorV2，2K / 4K 屏上不糊 |
| 🟢 **绿色单文件** | 一个 exe，不写注册表、不装服务、不留残留 |

---

## 📦 安装

### 第 1 步：先装 FFmpeg（**必须**）

Video2Mp4 **自己不带 FFmpeg** —— 转码和流探测全部交给它跑。没装的话，程序启动会显示
`✗ 缺少依赖：ffmpeg 未找到`，并且**开始按钮是灰的**。

从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`，
解压（比如到 `C:\ffmpeg`），然后把 `bin` 目录加进 PATH：

```powershell
# 以当前用户身份追加到 PATH
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\ffmpeg\bin",
  "User"
)
```

**新开一个终端**验证，两条都要有输出：

```powershell
ffmpeg -version
ffprobe -version
```

> ⚠️ 加完 PATH 必须**新开终端**（或重启程序）才生效，这是最常见的一次性卡点。

### 第 2 步：拿到 Video2Mp4.exe

从 [Releases](https://github.com/zcy205321334-bit/Video2Mp4/releases) 下载，双击运行。

**当前 Release 尚未发布** —— 可执行文件与源码会一起补上（见[路线图](#-路线图)）。

### （可选）建个开始菜单快捷方式

```powershell
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Video2Mp4.lnk")
$sc.TargetPath = "C:\path\to\Video2Mp4.exe"
$sc.WorkingDirectory = "C:\path\to"
$sc.Save()
```

---

## 🚀 使用

1. 启动 `Video2Mp4.exe`
2. 把视频文件（或整个文件夹）拖进窗口
3. 选一个转换模式 —— 只想换格式就选「**仅换容器**」
4. 需要的话展开「高级」调质量 / 速度 / 编码器
5. 点「开始转换」，等进度条走完
6. 输出文件出现在源目录（或你指定的输出位置）

窗口底部会给出汇总：`完成：N 成功，M 失败`。有失败的点「▶ 显示日志」看详情。

### 小提示

- **H.264 兼容性最广**，H.265 更省空间但老设备可能不认
- 硬件编码需要对应的显卡和驱动；探测不到就自动回落 CPU，不影响可用性
- 首次建议先拿一小段试，确认画质和体积符合预期再批量
- 输出文件名重复时它会自动加序号，**不会覆盖你已有的文件**

---

## 🛠️ 技术栈

| 组件 | 用途 |
|---|---|
| Python 3.11 | 主语言 |
| Tkinter + ttk | GUI（`clam` 主题） |
| tkinterdnd2 | 拖拽支持（内置 win-x64 / win-arm64 原生库） |
| FFmpeg / ffprobe | 转码核心 + 媒体流探测（**外部依赖，需自备**） |
| NVENC / AMF / QSV | NVIDIA / AMD / Intel 硬件编码 |
| libx264 / libx265 | CPU 软件编码 |
| PyInstaller | 打包为单文件 exe |

---

## 🔨 构建

源码公开后（见[路线图](#-路线图)）的构建流程，先占个位：

```bash
# 预期流程
uv venv
uv sync --extra dev
scripts\build.cmd
```

产物预期落在 `output\dist\Video2Mp4.exe`。

---

## 📝 路线图

- [x] 10 种输入格式 → MP4
- [x] 四种转换模式（自动 / 仅换容器 / H.264 / H.265）
- [x] 硬件编码自动探测（NVENC / AMF / QSV）→ CPU 回落
- [x] 仅换容器无损秒转
- [x] 拖拽 + 文件夹递归
- [x] 跟随系统主题实时切换
- [x] 高 DPI 感知
- [ ] **公开源码**
- [ ] **发布首个 Release（含 exe）**
- [ ] 批量队列
- [ ] 暂停 / 继续（当前只有取消）

---

## ❓ 常见问题

**Q：启动提示 `✗ 缺少依赖：ffmpeg 未找到`，开始按钮是灰的？**

没装 FFmpeg，或者装了但没进 PATH。按[安装第 1 步](#第-1-步先装-ffmpeg必须)做，
然后**新开终端**验证 `ffmpeg -version` 有输出。程序需要重启才能读到新的 PATH。

**Q：转出来为什么变大了？**

你选的是重编码模式（H.264 / H.265）。如果只是想要 mp4 这个壳，
改用「**仅换容器**」—— 它不重编码，大小不变。

**Q：为什么用不了硬件加速？**

程序会自己探测。探测不到通常是显卡驱动太旧，或者你的显卡不支持对应的编码器。
探测失败不影响使用，会自动走 CPU。

**Q：会偷偷上传我的视频吗？**

不会。这是个纯本地 GUI，没有联网代码，转码全部由你本机的 FFmpeg 完成。

---

## 📄 许可证

[MIT](./LICENSE) · © 2026 zcy205321334-bit

---

<div align="center">

顺手做的小工具，给和我一样懒得给 Windows 装编解码器的人用。

Made by [@zcy205321334-bit](https://github.com/zcy205321334-bit)

</div>
