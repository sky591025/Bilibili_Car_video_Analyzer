#!/usr/bin/env python3
"""Batch extract Bilibili subtitles to SRT.

Implemented by reverse-reading SubBatch CRX request flow:
view -> player subtitle list -> subtitle_url -> subtitle json body -> srt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class VideoTarget:
    raw_url: str
    bvid: str
    page: int


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return name or "untitled"


def parse_video_target(url: str) -> VideoTarget:
    u = url.strip()
    if not u:
        raise ValueError("Empty URL")

    bvid_match = re.search(r"(BV[0-9A-Za-z]{10})", u)
    if not bvid_match:
        raise ValueError(f"Cannot find BV id from URL: {u}")
    bvid = bvid_match.group(1)

    parsed = urlparse(u)
    query = parse_qs(parsed.query)
    page = 1
    if "p" in query:
        try:
            page = max(1, int(query["p"][0]))
        except (TypeError, ValueError):
            page = 1
    return VideoTarget(raw_url=u, bvid=bvid, page=page)


def discover_cookie_file() -> Path | None:
    for candidate in (
        PROJECT_ROOT / ".config" / "bili_cookie.txt",
        PROJECT_ROOT / "bili_cookie.txt",
    ):
        if candidate.exists():
            return candidate
    return None


class BilibiliClient:
    def __init__(self, cookie: str | None = None, timeout: int = 20) -> None:
        self.cookie = cookie.strip() if cookie else None
        self.timeout = timeout

    def _request_json(self, url: str) -> dict[str, Any]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return json.loads(data)
        except HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} for {url}") from e
        except URLError as e:
            raise RuntimeError(f"Network error for {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON from {url}") from e

    def _request_subtitle_json(self, url: str, bvid: str) -> dict[str, Any]:
        normalized = normalize_subtitle_url(url)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "Origin": "https://www.bilibili.com",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        req = Request(normalized, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return json.loads(data)
        except HTTPError as e:
            raise RuntimeError(f"Subtitle HTTP {e.code} for {normalized}") from e
        except URLError as e:
            raise RuntimeError(f"Subtitle network error for {normalized}: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid subtitle JSON: {normalized}") from e

    def fetch_view_info(self, bvid: str) -> dict[str, Any]:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        data = self._request_json(url)
        if data.get("code") != 0 or "data" not in data:
            raise RuntimeError(f"view API failed for {bvid}: {data.get('message', 'unknown')}")
        return data["data"]

    def fetch_nav_info(self) -> dict[str, Any]:
        return self._request_json("https://api.bilibili.com/x/web-interface/nav")

    def fetch_subtitle_list(self, bvid: str, aid: int, cid: int) -> list[dict[str, Any]]:
        # Prefer v2 first; fallback to wbi/v2.
        urls = [
            f"https://api.bilibili.com/x/player/v2?cid={cid}&bvid={bvid}",
            f"https://api.bilibili.com/x/player/wbi/v2?aid={aid}&cid={cid}",
        ]
        last_error = None
        for url in urls:
            try:
                data = self._request_json(url)
                if data.get("code") != 0 or "data" not in data:
                    last_error = RuntimeError(
                        f"subtitle list API error: {data.get('message', 'unknown')} ({url})"
                    )
                    continue
                subtitles = (((data.get("data") or {}).get("subtitle") or {}).get("subtitles")) or []
                return subtitles
            except Exception as e:  # noqa: BLE001
                last_error = e
        if last_error:
            raise RuntimeError(str(last_error))
        return []

    def fetch_ai_subtitle_url(self, aid: int, cid: int) -> str | None:
        url = f"https://api.bilibili.com/x/player/v2/ai/subtitle/search/stat?aid={aid}&cid={cid}"
        data = self._request_json(url)
        if data.get("code") == 0:
            return ((data.get("data") or {}).get("subtitle_url")) or None
        return None

    def fetch_subtitle_body(self, bvid: str, subtitle_url: str) -> list[dict[str, Any]]:
        data = self._request_subtitle_json(subtitle_url, bvid)
        # AI subtitle format.
        if data.get("type") == "AIsubtitle" and isinstance(data.get("body"), list):
            return data["body"]
        body = data.get("body")
        if not isinstance(body, list):
            raise RuntimeError("Subtitle JSON has no valid body list")
        return body


def normalize_subtitle_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url.lstrip("/")


def validate_login_or_raise(client: BilibiliClient) -> dict[str, Any]:
    if not client.cookie:
        raise RuntimeError("Bilibili login cookie is required. Please update .config/bili_cookie.txt.")

    data = client.fetch_nav_info()
    nav_data = data.get("data") or {}
    if data.get("code") != 0 or not nav_data.get("isLogin"):
        message = data.get("message") or "not logged in"
        raise RuntimeError(f"Bilibili cookie is invalid or logged out: {message}")
    return nav_data


def pick_track(subtitles: list[dict[str, Any]], lang_order: list[str]) -> dict[str, Any] | None:
    if not subtitles:
        return None
    for lang in lang_order:
        for track in subtitles:
            if track.get("lan") == lang:
                return track
    for track in subtitles:
        lan = str(track.get("lan", ""))
        if lan.startswith("zh") or lan.startswith("ai-zh"):
            return track
    return subtitles[0]


def track_priority(track: dict[str, Any], aid: int, cid: int) -> int:
    lan = str(track.get("lan") or "")
    subtitle_url = str(track.get("subtitle_url") or "").strip()
    track_type = int(track.get("type") or 0)

    # Highest confidence: non-AI / platform subtitle JSON.
    if track_type == 0 and "/bfs/subtitle/" in normalize_subtitle_url(subtitle_url):
        return 4
    # Current-video AI subtitle URL that embeds aid+cid.
    if lan.startswith("ai-") and is_ai_subtitle_url_for_current_video(subtitle_url, aid, cid):
        return 3
    # Other non-AI tracks still beat generic AI output.
    if not lan.startswith("ai-"):
        return 2
    # Generic AI subtitle URLs are the least trustworthy because Bilibili can
    # occasionally return cross-video content for them.
    return 1


def iter_tracks_by_preference(
    subtitles: list[dict[str, Any]], lang_order: list[str], aid: int, cid: int
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    chosen = pick_track(subtitles, lang_order)
    if chosen:
        ordered.append(chosen)
        seen_ids.add(str(chosen.get("id") or id(chosen)))

    for lang in lang_order:
        same_lang = [t for t in subtitles if str(t.get("lan") or "") == lang]
        same_lang.sort(key=lambda t: track_priority(t, aid, cid), reverse=True)
        for track in same_lang:
            marker = str(track.get("id") or id(track))
            if marker not in seen_ids:
                ordered.append(track)
                seen_ids.add(marker)

    remaining = [t for t in subtitles if str(t.get("id") or id(t)) not in seen_ids]
    remaining.sort(
        key=lambda t: (
            track_priority(t, aid, cid),
            -(lang_order.index(str(t.get("lan") or "")) if str(t.get("lan") or "") in lang_order else 999),
        ),
        reverse=True,
    )
    ordered.extend(remaining)
    return ordered


def sec_to_srt_time(sec: float) -> str:
    ms_total = int(round(sec * 1000))
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def body_to_srt(body: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for idx, row in enumerate(body, start=1):
        start = float(row.get("from", 0.0))
        end = float(row.get("to", start))
        text = str(row.get("content", "")).strip()
        if not text:
            continue
        chunks.append(f"{idx}\n{sec_to_srt_time(start)} --> {sec_to_srt_time(end)}\n{text}\n")
    return "\n".join(chunks).strip() + "\n"


def subtitle_signature(body: list[dict[str, Any]], take_lines: int = 8) -> str:
    parts: list[str] = []
    for row in body[:take_lines]:
        parts.append(str(row.get("content", "")).strip())
    return "|".join(parts)


def is_ai_subtitle_url_for_current_video(url: str, aid: int, cid: int) -> bool:
    if not url:
        return False
    norm = normalize_subtitle_url(url)
    marker = f"{aid}{cid}"
    if marker in norm:
        return True
    m = re.search(r"/prod/([^?/#]+)", norm)
    if m and str(cid) in m.group(1):
        return True
    return False


def fetch_stable_subtitle_body(
    client: BilibiliClient,
    bvid: str,
    aid: int,
    cid: int,
    lang_order: list[str],
    attempts: int = 12,
    min_consensus: int = 2,
) -> tuple[list[dict[str, Any]], str]:
    # signature -> (count, body, lan, strength)
    candidates: dict[str, tuple[int, list[dict[str, Any]], str, int]] = {}
    last_error: Exception | None = None

    for _ in range(max(1, attempts)):
        try:
            tracks = client.fetch_subtitle_list(bvid, aid, cid)
            if not tracks:
                raise RuntimeError("No subtitles track found")
            selected_any = False
            for chosen in iter_tracks_by_preference(tracks, lang_order, aid, cid):
                subtitle_url = str(chosen.get("subtitle_url") or "").strip()
                lan = str(chosen.get("lan") or "unknown")
                if not subtitle_url and lan.startswith("ai-"):
                    try:
                        subtitle_url = client.fetch_ai_subtitle_url(aid, cid) or ""
                    except Exception:
                        subtitle_url = ""
                if not subtitle_url:
                    continue

                strength = track_priority(chosen, aid, cid)
                # Generic AI subtitles are too error-prone; only use them when no
                # safer candidate was found after all retries.
                if strength <= 1:
                    continue

                body = client.fetch_subtitle_body(bvid, subtitle_url)
                if not body:
                    continue

                sig = subtitle_signature(body)
                if sig in candidates:
                    count, _, prev_lan, prev_strength = candidates[sig]
                    candidates[sig] = (count + 1, body, prev_lan, max(prev_strength, strength))
                else:
                    candidates[sig] = (1, body, lan, strength)
                selected_any = True

                if strength >= 3:
                    return body, lan
                if strength >= 2 and candidates[sig][0] >= min_consensus:
                    return body, lan

            if not selected_any:
                last_error = RuntimeError("No reliable subtitle track found in current response")
        except Exception as err:  # noqa: BLE001
            last_error = err
            continue

    if candidates:
        best_sig = max(candidates.items(), key=lambda kv: (kv[1][3], kv[1][0]))
        best_count, best_body, best_lan, best_strength = best_sig[1]
        if best_strength >= 3:
            return best_body, best_lan
        if best_strength >= 2 and best_count >= min_consensus:
            return best_body, best_lan
        raise RuntimeError("Subtitle source is unstable (no reliable current-video subtitle track)")
    if last_error:
        raise RuntimeError(str(last_error))
    raise RuntimeError("Failed to fetch subtitle body")


def read_inputs(urls: list[str], input_file: Path | None) -> list[str]:
    items = [u.strip() for u in urls if u.strip()]
    if input_file:
        text = input_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            items.append(line)
    return items


def choose_cid(view_data: dict[str, Any], page: int) -> tuple[int, str]:
    pages = view_data.get("pages") or []
    title = str(view_data.get("title") or "untitled")
    if pages and isinstance(pages, list):
        idx = min(max(page, 1), len(pages)) - 1
        page_obj = pages[idx] or {}
        cid = int(page_obj.get("cid") or 0)
        part = str(page_obj.get("part") or "").strip()
        if cid:
            if part:
                return cid, f"{title} - {part}"
            return cid, title
    cid = int(view_data.get("cid") or 0)
    return cid, title


def process_one(
    client: BilibiliClient,
    target: VideoTarget,
    out_dir: Path,
    lang_order: list[str],
    sleep_sec: float = 0.0,
) -> tuple[bool, str]:
    view = client.fetch_view_info(target.bvid)
    aid = int(view.get("aid") or 0)
    if not aid:
        raise RuntimeError(f"Cannot get aid for {target.bvid}")
    cid, file_title = choose_cid(view, target.page)
    if not cid:
        raise RuntimeError(f"Cannot get cid for {target.bvid}")

    body, lan = fetch_stable_subtitle_body(client, target.bvid, aid, cid, lang_order)
    srt_text = body_to_srt(body)

    filename = f"{safe_filename(file_title)}__{target.bvid}__p{target.page}__{lan}.srt"
    out_path = out_dir / filename
    out_path.write_text(srt_text, encoding="utf-8")
    if sleep_sec > 0:
        time.sleep(sleep_sec)
    return True, str(out_path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch download Bilibili subtitles to SRT (reverse-engineered from SubBatch CRX)."
    )
    p.add_argument("urls", nargs="*", help="Bilibili video URLs")
    p.add_argument("-i", "--input", type=Path, help="Text file with URLs (one per line)")
    p.add_argument("-o", "--out", type=Path, default=PROJECT_ROOT / ".video_note_tmp" / "subtitles_out", help="Output directory")
    p.add_argument("--cookie", type=str, default=None, help="Raw Bilibili cookie string")
    p.add_argument(
        "--cookie-file",
        type=Path,
        default=None,
        help="Path of cookie text file (if set, overrides --cookie; defaults to .config/bili_cookie.txt when present)",
    )
    p.add_argument(
        "--lang-order",
        type=str,
        default="zh-CN,zh-Hans,zh-Hant,ai-zh",
        help="Comma-separated subtitle language priority",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Sleep seconds between each item",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    urls = read_inputs(args.urls, args.input)
    if not urls:
        parser.error("Need at least one URL or --input file")

    cookie = args.cookie
    if args.cookie_file:
        cookie = args.cookie_file.read_text(encoding="utf-8", errors="replace").strip()
    else:
        discovered_cookie = discover_cookie_file()
        if discovered_cookie:
            cookie = discovered_cookie.read_text(encoding="utf-8", errors="replace").strip()

    args.out.mkdir(parents=True, exist_ok=True)
    lang_order = [x.strip() for x in args.lang_order.split(",") if x.strip()]

    client = BilibiliClient(cookie=cookie)
    try:
        nav_data = validate_login_or_raise(client)
        uname = str(nav_data.get("uname") or "").strip() or "unknown"
        print(f"[AUTH] logged in as: {uname}")
    except Exception as e:  # noqa: BLE001
        print(f"[AUTH FAIL] {e}")
        return 2

    success = 0
    failed = 0

    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] {url}")
        try:
            target = parse_video_target(url)
            ok, path = process_one(client, target, args.out, lang_order, sleep_sec=args.sleep)
            if ok:
                success += 1
                print(f"  [OK] saved: {path}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {e}")

    print(f"\nDone. success={success}, failed={failed}, out={args.out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
