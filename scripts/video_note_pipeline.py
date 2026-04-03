#!/usr/bin/env python3
"""Download Bilibili video and extract subtitles for note generation.

Flow:
1) Download video with yt-dlp
2) Extract subtitles with bilibili_subtitle_batch.py
3) If no subtitles, print message and stop
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PipelineError(RuntimeError):
    """Pipeline execution error."""


class NoSubtitleError(PipelineError):
    """No subtitle found for this video."""


@dataclass
class PipelineResult:
    url: str
    video_title: str
    work_dir: Path
    video_file: Path
    subtitle_file: Path
    canonical_video_file: Path
    canonical_subtitle_file: Path


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".flv", ".mov"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def safe_filename(name: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return value or "untitled"


def pick_existing_path_from_stdout(stdout: str) -> Path | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    existing: list[Path] = []
    for line in lines:
        candidate = Path(line)
        if candidate.exists():
            existing.append(candidate.resolve())
    if not existing:
        return None

    video_candidates = [p for p in existing if p.suffix.lower() in VIDEO_EXTS]
    if video_candidates:
        return video_candidates[-1]
    return existing[-1]


def download_video(url: str, download_dir: Path, cwd: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    out_tpl = str(download_dir / "%(title)s [%(id)s].%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-o",
        out_tpl,
        "--print",
        "after_move:filepath",
        url,
    ]
    proc = run_cmd(cmd, cwd)
    if proc.returncode != 0:
        raise PipelineError(f"yt-dlp下载失败:\n{proc.stderr.strip() or proc.stdout.strip()}")

    video_path = pick_existing_path_from_stdout(proc.stdout)
    if not video_path:
        candidates = sorted(download_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        video_candidates = [p for p in candidates if p.suffix.lower() in VIDEO_EXTS]
        if video_candidates:
            video_path = video_candidates[0].resolve()
        elif candidates:
            video_path = candidates[0].resolve()
    if not video_path:
        raise PipelineError("视频下载成功状态未知，未找到输出文件。")
    return video_path


def parse_subtitle_saved_path(output: str) -> Path | None:
    # Matches: [OK] saved: path
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("[OK] saved:"):
            path = line.split(":", 1)[1].strip()
            if path:
                p = Path(path)
                if p.exists():
                    return p.resolve()
    return None


def infer_video_title(video_file: Path) -> str:
    stem = video_file.stem
    stem = re.sub(r"\.f\d+$", "", stem)
    m = re.match(r"^(?P<title>.+?)\s+\[(BV[0-9A-Za-z]{10})\]$", stem)
    if m:
        return m.group("title").strip()
    return stem.strip() or "untitled"


def bundle_artifacts(
    root: Path,
    bundle_root: Path,
    video_title: str,
    video_file: Path,
    subtitle_file: Path,
) -> tuple[Path, Path, Path]:
    title_fs = safe_filename(video_title)
    work_dir = resolve_under_root(root, bundle_root) / title_fs
    work_dir.mkdir(parents=True, exist_ok=True)

    canonical_video = work_dir / f"{title_fs}{video_file.suffix.lower()}"
    canonical_subtitle = work_dir / f"{title_fs}.srt"

    shutil.copy2(video_file, canonical_video)
    shutil.copy2(subtitle_file, canonical_subtitle)
    return work_dir.resolve(), canonical_video.resolve(), canonical_subtitle.resolve()


def extract_subtitle(
    url: str,
    subtitle_script: Path,
    subtitle_dir: Path,
    cwd: Path,
    cookie_file: Path | None = None,
) -> Path:
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(subtitle_script), url, "-o", str(subtitle_dir), "--sleep", "0"]
    if cookie_file:
        cmd.extend(["--cookie-file", str(cookie_file)])
    proc = run_cmd(cmd, cwd)

    saved = parse_subtitle_saved_path(proc.stdout)
    if saved:
        return saved

    candidates = sorted(subtitle_dir.glob("*.srt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if proc.returncode == 0 and candidates:
        return candidates[0].resolve()

    text = (proc.stdout + "\n" + proc.stderr).strip()
    if "No subtitles track found" in text or "no subtitle" in text.lower():
        raise NoSubtitleError("无字幕，任务终止。")
    if "Subtitle source is unstable" in text:
        raise NoSubtitleError("字幕源不稳定（疑似串字幕），任务终止。")
    raise NoSubtitleError("无字幕，任务终止。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download video and extract subtitle for analysis.")
    parser.add_argument("url", help="Single Bilibili video URL")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Project root directory",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path(".video_note_tmp/downloads"),
        help="Temporary video download directory (relative to project root if not absolute)",
    )
    parser.add_argument(
        "--subtitle-dir",
        type=Path,
        default=Path(".video_note_tmp/subtitles_out"),
        help="Temporary subtitle output directory (relative to project root if not absolute)",
    )
    parser.add_argument(
        "--subtitle-script",
        type=Path,
        default=Path("scripts/bilibili_subtitle_batch.py"),
        help="Path to bilibili_subtitle_batch.py (relative to project root if not absolute)",
    )
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=Path("."),
        help="Root folder for per-video artifact folders (relative to project root if not absolute)",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=None,
        help="Optional Bilibili cookie file (defaults to .config/bili_cookie.txt when present)",
    )
    parser.add_argument(
        "--session-file",
        type=Path,
        default=Path(".video_note_tmp/.video_note_session.json"),
        help="Where to write pipeline session json",
    )
    return parser


def resolve_under_root(root: Path, p: Path) -> Path:
    return p if p.is_absolute() else (root / p)


def discover_cookie_file(root: Path) -> Path | None:
    for candidate in (
        root / ".config" / "bili_cookie.txt",
        root / "bili_cookie.txt",
    ):
        if candidate.exists():
            return candidate.resolve()
    return None


def validate_bilibili_cookie(cookie_file: Path | None) -> dict:
    if not cookie_file or not cookie_file.exists():
        raise PipelineError("Bilibili login cookie is required. Please update .config/bili_cookie.txt.")

    cookie = cookie_file.read_text(encoding="utf-8", errors="replace").strip()
    if not cookie:
        raise PipelineError("Bilibili login cookie is empty. Please update .config/bili_cookie.txt.")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Cookie": cookie,
    }
    req = Request("https://api.bilibili.com/x/web-interface/nav", headers=headers, method="GET")
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as err:
        raise PipelineError(f"Bilibili auth check failed with HTTP {err.code}.") from err
    except URLError as err:
        raise PipelineError(f"Bilibili auth check network error: {err}.") from err
    except json.JSONDecodeError as err:
        raise PipelineError("Bilibili auth check returned invalid JSON.") from err

    nav_data = payload.get("data") or {}
    if payload.get("code") != 0 or not nav_data.get("isLogin"):
        message = payload.get("message") or "not logged in"
        raise PipelineError(f"Bilibili cookie is invalid or logged out: {message}")
    return nav_data


def remove_file_if_exists(path: Path | None) -> None:
    if not path or not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        pass


def remove_dir_if_empty(path: Path | None) -> None:
    if not path or not path.exists() or not path.is_dir():
        return
    try:
        path.rmdir()
    except OSError:
        pass


def main() -> int:
    args = build_parser().parse_args()
    root = args.project_root.resolve()
    download_dir = resolve_under_root(root, args.download_dir)
    subtitle_dir = resolve_under_root(root, args.subtitle_dir)
    subtitle_script = resolve_under_root(root, args.subtitle_script)
    bundle_root = resolve_under_root(root, args.bundle_root)
    session_file = resolve_under_root(root, args.session_file)
    cookie_file = resolve_under_root(root, args.cookie_file) if args.cookie_file else discover_cookie_file(root)

    if not subtitle_script.exists():
        print(f"字幕脚本不存在: {subtitle_script}")
        return 2

    try:
        nav_data = validate_bilibili_cookie(cookie_file)
        uname = str(nav_data.get("uname") or "").strip() or "unknown"
        print(f"[AUTH] logged in as: {uname}")
    except PipelineError as err:
        print(f"娴佺▼澶辫触: {err}")
        return 1

    video_file: Path | None = None
    subtitle_file: Path | None = None
    canonical_video: Path | None = None
    canonical_subtitle: Path | None = None
    try:
        video_file = download_video(args.url, download_dir, root)
        subtitle_file = extract_subtitle(
            args.url, subtitle_script=subtitle_script, subtitle_dir=subtitle_dir, cwd=root, cookie_file=cookie_file
        )
        video_title = infer_video_title(video_file)
        work_dir, canonical_video, canonical_subtitle = bundle_artifacts(
            root=root,
            bundle_root=bundle_root,
            video_title=video_title,
            video_file=video_file,
            subtitle_file=subtitle_file,
        )
        result = PipelineResult(
            url=args.url,
            video_title=video_title,
            work_dir=work_dir,
            video_file=video_file,
            subtitle_file=subtitle_file,
            canonical_video_file=canonical_video,
            canonical_subtitle_file=canonical_subtitle,
        )
        payload = {
            "url": result.url,
            "video_title": result.video_title,
            "work_dir": str(result.work_dir),
            "video_file": str(result.canonical_video_file),
            "subtitle_file": str(result.canonical_subtitle_file),
            "canonical_video_file": str(result.canonical_video_file),
            "canonical_subtitle_file": str(result.canonical_subtitle_file),
            "project_root": str(root),
        }
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except NoSubtitleError as err:
        print(str(err))
        return 20
    except PipelineError as err:
        print(f"流程失败: {err}")
        return 1
    finally:
        if canonical_video and video_file and video_file.resolve() != canonical_video.resolve():
            remove_file_if_exists(video_file)
        if canonical_subtitle and subtitle_file and subtitle_file.resolve() != canonical_subtitle.resolve():
            remove_file_if_exists(subtitle_file)
        remove_dir_if_empty(download_dir)
        remove_dir_if_empty(subtitle_dir)
        common_temp_root = download_dir.parent if download_dir.parent == subtitle_dir.parent else None
        remove_dir_if_empty(common_temp_root)


if __name__ == "__main__":
    sys.exit(main())
