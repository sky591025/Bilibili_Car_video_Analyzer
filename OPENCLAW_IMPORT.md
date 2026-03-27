# OpenClaw 导入说明

本项目已按 OpenClaw 的工作区技能目录约定整理好 skill。

当前 skill 位置：

- `./skills/bilibili-video-to-obsidian/`

其中包含：

- `SKILL.md`
- `agents/openai.yaml`

## 推荐方式：作为工作区技能自动加载

如果你把 OpenClaw 的工作区直接指向本项目根目录：

- `E:\BaiduSyncdisk\100 - 工作\150_vibe_coding_Project\Bilibili_Video_to_Obsidian`

则 OpenClaw 应直接从以下目录发现技能：

- `./skills/bilibili-video-to-obsidian/`

也就是现在这个路径：

- `E:\BaiduSyncdisk\100 - 工作\150_vibe_coding_Project\Bilibili_Video_to_Obsidian\skills\bilibili-video-to-obsidian`

这种方式最省事，不需要额外配 `extraDirs`。

## 备用方式：通过 extraDirs 导入

如果你的 OpenClaw 工作区不是这个项目根目录，可以把下面这个目录加入 OpenClaw 的 skills 额外加载目录：

- `E:\BaiduSyncdisk\100 - 工作\150_vibe_coding_Project\Bilibili_Video_to_Obsidian\skills`

然后让 OpenClaw 从该目录扫描 `bilibili-video-to-obsidian/`。

建议加的是 `skills/` 这一层，而不是直接加 skill 内部的 `agents/` 或 `SKILL.md` 文件。

## 目录说明

OpenClaw 导入时主要使用：

- `skills/bilibili-video-to-obsidian/SKILL.md`
- `skills/bilibili-video-to-obsidian/agents/openai.yaml`

项目实际执行脚本仍然在项目根目录下的：

- `scripts/video_note_pipeline.py`
- `scripts/bilibili_subtitle_batch.py`
- `scripts/screenshot.py`
- `scripts/publish_to_obsidian.py`

配置文件在：

- `.config/bili_cookie.txt`
- `.config/obsidian_vault_path.txt`

因此导入后，最好让 OpenClaw 在本项目根目录作为工作区运行；否则 skill 能被发现，但脚本相对路径可能不在预期位置。

## 导入后建议检查

导入完成后，建议确认这几件事：

- OpenClaw 能识别到 skill 名称 `bilibili-video-to-obsidian`
- skill 描述能正常显示
- 工作区根目录就是当前项目根目录
- 项目内存在 `scripts/`、`.config/`、`.video_note_tmp/` 这些目录

## 当前推荐用法

导入后，可让 OpenClaw 直接执行类似任务：

`使用 bilibili-video-to-obsidian skill 分析这个 B 站视频链接，并发布到 Obsidian`

如果你后面要给 OpenClaw 做项目初始化，我建议把它的 workspace 直接设到本项目根目录，这样这套 skill 不需要再做第二次适配。
