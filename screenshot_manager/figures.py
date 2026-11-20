"""Deteksi gambar di dalam screenshot soal (soal figural / bergambar).

Tanpa OCR/AI — murni bentuk piksel:
  * "tinta" = piksel gelap atau berwarna pekat;
  * huruf dalam satu baris digabung (dilatasi horizontal) sehingga teks menjadi
    komponen pendek setinggi satu baris;
  * bar pilihan jawaban berwarna = komponen sangat lebar & padat -> diabaikan;
  * sisanya yang jauh lebih tinggi dari satu baris teks = gambar (bangun, pola,
    grafik, tabel, rumus bergambar).
Label bagian (soal / opsi A–E / pembahasan) ditentukan dari posisi gambar terhadap
bar pilihan jawaban (baris-baris berlatar warna yang membentang lebar).
"""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from .autosetup import components

LETTERS = "ABCDE"


def _ink(a: np.ndarray) -> np.ndarray:
    gray = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    return (gray < 150) | ((sat > 80) & (gray < 200))


def _dilate_h(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for k in range(1, r + 1):
        out[:, k:] |= mask[:, :-k]
        out[:, :-k] |= mask[:, k:]
    return out


def _row_modes(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Warna dominan tiap baris (terkuantisasi /2) dan porsinya."""
    h, w, _ = a.shape
    q = (a // 2).astype(np.int32)
    keys = (q[:, :, 0] << 16) | (q[:, :, 1] << 8) | q[:, :, 2]
    modes = np.zeros((h, 3), dtype=np.int16)
    frac = np.zeros(h)
    for y in range(h):
        vals, cnt = np.unique(keys[y], return_counts=True)
        i = cnt.argmax()
        v = int(vals[i])
        modes[y] = [(v >> 16) * 2, ((v >> 8) & 255) * 2, (v & 255) * 2]
        frac[y] = cnt[i] / w
    return modes, frac


def option_bands(a: np.ndarray, text_h: float, modes=None, frac=None) -> list[tuple[int, int, np.ndarray]]:
    """Baris berlatar warna selain latar halaman yang membentang lebar = bar pilihan jawaban.

    Mengembalikan (y_awal, y_akhir, warna_bar)."""
    if modes is None:
        modes, frac = _row_modes(a)
    h = a.shape[0]
    vals, cnt = np.unique(modes, axis=0, return_counts=True)
    page_bg = vals[cnt.argmax()]
    rows = (frac > 0.5) & (np.abs(modes - page_bg).max(axis=1) > 6)
    bands, start = [], None
    for y in range(h + 1):
        on = y < h and rows[y]
        if on and start is not None and np.abs(modes[y] - modes[start]).max() > 6:
            on = False                                         # warna berganti: bar lain
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start >= 1.6 * text_h:
                vals_b, cnt_b = np.unique(modes[start:y], axis=0, return_counts=True)
                bands.append((start, y - 1, vals_b[cnt_b.argmax()]))
            start = None if y >= h or not rows[y] else y
    return bands


def detect_figures(img: Image.Image) -> list[dict]:
    """Kotak gambar [{x, y, w, h, bagian}] di dalam screenshot soal; [] bila soal teks biasa."""
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    ink = _ink(a)
    comps = components(_dilate_h(ink, 3), 25)
    if not comps:
        return []
    hs = [c[3] - c[1] + 1 for c in comps if (c[2] - c[0] + 1) >= 2 * (c[3] - c[1] + 1) >= 12]
    text_h = float(np.median(hs)) if hs else 14.0
    text_h = min(max(text_h, 8.0), 40.0)

    # hapus warna latar bar pilihan dari "tinta" agar gambar di dalam bar berwarna tidak menyatu
    modes, frac = _row_modes(a)
    bands = option_bands(a, text_h, modes, frac)
    if bands:
        for b0, b1, col in bands:
            same = np.abs(a[b0:b1 + 1] - col).max(axis=2) <= 24
            ink[b0:b1 + 1] &= ~same
        comps = components(_dilate_h(ink, 3), 25)

    cands = []
    for x0, y0, x1, y1, n in comps:
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if h <= 2.2 * text_h:
            continue                                   # teks / ikon kecil
        if w >= 6 * h and n / (w * h) >= 0.5:
            continue                                   # bar pilihan berwarna
        if h <= 3.2 * text_h and n / (w * h) >= 0.7:
            continue                                   # tombol / label kecil berisi teks
        if w < 1.5 * text_h:
            continue                                   # garis tegak tipis (tepi kartu)
        if w * h > 0.6 * a.shape[0] * a.shape[1]:
            continue                                   # menutupi hampir seluruh layar = latar
        cands.append([x0, y0, x1, y1])
    if not cands:
        return []

    # gabungkan bagian-bagian satu gambar yang berdekatan
    gap = 0.9 * text_h
    merged = True
    while merged:
        merged = False
        out = []
        for c in cands:
            for m in out:
                if c[0] <= m[2] + gap and m[0] <= c[2] + gap and c[1] <= m[3] + gap and m[1] <= c[3] + gap:
                    m[0], m[1] = min(m[0], c[0]), min(m[1], c[1])
                    m[2], m[3] = max(m[2], c[2]), max(m[3], c[3])
                    merged = True
                    break
            else:
                out.append(list(c))
        cands = out

    opts = [(b0, b1) for b0, b1, _ in bands][:5] if len(bands) >= 2 else []
    H, W = a.shape[:2]
    pad = 6
    figs = []
    for x0, y0, x1, y1 in sorted(cands, key=lambda b: (b[1], b[0])):
        cy = (y0 + y1) / 2
        if opts and cy < opts[0][0]:
            part = "soal"
        elif opts and cy > opts[-1][1]:
            part = "pembahasan"
        else:
            part = "gambar"
            for i, (b0, b1) in enumerate(opts):
                if b0 <= cy <= b1:
                    part = f"opsi {LETTERS[i]}" if len(opts) == 5 else f"opsi {i + 1}"
                    break
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(W - 1, x1 + pad), min(H - 1, y1 + pad)
        figs.append({"x": int(x0), "y": int(y0), "w": int(x1 - x0 + 1), "h": int(y1 - y0 + 1), "bagian": part})
    return figs


def crop_png_bytes(img: Image.Image, fig: dict) -> bytes:
    buf = io.BytesIO()
    img.crop((fig["x"], fig["y"], fig["x"] + fig["w"], fig["y"] + fig["h"])).save(buf, "PNG")
    return buf.getvalue()


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
