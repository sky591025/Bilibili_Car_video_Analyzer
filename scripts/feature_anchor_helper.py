#!/usr/bin/env python3
"""Suggest precise subtitle anchors for feature summaries.

Rules encoded here:
1. Prefer subtitle lines that explicitly mention the feature itself.
2. Prefer lines that include concrete numbers/specs over transition sentences.
3. Penalize generic lead-ins like "首先" / "比如说" / "还有" / "所以".
4. If a summary spans multiple claims, simplify the summary or split the feature.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


TRANSITION_WORDS = (
    "首先",
    "然后",
    "还有",
    "比如说",
    "所以",
    "就是",
    "这个",
    "那个",
    "这里",
    "那边",
    "给你们看",
    "感受一下",
)


@dataclass
class Segment:
    start: str
    end: str
    text: str


def load_srt(path: Path) -> list[Segment]:
    text = path.read_text(encoding="utf-8")
    blocks = [b.strip().splitlines() for b in re.split(r"\n\s*\n", text) if b.strip()]
    items: list[Segment] = []
    for block in blocks:
        if len(block) < 3:
            continue
        items.append(Segment(start=block[1].split(" --> ")[0].replace(",", "."), end=block[1], text=block[2].strip()))
    return items


def score_segment(text: str, keywords: list[str]) -> int:
    score = 0
    lowered = text.lower()
    for kw in keywords:
        if kw.lower() in lowered:
            score += 5 if len(kw) >= 3 else 3
    if re.search(r"\d", text):
        score += 2
    if any(unit in text for unit in ("度", "线", "英寸", "km", "万元", "五座", "六座")):
        score += 2
    if any(word in text for word in TRANSITION_WORDS):
        score -= 2
    if len(text) >= 8:
        score += 1
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest better subtitle timestamps for feature anchors.")
    parser.add_argument("srt", type=Path)
    parser.add_argument("feature", help="Feature name for display only")
    parser.add_argument("keywords", nargs="+", help="Keywords that must align with the anchor sentence")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    segments = load_srt(args.srt)
    ranked = sorted(
        (
            {
                "time": seg.start[:8],
                "text": seg.text,
                "score": score_segment(seg.text, args.keywords),
            }
            for seg in segments
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    output = {
        "feature": args.feature,
        "keywords": args.keywords,
        "top_candidates": [item for item in ranked[: args.top] if item["score"] > 0],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
