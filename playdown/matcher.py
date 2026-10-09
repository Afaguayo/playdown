"""Pick the YouTube result that is most likely the same recording as the Spotify track."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional

from .spotify import Track

# Words that usually mean "not the studio version". They only count against a
# result when the Spotify title doesn't contain them too (so a track that IS
# "X (Extended Mix)" still matches extended uploads).
VERSION_WORDS = [
    "live", "cover", "karaoke", "instrumental", "acapella", "a cappella",
    "sped up", "speed up", "slowed", "reverb", "nightcore", "8d", "remix",
    "extended", "edit", "bass boosted", "lyrics video", "reaction", "tutorial",
    "loop", "1 hour", "mashup", "clean", "radio",
]

# Signs of a fan re-upload (lyric videos, translations). Often pitched,
# trimmed or with intros, so they lose to an official upload of the same song.
REUPLOAD_WORDS = ["lyrics", "lyric", "letra", "sub espanol", "traducida", "testo", "legendado"]


@dataclass
class Candidate:
    id: str
    title: str
    channel: str
    duration: Optional[float]  # seconds

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"\b(feat|ft|featuring)\.?\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def score(track: Track, cand: Candidate) -> float:
    """Higher is better. Roughly 0-100; below ~45 is probably the wrong song."""
    want_title = normalize(track.title)
    got = normalize(f"{cand.channel} {cand.title}")
    s = 0.0

    # Title words present in the result (most important signal).
    words = want_title.split()
    if words:
        s += 40 * sum(_has_word(got, w) for w in words) / len(words)
    s += 10 * SequenceMatcher(None, want_title, normalize(cand.title)).ratio()

    # Main artist present in channel name or video title.
    if track.artists and _has_word(got, normalize(track.artists[0])):
        s += 20

    # Duration is the best "is this the same cut" check.
    if track.duration_ms and cand.duration:
        diff = abs(track.duration_ms / 1000 - cand.duration)
        if diff <= 3:
            s += 25
        elif diff <= 10:
            s += 15
        elif diff <= 30:
            s += 0
        else:
            s -= min(40, diff / 3)

    # YouTube Music auto-generated "Artist - Topic" channels are official audio;
    # the artist's own channel is the next best thing.
    channel = normalize(cand.channel.replace(" - Topic", ""))
    artist_names = {normalize(a) for a in track.artists}
    if cand.channel.endswith(" - Topic") and channel in artist_names:
        s += 20
    elif channel in artist_names or channel.replace(" ", "") in {a.replace(" ", "") for a in artist_names}:
        s += 12
    if "official audio" in cand.title.lower():
        s += 5

    cand_title = normalize(cand.title)
    if any(_has_word(cand_title, w) for w in REUPLOAD_WORDS):
        s -= 12

    for w in VERSION_WORDS:
        if _has_word(cand_title, w) and not _has_word(want_title, w):
            s -= 25

    return s


def best_match(track: Track, candidates: List[Candidate], min_score: float = 45) -> Optional[Candidate]:
    ranked = sorted(candidates, key=lambda c: score(track, c), reverse=True)
    if ranked and score(track, ranked[0]) >= min_score:
        return ranked[0]
    return None
