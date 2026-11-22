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
    """Jumlah baris pilihan jawaban (bar abu muda / hijau / merah).

    Teks di dalam bar memotong warna bar, jadi baris bar dikenali dari PORSI warnanya (≥ 5% lebar;
    baris berteks panjang pun masih di atasnya), dan bar-bar dipisahkan oleh celah putih bersih. Bar sah bila
    tingginya 18–400 px, ada baris yang ≥ 40% (tepi bar yang polos), dan tidak menyentuh kedua tepi
    gambar (bukan header/menu situs).
    """
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w = a.shape[:2]
    if h < 20 or w < 20:
        return 0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    # abu bar = #F1F1F1 (bayangan kartu 247+ bukan bar), hijau = kunci, merah = jawaban salah
    bar = ((mn >= 230) & (mx <= 246) & (mx - mn <= 6)) | \
          ((g > r + 40) & (g > b + 40) & (g > 90)) | \
          ((r > g + 60) & (r > b + 60) & (r > 90))
    edge = bar[:, :6].all(axis=1) & bar[:, -6:].all(axis=1)  # pita padat dari tepi ke tepi = header
    bar[edge] = False                                         # (bayangan kartu 1–3 px tidak terhitung)
    frac = bar.sum(axis=1) / w
    on = frac >= 0.05                  # baris bar (baris berteks panjang di dalam bar pun masih ≥ 5%);
    #                                    celah antar bar = putih bersih (±0%)
    count, start = 0, None
    for y in range(h + 1):
        v = y < h and on[y]
        if v and start is None:
            start = y
        elif not v and start is not None:
            if 18 <= y - start <= 400 and frac[start:y].max() >= 0.40:
                count += 1
            start = None
    return count


def trim_for_export(img: Image.Image, margin: int = 10) -> Image.Image:
    """Pangkas screenshot soal untuk ekspor: dari judul "TRY OUT …" sampai kalimat terakhir pembahasan.

    - atas: lewati baris polos & garis/pita header yang membentang dari tepi ke tepi;
    - bawah: berhenti di baris TULISAN GELAP terakhir (tombol Sebelumnya/Selanjutnya, ruang kosong,
      dan tepi kartu di bawahnya dibuang);
    - kiri/kanan: buang area putih polos di samping isi.
    """
    rgb = img.convert("RGB")
    a = np.asarray(rgb, dtype=np.int16)
    h, w = a.shape[:2]
    smp = a[:: max(1, h // 200), :: max(1, w // 200)].reshape(-1, 3)
    vals, cnt = np.unique(smp, axis=0, return_counts=True)
    bg = vals[cnt.argmax()]
    diff = np.abs(a - bg).max(axis=2)
    content = diff > 12                                         # bukan latar polos
    mx, mn = a.max(axis=2), a.min(axis=2)
    dark = (mx < 170) & (mx - mn < 40)                          # tulisan hitam/abu (bukan tombol merah)

    rows = content.any(axis=1)
    if not rows.any():
        return rgb
    # atas: lewati pita/garis header yang menyentuh kedua tepi (hanya di bagian paling atas)
    top = 0
    limit = min(h, 160)
    while top < limit and (not rows[top] or (content[top, :3].any() and content[top, -3:].any())):
        top += 1
    if top >= limit:
        top = 0
    while top < h and not rows[top]:
        top += 1
    # bawah: baris terakhir yang berisi tulisan gelap
    dark_rows = np.flatnonzero(dark[top:].sum(axis=1) >= 2)
    bottom = top + int(dark_rows[-1]) if len(dark_rows) else int(np.flatnonzero(rows)[-1])
    # kiri/kanan: kolom berisi di antara top..bottom
    cols = np.flatnonzero(content[top:bottom + 1].any(axis=0))
    left, right = int(cols[0]), int(cols[-1])
    box = (max(0, left - margin), max(0, top - margin), min(w, right + margin + 1), min(h, bottom + margin + 1))
    return rgb.crop(box)
