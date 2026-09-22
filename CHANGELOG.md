# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

- 界面截图与演示动图
- 批量队列
- 暂停 / 继续（当前只有取消）

## [0.2.1] — 2026-09-22

### 修复

- **中文 / 非 ASCII 路径整批探测失败**：中文 Windows 默认代码页（cp936）下，`probe_streams` 用 `text=True` 解码 ffprobe 的 UTF-8 输出会失败，`r.stdout` 变 `None` 后 `json.loads` 抛 `TypeError`，导致含中文文件名的视频全部显示「探测失败」。改为字节捕获 + 显式 UTF-8 解码，并把错误分级说清：退出码非零（附 stderr 摘要）/ 无输出 / 非法 UTF-8 / 非法 JSON，不再让 `NoneType` 掩盖真实原因
- 其余 ffmpeg / ffprobe 子进程读取统一显式 UTF-8（编码器探测、硬件冒烟测试、进度读取），错误摘要用 `errors="replace"`
- 验收套件在 cp936 控制台打印 `✓` / `✗` 会 `UnicodeEncodeError` 中止的测试框架问题（仅测试输出，不影响产品）

### 新增

- 回归测试 `tests/test_probe_utf8.py`（7 项，真实 ffprobe）、`tests/test_probe_errorhandling.py`（7 项，含缺依赖、故障注入、非法 JSON/UTF-8、超时）
- `requirements-dev.txt` 与 `tools/`：可审查、可重复的构建流程（全新 venv → tkinterdnd2 1.7.3 的 Py3.13 兼容补丁 → PyInstaller → SHA256）

## [0.2.0] — 2026-09-18

### 新增

- **公开源码**：`mov2mp4.py`（主程序 GUI）、`core.py`（转码核心）、`theme.py`（主题）
- **六个测试**：`acceptance_smoke`（33 项验收）、`acceptance_theme`（19 项）、四个回归测试
- **构建配置**：`Video2Mp4.spec`（PyInstaller）、`assets/Video2Mp4.manifest`（DPI PerMonitorV2）、`requirements.txt`

### 说明

- 源码由开发会话记录重放恢复，经语法校验（9/9）、自带验收测试（smoke 33/34，唯一未过项为性能阈值、theme 19/19）、与已发布 exe 的字符串交叉验证（关键符号 21/21）

## [0.1.0] — 2026-09-18

首个公开版本。

### 新增

- **四种转换模式**：自动 / 仅换容器（无损秒转）/ H.264 兼容 / H.265 压缩
- **输入格式 10 种**：`.mov` `.mp4` `.mkv` `.avi` `.m4v` `.flv` `.wmv` `.ts` `.webm` `.3gp`
- **硬件编码自动探测**：NVENC(NVIDIA) / AMF(AMD) / QSV(Intel)，回落 CPU libx264 / libx265
- **高级参数**：质量 CRF、编码速度 preset（九档）、编码器选择
- **拖拽添加**（tkinterdnd2）+ 文件夹递归
- **输出位置可选**（留空 = 与源同目录）
- **可取消**：单一 CancelToken 贯穿全程
- **实时跟随 Windows 浅色 / 深色主题**
- **高 DPI 感知**（PerMonitorV2）
- 五列文件列表、可折叠日志、失败摘要
- 输出重名自动加序号，不覆盖已有文件

### 说明

- ⚠️ **不内置 FFmpeg**，需用户自备并加入 PATH，否则启动即禁用开始按钮
- 本版本未附带源码，后续单独公开
- 仅支持 Windows 10 / 11（x64）
