# bilibili-video-to-obsidian

一个适用于 OpenClaw 工作区的 Bilibili 视频分析 skill。

它会围绕一个 B 站视频链接执行完整工作流：

- 下载视频
- 提取字幕
- 无字幕则立即终止
- 基于字幕生成商业评测分析 Markdown
- 自动补齐时间戳截图
- 校验图片资源
- 发布到 Obsidian

## Repository Layout

```text
.
├─ skills/
│  └─ bilibili-video-to-obsidian/
│     ├─ SKILL.md
│     └─ agents/
│        └─ openai.yaml
├─ scripts/
│  ├─ video_note_pipeline.py
│  ├─ bilibili_subtitle_batch.py
│  ├─ screenshot.py
│  ├─ publish_to_obsidian.py
│  └─ feature_anchor_helper.py
├─ .config/
│  ├─ obsidian_vault_path.txt.example
│  └─ bili_cookie.txt.example
└─ OPENCLAW_IMPORT.md
```

## Prerequisites

- `python3`
- `yt-dlp`
- `ffmpeg`

## OpenClaw Usage

推荐把这个仓库本身作为 OpenClaw 的 workspace 根目录。

OpenClaw 会自动从：

```text
./skills/bilibili-video-to-obsidian/
```

发现 skill。

如果你的 OpenClaw workspace 不在这个仓库里，也可以把本仓库的 `skills/` 目录加入 `skills.load.extraDirs`。

## Required Config

1. 复制：

```text
.config/obsidian_vault_path.txt.example
```

为：

```text
.config/obsidian_vault_path.txt
```

并写入你自己的 Obsidian vault 绝对路径。

2. 如需带登录态抓取 Bilibili 字幕，再复制：

```text
.config/bili_cookie.txt.example
```

为：

```text
.config/bili_cookie.txt
```

并填入原始 Cookie header。

## Quick Start

```powershell
python .\scripts\video_note_pipeline.py "<bilibili-video-url>"
python .\scripts\screenshot.py
python .\scripts\publish_to_obsidian.py "<path-to-note.md>" --subdir "汽车评测/<车型名>"
```

## Notes

- 最终产物目录采用 `./<视频标题>/`
- 截图资源统一保存到 `assets/<笔记文件名>/`
- 表格中的“时间戳截图”列直接显示图片
- 截图阶段会优先锁定当前视频工作目录中的分析稿，避免误读 `README` 或导入说明文档
- 发布前后都会校验图片资源是否完整

更完整的导入说明见 [OPENCLAW_IMPORT.md](./OPENCLAW_IMPORT.md)。
