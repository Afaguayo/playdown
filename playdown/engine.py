"""The dig itself: Spotify link in, crate folder out. Shared by the CLI and the GUI.

Progress is reported through an `on_event(name, data)` callback so each front
end can render it its own way (print lines vs. LCD screen).
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .downloader import Downloader, existing, safe_filename
from .spotify import Collection, Track, fetch

# Track statuses
DOWNLOADED = "downloaded"
SKIPPED = "skipped"      # already in the crate
MATCHED = "matched"      # dry run
MISSING = "missing"      # no confident match
ERROR = "error"
CANCELLED = "cancelled"

EventFn = Callable[[str, dict], None]


@dataclass
class TrackResult:
    index: int
    track: Track
    status: str
    path: Optional[Path] = None
    detail: str = ""  # matched video title, or error message


@dataclass
class DigResult:
    collection: Collection
    out_dir: Path
    results: List[TrackResult] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c

    @property
    def problems(self) -> List[Track]:
        return [r.track for r in sorted(self.results, key=lambda r: r.index) if r.status in (MISSING, ERROR)]


def _process(dl: Downloader, track: Track, index: int, dry_run: bool, stop: threading.Event) -> TrackResult:
    if stop.is_set():
        return TrackResult(index, track, CANCELLED)
    found = existing(dl.out_dir, track, dl.fmt)
    if found:
        return TrackResult(index, track, SKIPPED, found)
    try:
        cand = dl.find(track)
    except Exception as e:  # network hiccups, age-gated results, etc.
        return TrackResult(index, track, ERROR, detail=f"search failed: {e}")
    if not cand:
        return TrackResult(index, track, MISSING)
    if dry_run:
        return TrackResult(index, track, MATCHED, detail=f"{cand.title} [{cand.channel}] {cand.url}")
    if stop.is_set():
        return TrackResult(index, track, CANCELLED)
    try:
        path = dl.download(track, cand)
    except Exception as e:
        return TrackResult(index, track, ERROR, detail=f"download failed: {e}")
    return TrackResult(index, track, DOWNLOADED, path, detail=cand.title)


def write_playlist(result: DigResult) -> Path:
    """Write an .m3u8 in Spotify order so it can be dragged into Rekordbox/Serato/Traktor as a playlist."""
    by_index = {r.index: r for r in result.results}
    lines = ["#EXTM3U"]
    for i, t in enumerate(result.collection.tracks, 1):
        r = by_index.get(i)
        if r and r.path:
            lines.append(f"#EXTINF:{t.duration_ms // 1000},{t.display}")
            lines.append(r.path.name)
    path = result.out_dir / f"{safe_filename(result.collection.name)}.m3u8"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def dig(
    link: str,
    out: Path,
    fmt: str = "mp3",
    jobs: int = 3,
    dry_run: bool = False,
    verbose: bool = False,
    on_event: Optional[EventFn] = None,
    stop: Optional[threading.Event] = None,
) -> DigResult:
    """Run a full dig. Raises on a bad link / unreadable playlist.

    Events: "collection" {collection, out_dir}, "track" {result, done, total},
    "finished" {result}.
    """
    emit = on_event or (lambda name, data: None)
    stop = stop or threading.Event()

    col = fetch(link)
    if not col.tracks:
        raise RuntimeError("No tracks found (is the playlist private?)")

    out_dir = Path(out) / safe_filename(col.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    emit("collection", {"collection": col, "out_dir": out_dir})

    dl = Downloader(out_dir, fmt=fmt, quiet=not verbose)
    result = DigResult(col, out_dir)
    total = len(col.tracks)
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(_process, dl, t, i, dry_run, stop) for i, t in enumerate(col.tracks, 1)]
        for fut in as_completed(futures):
            r = fut.result()
            result.results.append(r)
            emit("track", {"result": r, "done": len(result.results), "total": total})

    if not dry_run:
        write_playlist(result)
        report = out_dir / "_not_found.txt"
        if result.problems:
            report.write_text("\n".join(t.display for t in result.problems) + "\n", encoding="utf-8")
        elif report.exists():
            report.unlink()

    emit("finished", {"result": result})
    return result
