"""playdown: Spotify playlist link in, folder of DJ-ready audio files out."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .downloader import FORMATS
from .engine import DOWNLOADED, ERROR, MATCHED, MISSING, SKIPPED, dig

SYMBOLS = {DOWNLOADED: "✓", SKIPPED: "=", MATCHED: "→", MISSING: "?", ERROR: "!"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="playdown",
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


def print_event(name: str, data: dict) -> None:
    if name == "collection":
        col, out_dir = data["collection"], data["out_dir"]
        print(f"🎧 {col.name}: {len(col.tracks)} tracks → {out_dir}/", flush=True)
        if col.truncated:
            print("   (Spotify's public page stops at 100 tracks. Set SPOTIFY_CLIENT_ID/SECRET to get them all — see README.)")
    elif name == "track":
        r, total = data["result"], data["total"]
        line = f"[{r.index:>3}/{total}] {SYMBOLS.get(r.status, ' ')} {r.track.display}"
        if r.status == SKIPPED:
            line += " (already in crate)"
        elif r.status == MISSING:
            line += ": no confident match"
        elif r.status == MATCHED:
            line += f"\n        {r.detail}"
        elif r.status == ERROR:
            line += f": {r.detail}"
        print(line, flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = dig(args.link, args.out, args.format, args.jobs, args.dry_run, args.verbose, on_event=print_event)
    except Exception as e:
        print(f"Couldn't read that Spotify link: {e}", file=sys.stderr)
        return 1

    print()
    print("  ".join(f"{k}: {v}" for k, v in sorted(result.counts.items())))
    if result.problems and not args.dry_run:
        print(f"Tracks to dig for manually are listed in {result.out_dir / '_not_found.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
