#!/usr/bin/env python3
"""Copy markdown report into an Obsidian vault."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def first_existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def resolve_vault_path(cli_vault: str | None, project_root: Path) -> Path:
    if cli_vault:
        return Path(cli_vault).expanduser().resolve()
    env_vault = os.environ.get("OBSIDIAN_VAULT")
    if env_vault:
        return Path(env_vault).expanduser().resolve()

    hint_file = first_existing_path(
        [
            project_root / ".config" / "obsidian_vault_path.txt",
            project_root / ".obsidian_vault_path.txt",
        ]
    )
    if hint_file and hint_file.exists():
        first = hint_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if first:
            p = first[0].strip()
            if p:
                return Path(p).expanduser().resolve()
    raise RuntimeError(
        "未找到Obsidian库路径。请设置--vault或OBSIDIAN_VAULT，或创建 .config/obsidian_vault_path.txt。"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Publish markdown note to Obsidian vault.")
    p.add_argument("markdown", type=Path, help="Markdown file to publish")
    p.add_argument("--vault", type=str, default=None, help="Obsidian vault path")
    p.add_argument("--subdir", type=str, default="", help="Subdirectory inside vault")
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="Project root for config lookup")
    return p


def collect_asset_refs(markdown: str) -> list[str]:
    patterns = (
        r'\((assets/[^)\s]+)\)',
        r'src="(assets/[^"]+)"',
        r'!\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
        r'\[\[(assets/[^\]|]+)(?:\|[^\]]+)?\]\]',
    )
    refs: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for ref in re.findall(pattern, markdown):
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def validate_asset_refs(markdown_path: Path, note_dir: Path, label: str) -> list[str]:
    text = markdown_path.read_text(encoding="utf-8")
    refs = collect_asset_refs(text)
    missing = [ref for ref in refs if not (note_dir / ref).exists()]
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise RuntimeError(f"{label} 缺少引用资源：\n{joined}")
    return refs


def main() -> int:
    args = build_parser().parse_args()
    md = args.markdown.resolve()
    if not md.exists():
        print(f"Markdown不存在: {md}")
        return 2

    try:
        vault = resolve_vault_path(args.vault, args.project_root.resolve())
    except RuntimeError as err:
        print(str(err))
        return 3

    if not vault.exists():
        print(f"Obsidian库路径不存在: {vault}")
        return 4

    try:
        refs = validate_asset_refs(md, md.parent, "发布前校验")
    except RuntimeError as err:
        print(str(err))
        return 5

    target_dir = (vault / args.subdir).resolve() if args.subdir else vault
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / md.name
    shutil.copy2(md, target)

    asset_src = md.parent / "assets" / md.stem
    if asset_src.exists():
        asset_dst_root = target_dir / "assets"
        asset_dst_root.mkdir(parents=True, exist_ok=True)
        asset_dst = asset_dst_root / md.stem
        shutil.copytree(asset_src, asset_dst, dirs_exist_ok=True)
    try:
        validate_asset_refs(target, target_dir, "发布后校验")
    except RuntimeError as err:
        print(str(err))
        return 6
    print(f"validated_asset_refs={len(refs)}")
    print(str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
