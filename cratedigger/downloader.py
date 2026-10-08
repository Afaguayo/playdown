"""Search YouTube, download audio, convert and tag it."""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import List, Optional

from .matcher import Candidate, best_match
from .spotify import Track

FORMATS = {"mp3", "m4a", "flac", "wav"}
CACHE_BIN = Path.home() / ".cache" / "dj-cratedigger" / "bin"


def find_ffmpeg() -> str:
    """Return a directory containing an `ffmpeg` binary.

    Uses the system ffmpeg if there is one, otherwise the copy bundled by the
    imageio-ffmpeg package (symlinked as `ffmpeg` so yt-dlp can find it).
    """
    system = shutil.which("ffmpeg")
    if system:
        return str(Path(system).parent)
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("ffmpeg not found. Install it (brew install ffmpeg) or `pip install imageio-ffmpeg`.")
    exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    CACHE_BIN.mkdir(parents=True, exist_ok=True)
    link = CACHE_BIN / "ffmpeg"
    if not link.exists() or link.resolve() != exe.resolve():
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(exe)
    return str(CACHE_BIN)


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
        self.ffmpeg_dir = find_ffmpeg()

    def _ydl(self, extra: Optional[dict] = None):
        import yt_dlp

        opts = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": True,
            "ffmpeg_location": self.ffmpeg_dir,
        }
        # YouTube needs a JS runtime to solve its player challenges. yt-dlp looks
        # for deno by default; fall back to node, which more people already have.
        if not shutil.which("deno") and shutil.which("node"):
            opts["js_runtimes"] = {"node": {}}
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
