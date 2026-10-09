"""Search YouTube, download audio, convert and tag it."""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from .matcher import Candidate, best_match
from .spotify import Track

FORMATS = {"mp3", "m4a", "flac", "wav"}


def bundle_dir() -> Optional[Path]:
    """Folder holding binaries shipped inside the packaged app (PyInstaller), if any."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def find_ffmpeg() -> str:
    """Return the path of an ffmpeg executable (or a folder containing one).

    Prefers the system ffmpeg, then the copy bundled by the imageio-ffmpeg
    package. yt-dlp accepts the binary path directly, even with a versioned
    name like ffmpeg-win-x86_64-v7.1.exe.
    """
    system = shutil.which("ffmpeg")
    if system:
        return str(Path(system).parent)
    try:
        import imageio_ffmpeg
    except ImportError:
        raise RuntimeError("ffmpeg not found. Install it (brew install ffmpeg) or `pip install imageio-ffmpeg`.")
    return imageio_ffmpeg.get_ffmpeg_exe()


def find_js_runtime() -> Optional[dict]:
    """yt-dlp `js_runtimes` config. YouTube needs a JS runtime to solve its player challenges.

    Order: deno bundled in the app → deno on PATH → node on PATH.
    """
    exe = "deno.exe" if os.name == "nt" else "deno"
    bundled = bundle_dir() / exe if bundle_dir() else None
    if bundled and bundled.exists():
        return {"deno": {"path": str(bundled)}}
    if shutil.which("deno"):
        return {"deno": {}}
    if shutil.which("node"):
        return {"node": {}}
    return None


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or "untitled"


def track_filename(track: Track, fmt: str) -> str:
    return safe_filename(track.display) + "." + fmt


class Downloader:
    def __init__(self, out_dir: Path, fmt: str = "mp3", search_results: int = 8, quiet: bool = True):
        if fmt not in FORMATS:
            raise ValueError(f"format must be one of {sorted(FORMATS)}")
        self.out_dir = out_dir
        self.fmt = fmt
        self.search_results = search_results
        self.quiet = quiet
        self.ffmpeg = find_ffmpeg()
        self.js_runtimes = find_js_runtime()

    def _ydl(self, extra: Optional[dict] = None):
        import yt_dlp

        opts = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": True,
            "ffmpeg_location": self.ffmpeg,
        }
        if self.js_runtimes:
            opts["js_runtimes"] = self.js_runtimes
        opts.update(extra or {})
        return yt_dlp.YoutubeDL(opts)

    def search(self, track: Track) -> List[Candidate]:
        query = f"{track.artist} - {track.title}"
        with self._ydl({"extract_flat": "in_playlist", "skip_download": True}) as ydl:
            info = ydl.extract_info(f"ytsearch{self.search_results}:{query}", download=False)
        out = []
        for e in (info or {}).get("entries") or []:
            if not e or not e.get("id"):
                continue
            out.append(
                Candidate(
                    id=e["id"],
                    title=e.get("title") or "",
                    channel=e.get("channel") or e.get("uploader") or "",
                    duration=e.get("duration"),
                )
            )
        return out

    def find(self, track: Track) -> Optional[Candidate]:
        return best_match(track, self.search(track))

    def download(self, track: Track, cand: Candidate) -> Path:
        target = self.out_dir / track_filename(track, self.fmt)
        stem = str(target.with_suffix(""))
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": self.fmt}
        if self.fmt in ("mp3", "m4a"):
            pp["preferredquality"] = "320" if self.fmt == "mp3" else "256"
        opts = {
            "format": "bestaudio/best",
            "outtmpl": stem + ".%(ext)s",
            "postprocessors": [pp],
            "overwrites": True,
        }
        # YouTube hands out the occasional 403 on a stream URL; a fresh attempt
        # gets a new URL and almost always works.
        for attempt in range(3):
            try:
                with self._ydl(opts) as ydl:
                    ydl.download([cand.url])
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        if not target.exists():
            raise RuntimeError(f"download finished but {target.name} is missing")
        tag(target, track)
        return target


def tag(path: Path, track: Track) -> None:
    """Write Spotify's title/artist/album into the file so DJ software shows clean names."""
    try:
        import mutagen
    except ImportError:
        return
    try:
        f = mutagen.File(str(path), easy=True)
        if f is None:
            return
        if f.tags is None:
            f.add_tags()
        f["title"] = track.title
        f["artist"] = track.artist
        if track.album:
            f["album"] = track.album
        f.save()
    except Exception:
        # Tagging is a nice-to-have (WAV has no easy tags); never fail a download for it.
        pass


def existing(out_dir: Path, track: Track, fmt: str) -> Optional[Path]:
    p = out_dir / track_filename(track, fmt)
    return p if p.exists() and os.path.getsize(p) > 0 else None
