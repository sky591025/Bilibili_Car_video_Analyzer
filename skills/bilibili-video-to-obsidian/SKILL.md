---
name: bilibili-video-to-obsidian
description: 接收一个B站视频链接并执行完整流程：下载视频，提取字幕；若无字幕则终止；若有字幕则基于字幕生成商业评测分析 Markdown、补齐截图、并发布到 Obsidian。适用于当前项目内的 B 站视频分析工作流。
---

# Bilibili Video To Obsidian

此 skill 供当前项目直接使用，默认依赖项目根目录下的 `scripts/`、`.config/`、`.video_note_tmp/` 和按视频标题命名的产物目录。

## Quick Start

1. 先运行主流水线：

```powershell
python .\scripts\video_note_pipeline.py "<bilibili-video-url>"
```

2. 如果返回“无字幕，任务终止。”或“字幕源不稳定”，则停止，不得继续伪造分析。
3. 如果成功，读取 `.video_note_tmp/.video_note_session.json` 里的 `subtitle_file`、`video_file`、`work_dir`。
4. 基于字幕完成商业评测分析 Markdown。
5. 运行截图补全：

```powershell
python .\scripts\screenshot.py
```

6. 发布到 Obsidian：

```powershell
python .\scripts\publish_to_obsidian.py "<path-to-note.md>" --subdir "汽车评测/<车型名>"
```

## Workflow

### 1. 创建或复用视频工作目录

先运行 `scripts/video_note_pipeline.py`。它会：

- 下载视频到临时目录
- 提取字幕到临时目录
- 将最终 `mp4`、`srt` 归档到 `./<视频标题>/`
- 写入 `.video_note_tmp/.video_note_session.json`

最终工作目录固定为：

`./<视频标题>/`

其中应包含：

- `<视频标题>.md`
- `<视频标题>.mp4`
- `<视频标题>.srt`
- `assets/<视频标题>/`

### 2. 分析规则

必须基于 `subtitle_file` 输出完整分析，不得只靠视频标题或简介猜测内容。

分析时遵守这些硬规则：

- 若无字幕，立即终止，不做 ASR 兜底分析
- 时间戳必须对应“功能点被明确解释/参数被明确说出/价值被明确表达”的语句
- 禁止用“我们看这里”“这个地方”“接下来再说”等过渡句做截图锚点
- 若一句里出现明确数字、规格、容量、角度、线数或参数，优先选这一句
- 截图与时间戳必须严格一一对应，不可错位

### 3. 截图与 Markdown 规则

运行 `scripts/screenshot.py` 后，必须满足：

- 所有截图都保存在 `assets/<笔记文件名>/`
- Markdown 中的图片路径统一为 `assets/<笔记文件名>/<截图文件名>`
- “时间戳截图”列必须直接显示图片，而不是“截图”文字链接
- 若 Markdown 已引用某张截图但本地 `assets/<笔记文件名>/` 中不存在对应文件，必须先补齐再发布

截图占位符格式固定为：

`Screenshot-[hh:mm:ss]`

截图源稿选择还必须满足：
- 优先使用 `--markdown` 显式传入的分析稿
- 若未显式传入，则优先使用 session 中 `final_markdown` 或 `analysis_md` 指向的、且位于当前 `work_dir` 内的 Markdown
- 若 session 中记录的 Markdown 不在当前视频工作目录内，不得直接采用
- 禁止把项目根目录中的说明文档、导入文档、README 一类文件当成分析稿
- 若候选 Markdown 指向 `OPENCLAW_IMPORT.md`、`README.md` 或其他非视频分析文件，应立即停止并修正输入，再继续截图

### 4. 发布到 Obsidian

运行 `scripts/publish_to_obsidian.py` 时，库路径按以下顺序解析：

1. `--vault`
2. `OBSIDIAN_VAULT`
3. `.config/obsidian_vault_path.txt`

发布前后都必须校验图片资源是否完整；若缺图，视为发布失败。

### 5. 项目目录整理规则

- 所有可执行 Python 脚本统一放在 `scripts/`
- 配置文件统一放在 `.config/`：`bili_cookie.txt`、`obsidian_vault_path.txt`
- 会话态与临时中间产物统一放在 `.video_note_tmp/`
- 每条视频的最终产物统一放在 `./<视频标题>/`
- `downloads/`、`subtitles_out/`、`tmp_*`、`__pycache__/` 这类过程目录在验收完成后应删除
- 不再把最终产物存到 `video_artifacts/`

## Project Resources

### scripts/

- `video_note_pipeline.py`：下载视频、提取字幕、归档产物、写 session
- `bilibili_subtitle_batch.py`：字幕提取主脚本
- `screenshot.py`：按时间戳生成截图并修正 Markdown 图片引用
- `publish_to_obsidian.py`：发布 Markdown 到 Obsidian 并校验资源
- `feature_anchor_helper.py`：辅助挑选更准确的功能锚点

## Failure Handling

- 若字幕提取失败，明确返回失败原因，不继续分析
- 若截图缺失，优先补生成；补不出来则终止发布
- 若截图阶段发现源 Markdown 不是当前视频目录中的分析稿，必须先纠正 `session` 或显式传入 `--markdown`，不得继续沿用错误源稿
- 若 Obsidian 路径不存在或未配置，停止在发布步骤，不得伪称已发布
- 若发现项目结构与本 skill 文档不一致，应优先更新 skill 再继续运行
