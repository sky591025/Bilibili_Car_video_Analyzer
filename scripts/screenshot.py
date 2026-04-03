import argparse
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


TABLE_IMAGE_WIDTH = 300
SCREENSHOT_NAME_RE = re.compile(r"screenshot_(\d{2})_(\d{2})\.(?:jpg|jpeg|png)$", re.IGNORECASE)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def safe_filename(name: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return value or "untitled"


def write_markdown(path: Path, markdown: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    logging.info("Saved note: %s", path)
    return path


def extract_screenshot_markers(markdown: str) -> List[Tuple[str, int]]:
    """
    Match both:
    - Screenshot-[00:03:12]
    - Screenshot-00:03:12
    """
    pattern = r"(?:\*?)Screenshot-(?:\[(\d{2}):(\d{2}):(\d{2})\]|(\d{2}):(\d{2}):(\d{2}))"
    results: List[Tuple[str, int]] = []
    for match in re.finditer(pattern, markdown):
        hh = int(match.group(1) or match.group(4))
        mm = int(match.group(2) or match.group(5))
        ss = int(match.group(3) or match.group(6))
        total_seconds = hh * 3600 + mm * 60 + ss
        results.append((match.group(0), total_seconds))
    return results


def collect_asset_refs(markdown: str) -> List[str]:
    patterns = (
        r'\((assets/[^)\s]+)\)',
        r'src="(assets/[^"]+)"',
        r'!\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
        r'\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
    )
    refs: List[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for ref in re.findall(pattern, markdown):
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def resolve_ffmpeg_path(project_root: Path = PROJECT_ROOT) -> str:
    bundled = project_root / "ffmpeg" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("未找到可用ffmpeg，请安装ffmpeg或imageio-ffmpeg。") from exc


def generate_screenshot(video_path: Path, output_dir: Path, timestamp: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    mm = timestamp // 60
    ss = timestamp % 60
    filename = f"screenshot_{mm:02d}_{ss:02d}.jpg"
    output_path = output_dir / filename

    ffmpeg_path = resolve_ffmpeg_path()
    fast_seek = max(0, timestamp - 3)
    precise_seek = timestamp - fast_seek
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(fast_seek),
        "-i",
        str(video_path),
        # Two-stage seek: fast jump near the target, then accurate seek for the
        # last few seconds to stay aligned with the requested subtitle anchor.
        "-ss",
        str(precise_seek),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
        "-y",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"ffmpeg截图失败: {stderr.strip()}")
    return output_path


def extract_table_image_path(cell: str) -> Optional[str]:
    patterns = (
        r'!\[\]\((assets/[^)]+)\)',
        r'\[截图\]\((assets/[^)]+)\)',
        r'!\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
        r'\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
        r'<img\s+[^>]*src="(assets/[^"]+)"[^>]*>',
    )
    for pattern in patterns:
        match = re.search(pattern, cell)
        if match:
            return match.group(1)
    return None


def render_table_image(path: str, width: int = TABLE_IMAGE_WIDTH) -> str:
    return f'<img src="{path}" alt="timestamp screenshot" width="{width}" />'


def rebase_asset_ref(match: re.Match[str], image_base_url: str, note_folder: str) -> str:
    relative_path = match.group(1).lstrip("/")
    if relative_path.startswith(f"{note_folder}/"):
        return f"(assets/{relative_path})"
    return f"({image_base_url.rstrip('/')}/{relative_path})"


def dedupe_asset_prefixes(markdown: str, note_folder: str) -> str:
    duplicate_prefix = f"assets/{note_folder}/{note_folder}/"
    single_prefix = f"assets/{note_folder}/"
    while duplicate_prefix in markdown:
        markdown = markdown.replace(duplicate_prefix, single_prefix)
    return markdown


def normalize_table_screenshot_cells(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized: List[str] = []
    in_screenshot_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_screenshot_table = False
            normalized.append(line)
            continue

        if "时间戳截图" in line:
            in_screenshot_table = True
            normalized.append(line)
            continue

        if in_screenshot_table and re.match(r"^\|\s*[-: ]+\|", stripped):
            normalized.append(line)
            continue

        if not in_screenshot_table:
            normalized.append(line)
            continue

        cells = line.split("|")
        for idx in range(1, len(cells) - 1):
            cell = cells[idx].strip()
            image_path = extract_table_image_path(cell)
            if image_path:
                cells[idx] = f" {render_table_image(image_path)} "
        normalized.append("|".join(cells))

    return "\n".join(normalized)


def ensure_asset_refs_exist(markdown: str, markdown_dir: Path, output_dir: Path, video_path: Optional[Path]) -> None:
    missing: List[str] = []
    for ref in collect_asset_refs(markdown):
        asset_path = (markdown_dir / ref).resolve()
        if asset_path.exists():
            continue

        match = SCREENSHOT_NAME_RE.search(Path(ref).name)
        if match and video_path:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            timestamp = minutes * 60 + seconds
            generated = generate_screenshot(video_path, output_dir, timestamp)
            if generated.resolve() != asset_path:
                asset_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(generated, asset_path)

        if not asset_path.exists():
            missing.append(ref)

    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise RuntimeError(f"Markdown 引用的截图资源缺失：\n{joined}")


def replace_screenshots(
    markdown: str,
    video_path: Optional[Path],
    output_dir: Path,
    image_base_url: str,
    note_folder: str,
) -> str:
    if not video_path:
        logging.info("未提供视频文件，保留 Screenshot 标记不变。")
        return markdown

    markdown = re.sub(
        r"\((?:output/)?assets/([^)]+)\)",
        lambda m: rebase_asset_ref(m, image_base_url=image_base_url, note_folder=note_folder),
        markdown,
    )

    matches = extract_screenshot_markers(markdown)
    for marker, ts in matches:
        try:
            img_path = generate_screenshot(video_path, output_dir, ts)
            url = f"{image_base_url.rstrip('/')}/{img_path.name}"
            markdown = markdown.replace(marker, f"![]({url})", 1)
        except Exception as exc:  # noqa: BLE001
            logging.warning("生成截图失败（%s）：%s", marker, exc)
    markdown = normalize_table_screenshot_cells(markdown)
    return dedupe_asset_prefixes(markdown, note_folder=note_folder)


def load_session(session_file: Path) -> dict:
    if not session_file.exists():
        return {}
    try:
        return json.loads(session_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_session(session_file: Path, session: dict) -> None:
    session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_markdown(markdown_arg: Optional[Path], work_dir: Path, project_root: Path, session: dict) -> Path:
    if markdown_arg and markdown_arg.exists():
        return markdown_arg.resolve()

    analysis_md = session.get("analysis_md")
    if analysis_md:
        p = Path(analysis_md)
        if p.exists():
            return p.resolve()

    candidates = list(work_dir.glob("*.md")) + list(project_root.glob("*.md")) + list((project_root / "output").glob("*.md"))
    if not candidates:
        raise RuntimeError("未找到可处理的Markdown文件。")

    preferred = next((m for m in candidates if "商业评测解构" in m.name), None)
    if preferred:
        return preferred.resolve()
    return sorted(candidates)[0].resolve()


def pick_video(video_arg: Optional[Path], session: dict) -> Optional[Path]:
    if video_arg and video_arg.exists():
        return video_arg.resolve()

    for key in ("canonical_video_file", "video_file"):
        p = session.get(key)
        if p and Path(p).exists():
            return Path(p).resolve()
    return None


def pick_markdown_strict(markdown_arg: Optional[Path], work_dir: Path, project_root: Path, session: dict) -> Path:
    if markdown_arg and markdown_arg.exists():
        return markdown_arg.resolve()

    work_dir = work_dir.resolve()
    preferred_paths: List[Path] = []
    for key in ("final_markdown", "analysis_md"):
        raw = session.get(key)
        if not raw:
            continue
        p = Path(raw)
        if p.exists() and p.suffix.lower() == ".md":
            preferred_paths.append(p.resolve())

    for candidate in preferred_paths:
        if candidate.parent == work_dir:
            return candidate

    video_title = safe_filename(str(session.get("video_title") or "").strip())
    for candidate in preferred_paths:
        if video_title and candidate.stem == video_title:
            return candidate

    workdir_candidates = sorted(work_dir.glob("*.md"))
    if workdir_candidates:
        exact = next((m for m in workdir_candidates if video_title and m.stem == video_title), None)
        if exact:
            return exact.resolve()
        return workdir_candidates[0].resolve()

    fallback = pick_markdown(markdown_arg, work_dir, project_root, session)
    if fallback.parent == project_root.resolve() and fallback.name.upper().startswith("OPENCLAW_IMPORT"):
        raise RuntimeError("Refusing to use OPENCLAW_IMPORT.md as analysis markdown.")
    return fallback


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="将 Markdown 中的 Screenshot 标记替换为截图并输出最终笔记")
    parser.add_argument("--session-file", type=Path, default=Path(".video_note_tmp/.video_note_session.json"))
    parser.add_argument("--markdown", type=Path, default=None, help="分析Markdown路径（可选）")
    parser.add_argument("--video", type=Path, default=None, help="视频路径（可选）")
    parser.add_argument("--work-dir", type=Path, default=None, help="输出目录（可选）")
    parser.add_argument("--output-name", type=str, default=None, help="输出md文件名（不含后缀，可选）")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    session_file = args.session_file.resolve() if args.session_file.is_absolute() else (project_root / args.session_file).resolve()
    session = load_session(session_file)

    video_title = str(session.get("video_title") or "").strip()
    work_dir = args.work_dir
    if not work_dir:
        work_dir_raw = session.get("work_dir")
        if work_dir_raw:
            work_dir = Path(work_dir_raw)
        else:
            fallback = safe_filename(video_title) if video_title else "output"
            work_dir = project_root / fallback
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    source_md = pick_markdown_strict(args.markdown, work_dir, project_root, session)
    video_path = pick_video(args.video, session)

    markdown = source_md.read_text(encoding="utf-8")
    out_stem = args.output_name or (safe_filename(video_title) if video_title else source_md.stem)
    attachment_folder = safe_filename(out_stem)
    screenshots_dir = work_dir / "assets" / attachment_folder
    processed_md = replace_screenshots(
        markdown,
        video_path=video_path,
        output_dir=screenshots_dir,
        image_base_url=f"assets/{attachment_folder}",
        note_folder=attachment_folder,
    )
    ensure_asset_refs_exist(processed_md, markdown_dir=work_dir, output_dir=screenshots_dir, video_path=video_path)
    output_md = work_dir / f"{out_stem}.md"
    write_markdown(output_md, processed_md)

    session["work_dir"] = str(work_dir)
    session["analysis_md"] = str(source_md)
    session["final_markdown"] = str(output_md)
    session["screenshots_dir"] = str(screenshots_dir)
    if video_path:
        session["video_used_for_screenshot"] = str(video_path)
    save_session(session_file, session)

    print(
        json.dumps(
            {
                "output": str(output_md),
                "screenshots_dir": str(screenshots_dir),
                "video_used_for_screenshot": str(video_path) if video_path else None,
                "source_markdown": str(source_md),
                "work_dir": str(work_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
