import pytest

from cratedigger.downloader import safe_filename, track_filename
from cratedigger.matcher import Candidate, best_match, normalize, score
from cratedigger.spotify import Track, parse_link


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
        ("https://open.spotify.com/intl-es/playlist/37i9dQZF1DXcBWIGoYBM5M", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
        ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", ("playlist", "37i9dQZF1DXcBWIGoYBM5M")),
        ("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy", ("album", "4aawyAB9vmqN3uQ7FjRGTy")),
    ],
)
def test_parse_link(link, expected):
    assert parse_link(link) == expected


def test_parse_link_rejects_tracks():
    with pytest.raises(ValueError):
        parse_link("https://open.spotify.com/track/11hcBLPtbMp4aQI6zGQLub")


TRACK = Track(title="One More Time", artists=["Daft Punk"], duration_ms=320_000)


def test_prefers_official_audio_over_live_and_remix():
    cands = [
        Candidate("a", "Daft Punk - One More Time (Live at Alive 2007)", "fanuploads", 410),
        Candidate("b", "One More Time (Remix)", "Some DJ", 300),
        Candidate("c", "One More Time", "Daft Punk - Topic", 321),
    ]
    assert best_match(TRACK, cands).id == "c"


def test_keeps_version_when_spotify_title_has_it():
    t = Track(title="Strobe - Radio Edit", artists=["deadmau5"], duration_ms=214_000)
    c = Candidate("x", "deadmau5 - Strobe (Radio Edit)", "deadmau5", 215)
    assert score(t, c) > 60


def test_rejects_wrong_song():
    cands = [Candidate("z", "Totally Different Song", "Random Channel", 180)]
    assert best_match(TRACK, cands) is None


def test_normalize():
    assert normalize("Beyoncé feat. JAY-Z & Co!") == "beyonce jay z and co"


def test_filenames_are_safe():
    t = Track(title='What/Is: "This"?', artists=["AC/DC"])
    assert track_filename(t, "mp3") == "ACDC - WhatIs This.mp3"
    assert safe_filename("   ") == "untitled"
