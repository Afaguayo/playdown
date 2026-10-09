"""PlayDown desktop app: a skinned, Y2K-style front end for the engine.

Everything is drawn on one Tk canvas with images from `skin.py`. The dig runs
on a worker thread; it posts events to a queue that the UI drains every frame.
"""
from __future__ import annotations

import gc
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageTk

from . import __version__, skin
from .engine import CANCELLED, DOWNLOADED, ERROR, MATCHED, MISSING, SKIPPED, dig
from .spotify import parse_link

W, H = 780, 664  # logical window size; multiplied by the display scale
FORMATS = ["mp3", "m4a", "flac", "wav"]
TAGS = {
    DOWNLOADED: ("GOT ", "ok"),
    SKIPPED: ("HAVE", "have"),
    MATCHED: ("PREV", "info"),
    MISSING: ("MISS", "miss"),
    ERROR: ("ERR ", "err"),
    CANCELLED: ("STOP", "dim"),
}
IDLE_MARQUEE = "  ::  READY TO DIG  ::  PASTE A SPOTIFY PLAYLIST LINK AND HIT DIG IT!  ::  NO MORE ONE-BY-ONE  "
PLACEHOLDER = "https://open.spotify.com/playlist/..."


# ------------------------------------------------------------- settings --

def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "PlayDown" / "settings.json"


def load_settings() -> dict:
    s = {"out": str(Path.home() / "Music" / "PlayDown"), "format": "mp3", "jobs": 3, "preview": False}
    try:
        s.update(json.loads(settings_path().read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def enable_hidpi() -> None:
    """Ask Windows for real pixels so the skin renders crisp instead of blurry-scaled."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def display_scale(root: tk.Tk) -> float:
    if sys.platform != "win32":
        return 1.0  # macOS/Linux Tk already works in logical points
    s = root.winfo_fpixels("1i") / 96.0
    s = max(1.0, round(s * 4) / 4)
    max_h = root.winfo_screenheight() * 0.9
    return min(s, max_h / H) if H * s > max_h else s


# --------------------------------------------------------------- widgets --

class Button:
    """A skinned button living on the canvas. Optionally a toggle."""

    def __init__(self, app: "App", x: int, y: int, w: int, h: int, label: str, style: str = "aqua",
                 command: Optional[Callable[[], None]] = None, font_size: int = 0, radius: float = -1,
                 toggle_styles: Optional[Tuple[str, str]] = None):
        self.app, self.cv = app, app.cv
        self.w, self.h, self.label, self.style = w, h, label, style
        self.command, self.font_size, self.radius = command, font_size, radius
        self.toggle_styles = toggle_styles  # (on, off)
        self.on = False
        self.enabled = True
        self.hover = False
        self.pressed = False
        self.cache: Dict[Tuple[str, str], ImageTk.PhotoImage] = {}
        self.tag = f"btn{id(self)}"
        self.item = self.cv.create_image(app.px(x), app.px(y), anchor="nw", tags=(self.tag,))
        self.cv.tag_bind(self.tag, "<Enter>", self._enter)
        self.cv.tag_bind(self.tag, "<Leave>", self._leave)
        self.cv.tag_bind(self.tag, "<ButtonPress-1>", self._press)
        self.cv.tag_bind(self.tag, "<ButtonRelease-1>", self._release)
        self.refresh()

    def _image(self, style: str, state: str) -> ImageTk.PhotoImage:
        key = (style, state)
        if key not in self.cache:
            S = self.app.S
            img = skin.gloss_button(self.app.px(self.w), self.app.px(self.h), self.label, style, state,
                                    font_size=int(self.font_size * S), radius=self.radius * S if self.radius >= 0 else -1,
                                    S=S)
            self.cache[key] = ImageTk.PhotoImage(img)
        return self.cache[key]

    def refresh(self) -> None:
        style = self.style
        if self.toggle_styles:
            style = self.toggle_styles[0] if self.on else self.toggle_styles[1]
        if not self.enabled:
            state = "disabled"
        elif self.pressed and self.hover:
            state = "down"
        elif self.hover:
            state = "hover"
        else:
            state = "normal"
        self.cv.itemconfigure(self.item, image=self._image(style, state))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.refresh()

    def set_on(self, on: bool) -> None:
        self.on = on
        self.refresh()

    def _enter(self, _e=None) -> None:
        self.hover = True
        if self.enabled:
            self.cv.configure(cursor="hand2")
        self.refresh()

    def _leave(self, _e=None) -> None:
        self.hover = False
        self.cv.configure(cursor="")
        self.refresh()

    def _press(self, _e=None) -> None:
        self.pressed = True
        self.refresh()

    def _release(self, _e=None) -> None:
        fire = self.pressed and self.hover and self.enabled
        self.pressed = False
        self.refresh()
        if fire and self.command:
            self.command()


class Sprite:
    """Canvas image item whose picture can be swapped (keeps the Tk reference alive)."""

    def __init__(self, app: "App", x: int, y: int, anchor: str = "nw"):
        self.app = app
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.item = app.cv.create_image(app.px(x), app.px(y), anchor=anchor)

    def set(self, img: Image.Image) -> None:
        self.photo = ImageTk.PhotoImage(img)
        self.app.cv.itemconfigure(self.item, image=self.photo)


# ------------------------------------------------------------------- app --

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.S = display_scale(root)
        self.settings = load_settings()
        self.events: "queue.Queue[Tuple[str, dict]]" = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.last_out: Optional[Path] = None
        self.log: List[Tuple[str, str]] = []
        self.counts = {"ok": 0, "have": 0, "miss": 0, "err": 0}
        self.total = 0
        self.done = 0
        self.spin = 0.0
        self.spin_speed = 0.0
        self.frame_i = 0.0
        self.marquee_off = 0.0
        self.eq_levels = [0.0] * 14
        self.eq_peaks = [0.0] * 14

        root.title("PlayDown")
        root.resizable(False, False)
        root.configure(bg="#c9d0da")
        try:
            root.iconphoto(True, ImageTk.PhotoImage(Image.open(skin.ASSETS / "icon.png")))
        except Exception:
            pass

        self.cv = tk.Canvas(root, width=self.px(W), height=self.px(H), highlightthickness=0, bd=0, bg="#c9d0da")
        self.cv.pack()
        self._build()
        root.bind("<Return>", lambda e: self.start())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._tick()

    def px(self, v: float) -> int:
        return int(round(v * self.S))

    # ---------------------------------------------------------- layout --

    def _build(self) -> None:
        S, px = self.S, self.px
        bg = skin.brushed_metal(px(W), px(H))
        bg.alpha_composite(skin.bevel_frame(px(W), px(H), px(14), S))
        for x, y, a in ((12, 12, 30), (W - 26, 12, 75), (12, H - 26, 120), (W - 26, H - 26, 160)):
            bg.alpha_composite(skin.screw(px(14), a), (px(x), px(y)))

        # header
        logo = skin.chrome_text("PLAYDOWN", px(38))
        bg.alpha_composite(logo, (px(128), px(14)))
        tag = skin.text_img("SPOTIFY PLAYLIST  >>  DJ CRATE", px(11), "#4f5b6d", emboss="#ffffff", tracking=2 * S)
        bg.alpha_composite(tag, (px(146), px(78)))
        badge = skin.gloss_button(px(64), px(22), f"v{__version__}", "dark", S=S, font_size=px(10))
        bg.alpha_composite(badge, (px(W - 96), px(76)))
        bg.alpha_composite(skin.groove(px(W - 40), S), (px(20), px(106)))

        # panels
        for (x, y, w, h, title) in ((20, 116, 740, 84, "01 // SOURCE"), (20, 208, 740, 116, "02 // SETTINGS")):
            img, m = skin.panel(px(w), px(h), title, S)
            bg.alpha_composite(img, (px(x) - m, px(y) - m))

        # source row
        bg.alpha_composite(skin.inset(px(612), px(38), px(10), S), (px(34), px(146)))
        # settings row labels
        for x, label in ((34, "FORMAT"), (330, "SAVE TO"), (640, "SPEED")):
            bg.alpha_composite(skin.text_img(label, px(9), "#6a7587", emboss="#ffffff", tracking=1.5 * S), (px(x), px(236)))
        bg.alpha_composite(skin.inset(px(214), px(32), px(8), S), (px(330), px(252)))
        bg.alpha_composite(skin.inset(px(36), px(32), px(8), S, fill="#0b1f15"), (px(672), px(252)))

        # LCD
        self.lcd = (20, 398, 740, 206)  # x, y, w, h
        self.screen = (30, 408, 720, 186)
        bg.alpha_composite(skin.lcd_bezel(px(740), px(206), 10 * S, S), (px(20), px(398)))
        sx, sy, sw, sh = self.screen
        sep = skin.groove(px(sw - 24), S)
        sep = skin.fade(sep.point(lambda v: v), 0.25)
        bg.alpha_composite(sep, (px(sx + 12), px(sy + 30)))

        self.bg_photo = ImageTk.PhotoImage(bg)
        self.cv.create_image(0, 0, anchor="nw", image=self.bg_photo)

        # spinning record
        self.vinyl = skin.vinyl_frames(px(96), 36)
        self.vinyl_photos = [ImageTk.PhotoImage(f) for f in self.vinyl]
        self.vinyl_item = self.cv.create_image(px(22), px(8), anchor="nw", image=self.vinyl_photos[0])

        # twinkles around the logo
        self.sparkles = []
        for x, y, d, c in ((118, 18, 18, "#ffffff"), (520, 12, 22, skin.AQUA), (612, 58, 14, "#ffffff"),
                           (700, 26, 18, skin.PINK), (452, 70, 12, skin.AQUA)):
            frames = [ImageTk.PhotoImage(skin.fade(skin.sparkle(px(d), c), a)) for a in (0.0, 0.35, 0.7, 1.0)]
            item = self.cv.create_image(px(x), px(y), anchor="nw", image=frames[0])
            self.sparkles.append({"item": item, "frames": frames, "t": random.random() * 6.28, "speed": 0.06 + random.random() * 0.08})

        # link entry
        mono = ("Consolas" if sys.platform == "win32" else "Menlo", -px(15))
        self.entry = tk.Entry(self.cv, font=mono, bd=0, relief="flat", highlightthickness=0, bg="#f5f9ff",
                              fg="#0b2a4a", insertbackground="#0a6cd4", selectbackground="#40c4ff",
                              disabledbackground="#f5f9ff")
        self.cv.create_window(px(48), px(165), anchor="w", window=self.entry, width=px(586), height=px(24))
        self._placeholder(True)
        self.entry.bind("<FocusIn>", lambda e: self._placeholder(False))
        self.entry.bind("<FocusOut>", lambda e: self._placeholder(not self.entry.get().strip()))
        Button(self, 656, 146, 92, 38, "PASTE", "silver", self.paste, font_size=12)

        # format toggles
        self.fmt_buttons: Dict[str, Button] = {}
        for i, fmt in enumerate(FORMATS):
            b = Button(self, 34 + i * 70, 252, 64, 32, fmt.upper(), command=lambda f=fmt: self.set_format(f),
                       font_size=11, toggle_styles=("aqua", "silver"))
            self.fmt_buttons[fmt] = b
        self.set_format(self.settings.get("format", "mp3"))

        # output folder
        self.path_sprite = Sprite(self, 340, 268, anchor="w")
        Button(self, 550, 252, 80, 32, "BROWSE", "silver", self.browse, font_size=10)
        self._render_path()

        # jobs stepper
        Button(self, 640, 252, 28, 32, "-", "silver", lambda: self.set_jobs(self.jobs - 1), font_size=14, radius=8)
        Button(self, 712, 252, 28, 32, "+", "silver", lambda: self.set_jobs(self.jobs + 1), font_size=14, radius=8)
        self.jobs_sprite = Sprite(self, 690, 268, anchor="center")
        self.jobs = int(self.settings.get("jobs", 3))
        self.set_jobs(self.jobs)

        # preview toggle
        self.preview = bool(self.settings.get("preview", False))
        self.led_photos = {on: ImageTk.PhotoImage(skin.led(px(16), on)) for on in (True, False)}
        self.led_item = self.cv.create_image(px(30), px(292), anchor="nw", tags=("preview",))
        lbl = skin.text_img("PREVIEW ONLY  (SHOW MATCHES, DON'T DOWNLOAD)", px(10), "#3d4859", emboss="#ffffff", tracking=1.2 * S)
        self.preview_lbl_photo = ImageTk.PhotoImage(lbl)
        self.cv.create_image(px(58), px(296), anchor="nw", image=self.preview_lbl_photo, tags=("preview",))
        self.cv.tag_bind("preview", "<Button-1>", lambda e: self.toggle_preview())
        self.cv.tag_bind("preview", "<Enter>", lambda e: self.cv.configure(cursor="hand2"))
        self.cv.tag_bind("preview", "<Leave>", lambda e: self.cv.configure(cursor=""))
        self._render_preview()
        hint = skin.text_img("TIP: RUN A PREVIEW FIRST ON BIG SETS", px(9), "#7a8597", emboss="#ffffff", tracking=1.2 * S)
        self.hint_photo = ImageTk.PhotoImage(hint)
        self.cv.create_image(px(746), px(298), anchor="ne", image=self.hint_photo)

        # action buttons
        self.dig_btn = Button(self, 20, 336, 360, 54, "DIG IT!", "aqua", self.start, font_size=22)
        self.stop_btn = Button(self, 390, 336, 170, 54, "STOP", "pink", self.stop, font_size=16)
        self.open_btn = Button(self, 570, 336, 190, 54, "OPEN CRATE", "silver", self.open_crate, font_size=13)
        self.stop_btn.set_enabled(False)
        self.open_btn.set_enabled(False)

        # LCD contents
        sx, sy, sw, sh = self.screen
        self.marquee_w, self.marquee_h = px(sw - 24), px(24)
        self.marquee_photo = ImageTk.PhotoImage(Image.new("RGBA", (self.marquee_w, self.marquee_h)))
        self.cv.create_image(px(sx + 12), px(sy + 5), anchor="nw", image=self.marquee_photo)
        self.set_marquee(IDLE_MARQUEE)

        self.log_box = (sx + 12, sy + 38, sw - 24 - 150, sh - 38 - 34)
        self.log_sprite = Sprite(self, self.log_box[0], self.log_box[1])

        # EQ bars (right side of the LCD)
        self.eq_rects: List[List[int]] = []
        ex, ey, ew, eh = sx + sw - 150, sy + 40, 138, sh - 40 - 36
        nb, segs = len(self.eq_levels), 12
        bw, sgh = ew / nb, eh / segs
        for b in range(nb):
            col = []
            for k in range(segs):
                x0 = ex + b * bw + 1.5
                y1 = ey + eh - k * sgh - 1.5
                col.append(self.cv.create_rectangle(px(x0), px(y1 - sgh + 3), px(x0 + bw - 3), px(y1),
                                                    width=0, fill="#12301f"))
            self.eq_rects.append(col)
        self.eq_geom = (segs,)

        self.counter_sprite = Sprite(self, sx + 12, sy + sh - 30)
        self.render_counters()
        self.glass_photo = ImageTk.PhotoImage(skin.lcd_glass(px(sw - 4), px(sh - 4), S))
        self.cv.create_image(px(sx + 2), px(sy + 2), anchor="nw", image=self.glass_photo)

        # progress + status
        self.bar_sprite = Sprite(self, 20, 614)
        self.render_bar()
        self.status_sprite = Sprite(self, 44, 646, anchor="w")
        self.status("READY.")
        self.add_log("PLAYDOWN " + __version__ + " :: SYSTEM OK", "dim")
        self.add_log("PASTE A PLAYLIST OR ALBUM LINK, PICK A FORMAT, HIT DIG IT!", "info")

    # ------------------------------------------------------- renderers --

    def _placeholder(self, show: bool) -> None:
        if show and not self.entry.get().strip():
            self.entry.delete(0, "end")
            self.entry.insert(0, PLACEHOLDER)
            self.entry.configure(fg="#8d99ab")
            self._has_placeholder = True
        elif not show and getattr(self, "_has_placeholder", False):
            self.entry.delete(0, "end")
            self.entry.configure(fg="#0b2a4a")
            self._has_placeholder = False

    def link(self) -> str:
        return "" if getattr(self, "_has_placeholder", False) else self.entry.get().strip()

    def status(self, text: str, kind: str = "normal") -> None:
        color = {"normal": "#3d4859", "error": "#c4106f", "good": "#1d7a12"}[kind]
        text, room = text.upper(), self.px(W - 88)
        # shrink, then shorten, so long playlist names never run off the bar
        for size, track in ((10, 1.2), (9, 0.6)):
            img = skin.text_img(text, self.px(size), color, emboss="#ffffff", tracking=track * self.S)
            if img.width <= room:
                break
        while img.width > room and len(text) > 4:
            text = text[:-4] + "..."
            img = skin.text_img(text, self.px(9), color, emboss="#ffffff", tracking=0.6 * self.S)
        self.status_sprite.set(img)

    def _render_path(self) -> None:
        f = skin.font("VT323", self.px(19))
        text = skin.fit(self.settings["out"], f, self.px(196))
        if f.getlength(text) > self.px(196):
            text = "..." + self.settings["out"][-40:]
        self.path_sprite.set(skin.text_img(text, self.px(19), "#0b2a4a", face="VT323"))

    def _render_preview(self) -> None:
        self.cv.itemconfigure(self.led_item, image=self.led_photos[self.preview])

    def render_counters(self) -> None:
        c = self.counts
        parts = [(f"GOT {c['ok']:03d}", "ok"), (f"HAVE {c['have']:03d}", "have"),
                 (f"MISS {c['miss']:03d}", "miss"), (f"ERR {c['err']:03d}", "err")]
        size = self.px(19)
        imgs = [skin.text_img(t, size, skin.LCD_COLORS[k], face="VT323", glow=skin.LCD_COLORS[k]) for t, k in parts]
        pct = f"{(100 * self.done // self.total) if self.total else 0:3d}%"
        imgs.append(skin.text_img(pct, size, "#e6ffd6", face="VT323", glow=skin.LCD_TEXT))
        gap = self.px(18)
        w = sum(i.width for i in imgs) + gap * (len(imgs) - 1)
        out = Image.new("RGBA", (max(w, 1), max(i.height for i in imgs)), (0, 0, 0, 0))
        x = 0
        for i in imgs:
            out.alpha_composite(i, (x, 0))
            x += i.width + gap
        self.counter_sprite.set(out)

    def render_bar(self) -> None:
        n = 44
        lit = round(n * self.done / self.total) if self.total else 0
        self.bar_sprite.set(skin.led_bar(self.px(740), self.px(20), n, lit, self.S))

    def add_log(self, text: str, kind: str = "ok") -> None:
        self.log.append((text, kind))
        self.log = self.log[-60:]
        x, y, w, h = self.log_box
        self.log_sprite.set(skin.lcd_lines(self.log, self.px(w), self.px(h), self.S, self.px(20)))

    def set_marquee(self, text: str) -> None:
        self.marquee_src = skin.marquee_strip(text, self.px(21), self.S)
        self.marquee_off = 0.0

    def _draw_marquee(self) -> None:
        src = self.marquee_src
        w, h = self.marquee_w, self.marquee_h
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        x = -int(self.marquee_off)
        while x < w:
            frame.alpha_composite(src, (x, (h - src.height) // 2)) if x >= 0 else frame.alpha_composite(
                src.crop((-x, 0, src.width, src.height)), (0, (h - src.height) // 2))
            x += src.width
        self.marquee_photo.paste(frame)

    # --------------------------------------------------------- controls --

    def set_format(self, fmt: str) -> None:
        if self.busy:
            return
        self.settings["format"] = fmt
        for f, b in self.fmt_buttons.items():
            b.set_on(f == fmt)
        save_settings(self.settings)

    def set_jobs(self, n: int) -> None:
        if self.busy:
            return
        self.jobs = max(1, min(8, n))
        self.settings["jobs"] = self.jobs
        self.jobs_sprite.set(skin.text_img(str(self.jobs), self.px(22), skin.LCD_TEXT, face="VT323", glow=skin.LCD_TEXT))
        save_settings(self.settings)

    def toggle_preview(self) -> None:
        if self.busy:
            return
        self.preview = not self.preview
        self.settings["preview"] = self.preview
        self._render_preview()
        save_settings(self.settings)

    def paste(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            self.status("CLIPBOARD IS EMPTY.", "error")
            return
        self._placeholder(False)
        self._has_placeholder = False
        self.entry.configure(fg="#0b2a4a")
        self.entry.delete(0, "end")
        self.entry.insert(0, text)

    def browse(self) -> None:
        if self.busy:
            return
        d = filedialog.askdirectory(initialdir=self.settings["out"], title="Where should crates go?")
        if d:
            self.settings["out"] = d
            self._render_path()
            save_settings(self.settings)

    def open_crate(self) -> None:
        target = self.last_out or Path(self.settings["out"])
        if target.exists():
            open_folder(target)

    def start(self) -> None:
        if self.busy:
            return
        link = self.link()
        if not link:
            self.status("PASTE A SPOTIFY LINK FIRST.", "error")
            return
        try:
            parse_link(link)
        except ValueError:
            self.status("THAT'S NOT A SPOTIFY PLAYLIST / ALBUM LINK.", "error")
            self.add_log("BAD LINK: " + link, "err")
            return

        self.busy = True
        self.stop_event.clear()
        self.counts = {k: 0 for k in self.counts}
        self.total = self.done = 0
        self.render_counters()
        self.render_bar()
        self.dig_btn.set_enabled(False)
        self.stop_btn.set_enabled(True)
        self.open_btn.set_enabled(False)
        self.add_log("", "dim")
        self.add_log("CONNECTING TO SPOTIFY...", "info")
        self.status("READING PLAYLIST...")
        self.set_marquee("  ::  LOADING PLAYLIST  ::  ")

        out = Path(self.settings["out"])
        fmt, jobs, preview = self.settings["format"], self.jobs, self.preview

        def work() -> None:
            try:
                dig(link, out, fmt, jobs, preview, on_event=lambda n, d: self.events.put((n, d)), stop=self.stop_event)
            except Exception as e:
                self.events.put(("error", {"message": str(e)}))

        threading.Thread(target=work, daemon=True).start()

    def stop(self) -> None:
        if self.busy:
            self.stop_event.set()
            self.stop_btn.set_enabled(False)
            self.status("STOPPING AFTER THE TRACKS IN PROGRESS...")
            self.add_log("STOP REQUESTED", "miss")

    def close(self) -> None:
        self.stop_event.set()
        if getattr(self, "_after", None):
            self.root.after_cancel(self._after)
        self.root.destroy()

    # ----------------------------------------------------------- events --

    def handle(self, name: str, data: dict) -> None:
        if name == "collection":
            col, out_dir = data["collection"], data["out_dir"]
            self.total = len(col.tracks)
            self.last_out = out_dir
            mode = "PREVIEWING" if self.preview else "NOW DIGGING"
            self.set_marquee(f"  ::  {mode}: {col.name.upper()}  ::  {self.total} TRACKS  ::  {self.settings['format'].upper()}  ")
            self.add_log(f"LOADED {col.name} :: {self.total} TRACKS", "info")
            if col.truncated:
                self.add_log("NOTE: SPOTIFY'S PUBLIC PAGE STOPS AT 100 TRACKS (SEE README)", "miss")
            self.status(f"DIGGING {self.total} TRACKS INTO {out_dir.name}...")
            self.render_counters()
        elif name == "track":
            r = data["result"]
            self.done = data["done"]
            label, kind = TAGS.get(r.status, ("    ", "dim"))
            n = len(str(self.total))
            self.add_log(f"{r.index:0{n}d}/{self.total} {label} {r.track.display}", kind)
            if r.status == MATCHED:
                self.add_log("      > " + r.detail.rsplit(" https://", 1)[0], "dim")
            elif r.status == ERROR:
                self.add_log("      > " + r.detail, "err")
            counter = {DOWNLOADED: "ok", SKIPPED: "have", MISSING: "miss", ERROR: "err"}.get(r.status)
            if r.status == MATCHED:
                counter = "ok"
            if counter:
                self.counts[counter] += 1
            self.render_counters()
            self.render_bar()
            self.eq_kick()
        elif name == "finished":
            res = data["result"]
            self.busy = False
            self.dig_btn.set_enabled(True)
            self.stop_btn.set_enabled(False)
            self.open_btn.set_enabled(not self.preview)
            problems = len(res.problems)
            if self.stop_event.is_set():
                self.add_log("STOPPED.", "miss")
                self.status("STOPPED. RUN IT AGAIN TO PICK UP WHERE YOU LEFT OFF.")
            elif self.preview:
                self.add_log(f"PREVIEW DONE :: {self.counts['ok']} MATCHED, {problems} NOT FOUND", "info")
                self.status("PREVIEW DONE. TURN OFF PREVIEW AND HIT DIG IT! TO DOWNLOAD.", "good")
            else:
                self.add_log(f"CRATE READY :: {res.out_dir}", "info")
                if problems:
                    self.add_log(f"{problems} TRACK(S) LISTED IN _not_found.txt", "miss")
                self.status(f"CRATE READY. IMPORT {res.out_dir.name}.m3u8 INTO YOUR DJ SOFTWARE.", "good")
            self.set_marquee(f"  ::  DONE  ::  {res.collection.name.upper()}  ::  GOT {self.counts['ok']}  HAVE {self.counts['have']}  MISS {self.counts['miss']}  ")
        elif name == "error":
            self.busy = False
            self.dig_btn.set_enabled(True)
            self.stop_btn.set_enabled(False)
            self.add_log("ERROR: " + data["message"], "err")
            self.status("SOMETHING WENT WRONG. SEE THE SCREEN.", "error")
            self.set_marquee(IDLE_MARQUEE)

    # ---------------------------------------------------------- animation --

    def eq_kick(self) -> None:
        for i in range(len(self.eq_levels)):
            self.eq_levels[i] = min(1.0, self.eq_levels[i] + random.random() * 0.6)

    def _tick(self) -> None:
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass

        # record spins up while busy and coasts to a stop after
        target = 14.0 if self.busy else 0.0
        self.spin_speed += (target - self.spin_speed) * 0.05
        self.spin = (self.spin + self.spin_speed) % 360
        self.cv.itemconfigure(self.vinyl_item, image=self.vinyl_photos[int(self.spin / 10) % len(self.vinyl_photos)])

        self.marquee_off = (self.marquee_off + 1.6 * self.S) % max(1, self.marquee_src.width)
        self._draw_marquee()

        for sp in self.sparkles:
            sp["t"] += sp["speed"]
            v = (1 + math.sin(sp["t"])) / 2
            self.cv.itemconfigure(sp["item"], image=sp["frames"][min(3, int(v * 4))])

        segs = self.eq_geom[0]
        for i, col in enumerate(self.eq_rects):
            if self.busy:
                self.eq_levels[i] += (random.random() * 0.95 - self.eq_levels[i]) * 0.35
            else:
                self.eq_levels[i] *= 0.9
            self.eq_peaks[i] = max(self.eq_levels[i], self.eq_peaks[i] - 0.015)
            lit = int(self.eq_levels[i] * segs)
            peak = min(segs - 1, int(self.eq_peaks[i] * segs))
            for k, rect in enumerate(col):
                if k < lit:
                    c = skin.LIME if k < segs * 0.6 else (skin.AMBER if k < segs * 0.85 else skin.PINK)
                elif k == peak and self.eq_peaks[i] > 0.05:
                    c = skin.PINK
                else:
                    c = "#12301f"
                self.cv.itemconfigure(rect, fill=c)

        self._after = self.root.after(33, self._tick)


# -------------------------------------------------------------- selftest --

def selftest(report: Path) -> int:
    """Headless-ish checks for the packaged app (run in CI on the built .exe)."""
    lines: List[str] = []
    failed = False

    def flush() -> None:
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def check(name: str, fn: Callable[[], str], required: bool = True, timeout: float = 0) -> None:
        """Run one check and record it right away (so a hang still leaves a report).
        With a timeout the check runs on a helper thread and is abandoned if it stalls."""
        nonlocal failed
        try:
            if timeout:
                box: dict = {}

                def run() -> None:
                    try:
                        box["ok"] = fn()
                    except Exception as e:  # handed back to the main thread
                        box["err"] = e

                t = threading.Thread(target=run, daemon=True)
                t.start()
                t.join(timeout)
                if t.is_alive():
                    raise TimeoutError(f"no answer after {timeout:.0f}s")
                if "err" in box:
                    raise box["err"]
                result = box["ok"]
            else:
                result = fn()
            lines.append(f"PASS {name}: {result}")
        except Exception as e:
            lines.append(f"{'FAIL' if required else 'WARN'} {name}: {type(e).__name__}: {e}")
            failed = failed or required
        flush()

    def imports() -> str:
        import mutagen, yt_dlp, yt_dlp_ejs  # noqa: F401
        from yt_dlp.version import __version__ as v
        return f"yt-dlp {v}"

    def ffmpeg() -> str:
        from .downloader import find_ffmpeg
        path = find_ffmpeg()
        exe = path if os.path.isfile(path) else os.path.join(path, "ffmpeg")
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=60).stdout
        return out.splitlines()[0]

    def jsrt() -> str:
        from .downloader import find_js_runtime
        rt = find_js_runtime()
        if not rt:
            raise RuntimeError("no deno/node found")
        name, cfg = next(iter(rt.items()))
        exe = cfg.get("path") or name
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
        return f"{name} {out.splitlines()[0] if out else '?'}"

    def ui() -> str:
        # Run the real event loop briefly (root.update() can block on macOS).
        root = tk.Tk()
        app = App(root)
        seen = {}

        def finish() -> None:
            seen["items"] = len(app.cv.find_all())
            app.close()

        root.after(1500, finish)
        root.mainloop()
        # Free Tk objects here on the main thread; if the garbage collector got to
        # them later from a worker thread, Tcl would abort the process.
        del app, root
        gc.collect()
        return f"{seen.get('items', 0)} canvas items"

    def spotify() -> str:
        from .spotify import fetch
        col = fetch("https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa")
        return f"{col.name}: {len(col.tracks)} tracks"

    def search() -> str:
        from .downloader import Downloader
        from .spotify import Track
        import tempfile
        d = Downloader(Path(tempfile.gettempdir()))
        m = d.find(Track("One More Time", ["Daft Punk"], 320_000))
        return m.url if m else "no match"

    def download() -> str:
        # Big Buck Bunny (CC-BY Blender Foundation): exercises the JS runtime, ffmpeg and tagging.
        import tempfile
        from .downloader import Downloader
        from .matcher import Candidate
        from .spotify import Track
        d = Downloader(Path(tempfile.mkdtemp()), fmt="mp3")
        p = d.download(Track("Big Buck Bunny", ["Blender Foundation"], 596_000),
                       Candidate("aqz-KE-bpKQ", "Big Buck Bunny", "Blender", 596))
        return f"{p.name} {p.stat().st_size // 1024} KB"

    check("imports", imports)
    check("ffmpeg", ffmpeg)
    check("js runtime", jsrt)
    check("gui", ui)
    # Network checks: CI runners are sometimes blocked by YouTube, so these only warn.
    check("spotify", spotify, required=False, timeout=45)
    check("youtube search", search, required=False, timeout=45)
    check("youtube download", download, required=False, timeout=180)
    lines.append("RESULT: " + ("FAIL" if failed else "OK"))
    flush()
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--selftest":
        report = Path(argv[1] if len(argv) > 1 else "selftest.txt")
        return selftest(report)
    enable_hidpi()
    root = tk.Tk()
    App(root)
    root.mainloop()
    del root
    gc.collect()  # tear Tk down on the main thread (see selftest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
