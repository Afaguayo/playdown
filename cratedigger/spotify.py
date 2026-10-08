"""Read track lists from Spotify playlist / album links.

Two sources:
  1. Spotify Web API (client credentials) when SPOTIFY_CLIENT_ID and
     SPOTIFY_CLIENT_SECRET are set. Handles playlists of any length.
  2. The public embed page (no keys needed). Spotify only renders the first
     ~100 tracks there, so very long playlists get cut off.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[\w-]+/)?|spotify:)(playlist|album)[/:]([A-Za-z0-9]{22})"
)


@dataclass
class Track:
    title: str
    artists: List[str]
    duration_ms: int = 0
    album: str = ""

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class Collection:
    kind: str  # "playlist" or "album"
    id: str
    name: str
    tracks: List[Track] = field(default_factory=list)
    truncated: bool = False


def parse_link(link: str) -> Tuple[str, str]:
    """Return (kind, id) from a Spotify URL or URI."""
    m = _URL_RE.search(link.strip())
    if not m:
        raise ValueError(
            f"Not a Spotify playlist/album link: {link!r}\n"
            "Expected something like https://open.spotify.com/playlist/<id>"
        )
    return m.group(1), m.group(2)


def _get(url: str, headers: Optional[dict] = None, data: Optional[bytes] = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


# ---------------------------------------------------------------- Web API --

def _api_token(client_id: str, client_secret: str) -> str:
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = _get(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data=b"grant_type=client_credentials",
    )
    return json.loads(body)["access_token"]


def _api_track(t: dict, album_name: str = "") -> Optional[Track]:
    if not t or not t.get("name"):
        return None  # removed / local tracks show up as null
    return Track(
        title=t["name"],
        artists=[a["name"] for a in t.get("artists", []) if a.get("name")],
        duration_ms=t.get("duration_ms") or 0,
        album=(t.get("album") or {}).get("name", album_name),
    )


def fetch_via_api(kind: str, cid: str, client_id: str, client_secret: str) -> Collection:
    token = _api_token(client_id, client_secret)
    headers = {"Authorization": f"Bearer {token}"}
    meta = json.loads(_get(f"https://api.spotify.com/v1/{kind}s/{cid}?fields=name", headers))
    col = Collection(kind=kind, id=cid, name=meta.get("name", cid))

    url: Optional[str] = f"https://api.spotify.com/v1/{kind}s/{cid}/tracks?limit=50"
    while url:
        page = json.loads(_get(url, headers))
        for item in page.get("items", []):
            raw = item.get("track") if kind == "playlist" else item
            track = _api_track(raw, col.name)
            if track:
                col.tracks.append(track)
        url = page.get("next")
    return col


# ------------------------------------------------------------- Embed page --

def fetch_via_embed(kind: str, cid: str) -> Collection:
    html = _get(f"https://open.spotify.com/embed/{kind}/{cid}").decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("Spotify embed page changed format; set SPOTIFY_CLIENT_ID/SECRET to use the API instead.")
    entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]

    name = entity.get("name") or entity.get("title") or cid
    col = Collection(kind=kind, id=cid, name=name)
    for t in entity.get("trackList", []):
        if not t.get("title"):
            continue
        # The embed gives artists as one string ("A, B"); good enough for search.
        artists = [a.strip() for a in (t.get("subtitle") or "").split(",") if a.strip()]
        col.tracks.append(
            Track(
                title=t["title"],
                artists=artists,
                duration_ms=t.get("duration") or 0,
                album=name if kind == "album" else "",
            )
        )
    col.truncated = len(col.tracks) >= 100
    return col


def fetch(link: str) -> Collection:
    kind, cid = parse_link(link)
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if client_id and client_secret:
        return fetch_via_api(kind, cid, client_id, client_secret)
    return fetch_via_embed(kind, cid)
