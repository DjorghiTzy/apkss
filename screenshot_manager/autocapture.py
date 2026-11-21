"""Tangkap Otomatis: ambil screenshot semua soal + pembahasan tanpa campur tangan.

Aplikasi berperilaku seperti orang yang memakai mouse & keyboard:
  1. klik nomor soal di navigasi website (atau tombol "berikutnya"/keyboard),
  2. scroll ke atas, tunggu layar stabil, tangkap layar penuh -> dipotong ke area soal,
  3. scroll ke bawah bertahap, tangkap, sambung, sampai layar tidak berubah lagi,
  4. ulangi untuk soal berikutnya.

Kategori & nomor berasal dari rencana yang diatur pengguna (mis. TWK 30, TIU 35,
TKP 45), bukan dari OCR/AI. Tidak ada akses ke cookie, login, atau data browser.
Berhenti: tekan ESC atau geser mouse ke pojok kiri atas layar.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from PIL import Image

from .core import DuplicateImageError, ManagerError, Package, apply_crop, find_overlap, stitch

SCROLL_TOP_NOTCHES = 60


class StopRequested(Exception):
    pass


class AutoCaptureError(ManagerError):
    pass


class Driver(Protocol):
    def grab(self) -> Image.Image: ...
    def move(self, x: int, y: int) -> None: ...
    def click(self, x: int, y: int) -> None: ...
    def scroll(self, x: int, y: int, notches: int) -> None: ...   # >0 naik, <0 turun
    def key(self, name: str) -> None: ...
    def stop_requested(self) -> bool: ...
    def sleep(self, seconds: float) -> None: ...


# ---------------------------------------------------------------- konfigurasi

@dataclass
class Plan:
    sections: list = field(default_factory=lambda: [["TWK", 30], ["TIU", 35], ["TKP", 45]])
    start: int = 1                 # nomor urut global (1..total)
    end: Optional[int] = None
    global_numbering: bool = False  # True: TIU-031 dst; False: TIU-001 dst

    @property
    def total(self) -> int:
        return sum(int(n) for _, n in self.sections)

    def entries(self) -> list[tuple[int, str, int, int]]:
        """(urutan global, kategori, nomor untuk nama file, nomor di grid kategori)."""
        out, g = [], 0
        for cat, count in self.sections:
            for local in range(1, int(count) + 1):
                g += 1
                out.append((g, cat, g if self.global_numbering else local, local))
        end = self.end or self.total
        return [e for e in out if self.start <= e[0] <= end]


@dataclass
class NavConfig:
    mode: str = "grid"             # "grid" | "point" | "key"
    grid_first: Optional[list] = None   # posisi tombol nomor 1
    grid_second: Optional[list] = None  # posisi tombol nomor 2 (di kanan nomor 1)
    grid_below: Optional[list] = None   # posisi tombol tepat di bawah nomor 1
    columns: int = 5
    point: Optional[list] = None        # tombol "berikutnya"
    key: str = "right"
    per_category: bool = True           # grid mulai dari 1 lagi di tiap Tipe Soal
    category_dropdown: Optional[list] = None          # tombol dropdown "Tipe Soal"
    category_options: dict = field(default_factory=dict)  # kategori -> posisi pilihan

    def validate(self, categories: Optional[list] = None) -> None:
        if self.mode == "grid":
            if not (self.grid_first and self.grid_second and self.grid_below) or self.columns < 1:
                raise AutoCaptureError("Posisi grid nomor soal belum diatur")
            if self.per_category and categories and len(categories) > 1:
                missing = [c for c in categories if not self.category_options.get(c)]
                if not self.category_dropdown or missing:
                    raise AutoCaptureError("Posisi dropdown Tipe Soal belum diatur"
                                           + (f" (pilihan {', '.join(missing)})" if missing else ""))
        elif self.mode == "point":
            if not self.point:
                raise AutoCaptureError("Posisi tombol 'berikutnya' belum diatur")
        elif self.mode != "key":
            raise AutoCaptureError(f"Mode navigasi tidak dikenal: {self.mode}")

    def grid_problem(self, count: int, screen: tuple[int, int]) -> Optional[str]:
        """Pesan bila tandaan grid tidak masuk akal (salah klik), atau None bila OK."""
        if not (self.grid_first and self.grid_second and self.grid_below):
            return "posisi grid belum ditandai"
        x0, y0 = self.grid_first
        dx = (self.grid_second[0] - x0, self.grid_second[1] - y0)
        dy = (self.grid_below[0] - x0, self.grid_below[1] - y0)
        if abs(dx[0]) < 8 or abs(dx[1]) * 3 > abs(dx[0]):
            return "titik ke-2 harus tepat di KANAN nomor 1 (nomor 2, satu baris)"
        if abs(dy[1]) < 8 or abs(dy[0]) * 3 > abs(dy[1]):
            return "titik ke-3 harus tepat di BAWAH nomor 1 (nomor di baris kedua, kolom pertama)"
        if max(abs(dx[0]), abs(dy[1])) > min(screen) / 4:
            return "jarak antar nomor terlalu besar — klik tepat di tombol nomor 1, 2, dan di bawah 1"
        sw, sh = screen
        for n in (self.columns, count):
            px, py = self.grid_position(n)
            if not (0 <= px < sw and 0 <= py < sh):
                return (f"nomor {n} akan berada di luar layar ({px},{py}) — periksa jumlah kolom, atau perkecil "
                        "zoom browser agar seluruh Daftar Soal terlihat")
        return None

    def grid_position(self, g: int) -> tuple[int, int]:
        row, col = divmod(g - 1, self.columns)
        x0, y0 = self.grid_first
        dx = (self.grid_second[0] - x0, self.grid_second[1] - y0)
        dy = (self.grid_below[0] - x0, self.grid_below[1] - y0)
        return round(x0 + col * dx[0] + row * dy[0]), round(y0 + col * dx[1] + row * dy[1])


@dataclass
class RunConfig:
    crop: dict
    nav: NavConfig
    wait_load: float = 1.5          # batas tunggu halaman berganti (bukan jeda tetap)
    max_parts: int = 30
    notches: Optional[int] = None   # None = kalibrasi otomatis
    stable_timeout: float = 6.0     # batas tunggu layar diam
    stable_interval: float = 0.015  # jeda antar pemeriksaan layar
    step_ratio: float = 0.85        # langkah scroll ~85% tinggi area (sisanya tumpang tindih)
    settle_scroll: float = 0.045    # layar dianggap diam setelah scroll bila tak berubah selama ini
    settle_load: float = 0.08       # ... setelah pindah soal (memberi waktu gambar soal ikut dimuat)


@dataclass
class Report:
    done: list = field(default_factory=list)       # nama file
    problems: list = field(default_factory=list)   # (nama, pesan)
    stopped: bool = False
    aborted: Optional[str] = None
    notches: Optional[int] = None
    seconds: float = 0.0
    captured: int = 0                              # soal yang benar-benar diambil di sesi ini
    crop: Optional[dict] = None                    # area potong yang diperbaiki (diperlebar) selama berjalan
    t_load: float = 0.0                            # total waktu menunggu website memuat soal
    t_scroll: float = 0.0                          # total waktu scroll + menunggu layar diam
    t_app: float = 0.0                             # total waktu kerja aplikasi sendiri


# ---------------------------------------------------------------- runner

class AutoCapture:
    def __init__(self, pkg: Package, plan: Plan, cfg: RunConfig, driver: Driver,
                 progress: Callable[[str], None] = lambda m: None,
                 stop_event: Optional[threading.Event] = None):
        self.pkg, self.plan, self.cfg, self.d = pkg, plan, cfg, driver
        self.progress = progress
        self.stop_event = stop_event or threading.Event()
        self.notches = cfg.notches
        self.px_per_notch: Optional[float] = None
        self.step_px = 0                       # pergeseran terbesar yang pernah teramati
        self._shown_cat: Optional[str] = None
        self._grids: dict = {}                 # kategori -> (GridInfo, offset) grid nyata di layar
        self._at_top = False
        cats = [c for c, n in plan.sections if int(n) > 0]
        cfg.nav.validate(cats)
        if not (cfg.crop and cfg.crop.get("rect") and cfg.crop.get("screen")):
            raise AutoCaptureError("Area potong belum diatur")
        x, y, w, h = cfg.crop["rect"]
        sw, sh = cfg.crop["screen"]
        nav = cfg.nav
        if nav.mode == "grid":   # semua tombol nomor yang akan diklik harus ada di layar
            need = max((int(n) for _, n in plan.sections), default=1) if nav.per_category else plan.total
            problem = nav.grid_problem(need, (sw, sh))
            if problem:
                raise AutoCaptureError(f"Posisi Daftar Soal salah: {problem}. Jalankan 🪄 Atur Otomatis lagi "
                                       f"(titik tandaan: {nav.grid_first}, {nav.grid_second}, {nav.grid_below}).")
        self.rect = (x, y, w, h)
        self.area_h = h
        self.center = (x + w // 2, y + h // 2)
        # parkir mouse di luar area potong (tidak di pojok kiri atas = tombol berhenti)
        self.park = (min(sw - 3, x + w + 20), y + h // 2) if x + w + 25 < sw else (x + w // 2, min(sh - 3, y + h + 20))
        if x + w + 25 >= sw and y + h + 25 >= sh:
            self.park = (max(3, x - 20), y + h // 2) if x > 25 else (sw - 3, sh - 3)
        self._region_ok: Optional[bool] = None
        if self.notches is None and cfg.crop.get("px_per_notch"):     # kalibrasi dari Atur Otomatis
            self.px_per_notch = float(cfg.crop["px_per_notch"])
            self.notches = max(1, int(h * cfg.step_ratio // self.px_per_notch))
        self._latency = 0.0          # waktu terlama dari aksi (scroll) sampai layar mulai berubah
        self._last_latency = 0.0
        self._just_switched = False
        self._sticky: Optional[bool] = cfg.crop.get("sticky")   # Daftar Soal tetap terlihat saat di-scroll?
        self._cat_img: Optional[Image.Image] = None            # tampilan soal 1 setelah ganti kategori
        self._prev_first: Optional[bytes] = None
        self._bg = None
        self._edge_unfixable = False

    # ------------------------------------------------------------ dasar
    def _check(self):
        if self.stop_event.is_set() or self.d.stop_requested():
            raise StopRequested()

    def _sleep(self, s: float):
        end = time.monotonic() + s
        while True:
            self._check()
            left = end - time.monotonic()
            if left <= 0:
                return
            self.d.sleep(min(0.05, left))

    def _crop(self, img: Image.Image) -> Image.Image:
        out, ok = apply_crop(img, self.cfg.crop)
        if not ok:
            sw, sh = self.cfg.crop["screen"]
            raise AutoCaptureError(f"Ukuran layar {img.width}×{img.height} berbeda dengan acuan "
                                   f"{sw}×{sh}. Jalankan 🪄 Atur Otomatis lagi.")
        return out.convert("RGB")

    def _grab_area(self) -> Image.Image:
        """Potret hanya area soal bila driver mendukung (lebih cepat), selain itu layar penuh lalu potong."""
        x, y, w, h = self.rect
        if self._region_ok is not False:
            try:
                img = self.d.grab(bbox=(x, y, x + w, y + h))
                if img.size == (w, h):
                    self._region_ok = True
                    return img.convert("RGB")
                self._region_ok = False
                return self._crop(img)
            except TypeError:
                self._region_ok = False
        return self._crop(self.d.grab())

    def _wait_change(self, before: Optional[bytes], first_timeout: float, settle: float,
                     need_same: int = 2) -> Optional[Image.Image]:
        """Tunggu sampai area soal BERUBAH dari `before` lalu DIAM (need_same tangkapan sama berturut-turut).

        None = tidak ada perubahan dalam first_timeout."""
        t0 = time.monotonic()
        quiet = self.cfg.settle_load if need_same >= 3 else self.cfg.settle_scroll
        changed = before is None
        last = None
        last_img = None
        since = t0
        while True:
            self._check()
            cur = self._grab_area()
            b = cur.tobytes()
            now = time.monotonic()
            if not changed:
                if b != before:
                    self._last_latency = now - t0
                    changed, last, last_img, since = True, b, cur, now
                elif now - t0 > first_timeout:
                    return None
            else:
                if b == last:
                    if now - since >= quiet:              # tidak berubah selama `quiet` detik = diam
                        return last_img
                else:
                    last, last_img, since = b, cur, now
                if now - t0 > first_timeout + settle:
                    return last_img
            self._sleep(self.cfg.stable_interval)

    def _wait_new(self, exclude: set, timeout: float, need_same: int = 3) -> Optional[Image.Image]:
        """Tunggu tampilan yang BUKAN salah satu `exclude` (soal sebelumnya) dan sudah diam."""
        t0 = time.monotonic()
        quiet = self.cfg.settle_load if need_same >= 3 else self.cfg.settle_scroll
        last, last_img, since = None, None, t0
        while time.monotonic() - t0 < timeout + self.cfg.stable_timeout:
            self._check()
            cur = self._grab_area()
            b = cur.tobytes()
            now = time.monotonic()
            if b in exclude:
                last = None
                if now - t0 > timeout:
                    return None
            elif b == last:
                if now - since >= quiet:
                    return last_img
            else:
                last, last_img, since = b, cur, now
            self._sleep(self.cfg.stable_interval)
        return last_img

    def _check_sticky(self, cat: str):
        """Sekali saja, saat halaman sedang di-scroll ke bawah: apakah grid masih di tempat yang sama?"""
        if self._sticky is not None or self.cfg.nav.mode != "grid":
            return
        key = cat if self.cfg.nav.per_category else "*"
        known = self._grids.get(key, (None, None))[0]
        g, off, _ = self._detect_live_grid()
        if known is None or g is None:
            self._sticky = False
        else:
            self._sticky = abs(g.first[0] - known.first[0]) <= 2 and abs(g.first[1] - known.first[1]) <= 2
        self.progress("  Daftar Soal menempel saat scroll: klik langsung tanpa menunggu" if self._sticky
                      else "  Daftar Soal ikut ter-scroll: scroll ke atas sebelum klik")

    def _wait_scroll(self, last: Image.Image, expected: int) -> Optional[Image.Image]:
        """Tunggu hasil scroll. Begitu pergeseran tepat `expected` piksel (posisi akhir langkah penuh),
        foto langsung dipakai tanpa menunggu layar diam. None = halaman tidak bergeser."""
        if not expected:
            return self._wait_change(last.tobytes(), self._no_move_timeout(), self.cfg.stable_timeout)
        h = self.area_h
        before = last.tobytes()
        row = len(before) // h
        tail = before[expected * row:]                    # baris yang seharusnya naik ke atas
        t0 = time.monotonic()
        changed, prev, prev_img, since = False, None, None, t0
        timeout = self._no_move_timeout()
        while True:
            self._check()
            cur = self._grab_area()
            b = cur.tobytes()
            now = time.monotonic()
            if b[:len(tail)] == tail:                     # pas di posisi akhir langkah
                if not changed:
                    self._last_latency = now - t0
                return cur
            if not changed:
                if b != before:
                    self._last_latency = now - t0
                    changed, prev, prev_img, since = True, b, cur, now
                elif now - t0 > timeout:
                    return None
            else:
                if b == prev:
                    if now - since >= self.cfg.settle_scroll:
                        return prev_img                   # berhenti lebih pendek: dasar halaman
                else:
                    prev, prev_img, since = b, cur, now
                if now - t0 > timeout + self.cfg.stable_timeout:
                    return prev_img
            self._sleep(self.cfg.stable_interval)

    def _no_move_timeout(self) -> float:
        """Batas tunggu 'layar tidak bergerak' — menyesuaikan kecepatan browser yang teramati."""
        return 0.25 if self._latency == 0 else min(0.3, max(0.08, 2.5 * self._latency))

    def _note_latency(self):
        self._latency = max(self._latency, self._last_latency)

    def _stable(self) -> Image.Image:
        self.d.move(*self.park)
        return self._wait_change(None, 0, self.cfg.stable_timeout)

    # ------------------------------------------------------------ navigasi
    def _scroll_top(self):
        if self._at_top:
            return
        before = self._grab_area().tobytes()
        self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)
        self.d.move(*self.park)
        if self._wait_change(before, self._no_move_timeout(), self.cfg.stable_timeout) is not None:
            self._note_latency()
        self._at_top = True

    def _select_category(self, cat: str):
        nav = self.cfg.nav
        opt = nav.category_options.get(cat)
        self._grids.pop(cat, None)
        if not (nav.category_dropdown and opt):
            self.progress(f"  Tipe Soal {cat} tidak diatur — memakai tipe yang sedang tampil")
            self._shown_cat = cat
            return
        self.progress(f"  memilih Tipe Soal {cat}")
        if not self._sticky:
            self._scroll_top()
        before = self._grab_area().tobytes()
        menu = self._menu_region()
        menu_before = self._grab_box(menu).tobytes()        # foto SEBELUM klik
        self.d.click(*nav.category_dropdown)
        self.d.move(*self.park)
        self._wait_region_change(menu, 1.0, menu_before)    # menu terbuka (tanpa jeda tetap)
        self.d.click(*opt)
        self.d.move(*self.park)
        # soal nomor 1 kategori baru tampil = area soal berubah lalu diam
        self._cat_img = self._wait_change(before, max(1.0, self.cfg.wait_load), self.cfg.stable_timeout,
                                          need_same=3)
        self._at_top = self._cat_img is not None
        self._just_switched = True
        self._shown_cat = cat

    def _menu_region(self):
        nav = self.cfg.nav
        x, y = nav.category_dropdown
        sw, sh = self.cfg.crop["screen"]
        return (max(0, x - 150), y, min(sw, x + 150), min(sh, y + 250))

    def _grab_box(self, box):
        try:
            img = self.d.grab(bbox=box)
            return img if img.size == (box[2] - box[0], box[3] - box[1]) else img.crop(box)
        except TypeError:
            return self.d.grab().crop(box)

    def _wait_region_change(self, box, timeout: float, before: Optional[bytes] = None):
        if before is None:
            before = self._grab_box(box).tobytes()
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self._check()
            if self._grab_box(box).tobytes() != before:
                return True
            self._sleep(self.cfg.stable_interval)
        return False

    def _grid_region(self):
        nav = self.cfg.nav
        x0, y0 = nav.grid_first
        dx = abs(nav.grid_second[0] - x0) or 30
        dy = abs(nav.grid_below[1] - y0) or 30
        sw, sh = self.cfg.crop["screen"]
        left = max(0, int(x0 - 2 * dx))
        right = min(sw, int(x0 + (nav.columns + 1) * dx))
        top = max(0, int(y0 - 3 * dy))
        return left, top, right, sh, dx, dy

    def _detect_live_grid(self):
        """Grid Daftar Soal yang sedang tampil (posisi bisa sedikit berbeda tiap kategori)."""
        from .autosetup import GridInfo, detect_grid
        nav = self.cfg.nav
        left, top, right, bottom, dx, dy = self._grid_region()
        try:
            img = self.d.grab(bbox=(left, top, right, bottom))
            if img.size != (right - left, bottom - top):
                img = img.crop((left, top, right, bottom))
        except TypeError:
            img = self.d.grab().crop((left, top, right, bottom))
        box = int(0.7 * min(dx, dy))
        hint = GridInfo((nav.grid_first[0] - left, nav.grid_first[1] - top), dx, dy, nav.columns, 1, box,
                        (0, 0, 0, 0))
        g = detect_grid(img, hint=hint)
        if g is None or g.cols != nav.columns:
            return None, (left, top), img
        return g, (left, top), img

    def _current_index(self, img, g) -> Optional[int]:
        """Nomor soal aktif = satu-satunya tombol berwarna lain (oranye) di grid."""
        import numpy as np
        a = np.asarray(img.convert("RGB"), dtype=np.int16)
        cols = []
        for n in range(1, g.count + 1):
            x, y = g.position(n)
            r = max(2, g.box // 4)
            patch = a[max(0, y - r):y + r, max(0, x - r):x + r].reshape(-1, 3)
            if len(patch) == 0:
                return None
            cols.append(np.median(patch, axis=0))
        cols = np.array(cols)
        dist = np.abs(cols - np.median(cols, axis=0)).max(axis=1)
        k = int(dist.argmax())
        if dist[k] < 40 or (dist > 40).sum() != 1:
            return None
        return k + 1

    def _number_pos(self, cat: str, n: int, refresh: bool = False):
        nav = self.cfg.nav
        key = cat if nav.per_category else "*"
        if refresh or key not in self._grids:
            g, off, _ = self._detect_live_grid()
            self._grids[key] = (g, off)
        g, off = self._grids[key]
        if g is not None and g.count >= n:
            x, y = g.position(n)
            return x + off[0], y + off[1]
        return tuple(nav.grid_position(n))

    def _open_question(self, cat: str, n: int, g_index: int, first: bool) -> Image.Image:
        """Buka soal & kembalikan tangkapan pertamanya (bagian atas), sudah dipastikan berganti."""
        nav = self.cfg.nav
        if nav.mode == "grid" and nav.per_category and cat != self._shown_cat:
            self._select_category(cat)
        if (nav.mode == "grid" and self._sticky and not self._at_top and self._prev_first is not None
                and not self._just_switched):
            # grid tetap terlihat: klik sekarang, scroll ke atas BERSAMAAN dengan halaman memuat
            target = n if nav.per_category else g_index
            exclude = {self._prev_first, self._grab_area().tobytes()}
            self.d.click(*self._number_pos(cat, target))
            self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)
            self.d.move(*self.park)
            img = self._wait_new(exclude, max(0.8, self.cfg.wait_load))
            if img is not None:
                self._at_top = True
                return img
            self._at_top = False                           # tidak berganti: pakai jalur biasa
        self._scroll_top()
        before = self._grab_area().tobytes()
        target = n if (nav.mode != "grid" or nav.per_category) else g_index
        if nav.mode == "grid" and (first or self._just_switched):
            # soal yang dituju mungkin sudah tampil (mis. nomor 1 setelah ganti kategori): jangan klik & tunggu
            self._just_switched = False
            g, off, gimg = self._detect_live_grid()
            if g is not None:
                self._grids[cat if nav.per_category else "*"] = (g, off)
                if self._current_index(gimg, g) == target:
                    img, self._cat_img = self._cat_img, None
                    return img if img is not None and self._at_top else self._stable()
        self._just_switched = False
        self._cat_img = None
        for attempt in range(3):
            if nav.mode == "grid":
                self.d.click(*self._number_pos(cat, target, refresh=attempt > 0))
            elif nav.mode == "point":
                if first and attempt == 0:
                    return self._stable()
                self.d.click(*nav.point)
            else:
                if first and attempt == 0:
                    return self._stable()
                self.d.key(nav.key)
            self.d.move(*self.park)
            img = self._wait_change(before, max(0.8, self.cfg.wait_load), self.cfg.stable_timeout, need_same=3)
            if img is not None:
                self._at_top = True                        # diklik saat di atas -> soal baru mulai di atas
                return img
            if nav.mode == "grid":                         # tidak berubah: mungkin memang sudah di soal itu
                g, off, gimg = self._detect_live_grid()
                cur_idx = None
                if g is not None:
                    self._grids[cat if nav.per_category else "*"] = (g, off)
                    cur_idx = self._current_index(gimg, g)
                if cur_idx == target:
                    return self._stable()
                if cur_idx is None:
                    shown = self._stable()
                    from .core import image_fingerprint
                    if self.pkg.find_by_fingerprint(image_fingerprint(shown)) is None:
                        self.progress(f"  {cat} nomor {n} sudah tampil")
                        return shown
            self.progress(f"  halaman belum berganti, klik ulang ({attempt + 1}/3)")
            if nav.mode == "grid" and nav.per_category and attempt == 1:
                self._select_category(cat)
                self._scroll_top()
                before = self._grab_area().tobytes()
        raise AutoCaptureError(f"Soal {cat} nomor {n} gagal dibuka: halaman tidak berganti setelah 3 kali klik. "
                               "Jalankan 🪄 Atur Otomatis lagi.")

    # ------------------------------------------------------------ satu soal
    def _scroll_parts(self, first: Image.Image, notches: int, max_steps: int = 10_000) -> tuple[list, bool, bool]:
        """Scroll ke bawah sampai habis. Kembalikan (bagian, ada_celah, sudah_di_dasar)."""
        parts = [first]
        h = self.area_h
        gap = False
        steps = 0
        while len(parts) < self.cfg.max_parts:
            if steps >= max_steps:
                return parts, gap, False
            steps += 1
            last = parts[-1]
            self.d.scroll(*self.center, -notches)
            self.d.move(*self.park)
            cur = self._wait_scroll(last, self.step_px if notches == self.notches else 0)
            if cur is None:
                return parts, gap, True                    # tidak bergeser lagi: sudah paling bawah
            self._note_latency()
            self._at_top = False
            k = find_overlap(last, cur)
            if k == 0:
                parts.append(cur)
                return parts, True, False
            shift = h - k
            parts.append(cur)
            if self.px_per_notch is None:
                self.px_per_notch = shift / notches
            if shift > self.step_px:
                self.step_px = shift
            elif shift < 0.9 * self.step_px:
                return parts, gap, True                    # pergeseran terpotong: dasar halaman
        return parts, gap, True

    def _capture_question(self, first: Image.Image, name: str, rep: Report) -> list:
        """Ambil semua bagian satu soal (soal sampai akhir pembahasan)."""
        if self.notches is None:                           # kalibrasi: 1 notch = berapa piksel?
            parts, gap, bottom = self._scroll_parts(first, 1, max_steps=1)
            if self.px_per_notch:
                self.notches = max(1, int(self.area_h * self.cfg.step_ratio // self.px_per_notch))
                self.step_px = 0
                self.progress(f"  kalibrasi: 1 notch ≈ {self.px_per_notch:.0f}px → {self.notches} notch per langkah")
                if not gap and not bottom:
                    more, gap, _ = self._scroll_parts(parts[-1], self.notches)
                    parts += more[1:]
            elif not gap:
                return parts                               # halaman tidak bisa di-scroll
        else:
            parts, gap, _ = self._scroll_parts(first, self.notches)
        tries = 0
        while gap and tries < 2:                           # ada bagian terlewat: ulangi, langkah lebih kecil
            tries += 1
            self.notches = max(1, int(self.notches * 0.6))
            self.step_px = 0
            rep.problems.append((name, f"langkah scroll terlalu besar, diulang ({self.notches} notch)"))
            self._at_top = False
            self._scroll_top()
            start = self._stable()
            parts, gap, _ = self._scroll_parts(start, self.notches)
        if gap:
            rep.problems.append((name, "ada bagian yang tidak bertumpang tindih — periksa gambar"))
        return parts

    # ------------------------------------------------------------ jaga agar tidak terpotong
    def _edge_ink(self, img: Image.Image) -> tuple[bool, bool]:
        """Apakah tulisan menyentuh tepi kiri / kanan area (tanda terpotong)?"""
        import numpy as np
        a = np.asarray(img, dtype=np.int16)
        if self._bg is None:
            smp = a[::7, ::7].reshape(-1, 3)
            vals, cnt = np.unique(smp, axis=0, return_counts=True)
            self._bg = vals[cnt.argmax()]
        dark_l = (np.abs(a[:, :2] - self._bg).max(axis=2) > 60).sum()
        dark_r = (np.abs(a[:, -2:] - self._bg).max(axis=2) > 60).sum()
        return dark_l >= 2, dark_r >= 2

    def _widen(self, left: bool, right: bool) -> bool:
        """Lebarkan area sampai kolom polos terdekat di layar. True bila berhasil."""
        import numpy as np
        x, y, w, h = self.rect
        sw, sh = self.cfg.crop["screen"]
        scr = np.asarray(self.d.grab().convert("RGB"), dtype=np.int16)
        if scr.shape[1] != sw:
            return False
        band = scr[y:y + h]
        bg = self._bg if self._bg is not None else np.array([255, 255, 255])
        limit_r = sw
        if self.cfg.nav.mode == "grid":
            limit_r = int(self.cfg.nav.grid_first[0] - abs(self.cfg.nav.grid_second[0] - self.cfg.nav.grid_first[0]) / 2)

        plain_cols = (np.abs(band - bg).max(axis=2) <= 10).all(axis=0)
        RUN = 12                                   # ruang kosong sungguhan, bukan celah antar huruf

        def find(start, stop, step):
            run = 0
            for cx in range(start, stop, step):
                run = run + 1 if plain_cols[cx] else 0
                if run >= RUN:
                    return cx - step * (RUN - 1)   # kolom kosong pertama
            return None
        x0, x1 = x, x + w - 1
        ok = True
        if right:
            nx = find(x1 + 1, min(limit_r, x1 + 400, sw), 1)
            ok &= nx is not None
            if nx is not None:
                x1 = min(sw - 1, nx + 2)
        if left:
            nx = find(x0 - 1, max(-1, x0 - 400), -1)
            ok &= nx is not None
            if nx is not None:
                x0 = max(0, nx - 2)
        if (x0, x1) == (x, x + w - 1):
            return False
        self.rect = (x0, y, x1 - x0 + 1, h)
        crop = dict(self.cfg.crop)
        crop["rect"] = list(self.rect)
        self.cfg.crop = crop
        self.center = (x0 + (x1 - x0) // 2, y + h // 2)
        self._region_ok = None
        self.progress(f"  area diperlebar agar tidak terpotong: x {x}→{x0}, lebar {w}→{x1 - x0 + 1}px")
        return ok

    # ------------------------------------------------------------ main
    def run(self) -> Report:
        rep = Report()
        t_start = time.monotonic()
        entries = self.plan.entries()
        if not entries:
            raise AutoCaptureError("Rencana soal kosong")
        from .core import image_fingerprint, make_filename
        from .figures import detect_figures
        # penyimpanan (sambung + tulis PNG + deteksi gambar) di thread lain: penangkap langsung lanjut
        saver = ThreadPoolExecutor(max_workers=1)
        saves = []
        known = {fp for it in self.pkg.items for fp in [it.fingerprint, *it.part_fps]}

        def save(parts, cat, num, local):
            res = self.pkg.add_capture(parts, cat, num, source=f"otomatis:{cat} {local}")
            figs = [] if res.item.figures_off else detect_figures(res.image)
            res.item.figures, res.item.figures_checked = figs, True
            self.pkg.save()
            return res.item, figs

        try:
            self.d.move(*self.park)
            self._stable()                                 # jendela aplikasi sudah hilang & layar diam
            started = False
            for idx, (g, cat, num, local) in enumerate(entries):
                self._check()
                name = f"{cat}-{num:03d}"
                if self.pkg.find_slot(cat, num) is not None:     # sudah lengkap sebelumnya
                    rep.done.append(f"{name}.png")
                    continue
                t_q = time.monotonic()
                first = self._open_question(cat, local, g, not started)
                t_loaded = time.monotonic()
                started = True
                parts = self._capture_question(first, name, rep)
                for _ in range(2):                         # tulisan menyentuh tepi -> lebarkan & ulangi
                    edges = [self._edge_ink(p) for p in parts]
                    lft, rgt = any(e[0] for e in edges), any(e[1] for e in edges)
                    if not (lft or rgt) or self._edge_unfixable:
                        break
                    if not self._widen(lft, rgt):
                        self._edge_unfixable = True
                        rep.problems.append((name, "tulisan menyentuh tepi area — mungkin terpotong"))
                        break
                    rep.crop = dict(self.cfg.crop)
                    self._at_top = False
                    self._scroll_top()
                    parts = self._capture_question(self._stable(), name, rep)
                t_scrolled = time.monotonic()
                self._at_top = len(parts) == 1
                fp = image_fingerprint(parts[0])
                if fp in known:
                    dup = self.pkg.find_by_fingerprint(fp)
                    raise AutoCaptureError(
                        f"Soal {cat} nomor {local} ({name}) gagal: tampilannya sama dengan "
                        f"{dup.display_name if dup else 'soal sebelumnya'} (navigasi tidak berpindah). "
                        "Jalankan 🪄 Atur Otomatis lagi.")
                known.add(fp)
                self._prev_first = parts[0].tobytes()
                saves.append((name, saver.submit(save, parts, cat, num, local)))
                if len(parts) > 1:
                    self._check_sticky(cat)
                rep.done.append(make_filename(cat, num))
                rep.captured += 1
                now = time.monotonic()
                rep.t_load += t_loaded - t_q
                rep.t_scroll += t_scrolled - t_loaded
                rep.t_app += now - t_scrolled
                self.progress(f"[{idx + 1}/{len(entries)}] ✔ {name}.png ({len(parts)} bagian, {now - t_q:.2f} dtk)")
        except StopRequested:
            rep.stopped = True
        except AutoCaptureError as exc:
            rep.aborted = str(exc)
        finally:
            t_wait = time.monotonic()
            for name, fut in saves:                        # tunggu penyimpanan latar belakang selesai
                try:
                    item, figs = fut.result()
                    if figs:
                        self.progress(f"  🖼 {item.filename}: soal bergambar, {len(figs)} gambar")
                except DuplicateImageError as exc:
                    rep.problems.append((name, f"sama dengan {exc.existing.display_name}, tidak disimpan"))
                    rep.done.remove(f"{name}.png") if f"{name}.png" in rep.done else None
                except Exception as exc:  # noqa: BLE001
                    rep.problems.append((name, f"gagal disimpan: {exc}"))
            saver.shutdown(wait=True)
            rep.t_app += time.monotonic() - t_wait
            rep.notches = self.notches
            rep.seconds = time.monotonic() - t_start
        return rep

    def _apply_figures(self, pending: dict, wait: bool):
        changed = False
        for item_id in list(pending):
            fut = pending[item_id]
            if not wait and not fut.done():
                continue
            pending.pop(item_id)
            try:
                result = fut.result()
            except Exception:  # noqa: BLE001
                result = []
            try:
                it = self.pkg.get(item_id)
            except ManagerError:
                continue
            if not it.figures_off:
                it.figures, it.figures_checked = result, True
                changed = True
                if result:
                    self.progress(f"  🖼 {it.filename}: soal bergambar, {len(result)} gambar")
        if changed:
            self.pkg.save()
