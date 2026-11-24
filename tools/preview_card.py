"""
preview_card.py — Generador de vista previa de tarjeta estilo Letterboxd (320x240)
Dibuja exactamente la pantalla como se ve en el CYD ESP32.
"""
from PIL import Image, ImageDraw, ImageFont
import urllib.request
import io
import os

W, H = 320, 240
BG_COLOR    = (20, 24, 28)      # #14181C
CARD_COLOR  = (32, 40, 48)      # #202830
BORDER_COLOR= (56, 66, 78)      # #38424E
WHITE       = (255, 255, 255)
MUTED       = (154, 176, 192)   # #9AB0C0
LB_GREEN    = (0, 224, 84)      # #00E054
LB_ORANGE   = (255, 128, 0)     # #FF8000
LB_CYAN     = (64, 188, 244)    # #40BCF4

def create_preview(title="The Shining", year=1980, director="Stanley Kubrick",
                   genre="Terror Psicológico", rating=4.3,
                   tag="🎃 ESPECIAL HALLOWEEN", quote="«¡Aquí está Johnny!»",
                   poster_url="https://image.tmdb.org/t/p/w185/uAR0AWqhQL1hQa69UDEbb2rE5Wx.jpg",
                   output_path="preview_cinema.png"):
    img = Image.new("RGB", (W, H), BG_COLOR)
    d = ImageDraw.Draw(img)

    # 1. Descargar póster o hacer placeholder
    poster_w, poster_h = 108, 162
    poster_x, poster_y = 8, 8

    poster_img = None
    if poster_url:
        try:
            req = urllib.request.Request(poster_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw = resp.read()
                poster_img = Image.open(io.BytesIO(raw)).convert("RGB")
                poster_img = poster_img.resize((poster_w, poster_h), Image.Resampling.LANCZOS)
        except Exception as e:
            print("No se pudo descargar el póster:", e)

    if poster_img:
        img.paste(poster_img, (poster_x, poster_y))
        d.rounded_rectangle([poster_x-1, poster_y-1, poster_x+poster_w+1, poster_y+poster_h+1], 4, outline=BORDER_COLOR)
    else:
        d.rounded_rectangle([poster_x, poster_y, poster_x+poster_w, poster_y+poster_h], 6, fill=CARD_COLOR, outline=BORDER_COLOR)
        d.text((poster_x + poster_w//2, poster_y + 60), "🎬", fill=MUTED, anchor="mm")

    # 2. Valoración e icono Letterboxd bajo el póster
    d.text((poster_x + 2, poster_y + poster_h + 8), f"★ {rating:.1f} / 5", fill=LB_GREEN)

    # 3 círculos Letterboxd
    lx = poster_x + poster_w - 24
    ly = poster_y + poster_h + 14
    d.ellipse([lx, ly, lx+6, ly+6], fill=LB_ORANGE)
    d.ellipse([lx+8, ly, lx+14, ly+6], fill=LB_GREEN)
    d.ellipse([lx+16, ly, lx+22, ly+6], fill=LB_CYAN)

    # 3. Columna derecha
    rx = poster_x + poster_w + 14
    rw = W - rx - 8

    # Badge temático
    bw = len(tag) * 6 + 16
    d.rounded_rectangle([rx, 8, rx + bw, 24], 4, fill=CARD_COLOR, outline=LB_ORANGE)
    d.text((rx + 7, 10), tag, fill=LB_ORANGE)

    # Título
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 18)
        meta_font = ImageFont.truetype("segoeui.ttf", 12)
        quote_font = ImageFont.truetype("segoeuib.ttf", 13)
        small_font = ImageFont.truetype("segoeui.ttf", 10)
    except Exception:
        title_font = meta_font = quote_font = small_font = ImageFont.load_default()

    d.text((rx, 34), title, font=title_font, fill=WHITE)
    d.text((rx, 68), f"{year} · {director}", font=meta_font, fill=MUTED)
    d.text((rx, 86), f"Género: {genre}", font=meta_font, fill=MUTED)

    d.line([(rx, 110), (rx + rw, 110)], fill=BORDER_COLOR, width=1)

    # Cita célebre
    d.text((rx, 118), "CITA CÉLEBRE:", font=small_font, fill=LB_CYAN)
    d.text((rx, 136), quote, font=quote_font, fill=WHITE)

    # Navegación inferior
    d.text((rx, 222), "[Ver Sinopsis]", font=small_font, fill=MUTED)
    d.text((W - 14, 222), "Toca pantalla ►", font=small_font, fill=BORDER_COLOR, anchor="ra")

    # Guardar en doble resolución para nitidez
    scale = 2
    big = img.resize((W * scale, H * scale), Image.Resampling.NEAREST)
    big.save(output_path)
    print(f"Vista previa guardada en: {output_path}")

if __name__ == "__main__":
    create_preview()
