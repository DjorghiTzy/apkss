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

import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from PIL import Image

from .core import DuplicateImageError, ManagerError, Package, apply_crop, find_overlap

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
    wait_load: float = 1.5
    max_parts: int = 25
    notches: Optional[int] = None   # None = kalibrasi otomatis
    stable_timeout: float = 8.0
    stable_interval: float = 0.3


@dataclass
class Report:
    done: list = field(default_factory=list)       # nama file
    problems: list = field(default_factory=list)   # (nama, pesan)
    stopped: bool = False
    aborted: Optional[str] = None
    notches: Optional[int] = None


# ---------------------------------------------------------------- runner

class AutoCapture:
    def __init__(self, pkg: Package, plan: Plan, cfg: RunConfig, driver: Driver,
                 progress: Callable[[str], None] = lambda m: None,
                 stop_event: Optional[threading.Event] = None):
        self.pkg, self.plan, self.cfg, self.d = pkg, plan, cfg, driver
        self.progress = progress
        self.stop_event = stop_event or threading.Event()
        self.notches = cfg.notches
        self._shown_cat: Optional[str] = None
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
                raise AutoCaptureError(f"Posisi Daftar Soal salah: {problem}. Buka ⚡ Tangkap Otomatis → "
                                       "“Tandai Posisi di Layar…” dan tandai ulang (titik tandaan: "
                                       f"{nav.grid_first}, {nav.grid_second}, {nav.grid_below}).")
        self.area_h = h
        self.center = (x + w // 2, y + h // 2)
        # parkir mouse di luar area potong (tidak di pojok kiri atas = tombol berhenti)
        self.park = (min(sw - 3, x + w + 20), y + h // 2) if x + w + 25 < sw else (x + w // 2, min(sh - 3, y + h + 20))
        if x + w + 25 >= sw and y + h + 25 >= sh:
            self.park = (max(3, x - 20), y + h // 2) if x > 25 else (sw - 3, sh - 3)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sm-auto-"))

    # ------------------------------------------------------------ helpers
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
            self.d.sleep(min(0.1, left))

    def _crop(self, img: Image.Image) -> Image.Image:
        out, ok = apply_crop(img, self.cfg.crop)
        if not ok:
            sw, sh = self.cfg.crop["screen"]
            raise AutoCaptureError(f"Ukuran layar {img.width}×{img.height} berbeda dengan acuan "
                                   f"{sw}×{sh}. Atur ulang area potong.")
        return out.convert("RGB")

    def _stable(self) -> Image.Image:
        """Tangkap sampai dua tangkapan berturut-turut identik (halaman selesai dimuat/di-scroll)."""
        self.d.move(*self.park)
        prev = self._crop(self.d.grab())
        end = time.monotonic() + self.cfg.stable_timeout
        while time.monotonic() < end:
            self._sleep(self.cfg.stable_interval)
            cur = self._crop(self.d.grab())
            if cur.tobytes() == prev.tobytes():
                return cur
            prev = cur
        return prev

    def _save_tmp(self, img: Image.Image) -> Path:
        fd, p = tempfile.mkstemp(suffix=".png", dir=self.tmpdir)
        os.close(fd)
        img.save(p, "PNG")
        return Path(p)

    def _select_category(self, cat: str):
        nav = self.cfg.nav
        opt = nav.category_options.get(cat)
        if not (nav.category_dropdown and opt):
            self.progress(f"  Tipe Soal {cat} tidak diatur — memakai tipe yang sedang tampil")
            self._shown_cat = cat
            return
        self.progress(f"  memilih Tipe Soal {cat}")
        self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)
        self._sleep(0.4)
        self.d.click(*nav.category_dropdown)
        self._sleep(0.8)
        self.d.click(*opt)
        self._sleep(max(0.8, self.cfg.wait_load))
        self._shown_cat = cat

    def _navigate(self, g: int, first: bool, cat: str = "", local: int = 0, force_cat: bool = False):
        nav = self.cfg.nav
        if nav.mode == "grid":
            if nav.per_category and (force_cat or cat != self._shown_cat):
                self._select_category(cat)
            self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)   # grid di posisi awal
            self._sleep(0.3)
            self.d.click(*nav.grid_position(local if nav.per_category else g))
        elif not first:
            if nav.mode == "point":
                self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)
                self._sleep(0.3)
                self.d.click(*nav.point)
            else:
                self.d.key(nav.key)
        self._sleep(self.cfg.wait_load)
        self.d.scroll(*self.center, SCROLL_TOP_NOTCHES)

    # ------------------------------------------------------------ main
    def run(self) -> Report:
        rep = Report()
        self._current: Optional[str] = None     # soal yang sedang ditangkap (belum lengkap)
        entries = self.plan.entries()
        if not entries:
            raise AutoCaptureError("Rencana soal kosong")
        try:
            prev_first: Optional[bytes] = None
            started = False
            for idx, (g, cat, num, local) in enumerate(entries):
                self._check()
                name = f"{cat}-{num:03d}"
                if self.pkg.find_slot(cat, num) is not None:     # sudah lengkap sebelumnya
                    rep.done.append(f"{name}.png")
                    self.progress(f"[{idx + 1}/{len(entries)}] {name} sudah ada, dilewati")
                    continue
                self.progress(f"[{idx + 1}/{len(entries)}] {name}: membuka {cat} nomor {local}")
                item_id, first_bytes, existed = self._capture_first(g, cat, num, not started, prev_first,
                                                                    rep, local)
                started = True
                prev_first = first_bytes
                if existed:
                    rep.done.append(f"{name}.png")
                    self.progress(f"[{idx + 1}/{len(entries)}] {name} sudah ada, dilewati")
                    continue
                self._current = item_id
                self._capture_rest(item_id, name, rep)
                self._current = None
                if self.pkg.update_figures(item_id):
                    self.progress(f"  🖼 soal bergambar: {len(self.pkg.get(item_id).figures)} gambar")
                it = self.pkg.get(item_id)
                rep.done.append(it.filename)
                self.progress(f"[{idx + 1}/{len(entries)}] ✔ {it.filename} ({it.parts} bagian, "
                              f"{it.width}×{it.height}px)")
        except StopRequested:
            rep.stopped = True
        except AutoCaptureError as exc:
            rep.aborted = str(exc)
        finally:
            if self._current is not None:        # jangan tinggalkan soal setengah jadi
                try:
                    gone = self.pkg.remove(self._current)
                    self.progress(f"{gone.filename} belum lengkap, dibuang (akan diambil ulang)")
                except ManagerError:
                    pass
            rep.notches = self.notches
            for f in self.tmpdir.glob("*"):
                f.unlink(missing_ok=True)
            self.tmpdir.rmdir()
        return rep

    def _capture_first(self, g, cat, num, first, prev_first, rep, local=0):
        """Kembalikan (item_id, bytes tangkapan pertama, sudah_ada_sebelumnya)."""
        last_dup = None
        for attempt in range(3):
            self._navigate(g, first and attempt == 0, cat, local or num, force_cat=attempt > 0)
            img = self._stable()
            if prev_first is not None and img.tobytes() == prev_first:
                self.progress(f"  halaman belum berganti, coba lagi ({attempt + 1}/3)")
                self._sleep(1.0 + attempt)
                continue
            try:
                res = self.pkg.add_image(self._save_tmp(img), cat, num)
            except DuplicateImageError as exc:
                ex = exc.existing
                if ex.category == cat and ex.number == num:     # sudah ditangkap sebelumnya
                    return ex.id, img.tobytes(), True
                last_dup = ex.display_name
                self.progress(f"  sama dengan {last_dup}, coba lagi ({attempt + 1}/3)")
                self._sleep(1.0 + attempt)
                continue
            if res.replaced is not None:
                rep.problems.append((res.item.filename, "menggantikan gambar lama dengan nomor sama"))
            return res.item.id, img.tobytes(), False
        why = (f"tampilannya sama dengan {last_dup} yang sudah tersimpan (navigasi tidak berpindah, "
               f"atau soal ini sudah disimpan sebagai {last_dup})" if last_dup else "halaman tidak berganti")
        raise AutoCaptureError(f"Soal {cat} nomor {local or num} ({cat}-{num:03d}) gagal: {why}. "
                               "Periksa posisi grid / Tipe Soal.")

    def _scroll_down_and_grab(self, notches: int) -> Image.Image:
        self.d.scroll(*self.center, -notches)
        return self._stable()

    def _capture_rest(self, item_id: str, name: str, rep: Report):
        item = self.pkg.get(item_id)
        with Image.open(self.pkg.path_of(item)) as im:
            last = im.convert("RGB")
        if self.notches is None:   # kalibrasi: 1 notch = berapa piksel?
            cur = self._scroll_down_and_grab(1)
            if cur.tobytes() == last.tobytes():
                return            # halaman tidak bisa di-scroll; kalibrasi di soal berikutnya
            k = find_overlap(last, cur)
            shift = self.area_h - k if k else 0
            if shift <= 0:
                self.notches = 2
                rep.problems.append((name, "kalibrasi scroll gagal, memakai 2 notch"))
            else:
                self.notches = max(1, int(self.area_h * 0.6 // shift))
            self.progress(f"  kalibrasi: 1 notch ≈ {shift}px → {self.notches} notch per langkah")
            res = self.pkg.append_part(item_id, self._save_tmp(cur))
            last = cur
        while True:
            self._check()
            if self.pkg.get(item_id).parts >= self.cfg.max_parts:
                rep.problems.append((name, f"dihentikan di {self.cfg.max_parts} bagian (batas)"))
                return
            cur = self._scroll_down_and_grab(self.notches)
            if cur.tobytes() == last.tobytes():
                return            # sudah paling bawah
            try:
                res = self.pkg.append_part(item_id, self._save_tmp(cur))
            except ManagerError as exc:
                rep.problems.append((name, f"bagian dilewati: {exc}"))
                return
            if res.overlap_rows == 0:
                rep.problems.append((name, f"bagian {res.part_number} tidak bertumpang tindih — "
                                           "mungkin ada celah, periksa gambar"))
            self.progress(f"  bagian {res.part_number} disambung")
            last = cur
