"""Atur Otomatis: kenali tata letak halaman pembahasan dari screenshot.

Yang dideteksi (tanpa OCR/AI; murni bentuk & warna piksel):
  - grid "Daftar Soal": tombol-tombol persegi seukuran yang tersusun rapi
    -> posisi nomor 1, jarak antar kolom/baris, jumlah kolom, jumlah nomor;
  - tombol dropdown "Tipe Soal": blok lebar di atas grid;
  - pilihan dropdown: bagian layar yang berubah setelah dropdown diklik;
  - area konten: bagian layar yang bergeser saat halaman di-scroll.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw

from .autocapture import NavConfig, StopRequested


class SetupError(Exception):
    pass


# ---------------------------------------------------------------- komponen terhubung

def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.int16)


def components(mask: np.ndarray, min_pixels: int = 20) -> list[tuple[int, int, int, int, int]]:
    """Bounding box (x0, y0, x1, y1, piksel) tiap komponen terhubung pada mask boolean."""
    h, w = mask.shape
    parent: list[int] = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    runs = []          # (row, x0, x1, id)
    prev: list[tuple[int, int, int]] = []
    padded = np.zeros(w + 2, dtype=np.int8)
    for y in range(h):
        padded[1:-1] = mask[y]
        d = np.diff(padded)
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        cur = []
        j = 0
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            rid = len(parent)
            parent.append(rid)
            while j < len(prev) and prev[j][1] < x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < x1:
                ra, rb = find(rid), find(prev[k][2])
                if ra != rb:
                    parent[ra] = rb
                k += 1
            cur.append((x0, x1, rid))
            runs.append((y, x0, x1, rid))
        prev = cur
    boxes: dict[int, list[int]] = {}
    for y, x0, x1, rid in runs:
        r = find(rid)
        b = boxes.get(r)
        if b is None:
            boxes[r] = [x0, y, x1 - 1, y, x1 - x0]
        else:
            b[0] = min(b[0], x0)
            b[2] = max(b[2], x1 - 1)
            b[3] = y
            b[4] += x1 - x0
    return [tuple(b) for b in boxes.values() if b[4] >= min_pixels]


# ---------------------------------------------------------------- grid Daftar Soal

@dataclass
class GridInfo:
    first: tuple[int, int]
    dx: float
    dy: float
    cols: int
    count: int
    box: int
    bbox: tuple[int, int, int, int]        # x0, y0, x1, y1 seluruh grid

    def position(self, n: int) -> tuple[int, int]:
        r, c = divmod(n - 1, self.cols)
        return round(self.first[0] + c * self.dx), round(self.first[1] + r * self.dy)


def detect_grid(img: Image.Image, hint: Optional[GridInfo] = None) -> Optional[GridInfo]:
    """hint: grid yang sudah diketahui (kategori lain) — kelompok yang nomor 1-nya di posisi yang
    sama dipilih walau hanya satu baris."""
    a = _arr(img)
    sat = a.max(axis=2) - a.min(axis=2)
    lum = a.mean(axis=2)
    mask = (sat > 50) | (lum < 215)
    cands = []
    for x0, y0, x1, y1, n in components(mask, 150):
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if 16 <= w <= 120 and 16 <= h <= 120 and 0.75 <= w / h <= 1.33 and n / (w * h) >= 0.6:
            cands.append(((x0 + x1) / 2, (y0 + y1) / 2, (w + h) / 2))
    if len(cands) < 4:
        return None
    # kelompokkan kotak yang bertetangga & seukuran
    best: list = []
    used = [False] * len(cands)
    for i in range(len(cands)):
        if used[i]:
            continue
        group, stack = [], [i]
        used[i] = True
        while stack:
            k = stack.pop()
            group.append(cands[k])
            for j in range(len(cands)):
                if not used[j]:
                    s = max(cands[k][2], cands[j][2])
                    if (abs(cands[k][2] - cands[j][2]) <= 0.2 * s
                            and abs(cands[k][0] - cands[j][0]) <= 2.2 * s
                            and abs(cands[k][1] - cands[j][1]) <= 2.2 * s):
                        used[j] = True
                        stack.append(j)
        rows = _cluster([g[1] for g in group], 0.35 * np.median([g[2] for g in group]))
        if hint is not None:
            top_left = min(group, key=lambda g: (round(g[1] / max(1.0, g[2])), g[0]))
            if abs(top_left[0] - hint.first[0]) <= hint.box / 2 and abs(top_left[1] - hint.first[1]) <= hint.box / 2:
                best = group
                break
        if len(rows) >= 2 and len(group) > len(best):
            best = group
    if not best:
        return None
    box = float(np.median([g[2] for g in best]))
    row_ys = _cluster([g[1] for g in best], 0.35 * box)
    col_xs = _cluster([g[0] for g in best], 0.35 * box)
    if len(col_xs) < 2 and hint is None:
        return None
    dx = float(np.median(np.diff(col_xs))) if len(col_xs) > 1 else hint.dx
    dy = float(np.median(np.diff(row_ys))) if len(row_ys) > 1 else (hint.dy if hint else dx)
    if hint is not None and len(col_xs) < hint.cols:      # satu baris pendek: pakai ukuran grid acuan
        dx = hint.dx
    x0, y0 = col_xs[0], row_ys[0]
    cols = hint.cols if hint is not None else int(round((col_xs[-1] - x0) / dx)) + 1
    idx = set()
    for gx, gy, _ in best:
        c, r = round((gx - x0) / dx), round((gy - y0) / dy)
        if abs(gx - (x0 + c * dx)) < 0.3 * box and abs(gy - (y0 + r * dy)) < 0.3 * box:
            idx.add(r * cols + c)
    if not idx:
        return None
    count = max(idx) + 1
    half = box / 2
    bbox = (int(x0 - half), int(y0 - half), int(col_xs[-1] + half), int(row_ys[-1] + half))
    return GridInfo((round(x0), round(y0)), dx, dy, cols, count, round(box), bbox)


def _cluster(values, tol) -> list[float]:
    vals = sorted(values)
    groups: list[list[float]] = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [float(np.mean(g)) for g in groups]


# ---------------------------------------------------------------- dropdown Tipe Soal

def _bg_color(a: np.ndarray, x: int, y: int) -> np.ndarray:
    h, w, _ = a.shape
    return a[min(max(y, 0), h - 1), min(max(x, 0), w - 1)]


def detect_dropdown(img: Image.Image, grid: GridInfo) -> Optional[tuple[int, int, int, int]]:
    """Blok lebar terisi (tombol Tipe Soal) di atas grid, di kolom sidebar yang sama."""
    a = _arr(img)
    gx0, gy0, gx1, _ = grid.bbox
    bg = _bg_color(a, gx0 - grid.box // 3, gy0 + grid.box // 2)
    x_lo = max(0, int(gx0 - grid.dx * 1.5))
    x_hi = min(a.shape[1], int(gx1 + grid.dx * 1.5))
    y_lo = max(0, int(gy0 - grid.dy * 9))
    y_hi = max(0, int(gy0 - grid.box * 0.6))
    sub = a[y_lo:y_hi, x_lo:x_hi]
    if sub.size == 0:
        return None
    mask = np.abs(sub - bg).max(axis=2) > 8
    best = None
    for x0, y0, x1, y1, n in components(mask, 200):
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if w >= 2.5 * grid.box and 0.55 * grid.box <= h <= 2.5 * grid.box and n / (w * h) >= 0.45 \
                and w <= (x_hi - x_lo) * 0.98:
            if best is None or y1 > best[3]:            # yang paling dekat di atas grid
                best = (x0, y0, x1, y1)
    if best is None:
        return None
    x0, y0, x1, y1 = best
    return x_lo + x0, y_lo + y0, x1 - x0 + 1, y1 - y0 + 1


def detect_menu(before: Image.Image, after: Image.Image, dropdown: tuple[int, int, int, int],
                n_items: int) -> list[tuple[int, int]]:
    """Posisi tengah tiap pilihan pada menu yang muncul di bawah tombol dropdown."""
    a, b = _arr(before), _arr(after)
    dx, dy, dw, dh = dropdown
    y_start = dy + dh + 1
    x_lo, x_hi = max(0, dx - dw), min(a.shape[1], dx + 2 * dw)
    diff = np.abs(a[y_start:, x_lo:x_hi] - b[y_start:, x_lo:x_hi]).max(axis=2) > 25
    comps = components(diff, 400)
    if not comps:
        raise SetupError("Menu Tipe Soal tidak muncul setelah tombolnya diklik")
    # komponen terbesar yang menempel di bawah tombol
    x0, y0, x1, y1, _ = max(comps, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
    mx0, my0, mx1, my1 = x_lo + x0, y_start + y0, x_lo + x1, y_start + y1
    # cari garis pemisah antar pilihan di dalam menu
    region = b[my0:my1 + 1, mx0:mx1 + 1]
    inner = region[:, int(region.shape[1] * 0.1):int(region.shape[1] * 0.9)]
    row_mean = inner.mean(axis=(1, 2))
    row_std = inner.std(axis=(1, 2))
    base = np.median(row_mean)
    sep = [i for i in range(2, len(row_mean) - 2) if row_std[i] < 6 and base - row_mean[i] > 6]
    bands = []
    for i in sep:
        if bands and i - bands[-1][-1] <= 2:
            bands[-1].append(i)
        else:
            bands.append([i])
    cuts = [0] + [int(np.mean(bd)) for bd in bands] + [my1 - my0]
    if len(cuts) - 1 != n_items:
        step = (my1 - my0) / n_items                      # bagi rata
        cuts = [round(i * step) for i in range(n_items + 1)]
    cx = (mx0 + mx1) // 2
    return [(cx, my0 + (cuts[i] + cuts[i + 1]) // 2) for i in range(n_items)]


# ---------------------------------------------------------------- area konten

def sidebar_left(img: Image.Image, grid: GridInfo) -> int:
    """Tepi kiri kartu sidebar (tempat grid)."""
    a = _arr(img)
    y = grid.first[1]
    x = int(grid.bbox[0] - 3)
    bg = a[y, x]
    run = 0
    while x > 0:
        x -= 1
        if np.abs(a[y, x] - bg).max() > 6:
            run += 1
            if run >= 2:
                return x + 2
        else:
            run = 0
            bg = a[y, x]
    return 0


def detect_scroll_area(before: Image.Image, after: Image.Image, x_limit: int) -> tuple[int, int, int, int]:
    """Kotak (x, y, w, h) bagian layar yang bergeser saat di-scroll, di kiri x_limit.

    Header situs yang menempel, toolbar browser, dan taskbar tidak bergeser, jadi tidak ikut.
    """
    a, b = _arr(before)[:, :x_limit], _arr(after)[:, :x_limit]
    diff = np.abs(a - b).max(axis=2) > 20
    cols = np.flatnonzero(diff.sum(axis=0) > 2)
    if len(cols) < 50:
        raise SetupError("Halaman tidak bergeser saat di-scroll — buka soal yang pembahasannya panjang")
    rows = np.flatnonzero(diff[:, cols[0]:cols[-1] + 1].any(axis=1))
    if len(rows) < 50:
        raise SetupError("Halaman tidak bergeser saat di-scroll — buka soal yang pembahasannya panjang")
    y0, y1 = int(rows[0]), int(rows[-1])
    # kolom teks = kolom yang banyak berubah saat scroll (tepi kartu hanya berubah di sudutnya)
    cnt = diff[y0:y1 + 1].sum(axis=0)
    text = np.flatnonzero(cnt >= max(3, 0.03 * (y1 - y0 + 1)))
    c_l, c_r = (int(text[0]), int(text[-1])) if len(text) else (int(cols[0]), int(cols[-1]))
    region = a[y0:y1 + 1, c_l:c_r + 1].reshape(-1, 3)
    vals, cntc = np.unique(region[:: max(1, len(region) // 20000)], axis=0, return_counts=True)
    page_bg = vals[cntc.argmax()]

    def card_edge(start, stop, step):
        """Garis tepi kartu: kolom yang tidak polos di sebagian besar baris."""
        for x in range(start, stop, step):
            col = a[y0:y1 + 1, x]
            if (np.abs(col - page_bg).max(axis=1) > 6).mean() >= 0.3:
                return x
        return None
    # pas: semua tulisan + ruang 12px, tanpa menyentuh garis/elemen terdekat (tepi kartu, sidebar)
    right = card_edge(c_r + 1, x_limit, 1)
    left = card_edge(c_l - 1, -1, -1)
    x1 = c_r + 12
    if right is not None:
        x1 = min(x1, right - 2)
    x1 = max(c_r + 1, min(x1, x_limit - 2))
    x0 = c_l - 12
    if left is not None:
        x0 = max(x0, left + 2)
    x0 = max(0, min(x0, c_l - 1))
    # baris tepi yang polos berwarna latar konten (celah putih) ikut dimasukkan, maks. 40px
    region = a[y0:y1 + 1, x0:x1 + 1].reshape(-1, 3)
    vals, cnt = np.unique(region[:: max(1, len(region) // 20000)], axis=0, return_counts=True)
    bgc = vals[cnt.argmax()]

    def plain(y):
        return (np.abs(a[y, x0:x1 + 1] - bgc).max() <= 3) and (np.abs(b[y, x0:x1 + 1] - bgc).max() <= 3)
    for _ in range(40):
        if y0 > 0 and plain(y0 - 1):
            y0 -= 1
    for _ in range(40):
        if y1 < a.shape[0] - 1 and plain(y1 + 1):
            y1 += 1
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


# ---------------------------------------------------------------- jalankan

@dataclass
class SetupResult:
    crop: dict
    nav: NavConfig
    counts: dict
    preview: Image.Image
    notes: list = field(default_factory=list)


def run_autosetup(driver, categories: list[str], progress: Callable[[str], None] = lambda m: None,
                  wait_load: float = 1.5, stop_event=None) -> SetupResult:
    """Deteksi semua pengaturan Tangkap Otomatis dari halaman pembahasan yang sedang terbuka."""
    notes: list[str] = []

    def sleep(s):
        end = time.monotonic() + s
        while time.monotonic() < end:
            if driver.stop_requested() or (stop_event is not None and stop_event.is_set()):
                raise StopRequested()
            driver.sleep(min(0.1, end - time.monotonic()) if end > time.monotonic() else 0)

    def grab():
        return driver.grab().convert("RGB")

    def stable():
        prev = grab()
        for _ in range(20):
            sleep(0.3)
            cur = grab()
            if cur.tobytes() == prev.tobytes():
                return cur
            prev = cur
        return prev

    first = grab()
    sw, sh = first.size
    park = (sw - 4, sh // 2)
    driver.move(*park)
    progress("Mencari Daftar Soal…")
    base = stable()
    grid = detect_grid(base)
    if grid is None:
        raise SetupError("Daftar Soal (tombol nomor) tidak ditemukan di layar. Buka halaman pembahasan "
                         "dengan Daftar Soal terlihat, lalu coba lagi.")
    progress(f"Daftar Soal: {grid.cols} kolom, {grid.count} nomor, jarak {grid.dx:.0f}×{grid.dy:.0f}px")

    nav = NavConfig(mode="grid", grid_first=list(grid.position(1)), grid_second=list(grid.position(2)),
                    grid_below=list(grid.position(grid.cols + 1)), columns=grid.cols, per_category=True)
    counts = {}
    if len(categories) > 1:
        progress("Mencari tombol Tipe Soal…")
        dd = detect_dropdown(base, grid)
        if dd is None:
            raise SetupError("Tombol dropdown “Tipe Soal” tidak ditemukan di atas Daftar Soal")
        dd_center = (dd[0] + dd[2] // 2, dd[1] + dd[3] // 2)
        nav.category_dropdown = list(dd_center)
        driver.click(*dd_center)
        driver.move(*park)
        sleep(0.8)
        opened = stable()
        options = detect_menu(base, opened, dd, len(categories))
        nav.category_options = {c: list(p) for c, p in zip(categories, options)}
        progress("Pilihan Tipe Soal: " + ", ".join(f"{c}@{p}" for c, p in zip(categories, options)))
        driver.click(*options[0])           # tutup menu dengan memilih kategori pertama
        sleep(wait_load)
        for cat, opt in zip(categories, options):
            driver.click(*dd_center)
            sleep(0.8)
            driver.click(*opt)
            driver.move(*park)
            sleep(wait_load)
            g = detect_grid(stable(), hint=grid)
            if g is None:
                raise SetupError(f"Daftar Soal tidak terlihat setelah memilih {cat}")
            if abs(g.first[0] - grid.first[0]) > grid.box / 3 or abs(g.first[1] - grid.first[1]) > grid.box / 3:
                notes.append(f"posisi grid {cat} bergeser dari kategori pertama")
            counts[cat] = g.count
            progress(f"{cat}: {g.count} soal")
    else:
        counts[categories[0]] = grid.count

    progress("Mencari area konten (scroll uji)…")
    xl = int(grid.bbox[0] - grid.box / 2)         # batas: kiri tombol grid
    probe = (max(10, xl // 2), sh // 2)
    top = stable()
    driver.scroll(*probe, -4)
    driver.move(*park)
    sleep(0.6)
    moved = stable()
    driver.scroll(*probe, 60)
    sleep(0.6)
    rect = detect_scroll_area(top, moved, xl)
    crop = {"enabled": True, "rect": list(rect), "screen": [sw, sh]}
    progress(f"Area konten: {rect[2]}×{rect[3]}px di ({rect[0]},{rect[1]})")

    # gambar pratinjau hasil deteksi
    preview = stable().copy()
    d = ImageDraw.Draw(preview)
    x, y, w, h = rect
    d.rectangle([x, y, x + w, y + h], outline=(255, 210, 63), width=5)
    for n in range(1, max(counts.values()) + 1):
        px, py = nav.grid_position(n)
        d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(31, 111, 235), width=3)
    if nav.category_dropdown:
        px, py = nav.category_dropdown
        d.ellipse([px - 12, py - 12, px + 12, py + 12], outline=(255, 45, 85), width=4)
    return SetupResult(crop, nav, counts, preview, notes)
