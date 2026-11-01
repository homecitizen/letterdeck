"""Interfaz de la CYD (320x240) dibujada con Pillow.

Diseño original con carátula a la izquierda, información superior,
barra de progreso completa, botonera central y deslizador de volumen inferior.
Incluye optimización de color y tramado Bayer anti-banding para panel RGB565.
"""
import io
import os
from functools import lru_cache
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

BOX = Image.Resampling.BOX

W, H = 320, 240
SS = 4  # supersampling para las formas vectoriales (bordes suaves)

# ---- Textos y acento ----
STR_IDLE = "Nada sonando"
STR_IDLE_SUB = "Abre Apple Music y dale al play"
ACCENT = (250, 45, 72)  # rojo/rosa de Apple Music

# ---- Maquetación original (px) ----
ART_X, ART_Y, ART_S = 18, 22, 108
TEXT_X, TEXT_R = 140, 306
PROG_BOX = (0, 136, 320, 172)    # barra de progreso + tiempos
BTN_BOX = (72, 172, 248, 214)    # anterior / play-pausa / siguiente
VOL_BOX = (0, 214, 320, 240)     # volumen
BAR_X0, BAR_X1 = 20, 300
VOL_X0, VOL_X1 = 46, 274
BTN_Y = 193
BTN_X = {"prev": 104, "play": 160, "next": 216}

# ---------------------------------------------------------------- fuentes

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

FONT_FILES = {
    "latin": {"regular": ["segoeui.ttf", "arial.ttf"],
              "semibold": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"],
              "bold": ["segoeuib.ttf", "arialbd.ttf"]},
    "jp": {"regular": ["YuGothM.ttc", "meiryo.ttc"], "semibold": ["YuGothM.ttc", "meiryo.ttc"],
           "bold": ["YuGothB.ttc", "meiryob.ttc"]},
    "kr": {"regular": ["malgun.ttf"], "semibold": ["malgunbd.ttf"], "bold": ["malgunbd.ttf"]},
    "zh": {"regular": ["msyh.ttc"], "semibold": ["msyhbd.ttc"], "bold": ["msyhbd.ttc"]},
}
FALLBACK_FONTS = {
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "semibold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def script_of(text):
    """Elige familia de fuente según caracteres (Segoe UI no trae CJK)."""
    kana = hangul = han = False
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
            kana = True
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            hangul = True
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            han = True
    if hangul:
        return "kr"
    if kana:
        return "jp"
    if han:
        return "zh"
    return "latin"


@lru_cache(maxsize=None)
def font(script, weight, size):
    for name in FONT_FILES[script][weight]:
        path = os.path.join(FONT_DIR, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    for path in FALLBACK_FONTS[weight]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


@lru_cache(maxsize=None)
def symbol_font(size):
    for path in (os.path.join(FONT_DIR, "seguisym.ttf"), os.path.join(FONT_DIR, "segoeui.ttf"), FALLBACK_FONTS["regular"][0]):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def ellipsize(s, f, maxw):
    if f.getlength(s) <= maxw:
        return s
    while s and f.getlength(s + "…") > maxw:
        s = s[:-1]
    return s.rstrip() + "…"


def wrap(s, f, maxw, maxlines=2):
    """Parte en líneas (por espacios o caracteres) y añade elipsis si no cabe."""
    s = " ".join(s.split())
    lines = []
    while s and len(lines) < maxlines:
        if f.getlength(s) <= maxw:
            lines.append(s)
            s = ""
            break
        n = len(s)
        while n > 1 and f.getlength(s[:n]) > maxw:
            n -= 1
        cut = s[:n].rfind(" ")
        if cut > 0:
            n = cut
        lines.append(s[:n].rstrip())
        s = s[n:].lstrip()
    if s and lines:
        lines[-1] = ellipsize(lines[-1] + " " + s, f, maxw)
    return lines


# ---------------------------------------------------------------- utilidades de dibujo

def put_text(img, xy, text, f, fill=(255, 255, 255, 255), anchor="ls"):
    """Texto con transparencia y sin halos oscuros."""
    layer = Image.new("RGBA", img.size, tuple(fill[:3]) + (0,))
    ImageDraw.Draw(layer).text(xy, text, font=f, fill=tuple(fill), anchor=anchor)
    img.alpha_composite(layer)


def vector(img, fn):
    """Dibuja formas a 4x supersampling y las reduce con bordes suaves."""
    big = Image.new("RGBA", (img.width * SS, img.height * SS), (255, 255, 255, 0))
    fn(ImageDraw.Draw(big), lambda v: int(round(v * SS)))
    img.alpha_composite(big.resize(img.size, BOX))


def fmt_time(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def to_jpeg(img, quality=94):
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=quality, subsampling=0)
    return b.getvalue()


def to_jpeg_fit(img, max_bytes, quality=94):
    while True:
        data = to_jpeg(img, quality)
        if len(data) <= max_bytes or quality <= 55:
            return data
        quality -= 4


# ---------------------------------------------------------------- fondo y base

def vertical_gradient(size, top, bottom):
    w, h = size
    g = Image.linear_gradient("L").resize((w, h))
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), g)


def make_background(art):
    """Fondo ambiental suave con tramado Bayer para evitar escalonamiento en pantalla RGB565."""
    if art is None:
        bg = vertical_gradient((W, H), (58, 58, 72), (18, 18, 24))
    else:
        small = art.resize((24, 24), BOX)
        bg = small.resize((W, H), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(14))
        bg = ImageEnhance.Color(bg).enhance(1.4)
        bg = ImageEnhance.Brightness(bg).enhance(0.70)
        lum = ImageStat.Stat(bg.convert("L")).mean[0]
        if lum > 95:
            bg = ImageEnhance.Brightness(bg).enhance(95 / lum)

    # Velo oscuro degradado hacia abajo para dar contraste a los controles inferiores
    mask = Image.linear_gradient("L").resize((W, H)).point(lambda v: v * 105 // 255)
    bg.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), mask)

    # Tramado Bayer 4x4 para eliminar banding en 16-bit
    pixels = bg.load()
    bayer = [
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5]
    ]
    for y in range(H):
        by = y % 4
        for x in range(W):
            bx = x % 4
            dither = (bayer[by][bx] - 7.5) * 0.35
            r, g, b = pixels[x, y]
            pixels[x, y] = (
                max(0, min(255, int(r + dither))),
                max(0, min(255, int(g + dither))),
                max(0, min(255, int(b + dither)))
            )
    return bg


def rounded(img, size, radius):
    img = ImageOps.fit(img.convert("RGB"), (size, size), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius * SS, fill=255)
    img.putalpha(m.resize((size, size), BOX))
    return img


def placeholder_art():
    art = vertical_gradient((ART_S, ART_S), (96, 96, 112), (44, 44, 58)).convert("RGBA")
    put_text(art, (ART_S // 2, ART_S // 2 + 2), "♪", symbol_font(58), (255, 255, 255, 150), "mm")
    return art.convert("RGB")


def build_base(title, artist, album, art_bytes):
    """Fondo + carátula + textos (la parte que solo cambia al cambiar de canción)."""
    art = None
    if art_bytes:
        try:
            art = Image.open(io.BytesIO(art_bytes))
            art.load()
            art = art.convert("RGB")
        except Exception:
            art = None

    base = make_background(art).convert("RGBA")

    # Sombra + carátula con esquinas redondeadas
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [ART_X, ART_Y + 5, ART_X + ART_S, ART_Y + ART_S + 7], 10, fill=(0, 0, 0, 140))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    base.alpha_composite(rounded(art if art else placeholder_art(), ART_S, 10), (ART_X, ART_Y))

    maxw = TEXT_R - TEXT_X
    put_text(base, (TEXT_X, 32), "♫", symbol_font(13), ACCENT + (255,))
    put_text(base, (TEXT_X + 17, 32), "Apple Music", font("latin", "semibold", 11), (255, 255, 255, 160))

    tf = font(script_of(title), "bold", 19)
    lines = wrap(title or "—", tf, maxw, 2)
    y = 58 + (2 - len(lines)) * 8  # una línea: baja un poco para centrar el bloque
    for line in lines:
        put_text(base, (TEXT_X, y), line, tf, (255, 255, 255, 255))
        y += 23
    y += 1
    af = font(script_of(artist), "semibold", 15)
    put_text(base, (TEXT_X, y), ellipsize(artist or "", af, maxw), af, (255, 255, 255, 190))
    if album:
        y += 20
        bf = font(script_of(album), "regular", 12)
        put_text(base, (TEXT_X, y), ellipsize(album or "", bf, maxw), bf, (255, 255, 255, 125))
    return base


def build_idle():
    """Pantalla en reposo cuando no hay música activa."""
    base = vertical_gradient((W, H), (34, 34, 44), (10, 10, 15)).convert("RGBA")
    put_text(base, (W // 2, 96), "♫", symbol_font(60), ACCENT + (255,), "mm")
    put_text(base, (W // 2, 152), STR_IDLE, font("latin", "bold", 20), (255, 255, 255, 255), "ms")
    put_text(base, (W // 2, 176), STR_IDLE_SUB, font("latin", "regular", 12), (255, 255, 255, 135), "ms")
    return base


# ---------------------------------------------------------------- elementos dinámicos

def _patch(base, box):
    return base.crop(box).convert("RGBA")


def render_progress(base, pos, dur):
    p = _patch(base, PROG_BOX)
    ox, oy = PROG_BOX[0], PROG_BOX[1]
    x0, x1, by = BAR_X0 - ox, BAR_X1 - ox, 146 - oy
    frac = 0.0 if dur <= 0 else max(0.0, min(1.0, pos / dur))
    fx = x0 + (x1 - x0) * frac

    def shapes(d, k):
        d.rounded_rectangle([k(x0), k(by), k(x1), k(by + 5)], k(2.5), fill=(255, 255, 255, 65))
        if frac > 0:
            d.rounded_rectangle([k(x0), k(by), k(max(fx, x0 + 5)), k(by + 5)], k(2.5), fill=(255, 255, 255, 245))
    vector(p, shapes)

    tf = font("latin", "semibold", 11)
    put_text(p, (x0, 30), fmt_time(pos), tf, (255, 255, 255, 150), "ls")
    if dur > 0:
        put_text(p, (x1, 30), "-" + fmt_time(dur - pos), tf, (255, 255, 255, 150), "rs")
    return p


def _tri(d, k, pts, r=1.3):
    """Triángulo con esquinas redondeadas (relleno + contorno con unión curva)."""
    kp = [(k(x), k(y)) for x, y in pts]
    d.polygon(kp, fill=(255, 255, 255, 255))
    d.line(kp + [kp[0]], fill=(255, 255, 255, 255), width=k(2 * r), joint="curve")


def render_buttons(base, playing):
    p = _patch(base, BTN_BOX)
    ox, oy = BTN_BOX[0], BTN_BOX[1]
    cy = BTN_Y - oy

    def shapes(d, k):
        # Anterior: dos triángulos hacia la izquierda
        cx = BTN_X["prev"] - ox
        for off in (-11, 0):
            _tri(d, k, [(cx + off, cy), (cx + off + 10, cy - 8), (cx + off + 10, cy + 8)])
        # Siguiente: dos triángulos hacia la derecha
        cx = BTN_X["next"] - ox
        for off in (0, 11):
            _tri(d, k, [(cx + off, cy - 8), (cx + off + 10, cy), (cx + off, cy + 8)])
        # Play / Pausa central
        cx = BTN_X["play"] - ox
        if playing:
            for bx in (-11, 3):
                d.rounded_rectangle([k(cx + bx), k(cy - 13), k(cx + bx + 8), k(cy + 13)], k(2.2),
                                    fill=(255, 255, 255, 255))
        else:
            _tri(d, k, [(cx - 9, cy - 12), (cx + 12, cy), (cx - 9, cy + 12)], r=1.8)
    vector(p, shapes)
    return p


def _speaker(d, k, cx, cy, waves):
    pts = [(cx - 7, cy - 3), (cx - 3, cy - 3), (cx + 2, cy - 7.5), (cx + 2, cy + 7.5), (cx - 3, cy + 3), (cx - 7, cy + 3)]
    kp = [(k(x), k(y)) for x, y in pts]
    white = (255, 255, 255, 190)
    d.polygon(kp, fill=white)
    d.line(kp + [kp[0]], fill=white, width=k(1.2), joint="curve")
    for r in ([5.5, 9.5] if waves else []):
        d.arc([k(cx + 2 - r), k(cy - r), k(cx + 2 + r), k(cy + r)], -45, 45, fill=white, width=k(1.6))


def render_volume(base, vol):
    p = _patch(base, VOL_BOX)
    ox, oy = VOL_BOX[0], VOL_BOX[1]
    x0, x1, cy = VOL_X0 - ox, VOL_X1 - ox, 227 - oy
    fx = x0 + (x1 - x0) * max(0.0, min(1.0, vol))

    def shapes(d, k):
        _speaker(d, k, 26, cy, False)
        _speaker(d, k, 292, cy, True)
        d.rounded_rectangle([k(x0), k(cy - 2), k(x1), k(cy + 2)], k(2), fill=(255, 255, 255, 65))
        d.rounded_rectangle([k(x0), k(cy - 2), k(max(fx, x0 + 4)), k(cy + 2)], k(2), fill=(255, 255, 255, 240))
        d.ellipse([k(fx - 6), k(cy - 6), k(fx + 6), k(cy + 6)], fill=(255, 255, 255, 255))
    vector(p, shapes)
    return p


def compose(base, pos=0.0, dur=0.0, playing=False, vol=0.5, controls=True):
    """Fotograma completo: base + elementos dinámicos."""
    img = base.copy()
    if controls:
        img.paste(render_progress(base, pos, dur), PROG_BOX[:2])
        img.paste(render_buttons(base, playing), BTN_BOX[:2])
        img.paste(render_volume(base, vol), VOL_BOX[:2])
    return img


# ---------------------------------------------------------------- toques

def hit_test(x, y):
    """Qué se ha tocado: 'seek' | 'prev' | 'play' | 'next' | 'vol' | None."""
    if y >= 212:
        return "vol" if VOL_X0 - 18 <= x <= VOL_X1 + 18 else None
    if y >= 170:
        name = min(BTN_X, key=lambda n: abs(x - BTN_X[n]))
        return name if abs(x - BTN_X[name]) <= 30 else None
    if y >= 128 and BAR_X0 - 14 <= x <= BAR_X1 + 14:
        return "seek"
    return None


def frac_from_x(x, x0, x1):
    return max(0.0, min(1.0, (x - x0) / float(x1 - x0)))


# ---------------------------------------------------------------- prueba de orientación

def build_orient_test(n):
    """Pantalla para elegir orientación: texto legible + triángulo rojo en esquina superior derecha."""
    img = vertical_gradient((W, H), (30, 30, 40), (8, 8, 12)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.polygon([(W - 1, 0), (W - 80, 0), (W - 1, 80)], fill=ACCENT + (255,))
    d.polygon([(0, H - 1), (60, H - 1), (0, H - 61)], fill=(80, 140, 255, 255))
    put_text(img, (W // 2, 70), "Orientación %d" % n, font("latin", "bold", 26), (255, 255, 255, 255), "mm")
    put_text(img, (W // 2, 118), "¿Se lee bien (sin espejo)?", font("latin", "semibold", 16), (255, 255, 255, 220), "mm")
    put_text(img, (W // 2, 150), "Rojo = arriba a la derecha", font("latin", "regular", 14), (255, 255, 255, 170), "mm")
    put_text(img, (W // 2, 176), "Azul = abajo a la izquierda", font("latin", "regular", 14), (255, 255, 255, 170), "mm")
    return img


# ---------------------------------------------------------------- vista previa

def _demo_art():
    art = Image.new("RGB", (400, 400))
    d = ImageDraw.Draw(art)
    for i in range(400):
        d.line([(0, i), (400, i)], fill=(40 + i // 4, 70, 190 - i // 3))
    d.ellipse([90, 60, 310, 280], fill=(240, 190, 170))
    d.rectangle([70, 250, 330, 400], fill=(70, 120, 210))
    return art


if __name__ == "__main__":
    buf = io.BytesIO()
    _demo_art().save(buf, "JPEG")
    frames = []
    for title, artist, album, playing in [
        ("drivers license", "Olivia Rodrigo", "SOUR", True),
        ("Una canción larga", "Artista Con Nombre Largo", "Álbum", False),
        ("Track 3", "Artist 3", "Album 3", True),
    ]:
        base = build_base(title, artist, album, buf.getvalue())
        img = compose(base, 94, 242, playing, 0.55)
        data = to_jpeg_fit(img, 44000)
        frames.append(Image.open(io.BytesIO(data)))
    frames.append(compose(build_idle(), controls=False).convert("RGB"))
    sheet = Image.new("RGB", (W * 2 + 30, H * 2 + 30), (20, 20, 20))
    for i, f in enumerate(frames):
        sheet.paste(f, (10 + (i % 2) * (W + 10), 10 + (i // 2) * (H + 10)))
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.Resampling.LANCZOS).save("preview.png")
    print("preview.png generado con el diseño original")
