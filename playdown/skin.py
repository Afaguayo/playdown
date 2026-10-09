"""The Y2K skin: every visual piece of the GUI, drawn with Pillow.

Brushed metal, glossy aqua pill buttons, chrome logo type, sunken fields,
a green phosphor LCD and a spinning record: the look of early-2000s media
players and creative suites. Shapes are drawn supersampled (SS×) and scaled
down for smooth edges, since Tk can't anti-alias canvas shapes itself.
"""
from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path
from typing import List, Sequence, Tuple, Union

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ASSETS = Path(__file__).parent / "assets"
FONTS = ASSETS / "fonts"
SS = 3  # supersampling factor

Color = Union[str, Tuple[int, int, int], Tuple[int, int, int, int]]

# Palette
NAVY = "#14233a"
INK = "#1d2a3c"
LCD_TEXT = "#a6ff4d"
LCD_DIM = "#3d7a34"
AQUA = "#3cc8ff"
PINK = "#ff4fb8"
AMBER = "#ffc83d"
LIME = "#c6ff3a"

BUTTON_STYLES = {
    #          top        middle     bottom     border     text
    "aqua":   ("#c8f6ff", "#40c4ff", "#0a6cd4", "#063c80", "#ffffff"),
    "pink":   ("#ffd6f0", "#ff5cc0", "#cf1484", "#6a0944", "#ffffff"),
    "silver": ("#ffffff", "#e4e9f0", "#a8b2c0", "#5b6676", INK),
    "lime":   ("#f2ffc8", "#b8f230", "#57a600", "#2b5000", "#0f2208"),
    "dark":   ("#5d6a80", "#2c3646", "#141a24", "#05080d", LIME),
}


def rgba(c: Color, a: int = 255) -> Tuple[int, int, int, int]:
    if isinstance(c, str):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a
    if len(c) == 3:
        return c[0], c[1], c[2], a
    return tuple(c)  # type: ignore[return-value]


def mix(c1: Color, c2: Color, t: float) -> Tuple[int, int, int, int]:
    a, b = rgba(c1), rgba(c2)
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


@lru_cache(maxsize=None)
def font(name: str, size: int, weight: str = "") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / f"{name}.ttf"), max(1, int(size)))
    if weight:
        f.set_variation_by_name(weight)
    return f


def vgrad(w: int, h: int, stops: Sequence[Tuple[float, Color]]) -> Image.Image:
    """Vertical multi-stop gradient."""
    stops = [(p, rgba(c)) for p, c in stops]
    col = []
    for y in range(h):
        t = y / max(1, h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1 or (p1, c1) == stops[-1]:
                u = 0.0 if p1 == p0 else min(1.0, max(0.0, (t - p0) / (p1 - p0)))
                col.append(mix(c0, c1, u))
                break
    strip = Image.new("RGBA", (1, h))
    strip.putdata(col)
    return strip.resize((max(1, w), h), Image.NEAREST)


def rmask(w: int, h: int, r: float, inset: float = 0) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        (inset, inset, w - 1 - inset, h - 1 - inset), radius=max(0, r - inset), fill=255
    )
    return m


def layer(size: Tuple[int, int], fill: Union[Color, Image.Image], mask: Image.Image) -> Image.Image:
    """`fill` (a color or same-size image) cut out by `mask`."""
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    src = fill if isinstance(fill, Image.Image) else Image.new("RGBA", size, rgba(fill))
    out.paste(src, (0, 0), mask)
    return out


def down(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((max(1, w), max(1, h)), Image.LANCZOS)


def fade(img: Image.Image, alpha: float) -> Image.Image:
    a = img.getchannel("A").point(lambda v: int(v * alpha))
    out = img.copy()
    out.putalpha(a)
    return out


# ------------------------------------------------------------------ text --

def text_img(
    text: str,
    size: int,
    color: Color = INK,
    face: str = "Orbitron",
    weight: str = "Bold",
    emboss: Color = None,
    glow: Color = None,
    tracking: float = 0,
) -> Image.Image:
    """Tight RGBA image of a line of text. `emboss` adds a 1px highlight below
    (engraved-in-metal look); `glow` adds a soft halo (LCD phosphor look)."""
    f = font(face, size, weight if face == "Orbitron" else "")
    chars = list(text)
    widths = [f.getlength(c) + tracking for c in chars] if tracking else [f.getlength(text)]
    tw = int(sum(widths)) + 1
    asc, desc = f.getmetrics()
    pad = max(2, size // 4) if glow else 2
    W, H = tw + pad * 2, asc + desc + pad * 2
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def draw_into(img: Image.Image, dx: float, dy: float, c: Color) -> None:
        d = ImageDraw.Draw(img)
        if tracking:
            x = pad + dx
            for ch, cw in zip(chars, widths):
                d.text((x, pad + dy), ch, font=f, fill=rgba(c))
                x += cw
        else:
            d.text((pad + dx, pad + dy), text, font=f, fill=rgba(c))

    if glow:
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_into(g, 0, 0, glow)
        out.alpha_composite(g.filter(ImageFilter.GaussianBlur(max(1.5, size / 7))))
    if emboss:
        draw_into(out, 0, 1, emboss)
    draw_into(out, 0, 0, color)
    return out


def chrome_text(text: str, size: int, weight: str = "Black") -> Image.Image:
    """Big chrome logo type: mirror gradient with a horizon line, dark outline, drop shadow."""
    s = 2
    f = font("Orbitron", size * s, weight)
    stroke = max(2, size // 11) * s
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    pad = 10 * s
    W, H = r - l + pad * 2, b - t + pad * 2
    origin = (pad - l, pad - t)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).text(
        (origin[0] + 3 * s, origin[1] + 4 * s), text, font=f, fill=170, stroke_width=stroke, stroke_fill=170
    )
    out.alpha_composite(layer((W, H), (8, 18, 40), shadow.filter(ImageFilter.GaussianBlur(3 * s))))

    outline = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outline).text(origin, text, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
    ol, ot, orr, ob = outline.getbbox()
    out.alpha_composite(layer((W, H), _band(W, H, ot, ob, [(0, "#2b4a78"), (1, "#081428")]), outline))

    fill = Image.new("L", (W, H), 0)
    ImageDraw.Draw(fill).text(origin, text, font=f, fill=255)
    fl, ft, fr, fb = fill.getbbox()
    chrome = _band(W, H, ft, fb, [
        (0.00, "#ffffff"), (0.40, "#dbe6f2"), (0.49, "#7c8ea6"), (0.52, "#34435a"),
        (0.62, "#7f98b8"), (0.85, "#d8f4ff"), (1.00, "#ffffff"),
    ])
    out.alpha_composite(layer((W, H), chrome, fill))

    # thin specular rim along the top of each glyph
    rim = ImageChops.subtract(fill, fill.transform(fill.size, Image.AFFINE, (1, 0, 0, 0, 1, -2 * s)))
    out.alpha_composite(layer((W, H), (255, 255, 255, 200), rim))
    return down(out, W // s, H // s)


def _band(W: int, H: int, y0: int, y1: int, stops) -> Image.Image:
    """Full-size image whose gradient spans only rows y0..y1."""
    img = Image.new("RGBA", (W, H), rgba(stops[0][1]))
    g = vgrad(W, max(1, y1 - y0), stops)
    img.paste(g, (0, y0))
    img.paste(Image.new("RGBA", (W, max(0, H - y1)), rgba(stops[-1][1])), (0, y1))
    return img


# ---------------------------------------------------------------- chrome --

def brushed_metal(w: int, h: int, seed: int = 7) -> Image.Image:
    base = vgrad(w, h, [(0, "#eef1f6"), (0.5, "#d4dae3"), (1, "#b9c1cd")])
    random.seed(seed)
    noise = Image.effect_noise((max(1, w // 60), h), 40).convert("RGBA")
    streaks = noise.resize((w, h), Image.BICUBIC)
    out = Image.blend(base, streaks, 0.07)
    # faint diagonal sheen across the plate
    sheen = Image.new("L", (w, h), 0)
    ImageDraw.Draw(sheen).polygon([(w * 0.15, 0), (w * 0.45, 0), (w * 0.25, h), (-w * 0.05, h)], fill=26)
    out.alpha_composite(layer((w, h), (255, 255, 255), sheen.filter(ImageFilter.GaussianBlur(w / 20))))
    return out


def bevel_frame(w: int, h: int, r: int, S: float) -> Image.Image:
    """Raised outer rim of the whole window: dark edge + bright inner highlight."""
    s = SS
    W, H = w * s, h * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    lw = max(1, round(S)) * s
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=r * s, outline=rgba("#4e5868"), width=lw * 2)
    d.rounded_rectangle((lw * 2, lw * 2, W - 1 - lw * 2, H - 1 - lw * 2), radius=(r - 2) * s,
                        outline=rgba("#ffffff", 200), width=lw)
    return down(out, w, h)


def groove(w: int, S: float) -> Image.Image:
    """Engraved horizontal line."""
    t = max(1, round(S))
    img = Image.new("RGBA", (w, t * 2), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w, t), rgba("#7d8796", 200)), (0, 0))
    img.paste(Image.new("RGBA", (w, t), rgba("#ffffff", 220)), (0, t))
    return img


def screw(d: int, angle: float = 30) -> Image.Image:
    s = SS
    D = d * s
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    m = Image.new("L", (D, D), 0)
    ImageDraw.Draw(m).ellipse((s, s, D - 1 - s, D - 1 - s), fill=255)
    out.alpha_composite(layer((D, D), "#5b6676", m))
    m2 = Image.new("L", (D, D), 0)
    ImageDraw.Draw(m2).ellipse((2 * s, 2 * s, D - 1 - 2 * s, D - 1 - 2 * s), fill=255)
    out.alpha_composite(layer((D, D), vgrad(D, D, [(0, "#ffffff"), (1, "#9aa4b2")]), m2))
    slot = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    ImageDraw.Draw(slot).line((D * 0.25, D / 2, D * 0.75, D / 2), fill=rgba("#4a5464"), width=max(1, D // 9))
    out.alpha_composite(slot.rotate(angle, resample=Image.BICUBIC))
    return down(out, d, d)


def panel(w: int, h: int, title: str, S: float) -> Tuple[Image.Image, int]:
    """Raised plate with an engraved section title. Returns (image, margin) — the
    image is bigger than w×h by `margin` on every side to fit the drop shadow."""
    s = SS
    m = int(8 * S)
    W, H = (w + 2 * m) * s, (h + 2 * m) * s
    r = 12 * S * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    box = (m * s, m * s, W - m * s - 1, H - m * s - 1)

    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle((box[0], box[1] + 3 * S * s, box[2], box[3] + 3 * S * s), radius=r, fill=90)
    out.alpha_composite(layer((W, H), (20, 32, 56), sh.filter(ImageFilter.GaussianBlur(4 * S * s))))

    plate_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(plate_mask).rounded_rectangle(box, radius=r, fill=255)
    out.alpha_composite(layer((W, H), "#7f8a9a", plate_mask))
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inner).rounded_rectangle(
        (box[0] + s * S, box[1] + s * S, box[2] - s * S, box[3] - s * S), radius=r - s * S, fill=255
    )
    out.alpha_composite(layer((W, H), vgrad(W, H, [(0, "#ffffff"), (0.3, "#f1f4f8"), (1, "#d3d9e2")]), inner))
    img = down(out, w + 2 * m, h + 2 * m)

    # Section title: small aqua bullet + engraved caps
    tx, ty = m + int(14 * S), m + int(8 * S)
    dot = int(7 * S)
    bullet = gloss_dot(dot, AQUA)
    img.alpha_composite(bullet, (tx, ty + int(3 * S)))
    label = text_img(title, int(11 * S), "#4f5b6d", weight="Bold", emboss="#ffffff", tracking=1.6 * S)
    img.alpha_composite(label, (tx + dot + int(6 * S), ty - 2))
    return img, m


def gloss_dot(d: int, color: Color) -> Image.Image:
    s = SS
    D = d * s
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    m = Image.new("L", (D, D), 0)
    ImageDraw.Draw(m).ellipse((0, 0, D - 1, D - 1), fill=255)
    out.alpha_composite(layer((D, D), vgrad(D, D, [(0, mix(color, "#ffffff", 0.5)), (1, mix(color, "#000000", 0.35))]), m))
    hl = Image.new("L", (D, D), 0)
    ImageDraw.Draw(hl).ellipse((D * 0.2, D * 0.08, D * 0.8, D * 0.5), fill=170)
    out.alpha_composite(layer((D, D), (255, 255, 255), hl))
    return down(out, d, d)


def inset(w: int, h: int, r: float, S: float, fill: Color = "#f5f9ff") -> Image.Image:
    """Sunken field (text input / readout) with a beveled rim and inner shadow."""
    s = SS
    W, H, R = w * s, h * s, r * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(layer((W, H), vgrad(W, H, [(0, "#66717f"), (1, "#ffffff")]), rmask(W, H, R)))
    b = max(1, S) * s * 1.2
    out.alpha_composite(layer((W, H), fill, rmask(W, H, R, inset=b)))
    shade = vgrad(W, H, [(0, (0, 20, 50, 85)), (min(1, 7 / h), (0, 20, 50, 0)), (1, (0, 20, 50, 0))])
    out.alpha_composite(layer((W, H), shade, rmask(W, H, R, inset=b)))
    return down(out, w, h)


# --------------------------------------------------------------- buttons --

def gloss_button(
    w: int, h: int, label: str, style: str = "aqua", state: str = "normal",
    font_size: int = 0, radius: float = -1, S: float = 1.0,
) -> Image.Image:
    """Glossy 'lickable' pill button. state: normal | hover | down | disabled."""
    s = SS
    W, H = w * s, h * s
    top, midc, bot, border, textc = BUTTON_STYLES[style]
    if state == "hover":
        top, midc, bot = mix(top, "#ffffff", 0.25), mix(midc, "#ffffff", 0.18), mix(bot, "#ffffff", 0.12)
    elif state == "down":
        top, midc, bot = mix(bot, "#000000", 0.1), midc, mix(top, midc, 0.3)

    sh_off = max(1, round(2 * S)) * s
    BH = H - sh_off
    R = (h / 2 if radius < 0 else radius) * s
    R = min(R, BH / 2)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    if state != "down":
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle((s, sh_off, W - 1 - s, H - 1), radius=R, fill=110)
        out.alpha_composite(layer((W, H), (10, 22, 48), sh.filter(ImageFilter.GaussianBlur(1.2 * s * S))))
        oy = 0
    else:
        oy = sh_off // 2

    body = Image.new("RGBA", (W, BH), (0, 0, 0, 0))
    body.alpha_composite(layer((W, BH), border, rmask(W, BH, R)))
    b = max(1.0, S) * s
    inner = rmask(W, BH, R, inset=b)
    body.alpha_composite(layer((W, BH), vgrad(W, BH, [(0, top), (0.5, midc), (1, bot)]), inner))

    # bottom glow: light bouncing inside the "gel"
    glow = Image.new("L", (W, BH), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.12, BH * 0.55, W * 0.88, BH * 1.25), fill=120 if state != "down" else 60)
    glow = Image.composite(glow.filter(ImageFilter.GaussianBlur(BH / 6)), Image.new("L", (W, BH), 0), inner)
    body.alpha_composite(layer((W, BH), mix(midc, "#ffffff", 0.55), glow))

    # top gloss highlight
    gh = int(BH * 0.5)
    gloss_mask = Image.new("L", (W, BH), 0)
    ImageDraw.Draw(gloss_mask).rounded_rectangle(
        (b * 2.2, b * 1.6, W - 1 - b * 2.2, gh), radius=max(0, R - b * 2), fill=255
    )
    galpha = 0.85 if state != "down" else 0.35
    gloss = vgrad(W, BH, [(0, (255, 255, 255, int(235 * galpha))), (gh / BH, (255, 255, 255, int(40 * galpha))),
                          (1, (255, 255, 255, 0))])
    body.alpha_composite(layer((W, BH), gloss, gloss_mask))

    if label:
        fs = (font_size or h * 0.36) * s
        f = font("Orbitron", fs, "Black" if style != "silver" else "Bold")
        tl, tt, tr, tb = f.getbbox(label)
        tx = (W - (tr - tl)) / 2 - tl
        ty = (BH - (tb - tt)) / 2 - tt
        d = ImageDraw.Draw(body)
        if style in ("silver",):
            d.text((tx, ty + s), label, font=f, fill=rgba("#ffffff", 230))
        else:
            d.text((tx, ty + s * 1.2), label, font=f, fill=rgba(mix(border, "#000000", 0.2), 200))
        d.text((tx, ty), label, font=f, fill=rgba(textc))

    out.alpha_composite(body, (0, oy))
    img = down(out, w, h)
    if state == "disabled":
        img = ImageEnhance.Color(img).enhance(0.1)
        img = fade(ImageEnhance.Brightness(img).enhance(1.08), 0.55)
    return img


def led(d: int, on: bool, color: Color = LIME) -> Image.Image:
    """Round indicator LED for toggles. Image is d×d plus room for the glow."""
    s = SS
    g = d // 3
    D = (d + 2 * g) * s
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    c0 = (g * s, g * s, D - 1 - g * s, D - 1 - g * s)
    if on:
        halo = Image.new("L", (D, D), 0)
        ImageDraw.Draw(halo).ellipse(c0, fill=200)
        out.alpha_composite(layer((D, D), color, halo.filter(ImageFilter.GaussianBlur(g * s * 0.7))))
    rim = Image.new("L", (D, D), 0)
    ImageDraw.Draw(rim).ellipse(c0, fill=255)
    out.alpha_composite(layer((D, D), vgrad(D, D, [(0, "#4e5868"), (1, "#ffffff")]), rim))
    lens = Image.new("L", (D, D), 0)
    k = 1.6 * s
    ImageDraw.Draw(lens).ellipse((c0[0] + k, c0[1] + k, c0[2] - k, c0[3] - k), fill=255)
    lit = [(0, mix(color, "#ffffff", 0.6)), (1, mix(color, "#000000", 0.15))]
    dark = [(0, mix(color, "#000000", 0.55)), (1, mix(color, "#000000", 0.8))]
    out.alpha_composite(layer((D, D), vgrad(D, D, lit if on else dark), lens))
    hl = Image.new("L", (D, D), 0)
    cx0, cy0, cx1, cy1 = c0
    ImageDraw.Draw(hl).ellipse((cx0 + (cx1 - cx0) * 0.28, cy0 + (cy1 - cy0) * 0.14,
                                cx0 + (cx1 - cx0) * 0.72, cy0 + (cy1 - cy0) * 0.45), fill=190)
    out.alpha_composite(layer((D, D), (255, 255, 255), hl))
    return down(out, d + 2 * g, d + 2 * g)


# -------------------------------------------------------------------- LCD --

def lcd_bezel(w: int, h: int, screen_inset: int, S: float) -> Image.Image:
    s = SS
    W, H = w * s, h * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    R = 16 * S * s
    out.alpha_composite(layer((W, H), "#05080d", rmask(W, H, R)))
    out.alpha_composite(layer((W, H), vgrad(W, H, [(0, "#5a6578"), (0.1, "#2c3442"), (1, "#0f141c")]),
                              rmask(W, H, R, inset=S * s * 1.2)))
    k = screen_inset * s
    screen = Image.new("L", (W, H), 0)
    ImageDraw.Draw(screen).rounded_rectangle((k, k, W - 1 - k, H - 1 - k), radius=7 * S * s, fill=255)
    out.alpha_composite(layer((W, H), "#000000", screen))
    screen2 = Image.new("L", (W, H), 0)
    ImageDraw.Draw(screen2).rounded_rectangle((k + s, k + s, W - 1 - k - s, H - 1 - k - s), radius=7 * S * s - s, fill=255)
    out.alpha_composite(layer((W, H), vgrad(W, H, [(0, "#0f2a1e"), (1, "#03100a")]), screen2))
    return down(out, w, h)


def lcd_glass(w: int, h: int, S: float) -> Image.Image:
    """Overlay drawn on top of LCD content: scanlines + glare. Mostly transparent."""
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    step = max(2, round(3 * S))
    for y in range(0, h, step):
        d.line((0, y, w, y), fill=(0, 0, 0, 55))
    glare = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glare).polygon([(0, 0), (w * 0.55, 0), (w * 0.35, h * 0.45), (0, h * 0.62)], fill=20)
    out.alpha_composite(layer((w, h), (190, 255, 220), glare.filter(ImageFilter.GaussianBlur(6 * S))))
    return out


LCD_COLORS = {"ok": LCD_TEXT, "have": AQUA, "miss": AMBER, "err": PINK, "info": "#e6ffd6", "dim": LCD_DIM}


def lcd_lines(lines: List[Tuple[str, str]], w: int, h: int, S: float, size: int) -> Image.Image:
    """Render the scrolling log (newest at the bottom) with phosphor glow."""
    f = font("VT323", size)
    lh = int(size * 1.0)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    visible = lines[-(h // lh):]
    y = h - lh * len(visible)
    d, dg = ImageDraw.Draw(out), ImageDraw.Draw(glow)
    for text, kind in visible:
        c = rgba(LCD_COLORS.get(kind, LCD_TEXT))
        text = fit(text, f, w - 4)
        dg.text((2, y), text, font=f, fill=c)
        d.text((2, y), text, font=f, fill=c)
        y += lh
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    base.alpha_composite(fade(glow.filter(ImageFilter.GaussianBlur(2.2 * S)), 0.9))
    base.alpha_composite(out)
    return base


def fit(text: str, f: ImageFont.FreeTypeFont, width: float) -> str:
    if f.getlength(text) <= width:
        return text
    while text and f.getlength(text + "...") > width:
        text = text[:-1]
    return text + "..."


def marquee_strip(text: str, size: int, S: float, color: Color = LCD_TEXT) -> Image.Image:
    """One loop of marquee text (caller tiles it)."""
    img = text_img(text, size, color, face="VT323", glow=color)
    return img


def led_bar(w: int, h: int, n: int, lit: int, S: float) -> Image.Image:
    """Segmented LED progress meter: green → yellow → pink like a VU meter."""
    s = SS
    W, H = w * s, h * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    R = H / 2.4
    out.alpha_composite(layer((W, H), "#05080d", rmask(W, H, R)))
    out.alpha_composite(layer((W, H), vgrad(W, H, [(0, "#0b1410"), (1, "#18241d")]), rmask(W, H, R, inset=s * S)))
    pad, gap = 4 * S * s, 2.5 * S * s
    sw = (W - pad * 2 - gap * (n - 1)) / n
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    segs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dg, ds = ImageDraw.Draw(glow), ImageDraw.Draw(segs)
    for i in range(n):
        t = i / max(1, n - 1)
        c = LIME if t < 0.68 else (AMBER if t < 0.86 else PINK)
        x0 = pad + i * (sw + gap)
        box = (x0, pad, x0 + sw, H - pad)
        if i < lit:
            dg.rounded_rectangle(box, radius=s * S, fill=rgba(c))
            ds.rounded_rectangle(box, radius=s * S, fill=rgba(mix(c, "#ffffff", 0.15)))
            ds.rectangle((x0 + s, pad + s, x0 + sw - s, pad + (H - 2 * pad) * 0.35), fill=(255, 255, 255, 90))
        else:
            ds.rounded_rectangle(box, radius=s * S, fill=rgba(mix(c, "#0b1410", 0.82)))
    out.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * s * S)))
    out.alpha_composite(segs)
    return down(out, w, h)


# ------------------------------------------------------------ decoration --

def vinyl_frames(d: int, n: int = 36) -> List[Image.Image]:
    """Frames of a spinning record with a pink/aqua label."""
    s = 2
    D = d * s
    c = D / 2
    R = D / 2 - 2 * s
    disc = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    dd.ellipse((c - R, c - R, c + R, c + R), fill=rgba("#0c0c10"), outline=rgba("#3d4250"), width=2 * s)
    label_r = R * 0.36
    rr = R - 4 * s
    k = 0
    while rr > label_r + 3 * s:
        dd.ellipse((c - rr, c - rr, c + rr, c + rr), outline=rgba("#1d1f26" if k % 2 else "#141519"), width=s)
        rr -= 2.2 * s
        k += 1
    dd.pieslice((c - label_r, c - label_r, c + label_r, c + label_r), 0, 180, fill=rgba(PINK))
    dd.pieslice((c - label_r, c - label_r, c + label_r, c + label_r), 180, 360, fill=rgba(AQUA))
    star = sparkle(int(label_r * 0.8), "#ffffff", glow=False)
    disc.alpha_composite(star, (int(c + label_r * 0.15), int(c - label_r * 0.75)))
    hole = label_r * 0.14
    dd.ellipse((c - hole, c - hole, c + hole, c + hole), fill=rgba("#cfd6df"))

    sheen = Image.new("L", (D, D), 0)
    sd = ImageDraw.Draw(sheen)
    sd.pieslice((c - R, c - R, c + R, c + R), 200, 235, fill=70)
    sd.pieslice((c - R, c - R, c + R, c + R), 20, 55, fill=55)
    sheen = sheen.filter(ImageFilter.GaussianBlur(3 * s))
    discmask = Image.new("L", (D, D), 0)
    ImageDraw.Draw(discmask).ellipse((c - R, c - R, c + R, c + R), fill=255)
    sheen = ImageChops.multiply(sheen, discmask)
    shadow = Image.new("L", (D, D), 0)
    ImageDraw.Draw(shadow).ellipse((c - R + 2 * s, c - R + 4 * s, c + R + 2 * s, c + R + 4 * s), fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(3 * s))

    frames = []
    for i in range(n):
        f = layer((D, D), (10, 18, 36), shadow)
        f.alpha_composite(disc.rotate(-i * 360 / n, resample=Image.BICUBIC, center=(c, c)))
        f.alpha_composite(layer((D, D), (255, 255, 255), sheen))
        frames.append(down(f, d, d))
    return frames


def sparkle(d: int, color: Color = "#ffffff", glow: bool = True) -> Image.Image:
    """Four-point twinkle star."""
    s = SS
    D = d * s
    c = D / 2
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    if glow:
        g = Image.new("L", (D, D), 0)
        ImageDraw.Draw(g).ellipse((c - D * 0.18, c - D * 0.18, c + D * 0.18, c + D * 0.18), fill=200)
        out.alpha_composite(layer((D, D), color, g.filter(ImageFilter.GaussianBlur(D / 10))))
    m = Image.new("L", (D, D), 0)
    t = D * 0.07
    ImageDraw.Draw(m).polygon(
        [(c, 0), (c + t, c - t), (D, c), (c + t, c + t), (c, D), (c - t, c + t), (0, c), (c - t, c - t)], fill=255
    )
    out.alpha_composite(layer((D, D), color, m))
    core = Image.new("L", (D, D), 0)
    ImageDraw.Draw(core).ellipse((c - t * 1.3, c - t * 1.3, c + t * 1.3, c + t * 1.3), fill=255)
    out.alpha_composite(layer((D, D), "#ffffff", core))
    return down(out, d, d)


def app_icon(size: int = 256) -> Image.Image:
    img = vinyl_frames(size, n=1)[0]
    sp = sparkle(size // 3, AQUA)
    img.alpha_composite(sp, (size - size // 3 - size // 24, size // 40))
    return img


if __name__ == "__main__":
    # python -m playdown.skin  → regenerate the app icons in assets/
    icon = app_icon(256)
    icon.save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", ASSETS / "icon.png", ASSETS / "icon.ico")
