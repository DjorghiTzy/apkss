"""Pemeriksa kualitas tangkapan: layar kosong/hitam & jumlah baris pilihan jawaban (A–E)."""
from __future__ import annotations

import numpy as np
from PIL import Image


def is_blank(img: Image.Image) -> bool:
    """True bila gambar nyaris satu warna (hitam / putih polos / layar loading)."""
    g = img.convert("L")
    small = g.resize((64, max(1, 64 * g.height // max(1, g.width))))
    lo, hi = small.getextrema()
    return hi - lo < 12


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    out = np.zeros(h, dtype=np.int32)
    pad = np.zeros(w + 2, dtype=np.int8)
    for y in np.flatnonzero(mask.any(axis=1)):
        pad[1:-1] = mask[y]
        d = np.diff(pad)
        s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        out[y] = int((e - s).max())
    return out


def option_rows(img: Image.Image) -> int:
    """Jumlah baris pilihan jawaban: pita ±40 px, ≥ 30% lebar, abu muda / hijau / merah."""
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w = a.shape[:2]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    masks = {
        "abu": (mn >= 225) & (mx <= 250) & (mx - mn <= 8),
        "hijau": (g > r + 40) & (g > b + 40) & (g > 90),
        "merah": (r > g + 60) & (r > b + 60) & (r > 90),
    }
    bands = 0
    for m in masks.values():
        runs = _longest_runs(m)
        # baris jawaban punya jarak di kiri & kanan; pita yang menyentuh tepi = header/menu situs
        on = (runs >= 0.30 * w) & (runs < 0.98 * w) & ~(m[:, 0] | m[:, -1])
        start = None
        for y in range(h + 1):
            v = y < h and on[y]
            if v and start is None:
                start = y
            elif not v and start is not None:
                if 20 <= y - start <= 90:
                    bands += 1
                start = None
    return bands
