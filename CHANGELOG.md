# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

- 界面截图与演示动图
- 批量队列
- 暂停 / 继续（当前只有取消）

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
