"""Pembuat halaman soal + pembahasan tiruan (teks biasa atau figural)."""
import random

from PIL import Image, ImageDraw

W = 760
BAR_COLORS = [(240, 240, 240), (139, 0, 0), (240, 240, 240), (240, 240, 240), (0, 170, 0)]


def shapes(d, x, y, w, h, seed):
    """Gambar bangun-bangun (pola figural) di kotak (x, y, w, h)."""
    rnd = random.Random(seed)
    n = max(1, w // h)
    for i in range(n):
        cx = x + i * h + h // 2
        cy = y + h // 2
        r = h // 2 - 4
        kind = rnd.randint(0, 2)
        if kind == 0:
            d.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], outline="black", width=2)
        elif kind == 1:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="black", width=2)
            d.line([cx - r, cy, cx + r, cy], fill="black", width=2)
        else:
            d.rectangle([cx - r, cy - r, cx + r, cy + r], outline="black", width=2)
            d.rectangle([cx - r // 2, cy - r // 2, cx, cy], fill="black")


def text_lines(d, x, y, n, rnd, fill="black", width=700):
    for i in range(n):
        d.text((x, y + i * 16), " ".join("kata" + "x" * rnd.randint(0, 6) for _ in range(rnd.randint(6, 14)))[:110],
               fill=fill)
    return y + n * 16


def make_question(seed=1, fig_soal=False, fig_opsi=False, fig_pembahasan=False):
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, 1400), "white")
    d = ImageDraw.Draw(img)
    truth = []
    d.rounded_rectangle([4, 4, W - 5, 640], radius=14, outline=(230, 230, 230))     # kartu soal
    d.text((24, 22), f"Soal Nomor {seed} (PG)", fill="black")
    d.rectangle([W - 90, 18, W - 30, 36], fill=(26, 128, 76))                         # "Tampilkan"
    d.text((W - 84, 22), "Tampilkan", fill="white")
    y = text_lines(d, 24, 56, 3, rnd)
    if fig_soal:
        y += 8
        shapes(d, 30, y, 4 * 80, 80, seed)
        d.text((380, y + 30), "?", fill="black")
        truth.append(("soal", (30, y, 4 * 80, 80)))
        y += 92
    y += 10
    for i, col in enumerate(BAR_COLORS):
        bh = 56 if fig_opsi else 44
        d.rounded_rectangle([24, y, W - 24, y + bh], radius=10, fill=col)
        txt = "white" if col != (240, 240, 240) else "black"
        d.text((40, y + bh // 2 - 6), "ABCDE"[i], fill=txt)
        if fig_opsi:
            d.rectangle([70, y + 6, 70 + 3 * 44, y + 50], fill="white")
            shapes(d, 70, y + 6, 3 * 44, 44, seed * 10 + i)
            truth.append((f"opsi {'ABCDE'[i]}", (70, y + 6, 3 * 44, 44)))
        else:
            d.text((64, y + bh // 2 - 6), "pilihan jawaban " + "y" * rnd.randint(5, 40), fill=txt)
        y += bh + 12
    y = max(y, 0) + 30
    d.text((24, y), f"Pembahasan Nomor {seed}", fill="black")
    d.text((24, y + 24), "Jawaban kamu : B", fill="black")
    d.rectangle([130, y + 22, 160, y + 36], fill=(220, 53, 69))                        # badge "Salah"
    d.text((133, y + 24), "Salah", fill="white")
    d.rounded_rectangle([24, y + 50, W - 24, y + 80], radius=8, outline=(240, 200, 210))
    d.rectangle([330, y + 59, 342, y + 71], fill=(139, 0, 0))                           # ikon buku
    d.text((350, y + 59), "Pembahasan Soal", fill=(139, 0, 0))
    y = text_lines(d, 24, y + 96, 6, rnd)
    if fig_pembahasan:
        shapes(d, 200, y + 10, 2 * 90, 90, seed + 99)
        truth.append(("pembahasan", (200, y + 10, 180, 90)))
        y += 110
    y = text_lines(d, 24, y + 10, 4, rnd)
    return img.crop((0, 0, W, y + 40)), truth
