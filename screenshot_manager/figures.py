"""Potong gambar soal figural dari screenshot soal (tanpa OCR/AI, murni piksel).

Aturan:
  a. BARIS JAWABAN PERTAMA = pita horizontal ±40 px yang panjangnya ≥ 30% lebar gambar,
     berwarna abu muda (±#F1F1F1), hijau (kunci), atau merah (jawaban salah). Pita yang
     membentang hampir selebar gambar (header situs) diabaikan.
  b. AWAL GAMBAR = baris pertama di bawah 8% teratas yang punya garis lurus GELAP
     (hitam/abu tua, bukan merah/hijau) sepanjang ≥ 45 px. Teks & tombol tidak memenuhi.
  c. Area = awal gambar … 10 px di atas baris jawaban pertama, dipangkas ke kotak tinta
     gelap + margin 12 px.
  d. Diterima hanya bila ≥ 300×100 px dan tanpa piksel hijau/merah (kunci tidak bocor).
  e. Garis gelap ≥ 45 px DI DALAM pita jawaban = pilihan berupa gambar -> "manual".
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image

LINE_MIN = 45          # panjang garis lurus gelap minimum (px)
TOP_IGNORE = 0.08      # bagian atas yang diabaikan (header, logo)
MARGIN = 12
MIN_W, MIN_H = 300, 100


@dataclass
class FigureResult:
    status: str                         # "ok" | "manual" | "none"
    box: Optional[dict] = None          # {x, y, w, h} bila ok (atau saran awal bila manual)
    reason: str = ""
    bands: list = field(default_factory=list)


def _masks(a: np.ndarray):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = mx - mn
    dark = (mx < 110) & (sat < 40)
    green = (g > r + 40) & (g > b + 40) & (g > 90)
    red = (r > g + 60) & (r > b + 60) & (r > 90)
    light = (mn >= 225) & (mx <= 250) & (sat <= 8)          # abu muda ±#F1F1F1
    return dark, green, red, light


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    """Panjang run True terpanjang di tiap baris."""
    h, w = mask.shape
    out = np.zeros(h, dtype=np.int32)
    pad = np.zeros(w + 2, dtype=np.int8)
    for y in np.flatnonzero(mask.any(axis=1)):
        pad[1:-1] = mask[y]
        d = np.diff(pad)
        s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        out[y] = int((e - s).max())
    return out


def answer_bands(a: np.ndarray) -> list[tuple[int, int, str]]:
    """Pita jawaban (y0, y1, warna) dari atas ke bawah."""
    h, w = a.shape[:2]
    _, green, red, light = _masks(a)
    rows = {}
    for name, m in (("abu", light), ("hijau", green), ("merah", red)):
        runs = _longest_runs(m)
        rows[name] = (runs >= 0.30 * w) & (runs < 0.98 * w)
    bands = []
    for name, on in rows.items():
        start = None
        for y in range(h + 1):
            v = y < h and on[y]
            if v and start is None:
                start = y
            elif not v and start is not None:
                if 20 <= y - start <= 90:
                    bands.append((start, y - 1, name))
                start = None
    return sorted(bands)


def detect_question_figure(img: Image.Image) -> FigureResult:
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    H, W = a.shape[:2]
    top = int(TOP_IGNORE * H) if H < 1500 else int(TOP_IGNORE * 1500)
    bands = [b for b in answer_bands(a) if b[0] > top]
    if not bands:
        return FigureResult("none", reason="baris jawaban tidak ditemukan")
    dark, green, red, _ = _masks(a)
    dark_runs = _longest_runs(dark)
    first = bands[0]

    # e. gambar di dalam pilihan jawaban -> potong manual
    opts = bands[:5]
    in_opts = any((dark_runs[b0:b1 + 1] >= LINE_MIN).any() for b0, b1, _ in opts)

    # b. awal gambar
    stop = first[0] - 10
    cand = np.flatnonzero(dark_runs[top:max(top, stop)] >= LINE_MIN)
    box = None
    reason = ""
    if len(cand):
        y_start = top + int(cand[0])
        region = dark[y_start:stop]
        ys, xs = np.nonzero(region)
        if len(ys):
            x0, x1 = int(xs.min()) - MARGIN, int(xs.max()) + MARGIN
            y0, y1 = y_start + int(ys.min()) - MARGIN, y_start + int(ys.max()) + MARGIN
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W - 1, x1), min(H - 1, min(y1, stop))
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            colored = int(green[y0:y1 + 1, x0:x1 + 1].sum() + red[y0:y1 + 1, x0:x1 + 1].sum())
            if bw < MIN_W or bh < MIN_H:
                reason = f"terlalu kecil ({bw}×{bh})"
            elif colored > 10:
                reason = "ada warna hijau/merah di dalam potongan"
            else:
                box = {"x": x0, "y": y0, "w": bw, "h": bh}
    else:
        reason = "tidak ada garis gambar di atas pilihan jawaban"
    if in_opts:
        return FigureResult("manual", box, "gambar ada di dalam pilihan jawaban — potong manual", bands)
    if box is not None:
        return FigureResult("ok", box, "", bands)
    return FigureResult("none", None, reason, bands)


def crop_png_bytes(img: Image.Image, box: dict) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(buf, "PNG")
    return buf.getvalue()


# kompatibilitas: daftar kotak gambar (0 atau 1) seperti versi lama
def detect_figures(img: Image.Image) -> list[dict]:
    r = detect_question_figure(img)
    return [dict(r.box, bagian="soal")] if r.status == "ok" else []
