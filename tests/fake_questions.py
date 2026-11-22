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


# ---------------------------------------------------------------- tangkapan mirip Privat Alfaiz
GRAY, RED, GREEN = (241, 241, 241), (183, 28, 28), (46, 160, 67)


def _figure_panel(d, x, y, w, h, seed):
    """Panel figural: kotak-kotak bergaris hitam berisi bangun (Analogi/Serial Figural)."""
    rnd = random.Random(seed)
    n = 4
    cw = w // n
    for i in range(n):
        bx = x + i * cw
        d.rectangle([bx + 4, y, bx + cw - 4, y + h], outline="black", width=2)
        cx, cy, r = bx + cw // 2, y + h // 2, min(cw, h) // 3
        k = rnd.randint(0, 2)
        if k == 0:
            d.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], outline="black", width=2)
        elif k == 1:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="black", width=2)
        else:
            d.rectangle([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill="black")


def make_alfaiz_question(seed=1, kind="text", header=True):
    """kind: text | figural | opsi (pilihan berupa gambar) | table."""
    rnd = random.Random(seed)
    W = 790
    img = Image.new("RGB", (W, 2000), "white")
    d = ImageDraw.Draw(img)
    y = 0
    if header:
        d.rectangle([0, 0, W, 56], fill=(139, 0, 0))                  # header situs
        d.rectangle([40, 8, 132, 47], fill=(30, 30, 30))               # logo AL FAIZ 92×39
        d.text((52, 20), "AL FAIZ", fill="white")
        d.text((300, 22), "Beranda   Mulai Belajar   Paket Belajar Saya", fill="white")
        y = 70
        d.text((20, y), "< TRY OUT SKD CASN 2026 - PART 39", fill=(139, 0, 0))
        y += 30
    d.text((24, y + 8), f"Soal Nomor {seed + 30} (PG)", fill="black")
    d.rectangle([W - 110, y + 4, W - 40, y + 26], fill=(26, 128, 76))     # tombol "Tampilkan"
    d.text((W - 102, y + 9), "Tampilkan", fill="white")
    y += 44
    y = text_lines(d, 24, y, 2 + rnd.randint(0, 2), rnd)
    truth = None
    if kind == "figural":
        y += 10
        _figure_panel(d, 40, y, 520, 130, seed)
        truth = (40, y, 520, 130)
        y += 150
    elif kind == "table":                                              # tabel bergaris abu muda
        y += 8
        for i in range(3):
            d.line([24, y + i * 26, 500, y + i * 26], fill=(210, 210, 210))
        d.text((30, y + 6), "Kuantitas P        Kuantitas Q", fill="black")
        d.text((30, y + 32), "2/3 dari 90         65", fill="black")
        y += 70
    y += 12
    colors = [GRAY, RED, GRAY, GRAY, GREEN]
    for i, col in enumerate(colors):
        d.rounded_rectangle([24, y, W - 24, y + 40], radius=10, fill=col)
        tc = "black" if col == GRAY else "white"
        d.text((40, y + 14), "ABCDE"[i], fill=tc)
        if kind == "opsi":
            d.rectangle([70, y + 4, 70 + 150, y + 36], fill="white", outline="black", width=2)
            _figure_panel(d, 74, y + 8, 140, 24, seed * 10 + i)
        else:
            d.text((64, y + 14), "pilihan jawaban " + "y" * rnd.randint(5, 40), fill=tc)
        y += 52
    y += 30
    d.text((24, y), f"Pembahasan Nomor {seed + 30}", fill="black")
    d.text((24, y + 24), "Jawaban kamu : B", fill="black")
    d.rectangle([130, y + 22, 160, y + 36], fill=(220, 53, 69))          # badge "Salah"
    d.rounded_rectangle([24, y + 50, W - 24, y + 80], radius=8, outline=(240, 200, 210))
    d.text((350, y + 59), "Pembahasan Soal", fill=(139, 0, 0))
    y = text_lines(d, 24, y + 96, 6, rnd)
    d.text((24, y + 8), "Jawaban: E.", fill="black")
    y += 40
    d.rectangle([24, y, 24 + 155, y + 48], fill=(220, 53, 69))          # "Sebelumnya"
    d.rectangle([W - 24 - 155, y, W - 24, y + 48], fill=(220, 53, 69))  # "Selanjutnya" 155×48
    d.text((W - 150, y + 18), "Selanjutnya", fill="white")
    return img.crop((0, 0, W, y + 70)), truth


def make_long_question(q: int, height: int) -> Image.Image:
    """Soal panjang: teks soal ±560 px, lalu pilihan A–E, lalu pembahasan (E jatuh di bagian ke-2)."""
    rnd = random.Random(q)
    img = Image.new("RGB", (760, max(height, 1500)), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), f"Soal Nomor {q}", fill="black")
    y = text_lines(d, 20, 40, 32, rnd)
    for i, col in enumerate([GRAY, RED, GRAY, GRAY, GREEN]):
        d.rounded_rectangle([20, y, 740, y + 40], radius=8, fill=col)
        d.text((34, y + 14), "ABCDE"[i] + f"  pilihan {q}-{i}", fill="black" if col == GRAY else "white")
        y += 52
    y = text_lines(d, 20, y + 30, 25, rnd)
    return img.crop((0, 0, 760, y + 20))
