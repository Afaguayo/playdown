# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm packaging/PlayDown.spec
# Set DENO_BIN to a deno executable to bundle it (YouTube needs a JS runtime).
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "playdown", "assets")

datas = [(ASSETS, "playdown/assets")]
binaries = []
hiddenimports = []

ejs_datas, ejs_bins, ejs_hidden = collect_all("yt_dlp_ejs")
datas += ejs_datas
binaries += ejs_bins
hiddenimports += ejs_hidden
datas += collect_data_files("imageio_ffmpeg")  # ships the ffmpeg binary as package data

deno = os.environ.get("DENO_BIN")
if deno:
    binaries.append((deno, "."))

a = Analysis(
    [os.path.join(SPECPATH, "PlayDown.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["numpy", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PlayDown", console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="PlayDown", upx=False)
    app = BUNDLE(
        coll,
        name="PlayDown.app",
        icon=os.path.join(ASSETS, "icon.png"),
        bundle_identifier="com.afaguayo.playdown",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "0.2.1"},
    )
else:
    # One self-contained .exe on Windows
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="PlayDown",
        console=False,
        upx=False,
        icon=os.path.join(ASSETS, "icon.ico"),
    )
