"""dj-cratedigger: Spotify playlist link in, folder of DJ-ready audio files out."""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import List, Optional, Tuple

from . import __version__
from .downloader import FORMATS, Downloader, existing, safe_filename
from .spotify import Collection, Track, fetch

_print_lock = Lock()


def say(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cratedigger",
        description="Turn a Spotify playlist (or album) link into a folder of tagged audio files for your DJ library.",
    )
    p.add_argument("link", help="Spotify playlist or album URL / URI")
    p.add_argument("-o", "--out", default="crates", help="parent folder for downloads (default: ./crates)")
    p.add_argument("-f", "--format", default="mp3", choices=sorted(FORMATS), help="audio format (default: mp3)")
    p.add_argument("-j", "--jobs", type=int, default=3, help="tracks to download at once (default: 3)")
    p.add_argument("--dry-run", action="store_true", help="show the match for every track without downloading")
    p.add_argument("--verbose", action="store_true", help="show yt-dlp output")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def process(dl: Downloader, track: Track, i: int, total: int, dry_run: bool) -> Tuple[Track, Optional[Path], str]:
    tag = f"[{i:>3}/{total}]"
    found = existing(dl.out_dir, track, dl.fmt)
    if found:
        say(f"{tag} = {track.display} (already in crate)")
        return track, found, "skipped"
    try:
        cand = dl.find(track)
    except Exception as e:  # network hiccups, age-gated results, etc.
        say(f"{tag} ! {track.display}: search failed ({e})")
        return track, None, "error"
    if not cand:
        say(f"{tag} ? {track.display}: no confident match")
        return track, None, "missing"
    if dry_run:
        say(f"{tag} → {track.display}\n        {cand.title} [{cand.channel}] {cand.url}")
        return track, None, "matched"
    try:
        path = dl.download(track, cand)
    except Exception as e:
        say(f"{tag} ! {track.display}: download failed ({e})")
        return track, None, "error"
    say(f"{tag} ✓ {track.display}")
    return track, path, "downloaded"


def write_playlist(out_dir: Path, col: Collection, results: List[Tuple[Track, Optional[Path], str]]) -> None:
    """Write an .m3u8 in Spotify order so it can be dragged into Rekordbox/Serato/Traktor as a playlist."""
    by_track = {id(t): p for t, p, _ in results}
    lines = ["#EXTM3U"]
    for t in col.tracks:
        p = by_track.get(id(t))
        if p:
            lines.append(f"#EXTINF:{t.duration_ms // 1000},{t.display}")
            lines.append(p.name)
    (out_dir / f"{safe_filename(col.name)}.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        col = fetch(args.link)
    except Exception as e:
        print(f"Couldn't read that Spotify link: {e}", file=sys.stderr)
        return 1
    if not col.tracks:
        print("No tracks found (is the playlist private?).", file=sys.stderr)
        return 1

    out_dir = Path(args.out) / safe_filename(col.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"🎧 {col.name}: {len(col.tracks)} tracks → {out_dir}/")
    if col.truncated:
        print("   (Spotify's public page stops at 100 tracks. Set SPOTIFY_CLIENT_ID/SECRET to get them all — see README.)")

    dl = Downloader(out_dir, fmt=args.format, quiet=not args.verbose)
    total = len(col.tracks)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(process, dl, t, i, total, args.dry_run) for i, t in enumerate(col.tracks, 1)]
        for fut in as_completed(futures):
            results.append(fut.result())

    counts = {}
    for _, _, status in results:
        counts[status] = counts.get(status, 0) + 1
    problems = [t for t, _, s in results if s in ("missing", "error")]

    if not args.dry_run:
        write_playlist(out_dir, col, results)
        report = out_dir / "_not_found.txt"
        if problems:
            report.write_text("\n".join(t.display for t in problems) + "\n", encoding="utf-8")
        elif report.exists():
            report.unlink()

    print()
    print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    if problems and not args.dry_run:
        print(f"Tracks to dig for manually are listed in {out_dir / '_not_found.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
