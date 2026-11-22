"""Jendela utama Screenshot Manager (PySide6)."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImageReader, QPainter, QPen,
                           QKeySequence, QPixmap)
from PySide6.QtWidgets import (QMenu, QPlainTextEdit, QProgressDialog, QDoubleSpinBox, QAbstractItemView, QApplication, QButtonGroup, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
                               QCheckBox)

from . import __version__
from .core import (DuplicateImageError, IMAGE_EXTS, Item, ManagerError, Package,
                   SlotTakenError, list_packages, make_filename, sanitize_package_name)
from . import updater, win_input
from .autocapture import AutoCapture, AutoCaptureError, NavConfig, Plan, RunConfig, StopRequested
from .autosetup import SetupError, run_autosetup
from .watcher import FolderWatcher

APP_NAME = "Screenshot Manager"
PRIMARY_DEFAULT_FOLDER = r"C:\Users\djtzy\Pictures\Screenshots"
THUMB = QSize(112, 63)
log = logging.getLogger("screenshot_manager")


# ---------------------------------------------------------------- settings

def config_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get(
        "XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base or Path.home()) / "ScreenshotManager"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_watch_folder() -> str:
    home = Path.home()
    candidates = [Path(PRIMARY_DEFAULT_FOLDER), home / "Pictures" / "Screenshots",
                  home / "OneDrive" / "Pictures" / "Screenshots",
                  home / "OneDrive" / "Gambar" / "Screenshots"]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return PRIMARY_DEFAULT_FOLDER if sys.platform == "win32" else str(candidates[1])


def default_workspace() -> str:
    return str(Path.home() / "Documents" / "ScreenshotManager")


class Settings:
    def __init__(self):
        self.path = config_dir() / "settings.json"
        self.data = {"watch_folder": default_watch_folder(), "workspace": default_workspace(),
                     "package": "Paket-01", "always_on_top": False, "zip_dir": "",
                     "crop": {"enabled": False, "rect": None, "screen": None}}
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v
        try:
            self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("Gagal menyimpan pengaturan: %s", exc)


# ---------------------------------------------------------------- dialogs

class EditItemDialog(QDialog):
    def __init__(self, parent, pkg: Package, item: Item):
        super().__init__(parent)
        self.setWindowTitle("Ubah Kategori / Nomor")
        self.cat = QComboBox()
        self.cat.addItems(pkg.categories)
        self.cat.setCurrentText(item.category or pkg.capture.category)
        self.num = QSpinBox()
        self.num.setRange(1, 9999)
        self.num.setValue(item.number or pkg.next_number_for(self.cat.currentText()))
        self.preview = QLabel()
        self.preview.setStyleSheet("font-weight:bold; font-size:15px")
        form = QFormLayout(self)
        form.addRow("Kategori", self.cat)
        form.addRow("Nomor", self.num)
        form.addRow("Nama file", self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.cat.currentTextChanged.connect(self._upd)
        self.num.valueChanged.connect(self._upd)
        self._upd()

    def _upd(self):
        self.preview.setText(make_filename(self.cat.currentText(), self.num.value()))

    def values(self):
        return self.cat.currentText(), self.num.value()


class PreviewDialog(QDialog):
    def __init__(self, parent, path: Path, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        pm = QPixmap(str(path))
        screen = QApplication.primaryScreen().availableGeometry()
        lbl.setPixmap(pm.scaled(int(screen.width() * .85), int(screen.height() * .85),
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
                      if pm.width() > screen.width() * .85 or pm.height() > screen.height() * .85 else pm)
        lay = QVBoxLayout(self)
        lay.addWidget(lbl)


# ---------------------------------------------------------------- main window

BANNER_STYLES = {
    "ok": "background:#d7f5dd; color:#0b5d1e; border:2px solid #2e9e48;",
    "warn": "background:#fff1c9; color:#6b4b00; border:2px solid #d9a400;",
    "err": "background:#fde0e0; color:#8a1212; border:2px solid #d33;",
    "info": "background:#e6eefc; color:#1c3d7a; border:2px solid #7a9be0;",
}


class CropCanvas(QWidget):
    """Menampilkan screenshot acuan; seret mouse untuk memilih area soal."""
    def __init__(self, pixmap: QPixmap, rect: QRect | None = None):
        super().__init__()
        self.src = pixmap
        geo = QApplication.primaryScreen().availableGeometry()   # sebesar mungkin agar mudah diklik
        self.MAX = QSize(max(900, int(geo.width() * 0.94)), max(500, int(geo.height() * 0.78)))
        self.view = pixmap.scaled(self.MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
            if pixmap.width() > self.MAX.width() or pixmap.height() > self.MAX.height() else pixmap
        self.k = pixmap.width() / max(1, self.view.width())
        self.sel = rect if rect is not None else QRect()
        self._start: QPoint | None = None
        self.setFixedSize(self.view.size())
        self.setCursor(Qt.CrossCursor)
        self.on_change = lambda: None

    def _img_point(self, p: QPoint) -> QPoint:
        x = min(max(p.x(), 0), self.view.width())
        y = min(max(p.y(), 0), self.view.height())
        return QPoint(round(x * self.k), round(y * self.k))

    def mousePressEvent(self, e):
        self._start = self._img_point(e.position().toPoint())
        self.sel = QRect(self._start, self._start)
        self.update()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self.sel = QRect(self._start, self._img_point(e.position().toPoint())).normalized()
            self.update()
            self.on_change()

    def mouseReleaseEvent(self, e):
        self.mouseMoveEvent(e)
        self._start = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.view)
        if self.sel.width() > 2 and self.sel.height() > 2:
            r = QRect(round(self.sel.x() / self.k), round(self.sel.y() / self.k),
                      round(self.sel.width() / self.k), round(self.sel.height() / self.k))
            shade = QColor(0, 0, 0, 120)
            full = self.rect()
            p.fillRect(QRect(0, 0, full.width(), r.top()), shade)
            p.fillRect(QRect(0, r.bottom() + 1, full.width(), full.height() - r.bottom()), shade)
            p.fillRect(QRect(0, r.top(), r.left(), r.height()), shade)
            p.fillRect(QRect(r.right() + 1, r.top(), full.width() - r.right(), r.height()), shade)
            p.setPen(QPen(QColor("#ffd23f"), 3))
            p.drawRect(r)


class CropDialog(QDialog):
    def __init__(self, parent, image_path: str, current: dict | None):
        super().__init__(parent)
        self.setWindowTitle("Atur Area Potong")
        pm = QPixmap(image_path)
        rect = None
        if current and current.get("rect") and current.get("screen") == [pm.width(), pm.height()]:
            rect = QRect(*current["rect"])
        self.canvas = CropCanvas(pm, rect)
        self.info = QLabel()
        self.canvas.on_change = self._upd
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Seret kotak</b> menutupi area konten soal di browser (soal, pilihan, "
                             "jawaban & pembahasan). Jangan sertakan tab browser dan taskbar."))
        lay.addWidget(self.canvas, 0, Qt.AlignCenter)
        lay.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.screen = [pm.width(), pm.height()]
        self._upd()

    def _upd(self):
        r = self.canvas.sel
        self.info.setText(f"Layar acuan: {self.screen[0]}×{self.screen[1]} px   •   Area: "
                          + (f"x={r.x()}, y={r.y()}, {r.width()}×{r.height()} px"
                             if r.width() > 10 else "belum dipilih"))

    def _accept(self):
        if self.canvas.sel.width() < 50 or self.canvas.sel.height() < 50:
            QMessageBox.warning(self, "Area terlalu kecil", "Seret kotak yang lebih besar.")
            return
        self.accept()

    def result_crop(self) -> dict:
        r = self.canvas.sel
        return {"enabled": True, "rect": [r.x(), r.y(), r.width(), r.height()], "screen": self.screen}


class PointCanvas(CropCanvas):
    """Klik untuk menandai titik (posisi tombol) di screenshot acuan."""

    def __init__(self, pixmap: QPixmap, count: int):
        super().__init__(pixmap)
        self.count = count
        self.points: list[QPoint] = []
        self.grid_nav: NavConfig | None = None    # pratinjau posisi nomor 1..n
        self.grid_count = 0

    def mousePressEvent(self, e):
        if len(self.points) < self.count:
            self.points.append(self._img_point(e.position().toPoint()))
            self.update()
            self.on_change()

    def mouseMoveEvent(self, e):
        pass

    def mouseReleaseEvent(self, e):
        pass

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.view)
        if self.grid_nav is not None and len(self.points) == 3:
            p.setPen(QPen(QColor("#1f6feb"), 2))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            for n in range(1, self.grid_count + 1):
                gx, gy = self.grid_nav.grid_position(n)
                x, y = round(gx / self.k), round(gy / self.k)
                p.drawEllipse(QPoint(x, y), 6, 6)
                p.drawText(x + 7, y + 14, str(n))
        p.setPen(QPen(QColor("#ff2d55"), 3))
        for i, pt in enumerate(self.points, start=1):
            x, y = round(pt.x() / self.k), round(pt.y() / self.k)
            p.drawEllipse(QPoint(x, y), 9, 9)
            p.drawText(x + 12, y - 8, str(i))


class PointPickDialog(QDialog):
    def __init__(self, parent, image_path: str, prompts: list[str],
                 grid: tuple[int, int] | None = None):
        """grid=(kolom, jumlah nomor terbanyak): tampilkan pratinjau & validasi posisi grid."""
        super().__init__(parent)
        self.setWindowTitle("Tandai Posisi")
        self.prompts = prompts
        self.grid = grid
        self.canvas = PointCanvas(QPixmap(image_path), len(prompts))
        self.screen_size = (self.canvas.src.width(), self.canvas.src.height())
        self.canvas.on_change = self._upd
        self.info = QLabel()
        self.info.setStyleSheet("font-size:15px; font-weight:bold")
        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addWidget(self.canvas, 0, Qt.AlignCenter)
        row = QHBoxLayout()
        b_reset = QPushButton("Ulang")
        b_reset.clicked.connect(self._reset)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        row.addWidget(b_reset)
        row.addStretch(1)
        row.addWidget(self.bb)
        lay.addLayout(row)
        self._upd()

    def _reset(self):
        self.canvas.points.clear()
        self.canvas.update()
        self._upd()

    def _upd(self):
        n = len(self.canvas.points)
        done = n >= len(self.prompts)
        ok = done
        text = ("✔ Semua titik ditandai. Klik OK." if done
                else f"Klik {n + 1}/{len(self.prompts)}: {self.prompts[n]}")
        self.canvas.grid_nav = None
        if self.grid and done:
            cols, count = self.grid
            pts = self.points()
            nav = NavConfig(mode="grid", grid_first=pts[0], grid_second=pts[1], grid_below=pts[2], columns=cols)
            problem = nav.grid_problem(count, self.screen_size)
            self.canvas.grid_nav, self.canvas.grid_count = nav, count
            if problem:
                ok = False
                text = f"⚠ {problem}. Klik “Ulang” lalu tandai lagi."
            else:
                text = (f"Cek: lingkaran biru 1–{count} harus tepat di atas tombol nomornya "
                        f"({cols} kolom). Jika pas, klik OK; jika tidak, klik “Ulang”.")
        self.canvas.update()
        self.info.setText(text)
        self.info.setStyleSheet("font-size:15px; font-weight:bold; color:%s" % ("#b00" if text.startswith("⚠")
                                                                                 else "#000"))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(ok)

    def points(self) -> list[list[int]]:
        return [[p.x(), p.y()] for p in self.canvas.points]


NAV_MODES = [("grid", "Klik nomor soal di grid navigasi (disarankan)"),
             ("point", "Klik tombol “Berikutnya” (posisi tetap)"),
             ("key", "Tekan tombol keyboard → (panah kanan)")]


class AutoCaptureDialog(QDialog):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Tangkap Otomatis — semua soal + pembahasan")
        self.setMinimumWidth(620)
        saved = win.settings["auto"] or {}
        self.nav = NavConfig(**{k: v for k, v in (saved.get("nav") or {}).items()
                                if k in NavConfig.__dataclass_fields__})
        counts = dict(saved.get("sections") or [["TWK", 30], ["TIU", 35], ["TKP", 45]])
        lay = QVBoxLayout(self)

        b_auto = QPushButton("🪄 Atur Otomatis — deteksi semua pengaturan dari layar (disarankan)")
        b_auto.setStyleSheet("font-weight:bold; background:#2e9e48; color:white; padding:8px")
        b_auto.clicked.connect(lambda: (self.reject(), QTimer.singleShot(200, self.win.run_auto_setup)))
        lay.addWidget(b_auto)
        lay.addWidget(QLabel("<i>atau atur manual:</i>"))
        g_plan = QGroupBox("1. Rencana soal (urutan sama dengan website)")
        fp = QFormLayout(g_plan)
        self.spins = {}
        for cat in win.pkg.categories:
            sp = QSpinBox()
            sp.setMinimumSize(90, 28)
            sp.setRange(0, 500)
            sp.setValue(int(counts.get(cat, 0)))
            sp.valueChanged.connect(self._upd)
            self.spins[cat] = sp
            fp.addRow(f"Jumlah soal {cat}", sp)
        self.rb_local = QRadioButton("Nomor per kategori (TWK-001…030, TIU-001…035, TKP-001…045)")
        self.rb_global = QRadioButton("Nomor global (TWK-001…030, TIU-031…065, TKP-066…110)")
        (self.rb_global if saved.get("global") else self.rb_local).setChecked(True)
        self.rb_local.toggled.connect(self._upd)
        fp.addRow(self.rb_local)
        fp.addRow(self.rb_global)
        hr = QHBoxLayout()
        self.sp_start, self.sp_end = QSpinBox(), QSpinBox()
        for sp in (self.sp_start, self.sp_end):
            sp.setMinimumSize(80, 28)
            sp.setRange(1, 2000)
            sp.valueChanged.connect(self._upd)
        hr.addWidget(QLabel("Dari soal ke"))
        hr.addWidget(self.sp_start)
        hr.addWidget(QLabel("sampai"))
        hr.addWidget(self.sp_end)
        hr.addStretch(1)
        fp.addRow(hr)
        lay.addWidget(g_plan)

        g_nav = QGroupBox("2. Cara pindah soal")
        vn = QVBoxLayout(g_nav)
        self.chk_percat = QCheckBox("Nomor mulai dari 1 di tiap Tipe Soal (ganti kategori lewat dropdown)")
        self.chk_percat.setToolTip("Seperti Privat Alfaiz: Daftar Soal TWK 1–30, lalu pilih Tipe Soal TIU, "
                                   "Daftar Soal 1–35, dst.")
        self.chk_percat.setChecked(self.nav.per_category)
        self.chk_percat.toggled.connect(self._upd)
        self.cb_nav = QComboBox()
        for key, label in NAV_MODES:
            self.cb_nav.addItem(label, key)
        self.cb_nav.setCurrentIndex([k for k, _ in NAV_MODES].index(self.nav.mode))
        self.cb_nav.currentIndexChanged.connect(self._upd)
        vn.addWidget(self.cb_nav)
        vn.addWidget(self.chk_percat)
        hn = QHBoxLayout()
        self.sp_cols = QSpinBox()
        self.sp_cols.setMinimumSize(70, 28)
        self.sp_cols.setRange(1, 50)
        self.sp_cols.setValue(self.nav.columns)
        self.sp_cols.valueChanged.connect(self._upd)
        self.lbl_cols = QLabel("Jumlah kolom grid:")
        self.btn_pos = QPushButton("Tandai Posisi di Layar…")
        self.btn_pos.clicked.connect(self._pick)
        hn.addWidget(self.lbl_cols)
        hn.addWidget(self.sp_cols)
        hn.addStretch(1)
        hn.addWidget(self.btn_pos)
        vn.addLayout(hn)
        hd = QHBoxLayout()
        self.btn_dd = QPushButton("Tandai Dropdown Tipe Soal…")
        self.btn_dd.clicked.connect(self._pick_dropdown)
        hd.addStretch(1)
        hd.addWidget(self.btn_dd)
        vn.addLayout(hd)
        self.lbl_nav = QLabel()
        self.lbl_nav.setWordWrap(True)
        self.lbl_nav.setMinimumHeight(48)
        vn.addWidget(self.lbl_nav)
        lay.addWidget(g_nav)

        g_opt = QGroupBox("3. Lain-lain")
        fo = QFormLayout(g_opt)
        self.sp_wait = QDoubleSpinBox()
        self.sp_wait.setRange(0.3, 15)
        self.sp_wait.setSingleStep(0.5)
        self.sp_wait.setValue(float(saved.get("wait_load", 1.5)))
        self.sp_wait.setSuffix(" detik")
        fo.addRow("Tunggu halaman dimuat", self.sp_wait)
        self.lbl_crop = QLabel()
        self.lbl_crop.setWordWrap(True)
        fo.addRow("Area potong", self.lbl_crop)
        lay.addWidget(g_opt)

        tip = QLabel("<b>Sebelum mulai:</b> buka halaman <u>pembahasan</u> tryout di browser (layar penuh), "
                     "pastikan seluruh Daftar Soal terlihat. Aplikasi akan bersembunyi, lalu memilih Tipe Soal, "
                     "mengklik nomor, scroll, dan memotret sendiri. Jangan sentuh mouse/keyboard selama berjalan.<br>"
                     "<b>F10</b> = mulai / berhenti dari jendela mana pun (memakai pengaturan terakhir). "
                     "Juga bisa berhenti dengan <b>ESC</b> atau mouse ke <b>pojok kiri atas</b>. "
                     "Menjalankan lagi akan melanjutkan soal yang belum ada.")
        tip.setWordWrap(True)
        tip.setStyleSheet("background:#fff1c9; padding:8px; border-radius:6px")
        lay.addWidget(tip)

        self.lbl_summary = QLabel()
        self.lbl_summary.setStyleSheet("font-weight:bold")
        lay.addWidget(self.lbl_summary)
        bb = QDialogButtonBox()
        self.btn_start = bb.addButton("MULAI TANGKAP OTOMATIS", QDialogButtonBox.AcceptRole)
        self.btn_start.setStyleSheet("font-weight:bold; background:#1f6feb; color:white; padding:8px 16px")
        bb.addButton("Tutup", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._start)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.sp_start.setValue(1)
        self.sp_end.setValue(max(1, self._total()))
        self._upd()

    def _total(self) -> int:
        return sum(sp.value() for sp in self.spins.values())

    def plan(self) -> Plan:
        return Plan(sections=[[c, sp.value()] for c, sp in self.spins.items() if sp.value()],
                    start=self.sp_start.value(), end=self.sp_end.value(),
                    global_numbering=self.rb_global.isChecked())

    def _plan_cats(self) -> list[str]:
        return [c for c, sp in self.spins.items() if sp.value()]

    def _upd(self):
        mode = self.cb_nav.currentData()
        self.nav.mode = mode
        self.nav.per_category = self.chk_percat.isChecked()
        percat = mode == "grid" and self.nav.per_category
        self.sp_cols.setVisible(mode == "grid")
        self.lbl_cols.setVisible(mode == "grid")
        self.chk_percat.setVisible(mode == "grid")
        self.btn_dd.setVisible(percat)
        self.btn_pos.setVisible(mode != "key")
        if mode == "grid":
            self.nav.columns = self.sp_cols.value()
            c = self.win.settings["crop"] or {}
            screen = tuple(c.get("screen") or (99999, 99999))
            count = (max((sp.value() for sp in self.spins.values()), default=1) if self.nav.per_category
                     else self._total())
            problem = self.nav.grid_problem(max(1, count), screen)
            ok = problem is None
            text = ("✔ Posisi Daftar Soal sudah ditandai." if ok else f"⚠ Daftar Soal: {problem}.") \
                + " (tombol nomor 1, nomor 2, dan nomor tepat di bawah nomor 1)"
            if percat:
                cats = self._plan_cats()
                miss = [c for c in cats if not self.nav.category_options.get(c)]
                dd_ok = bool(self.nav.category_dropdown) and not miss
                text += ("<br>✔ Dropdown Tipe Soal sudah ditandai (" + ", ".join(cats) + ")." if dd_ok else
                         "<br>⚠ Dropdown Tipe Soal belum ditandai" + (f" ({', '.join(miss)})" if miss else "") + ".")
            self.lbl_nav.setText(text)
        elif mode == "point":
            self.lbl_nav.setText(("✔ Posisi tombol sudah ditandai." if self.nav.point else "⚠ Belum ditandai.")
                                 + " Tombol harus terlihat di posisi yang sama setelah halaman di-scroll ke atas. "
                                 "Soal pertama harus sudah terbuka.")
        else:
            self.lbl_nav.setText("Soal pertama harus sudah terbuka. Pastikan panah kanan berpindah soal di website.")
        c = self.win.settings["crop"] or {}
        self.lbl_crop.setText(f"✔ {c['rect'][2]}×{c['rect'][3]}px untuk layar {c['screen'][0]}×{c['screen'][1]}"
                              if c.get("rect") and c.get("screen")
                              else "⚠ Belum diatur — tutup dialog ini, klik “Atur Area…”")
        total = self._total()
        self.sp_start.setMaximum(max(1, total))
        self.sp_end.setMaximum(max(1, total))
        entries = self.plan().entries() if total else []
        if entries:
            f = entries[0]
            l = entries[-1]
            self.lbl_summary.setText(f"{len(entries)} soal: {f[1]}-{f[2]:03d} … {l[1]}-{l[2]:03d} "
                                     f"(perkiraan {max(1, round(len(entries) * 6 / 60))}–"
                                     f"{max(2, round(len(entries) * 12 / 60))} menit)")
        else:
            self.lbl_summary.setText("Rencana kosong")

    def _pick_dropdown(self):
        cats = self._plan_cats()
        names = {"TWK": "Tes Wawasan Kebangsaan", "TIU": "Tes Intelegensi Umum", "TKP": "Tes Karakteristik Pribadi"}

        def got_button(path):
            dlg = PointPickDialog(self, path, ["tombol dropdown “Tipe Soal” (dalam keadaan TERTUTUP)"])
            if dlg.exec() != QDialog.Accepted:
                return self._upd()
            self.nav.category_dropdown = dlg.points()[0]
            self._save()
            QMessageBox.information(
                self, "Tandai pilihan Tipe Soal",
                "Langkah 2: setelah klik OK, aplikasi bersembunyi 5 detik.\n\n"
                "Dalam 5 detik itu klik dropdown “Tipe Soal” di browser sampai daftar pilihannya TERBUKA, "
                "lalu diamkan (jangan pilih apa pun).")
            self.win.grab_reference(got_options, hide=[self], delay_ms=5000)

        def got_options(path):
            prompts = [f"pilihan “{names.get(c, c)}” ({c})" for c in cats]
            dlg = PointPickDialog(self, path, prompts)
            if dlg.exec() == QDialog.Accepted:
                self.nav.category_options = dict(zip(cats, dlg.points()))
                self._save()
            self._upd()
        if not cats:
            return
        QMessageBox.information(self, "Tandai dropdown Tipe Soal",
                                "Langkah 1: pastikan dropdown “Tipe Soal” di browser TERTUTUP. "
                                "Setelah klik OK aplikasi memotret layar, lalu klik tombol dropdown itu di gambar.")
        self.win.grab_reference(got_button, hide=[self])

    def _pick(self):
        mode = self.cb_nav.currentData()
        prompts = (["tombol nomor 1 di Daftar Soal", "tombol nomor 2 (di kanan nomor 1)",
                    "tombol tepat di BAWAH nomor 1 (mis. nomor 6)"] if mode == "grid" else ["tombol “Berikutnya”"])

        count = (max((sp.value() for sp in self.spins.values()), default=1) if self.chk_percat.isChecked()
                 else self._total())

        def got(path):
            dlg = PointPickDialog(self, path, prompts,
                                  grid=(self.sp_cols.value(), max(1, count)) if mode == "grid" else None)
            if dlg.exec() == QDialog.Accepted:
                pts = dlg.points()
                if mode == "grid":
                    self.nav.grid_first, self.nav.grid_second, self.nav.grid_below = pts
                else:
                    self.nav.point = pts[0]
                self._save()
            self._upd()
        self.win.grab_reference(got, hide=[self])

    def _save(self):
        self.nav.columns = self.sp_cols.value()
        self.nav.mode = self.cb_nav.currentData()
        self.nav.per_category = self.chk_percat.isChecked()
        from dataclasses import asdict
        self.win.settings["auto"] = {
            "sections": [[c, sp.value()] for c, sp in self.spins.items()],
            "global": self.rb_global.isChecked(), "nav": asdict(self.nav),
            "wait_load": self.sp_wait.value()}

    def _start(self):
        self._save()
        try:
            self.nav.validate(self._plan_cats())
        except AutoCaptureError as exc:
            QMessageBox.warning(self, "Tangkap Otomatis", str(exc))
            return
        c = self.win.settings["crop"] or {}
        if not (c.get("rect") and c.get("screen")):
            QMessageBox.warning(self, "Tangkap Otomatis", "Atur area potong dulu (tombol “Atur Area…”).")
            return
        if not self.plan().entries():
            QMessageBox.warning(self, "Tangkap Otomatis", "Rencana soal kosong.")
            return
        self.accept()


class SetupResultDialog(QDialog):
    """Tampilkan hasil Atur Otomatis untuk dicek sebelum dipakai."""

    def __init__(self, parent, res):
        super().__init__(parent)
        self.setWindowTitle("Hasil Atur Otomatis")
        self.choice = None
        lay = QVBoxLayout(self)
        x, y, w, h = res.crop["rect"]
        counts = ", ".join(f"{c} {n}" for c, n in res.counts.items())
        info = QLabel(f"<b>Terdeteksi:</b> {counts} soal (total {sum(res.counts.values())}) · Daftar Soal "
                      f"{res.nav.columns} kolom · area konten {w}×{h}px<br>"
                      "Kotak <b style='color:#d9a400'>kuning</b> = area yang dipotret, lingkaran "
                      "<b style='color:#1f6feb'>biru</b> = nomor yang akan diklik, lingkaran "
                      "<b style='color:#ff2d55'>merah</b> = tombol Tipe Soal."
                      + ("<br>⚠ " + "; ".join(res.notes) if res.notes else ""))
        info.setWordWrap(True)
        lay.addWidget(info)
        from PIL.ImageQt import ImageQt
        pm = QPixmap.fromImage(ImageQt(res.preview))
        geo = QApplication.primaryScreen().availableGeometry()
        pic = QLabel()
        pic.setPixmap(pm.scaled(int(geo.width() * 0.85), int(geo.height() * 0.65),
                                Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(pic, 0, Qt.AlignCenter)
        row = QHBoxLayout()
        if res.crop.get("smooth_scroll"):
            warn = QLabel("⚠ <b>Scroll halus browser AKTIF</b> — ini satu-satunya yang membuat soal panjang > 1 detik. "
                          "Buka <code>brave://flags/#smooth-scrolling</code> (Chrome: <code>chrome://flags/#smooth-scrolling"
                          "</code>) → <b>Disabled</b> → <b>Relaunch</b>, lalu jalankan Atur Otomatis lagi.")
            warn.setWordWrap(True)
            warn.setStyleSheet("background:#fff1c9; padding:8px; border-radius:6px")
            lay.insertWidget(1, warn)
            b_copy = QPushButton("Salin alamat brave://flags/#smooth-scrolling")
            b_copy.clicked.connect(lambda: QApplication.clipboard().setText("brave://flags/#smooth-scrolling"))
            lay.insertWidget(2, b_copy)
        b_start = QPushButton("▶ Simpan && Mulai Sekarang")
        b_start.setStyleSheet("font-weight:bold; background:#1f6feb; color:white; padding:8px 16px")
        b_save = QPushButton("Simpan Saja")
        b_cancel = QPushButton("Batal")
        b_start.clicked.connect(lambda: self._done("start"))
        b_save.clicked.connect(lambda: self._done("save"))
        b_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        for b in (b_cancel, b_save, b_start):
            row.addWidget(b)
        lay.addLayout(row)

    def _done(self, choice):
        self.choice = choice
        self.accept()


class SetupWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def start(self, driver, categories, wait_load, stop_event):
        def run():
            try:
                self.finished.emit(run_autosetup(driver, categories, self.progress.emit, wait_load, stop_event))
            except StopRequested:
                self.failed.emit("dihentikan")
            except SetupError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")
        threading.Thread(target=run, daemon=True).start()


class AutoWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def start(self, runner: AutoCapture):
        def run():
            try:
                self.finished.emit(runner.run())
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")
        threading.Thread(target=run, daemon=True).start()


class MovableBoxCanvas(CropCanvas):
    """Kotak seleksi: seret di dalam kotak untuk MENGGESER, seret di luar untuk membuat kotak baru."""

    def mousePressEvent(self, e):
        p = self._img_point(e.position().toPoint())
        if self.sel.width() > 2 and self.sel.contains(p):
            self._move_from = p
            self._start = None
        else:
            self._move_from = None
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self, "_move_from", None) is not None:
            p = self._img_point(e.position().toPoint())
            d = p - self._move_from
            r = self.sel.translated(d)
            r.moveLeft(min(max(0, r.left()), self.src.width() - r.width()))
            r.moveTop(min(max(0, r.top()), self.src.height() - r.height()))
            self.sel, self._move_from = r, p
            self.update()
            self.on_change()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if getattr(self, "_move_from", None) is not None:
            self._move_from = None
        else:
            super().mouseReleaseEvent(e)


class FigureBoxDialog(QDialog):
    """Potong manual gambar soal: kotak bisa digeser atau digambar ulang."""

    def __init__(self, parent, path: Path, box: dict | None, title: str):
        super().__init__(parent)
        self.setWindowTitle(f"Potong gambar — {title}")
        pm = QPixmap(str(path))
        rect = QRect(box["x"], box["y"], box["w"], box["h"]) if box else QRect()
        self.canvas = MovableBoxCanvas(pm, rect)
        self.info = QLabel()
        self.canvas.on_change = self._upd
        area = QScrollArea()
        area.setWidget(self.canvas)
        area.setWidgetResizable(False)
        geo = QApplication.primaryScreen().availableGeometry()
        area.setMinimumSize(min(self.canvas.width() + 24, int(geo.width() * 0.9)),
                            min(self.canvas.height() + 24, int(geo.height() * 0.7)))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Seret di <b>dalam</b> kotak untuk menggeser, di <b>luar</b> kotak untuk membuat kotak "
                             "baru. Kotak hanya berisi gambar soal — tanpa warna hijau/merah pilihan jawaban."))
        lay.addWidget(area)
        lay.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._upd()

    def _upd(self):
        r = self.canvas.sel
        self.info.setText(f"Kotak: {r.width()}×{r.height()}px di ({r.x()},{r.y()})" if r.width() > 2
                          else "Belum ada kotak")

    def box(self) -> dict | None:
        r = self.canvas.sel
        return {"x": r.x(), "y": r.y(), "w": r.width(), "h": r.height()} if r.width() > 10 else None

    @staticmethod
    def cut(parent, pkg, item) -> bool:
        start = (item.figures[0] if item.figures else item.figure_hint) or \
            {"x": 20, "y": max(0, item.height // 6), "w": max(50, item.width - 40), "h": 160}
        dlg = FigureBoxDialog(parent, pkg.path_of(item), start, item.display_name)
        if dlg.exec() != QDialog.Accepted or dlg.box() is None:
            return False
        pkg.set_figure_box(item.id, dlg.box())
        return True


class FigurePreviewDialog(QDialog):
    """Pratinjau semua potongan gambar sebelum ekspor: buang / potong ulang per soal."""

    def __init__(self, win: "MainWindow", for_export: bool = False):
        super().__init__(win)
        self.win, self.pkg = win, win.pkg
        self.setWindowTitle("Pratinjau gambar soal bergambar")
        self.lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.lay.addWidget(self.head)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.lay.addWidget(self.area, 1)
        bb = QDialogButtonBox()
        if for_export:
            self.b_ok = bb.addButton("Lanjut Ekspor ZIP", QDialogButtonBox.AcceptRole)
            self.b_ok.setStyleSheet("font-weight:bold; background:#1f6feb; color:white; padding:6px 14px")
            bb.addButton("Batal", QDialogButtonBox.RejectRole)
        else:
            bb.addButton("Tutup", QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.lay.addWidget(bb)
        geo = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1000, int(geo.width() * 0.8)), int(geo.height() * 0.8))
        self._build()

    def _items(self):
        return [it for it in self.pkg.sorted_items() if it.assigned and not it.figures_off
                and (it.figures or it.figure_manual)]

    def _build(self):
        items = self._items()
        ok = sum(1 for it in items if it.figures)
        todo = sum(1 for it in items if not it.figures)
        self.head.setText(f"<b>{ok} soal bergambar</b> akan masuk folder gambar/."
                          + (f" <span style='color:#b35c00'><b>{todo} soal perlu dipotong manual</b> "
                             "(gambar di pilihan jawaban) — klik “Potong” atau “Buang”.</span>" if todo else "")
                          + " Pastikan tiap potongan hanya berisi gambar soal.")
        box = QWidget()
        grid = QGridLayout(box)
        for r, it in enumerate(items):
            name = QLabel(f"<b>{it.display_name}</b><br>"
                          + ("manual" if it.figure_by_hand else "otomatis" if it.figures else
                             "<span style='color:#b35c00'>perlu dipotong manual</span>"))
            pic = QLabel()
            if it.figures:
                img = QPixmap()
                img.loadFromData(self.pkg.figure_png(it))
                pic.setPixmap(img.scaled(560, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                pic.setText("—")
            b_cut = QPushButton("Potong Ulang" if it.figures else "Potong")
            b_drop = QPushButton("Buang")
            b_cut.clicked.connect(lambda _=False, i=it: self._cut(i))
            b_drop.clicked.connect(lambda _=False, i=it: self._drop(i))
            grid.addWidget(name, r, 0)
            grid.addWidget(pic, r, 1)
            grid.addWidget(b_cut, r, 2)
            grid.addWidget(b_drop, r, 3)
        if not items:
            grid.addWidget(QLabel("Tidak ada soal bergambar."), 0, 0)
        self.area.setWidget(box)

    def _cut(self, it):
        if FigureBoxDialog.cut(self, self.pkg, it):
            self._build()

    def _drop(self, it):
        self.pkg.set_figural(it.id, False)
        self._build()


class ImportDialog(QDialog):
    """Buat ZIP siap impor SKD Intelligence dari soal.json hasil ChatGPT."""

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        from . import skdimport
        self.sk, self.win, self.pkg = skdimport, win, win.pkg
        self.doc = None
        self.setWindowTitle("Buat ZIP siap impor — SKD Intelligence")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Tempel isi <b>soal.json</b> dari ChatGPT di bawah, atau pilih filenya."))
        row = QHBoxLayout()
        b_file = QPushButton("Pilih file soal.json…")
        b_file.clicked.connect(self._pick)
        b_check = QPushButton("Periksa")
        b_check.clicked.connect(self._check)
        row.addWidget(b_file)
        row.addWidget(b_check)
        row.addStretch(1)
        lay.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('{"paket": "Paket 01", "soal": [ ... ]}')
        lay.addWidget(self.text, 2)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.issues = QListWidget()
        lay.addWidget(self.issues, 2)
        bb = QDialogButtonBox()
        self.b_make = bb.addButton("Buat ZIP siap impor", QDialogButtonBox.AcceptRole)
        self.b_make.setEnabled(False)
        self.b_make.setStyleSheet("font-weight:bold")
        bb.addButton("Tutup", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._make)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        geo = QApplication.primaryScreen().availableGeometry()
        self.resize(min(900, int(geo.width() * 0.7)), int(geo.height() * 0.75))

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Pilih soal.json",
                                           self.win.settings["zip_dir"] or str(Path.home() / "Downloads"),
                                           "JSON (*.json *.txt)")
        if f:
            self.text.setPlainText(Path(f).read_text(encoding="utf-8-sig"))
            self._check()

    def _images(self) -> dict:
        return {f"gambar/{it.filename}": self.pkg.figure_png(it) for it in self.pkg.figural_items()}

    def _check(self):
        self.issues.clear()
        self.b_make.setEnabled(False)
        try:
            doc, changes = self.sk.clean(self.sk.parse_soal_json(self.text.toPlainText()))
        except ValueError as exc:
            self.summary.setText(f"✖ {exc}")
            return
        self.images = self._images()
        expected = sum(1 for it in self.pkg.items if it.assigned)
        figural = {Path(it.filename).stem for it in self.pkg.figural_items()}
        v = self.sk.validate(doc, set(self.images), expected, figural)
        self.doc = doc
        for c in changes:
            self.issues.addItem(QListWidgetItem(f"🧹 dibersihkan: {c}"))
        for who, msg in v.issues:
            it = QListWidgetItem(f"⚠ {who}: {msg}")
            it.setForeground(QColor("#8a6100"))
            self.issues.addItem(it)
        self.summary.setText(f"<b>{v.total} soal, {v.gambar} gambar.</b> "
                             + (f"<span style='color:#8a6100'>{len(v.issues)} masalah ditemukan — boleh tetap "
                                "lanjut.</span>" if v.issues else "<span style='color:#0b7a32'>Tidak ada masalah."
                                                                  "</span>"))
        self.b_make.setEnabled(True)

    def _make(self):
        if self.doc is None:
            return
        start = self.win.settings["zip_dir"] or str(Path.home() / "Downloads")
        dest, _ = QFileDialog.getSaveFileName(self, "Simpan ZIP siap impor",
                                              str(Path(start) / f"{self.pkg.name}-siap-impor.zip"),
                                              "Arsip ZIP (*.zip)")
        if not dest:
            return
        try:
            out = self.sk.build_import_zip(dest, self.doc, self.images)
        except (ValueError, OSError) as exc:
            return QMessageBox.warning(self, "Buat ZIP siap impor", f"Gagal: {exc}")
        n_soal = len(self.doc["soal"])
        n_img = sum(1 for s in self.doc["soal"] if isinstance(s, dict) and s.get("gambar") in self.images)
        msg = f"{n_soal} soal, {n_img} gambar. Unggah di SKD Intelligence → Impor Soal → Unggah ZIP."
        self.win.set_banner(f"✔ {out.name}: {msg}", "ok")
        self.win.log_event(f"ZIP siap impor: {out} — {msg}", "ok")
        QMessageBox.information(self, "ZIP siap impor", f"{out}\n\n{msg}")
        self.accept()


class UpdateWorker(QObject):
    """Menjalankan cek/unduh update di thread terpisah agar UI tidak macet."""
    checked = Signal(object, bool)      # ReleaseInfo, silent
    failed = Signal(str, bool)          # pesan, silent
    progress = Signal(int, int)
    downloaded = Signal(str)
    download_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.cancel_flag = False

    def check(self, silent: bool):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                self.checked.emit(updater.fetch_latest(), silent)
            except updater.UpdateError as exc:
                self.failed.emit(str(exc), silent)
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def download(self, info):
        self.cancel_flag = False

        def run():
            try:
                path = updater.download_installer(info, lambda d, t: self.progress.emit(d, t),
                                                  lambda: self.cancel_flag)
                self.downloaded.emit(str(path))
            except updater.UpdateError as exc:
                self.download_failed.emit(str(exc))
        threading.Thread(target=run, daemon=True).start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.pkg: Package | None = None
        self.armed = False
        self.redo_restore: tuple[str, int] | None = None   # (kategori, nomor) setelah "Ulangi Nomor"
        self.append_target: str | None = None              # id item untuk "Tambah Bagian"
        self.append_prev_armed = False
        self.waiting_crop_reference = False
        self.auto_running = False
        self.auto_worker: AutoWorker | None = None
        self.auto_stop = threading.Event()
        self._hotkey_hwnd = None
        self.setup_running = False
        self.screen_grabber = win_input.grab_screen if win_input.available() else None
        self.driver_factory = win_input.WindowsDriver if win_input.available() else None
        self.last_item_id: str | None = None
        self._thumbs: dict[str, QPixmap] = {}
        self._loading = False

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1360, 820)
        self._build_ui()

        self.watcher = FolderWatcher(self)
        self.watcher.fileReady.connect(lambda p: self.handle_incoming(p, "folder"))
        self.watcher.fileRejected.connect(lambda p, why: self.log_event(
            f"Diabaikan: {Path(p).name} — {why}", "err"))
        self.watcher.statusChanged.connect(self._on_watch_status)

        self._open_package(self.settings["package"] or "Paket-01")
        self.chk_top.setChecked(bool(self.settings["always_on_top"]))
        self.chk_figural.setChecked(self.settings["zip_figural"] is not False)
        self._refresh_crop_label()
        self.start_watching(self.settings["watch_folder"])
        self.set_banner("Siap. Atur paket, kategori, dan nomor lalu klik “Siapkan Screenshot Berikutnya”.",
                        "info")

        self.updates = UpdateWorker(self)
        self.updates.checked.connect(self._on_update_checked)
        self.updates.failed.connect(self._on_update_failed)
        self.updates.progress.connect(self._on_update_progress)
        self.updates.downloaded.connect(self._on_update_downloaded)
        self.updates.download_failed.connect(self._on_update_download_failed)
        self._update_dialog: QProgressDialog | None = None
        self._update_downloading = False
        self._pending_installer: str | None = None
        self._update_version = ""
        if self.settings["auto_update_check"] is not False:
            QTimer.singleShot(2500, lambda: self.check_updates(silent=True))
            self._update_timer = QTimer(self)                  # cek ulang tiap 2 jam
            self._update_timer.setInterval(2 * 60 * 60 * 1000)
            self._update_timer.timeout.connect(lambda: self.check_updates(silent=True))
            self._update_timer.start()

    # ============================================================ UI build
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)

        # --- baris status pemantauan
        top = QHBoxLayout()
        self.lbl_watch = QLabel("● BERHENTI")
        self.lbl_watch.setMinimumWidth(130)
        self.lbl_watch.setStyleSheet("font-weight:bold; font-size:14px; color:#b00")
        self.ed_folder = QLineEdit()
        self.ed_folder.setReadOnly(True)
        btn_folder = QPushButton("Ganti Folder…")
        btn_folder.clicked.connect(self.choose_folder)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setShortcut(QKeySequence("F5"))
        btn_refresh.clicked.connect(self.refresh_folder)
        btn_manual = QPushButton("Pilih File Manual…")
        btn_manual.clicked.connect(self.pick_files)
        btn_clip = QPushButton("Tempel dari Clipboard")
        btn_clip.setToolTip("Ambil gambar dari clipboard (Ctrl+Shift+V)")
        btn_clip.clicked.connect(self.paste_clipboard)
        self.chk_top = QCheckBox("Selalu di atas")
        self.chk_top.toggled.connect(self.set_on_top)
        self.btn_update = QPushButton("Periksa Update")
        self.btn_update.setToolTip(f"Versi terpasang: {__version__}. Update baru dipasang otomatis "
                                   "(saat aplikasi tidak sedang menangkap).")
        self.btn_update.clicked.connect(lambda: self.check_updates(silent=False))
        top.addWidget(self.lbl_watch)
        top.addWidget(QLabel("Folder Screenshots:"))
        top.addWidget(self.ed_folder, 1)
        for w in (btn_folder, btn_refresh, btn_manual, btn_clip, self.chk_top, self.btn_update):
            top.addWidget(w)
        outer.addLayout(top)

        # --- banner konfirmasi
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setMinimumHeight(46)
        self.banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.banner)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)
        cap = QScrollArea()
        cap.setWidget(self._build_capture_panel())
        cap.setWidgetResizable(True)
        cap.setFrameShape(QFrame.NoFrame)
        cap.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cap.setMinimumWidth(320)
        split.addWidget(cap)
        split.addWidget(self._build_list_panel())
        split.addWidget(self._build_preview_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([330, 700, 330])

        # --- bawah: log + ZIP
        bottom = QHBoxLayout()
        self.log_list = QListWidget()
        self.log_list.setMaximumHeight(110)
        bottom.addWidget(self.log_list, 1)
        zipbox = QVBoxLayout()
        self.lbl_counts = QLabel()
        self.lbl_counts.setAlignment(Qt.AlignCenter)
        self.lbl_counts.setStyleSheet("font-size:13px")
        self.btn_zip = QPushButton("BUAT ZIP")
        self.btn_zip.setMinimumSize(220, 64)
        self.btn_zip.setStyleSheet("font-size:20px; font-weight:bold; background:#1f6feb; color:white;"
                                   "border-radius:6px;")
        self.btn_zip.clicked.connect(self.make_zip)
        zipbox.addWidget(self.lbl_counts)
        zipbox.addWidget(self.btn_zip)
        self.chk_figural = QCheckBox("Sertakan PROMPT.txt + daftar.json + gambar/")
        self.chk_figural.setToolTip("ZIP untuk ChatGPT: PROMPT.txt (terisi otomatis), daftar.json, dan gambar/ "
                                    "berisi potongan soal bergambar saja. Tanpa base64.")
        zipbox.addWidget(self.chk_figural)
        self.btn_import = QPushButton("📦 Buat ZIP siap impor…")
        self.btn_import.setToolTip("Tempel / pilih soal.json dari ChatGPT → divalidasi & dibersihkan → "
                                   "<paket>-siap-impor.zip (soal.json + gambar/) untuk SKD Intelligence.")
        self.btn_import.clicked.connect(self.open_import_dialog)
        zipbox.addWidget(self.btn_import)
        bottom.addLayout(zipbox)
        outer.addLayout(bottom)

        paste = QAction(self)
        paste.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste.triggered.connect(self.paste_clipboard)
        self.addAction(paste)

    def _build_capture_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 6, 0)

        g_pkg = QGroupBox("Paket")
        hp = QHBoxLayout(g_pkg)
        self.cb_pkg = QComboBox()
        self.cb_pkg.activated.connect(lambda _i: self._open_package(self.cb_pkg.currentText()))
        btn_new = QPushButton("Paket Baru…")
        btn_new.clicked.connect(self.new_package)
        hp.addWidget(self.cb_pkg, 1)
        hp.addWidget(btn_new)
        lay.addWidget(g_pkg)

        g_cat = QGroupBox("Kategori")
        self.cat_layout = QGridLayout(g_cat)
        self.cat_group = QButtonGroup(self)
        self.cat_group.setExclusive(True)
        self.cat_group.buttonClicked.connect(lambda b: self.select_category(b.text()))
        lay.addWidget(g_cat)

        g_num = QGroupBox("Nomor soal berikutnya")
        vn = QVBoxLayout(g_num)
        self.spin = QSpinBox()
        self.spin.setRange(1, 9999)
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumHeight(44)
        self.spin.setStyleSheet("font-size:24px; font-weight:bold")
        self.spin.valueChanged.connect(self._on_spin)
        vn.addWidget(self.spin)
        hm = QHBoxLayout()
        self.rb_auto = QRadioButton("Otomatis (+1 setelah diterima)")
        self.rb_manual = QRadioButton("Manual")
        self.rb_auto.toggled.connect(self._on_mode)
        hm.addWidget(self.rb_auto)
        hm.addWidget(self.rb_manual)
        vn.addLayout(hm)
        g_num.setMinimumHeight(110)
        lay.addWidget(g_num)

        self.lbl_target = QLabel()
        self.lbl_target.setAlignment(Qt.AlignCenter)
        self.lbl_target.setStyleSheet("font-size:26px; font-weight:bold; padding:6px")
        self.lbl_state = QLabel()
        self.lbl_state.setAlignment(Qt.AlignCenter)
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setMinimumHeight(52)
        lay.addWidget(self.lbl_target)
        lay.addWidget(self.lbl_state)

        self.btn_arm = QPushButton("Siapkan Screenshot Berikutnya")
        self.btn_arm.setMinimumHeight(50)
        self.btn_arm.setStyleSheet("font-size:16px; font-weight:bold; background:#2e9e48; color:white;"
                                   "border-radius:6px;")
        self.btn_arm.setShortcut(QKeySequence("Ctrl+Return"))
        self.btn_arm.clicked.connect(self.arm)
        lay.addWidget(self.btn_arm)
        self.btn_append = QPushButton("+ Tambah Bagian Lanjutan")
        self.btn_append.setToolTip("Screenshot berikutnya DISAMBUNG ke bawah gambar terakhir "
                                   "(untuk soal/pembahasan yang perlu di-scroll)")
        self.btn_append.setMinimumHeight(40)
        self.btn_append.setStyleSheet("font-size:14px; font-weight:bold; background:#d9822b; color:white;"
                                      "border-radius:6px;")
        self.btn_append.setShortcut(QKeySequence("Ctrl+B"))
        self.btn_append.clicked.connect(self.append_next)
        lay.addWidget(self.btn_append)
        self.btn_grab = QPushButton("📷 Ambil Layar")
        self.btn_grab.setToolTip("Aplikasi bersembunyi sebentar lalu memotret layar penuh "
                                 "(sama seperti Win+PrtScn). Ctrl+Shift+S")
        self.btn_grab.setMinimumHeight(40)
        self.btn_grab.setStyleSheet("font-size:14px; font-weight:bold")
        self.btn_grab.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.btn_grab.clicked.connect(self.grab_now)
        lay.addWidget(self.btn_grab)
        self.btn_auto = QPushButton("⚡ TANGKAP OTOMATIS…  (F10)")
        self.btn_auto.setToolTip("F10 di mana pun: mulai dengan pengaturan terakhir / berhenti")
        self.btn_auto.setMinimumHeight(48)
        self.btn_auto.setStyleSheet("font-size:15px; font-weight:bold; background:#6f42c1; color:white;"
                                    "border-radius:6px;")
        self.btn_auto.clicked.connect(self.open_auto_capture)
        lay.addWidget(self.btn_auto)
        self.btn_setup = QPushButton("🪄 ATUR OTOMATIS (deteksi layar)")
        self.btn_setup.setToolTip("Buka halaman pembahasan di browser, lalu klik ini: aplikasi mengenali "
                                  "Daftar Soal, Tipe Soal, jumlah soal, dan area konten sendiri.")
        self.btn_setup.setMinimumHeight(44)
        self.btn_setup.setStyleSheet("font-size:14px; font-weight:bold; background:#2e9e48; color:white;"
                                     "border-radius:6px;")
        self.btn_setup.clicked.connect(lambda: self.run_auto_setup())
        lay.addWidget(self.btn_setup)
        grid = QGridLayout()
        btn_cancel = QPushButton("Batalkan")
        btn_cancel.setShortcut(QKeySequence("Esc"))
        btn_cancel.clicked.connect(self.disarm_clicked)
        btn_redo = QPushButton("Ulangi Nomor")
        btn_redo.setToolTip("Ambil ulang screenshot terakhir: screenshot berikutnya menggantikannya")
        btn_redo.clicked.connect(self.redo_last)
        btn_change = QPushButton("Ubah Nomor…")
        btn_change.clicked.connect(self.change_number)
        btn_addcat = QPushButton("+ Kategori…")
        btn_addcat.clicked.connect(self.add_category)
        for b in (btn_cancel, btn_redo, btn_change, btn_addcat):
            b.setMinimumHeight(34)
        grid.addWidget(btn_cancel, 0, 0)
        grid.addWidget(btn_redo, 0, 1)
        grid.addWidget(btn_change, 1, 0)
        grid.addWidget(btn_addcat, 1, 1)
        lay.addLayout(grid)

        g_crop = QGroupBox("Area potong (soal + pembahasan)")
        vc = QVBoxLayout(g_crop)
        hc = QHBoxLayout()
        self.chk_crop = QCheckBox("Aktif")
        self.chk_crop.toggled.connect(self._on_crop_toggled)
        btn_crop = QPushButton("Atur Area…")
        btn_crop.clicked.connect(self.setup_crop)
        hc.addWidget(self.chk_crop)
        hc.addWidget(btn_crop, 1)
        vc.addLayout(hc)
        self.lbl_crop = QLabel()
        self.lbl_crop.setWordWrap(True)
        self.lbl_crop.setStyleSheet("font-size:11px; color:#555")
        vc.addWidget(self.lbl_crop)
        lay.addWidget(g_crop)
        lay.addStretch(1)
        # urutan: Paket -> Tangkap Otomatis -> Area potong -> kontrol manual
        for i, wdg in enumerate((self.btn_setup, self.btn_auto, g_crop), start=1):
            lay.removeWidget(wdg)
            lay.insertWidget(i, wdg)
        lbl_manual = QLabel("<b>Manual / per soal</b>")
        lbl_manual.setStyleSheet("margin-top:6px")
        lay.insertWidget(4, lbl_manual)
        return panel

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 0, 6, 0)
        self.lbl_list = QLabel("Screenshot diterima")
        self.lbl_list.setStyleSheet("font-weight:bold")
        lay.addWidget(self.lbl_list)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Preview", "Kategori", "Nomor", "Nama File", "Bagian",
                                              "Gambar", "File Asli", "Diterima"])
        self.table.setIconSize(THUMB)
        self.table.verticalHeader().setDefaultSectionSize(THUMB.height() + 8)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, THUMB.width() + 12)
        self.table.itemSelectionChanged.connect(self._update_preview)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        b_edit = QPushButton("Ubah Kategori/Nomor…")
        b_edit.clicked.connect(self.edit_selected)
        b_del = QPushButton("Hapus dari Daftar")
        b_del.setShortcut(QKeySequence.Delete)
        b_del.clicked.connect(self.delete_selected)
        b_ren = QPushButton("Ulangi Penamaan (1..n)")
        b_ren.clicked.connect(self.renumber)
        b_part = QPushButton("Hapus Bagian Terakhir")
        b_part.setToolTip("Lepas sambungan terakhir dari gambar terpilih")
        b_part.clicked.connect(self.remove_last_part)
        b_fig = QPushButton("🖼 Gambar ▾")
        b_fig.setToolTip("Soal bergambar (figural): gambar di dalam soal ikut diekspor sebagai JSON")
        m_fig = QMenu(b_fig)
        m_fig.addAction("Pratinjau semua potongan gambar…", lambda: FigurePreviewDialog(self).exec())
        m_fig.addAction("Potong manual (baris terpilih)…", self.cut_figure_selected)
        m_fig.addAction("Deteksi ulang gambar (baris terpilih)", lambda: self.set_figural(True))
        m_fig.addAction("Buang gambar / BUKAN soal bergambar", lambda: self.set_figural(False))
        b_fig.setMenu(m_fig)
        b_ws = QPushButton("Buka Workspace")
        b_ws.clicked.connect(lambda: self.open_path(self.pkg.root))
        for b in (b_edit, b_del, b_ren, b_part, b_fig, b_ws):
            row.addWidget(b)
        lay.addLayout(row)
        return panel

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 0, 0, 0)
        lay.addWidget(QLabel("<b>Preview</b>"))
        self.preview = QLabel("Pilih baris untuk melihat preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(250, 250)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setFrameShape(QFrame.StyledPanel)
        lay.addWidget(self.preview, 1)
        self.preview_info = QLabel()
        self.preview_info.setWordWrap(True)
        self.preview_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.preview_info)
        return panel

    # ============================================================ helpers
    def set_banner(self, text: str, kind: str = "info"):
        self.banner.setText(text)
        self.banner.setStyleSheet(BANNER_STYLES[kind] + "font-size:17px; font-weight:bold;"
                                  "padding:8px; border-radius:6px;")

    def log_event(self, text: str, kind: str = "info"):
        stamp = datetime.now().strftime("%H:%M:%S")
        it = QListWidgetItem(f"{stamp}  {text}")
        it.setForeground(QColor({"ok": "#0b5d1e", "warn": "#8a6100", "err": "#b00000"}.get(kind, "#333")))
        self.log_list.insertItem(0, it)
        while self.log_list.count() > 300:
            self.log_list.takeItem(self.log_list.count() - 1)
        getattr(log, {"err": "error", "warn": "warning"}.get(kind, "info"))(text)

    def error(self, text: str):
        self.set_banner("✖ " + text, "err")
        self.log_event(text, "err")

    @staticmethod
    def open_path(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def current_category(self) -> str:
        return self.pkg.capture.category

    def target(self) -> tuple[str, int]:
        self.spin.interpretText()
        return self.current_category(), self.spin.value()

    # ============================================================ package
    def _reload_pkg_combo(self):
        names = list_packages(self.settings["workspace"])
        if self.pkg and self.pkg.name not in names:
            names.append(self.pkg.name)
        self.cb_pkg.blockSignals(True)
        self.cb_pkg.clear()
        self.cb_pkg.addItems(sorted(names))
        if self.pkg:
            self.cb_pkg.setCurrentText(self.pkg.name)
        self.cb_pkg.blockSignals(False)

    def _open_package(self, name: str):
        try:
            pkg = Package(self.settings["workspace"], name)
        except (ManagerError, OSError) as exc:
            self.error(f"Tidak bisa membuka paket '{name}': {exc}")
            if self.pkg is None:
                pkg = Package(self.settings["workspace"], "Paket-01")
            else:
                return
        fixed = pkg.repair()
        self.pkg = pkg
        self.settings["package"] = pkg.name
        self._thumbs.clear()
        self.disarm(silent=True)
        self.last_item_id = None
        self._reload_pkg_combo()
        self._rebuild_category_buttons()
        self._loading = True
        (self.rb_auto if pkg.capture.auto_number else self.rb_manual).setChecked(True)
        self._loading = False
        self.select_category(pkg.capture.category)
        self.refresh_table()
        self.log_event(f"Paket dibuka: {pkg.name} ({len(pkg.items)} screenshot) — {pkg.root}")
        if fixed:
            self.log_event(f"{fixed} file workspace diperbaiki namanya", "warn")
        missing = pkg.missing_files()
        if missing:
            self.log_event(f"{len(missing)} file workspace hilang: "
                           + ", ".join(i.filename for i in missing[:5]), "err")

    def new_package(self):
        existing = list_packages(self.settings["workspace"])
        n = len(existing) + 1
        while f"Paket-{n:02d}" in existing:
            n += 1
        name, ok = QInputDialog.getText(self, "Paket Baru", "Nama paket:", text=f"Paket-{n:02d}")
        if not ok:
            return
        try:
            name = sanitize_package_name(name)
        except ManagerError as exc:
            return self.error(str(exc))
        self._open_package(name)
        self.set_banner(f"Paket aktif: {name}", "info")

    # ============================================================ categories / number
    def _rebuild_category_buttons(self):
        for b in self.cat_group.buttons():
            self.cat_group.removeButton(b)
            b.deleteLater()
        for i, cat in enumerate(self.pkg.categories):
            b = QPushButton(cat)
            b.setCheckable(True)
            b.setMinimumHeight(44)
            b.setStyleSheet("QPushButton{font-size:18px; font-weight:bold}"
                            "QPushButton:checked{background:#1f6feb; color:white}")
            self.cat_group.addButton(b)
            self.cat_layout.addWidget(b, i // 3, i % 3)

    def select_category(self, cat: str):
        if cat not in self.pkg.categories:
            cat = self.pkg.categories[0]
        self.pkg.capture.category = cat
        self.pkg.save()
        for b in self.cat_group.buttons():
            b.setChecked(b.text() == cat)
        self._loading = True
        self.spin.setValue(self.pkg.next_number_for(cat))
        self._loading = False
        self._update_capture_labels()

    def _on_spin(self, value: int):
        if self._loading or self.pkg is None:
            return
        self.pkg.set_next_number(self.current_category(), value)
        self._update_capture_labels()

    def _on_mode(self):
        if self._loading or self.pkg is None:
            return
        self.pkg.capture.auto_number = self.rb_auto.isChecked()
        self.pkg.save()
        self._update_capture_labels()

    def set_number(self, value: int):
        self.spin.setValue(value)       # memicu _on_spin
        self.pkg.set_next_number(self.current_category(), value)
        self._update_capture_labels()

    def change_number(self):
        val, ok = QInputDialog.getInt(self, "Ubah Nomor",
                                      f"Nomor soal berikutnya untuk {self.current_category()}:",
                                      self.spin.value(), 1, 9999)
        if ok:
            self.set_number(val)
            self.log_event(f"Nomor berikutnya diubah: {make_filename(*self.target())}")

    def add_category(self):
        name, ok = QInputDialog.getText(self, "Tambah Kategori", "Kode kategori (mis. TWK):")
        if not ok or not name.strip():
            return
        try:
            cat = self.pkg.add_category(name)
        except ManagerError as exc:
            return self.error(str(exc))
        self._rebuild_category_buttons()
        self.select_category(cat)
        self.log_event(f"Kategori ditambahkan: {cat}")

    def _update_capture_labels(self):
        cat, num = self.target()
        fname = make_filename(cat, num)
        occupant = self.pkg.find_slot(cat, num)
        self.lbl_target.setText(fname)
        mode = "otomatis" if self.pkg.capture.auto_number else "manual"
        if self.append_target:
            try:
                it = self.pkg.get(self.append_target)
            except ManagerError:
                self.append_target = None
                return self._update_capture_labels()
            self.lbl_target.setText(f"{it.filename} + bagian {it.parts + 1}")
            self.lbl_state.setText("● SIAP: BAGIAN LANJUTAN<br><span style='font-size:12px'>Screenshot "
                                   f"berikutnya disambung ke bawah {it.filename}</span>")
            self.lbl_state.setStyleSheet("background:#d9822b; color:white; font-size:18px;"
                                         "font-weight:bold; border-radius:6px; padding:4px")
            self.lbl_target.setStyleSheet("font-size:22px; font-weight:bold; padding:6px; color:#a35400")
            self.setWindowTitle(f"{APP_NAME} — SIAP: BAGIAN {it.parts + 1} {it.filename} [{self.pkg.name}]")
        elif self.armed:
            extra = ""
            if self.redo_restore:
                extra = "<br>(ULANGI: menggantikan versi sebelumnya)"
            elif occupant:
                extra = f"<br>⚠ {fname} sudah ada — akan DIGANTI"
            self.lbl_state.setText(f"● SIAP MENERIMA<br><span style='font-size:12px'>"
                                   f"Paket {self.pkg.name} · nomor {mode}{extra}</span>")
            self.lbl_state.setStyleSheet("background:#2e9e48; color:white; font-size:18px;"
                                         "font-weight:bold; border-radius:6px; padding:4px")
            self.lbl_target.setStyleSheet("font-size:26px; font-weight:bold; padding:6px; color:#0b5d1e")
            self.setWindowTitle(f"{APP_NAME} — SIAP: {fname} [{self.pkg.name}]")
        else:
            warn = f"<br>⚠ {fname} sudah ada" if occupant else ""
            self.lbl_state.setText("○ BELUM SIAP<br><span style='font-size:12px'>Klik “Siapkan "
                                   f"Screenshot Berikutnya” sebelum mengambil screenshot{warn}</span>")
            self.lbl_state.setStyleSheet("background:#e9e9e9; color:#555; font-size:18px;"
                                         "font-weight:bold; border-radius:6px; padding:4px")
            self.lbl_target.setStyleSheet("font-size:26px; font-weight:bold; padding:6px; color:#777")
            self.setWindowTitle(f"{APP_NAME} — belum siap [{self.pkg.name}]")

    # ============================================================ arm / capture
    def arm(self):
        if not self.watcher.active:
            self.set_banner("⚠ Folder tidak sedang dipantau. Periksa folder Screenshots.", "warn")
        self.armed = True
        self._update_capture_labels()
        fname = make_filename(*self.target())
        self.set_banner(f"SIAP — screenshot berikutnya akan disimpan sebagai {fname}", "info")
        self.log_event(f"Siap menerima: {fname}")

    def disarm(self, silent=False):
        was = self.armed or self.append_target is not None
        self.armed = False
        self.append_target = None
        if self.redo_restore:
            cat, num = self.redo_restore
            self.redo_restore = None
            self.select_category(cat)
            self.set_number(num)
        if self.pkg:
            self._update_capture_labels()
        if was and not silent:
            self.log_event("Persiapan dibatalkan")

    def disarm_clicked(self):
        self.disarm()
        self.set_banner("Dibatalkan — screenshot berikutnya tidak akan diberi nomor.", "warn")

    def redo_last(self):
        item = None
        if self.last_item_id:
            try:
                item = self.pkg.get(self.last_item_id)
            except ManagerError:
                item = None
        if item is None or not item.assigned:
            sel = self.selected_items()
            item = sel[0] if sel and sel[0].assigned else None
        if item is None:
            return self.error("Belum ada screenshot terakhir untuk diulang. Pilih baris di daftar.")
        if self.append_target:
            self.append_target = None
            self.armed = self.append_prev_armed
        if not self.redo_restore:
            self.redo_restore = self.target()
        self.select_category(item.category)
        self._loading = True
        self.spin.setValue(item.number)
        self._loading = False
        self.armed = True
        self._update_capture_labels()
        self.set_banner(f"ULANGI — screenshot berikutnya akan MENGGANTIKAN {item.filename}", "warn")
        self.log_event(f"Ulangi nomor: {item.filename}", "warn")

    def handle_incoming(self, path: str, origin: str):
        if self.pkg is None:
            return
        name = Path(path).name
        if self.waiting_crop_reference:
            self.waiting_crop_reference = False
            self._open_crop_dialog(path)
            return
        if self.append_target:
            return self._handle_append(path, name, origin)
        crop = self.settings["crop"]
        try:
            if self.armed:
                cat, num = self.target()
                res = self.pkg.add_image(path, cat, num, crop=crop)
            else:
                res = self.pkg.add_image(path, crop=crop)
        except DuplicateImageError as exc:
            self.set_banner(f"✖ DUPLIKAT — {name} sama dengan {exc.existing.display_name}. "
                            "Tidak disimpan.", "err")
            self.log_event(f"Duplikat diabaikan: {name} = {exc.existing.display_name}", "err")
            return
        except (ManagerError, OSError) as exc:
            return self.error(f"Gagal memproses {name}: {exc}")

        item = res.item
        self.last_item_id = item.id
        if item.assigned:
            replaced = f" (menggantikan versi lama)" if res.replaced else ""
            msg = f"✔ DITERIMA: {item.filename}{replaced}{' (dipotong)' if res.cropped else ''}  ←  {name}"
            if self.redo_restore:
                cat, num = self.redo_restore
                self.redo_restore = None
                self.select_category(cat)
                self.set_number(num)
                if not self.pkg.capture.auto_number:
                    self.armed = False
            elif self.pkg.capture.auto_number:
                self.set_number(item.number + 1)
            else:
                self.armed = False
            nxt = make_filename(*self.target())
            msg += (f"   •   Berikutnya: {nxt}" if self.armed
                    else "   •   Atur nomor lalu klik “Siapkan” lagi")
            self.set_banner(msg, "ok")
            self.log_event(f"Diterima {item.filename}{replaced} dari {name} [{origin}]", "ok")
        else:
            self.set_banner(f"⚠ MASUK TANPA NOMOR: {name}. Tetapkan kategori/nomor di daftar "
                            "(klik dua kali), atau klik “Siapkan” sebelum screenshot berikutnya.", "warn")
            self.log_event(f"Masuk tanpa metadata: {name} [{origin}]", "warn")
        self._update_capture_labels()
        self._figures_for(item)
        self.refresh_table(select_id=item.id)

    # ============================================================ bagian lanjutan
    def append_next(self):
        item = None
        sel = self.selected_items()
        if self.last_item_id:
            try:
                item = self.pkg.get(self.last_item_id)
            except ManagerError:
                item = None
        if item is None and sel:
            item = sel[0]
        if item is None:
            return self.error("Belum ada gambar untuk disambung. Ambil screenshot bagian pertama dulu.")
        if self.append_target is None:
            self.append_prev_armed = self.armed
        self.append_target = item.id
        self._update_capture_labels()
        self.set_banner(f"SIAP BAGIAN LANJUTAN — screenshot berikutnya disambung ke bawah {item.filename} "
                        f"(bagian {item.parts + 1})", "info")
        self.log_event(f"Siap bagian lanjutan untuk {item.filename}")

    def _handle_append(self, path: str, name: str, origin: str):
        try:
            res = self.pkg.append_part(self.append_target, path, crop=self.settings["crop"])
        except DuplicateImageError as exc:
            self.set_banner(f"✖ DUPLIKAT — {name} sama dengan {exc.existing.display_name}. Tidak disambung. "
                            "Scroll halaman lalu ambil lagi.", "err")
            self.log_event(f"Bagian duplikat diabaikan: {name}", "err")
            return
        except (ManagerError, OSError) as exc:
            return self.error(f"Gagal menyambung {name}: {exc}. Scroll halaman lalu ambil lagi.")
        item = res.item
        self.append_target = None
        self.armed = self.append_prev_armed
        self.last_item_id = item.id
        self._thumbs.clear()
        ov = f", tumpang tindih {res.overlap_rows}px dibuang" if res.overlap_rows else ""
        nxt = (f"   •   Berikutnya: {make_filename(*self.target())}" if self.armed
               else "   •   Atur nomor lalu klik “Siapkan” lagi")
        self.set_banner(f"✔ BAGIAN {res.part_number} DISAMBUNG ke {item.filename} "
                        f"({item.width}×{item.height}px{ov}){nxt}", "ok")
        self.log_event(f"Bagian {res.part_number} disambung ke {item.filename} dari {name} [{origin}]", "ok")
        self._update_capture_labels()
        self._figures_for(item)
        self.refresh_table(select_id=item.id)

    # ============================================================ soal bergambar
    def _figure_cell(self, it: Item) -> QTableWidgetItem:
        if it.figures_off:
            c = QTableWidgetItem("bukan")
            c.setToolTip("Ditandai bukan soal bergambar")
        elif it.figures:
            c = QTableWidgetItem("🖼 manual" if it.figure_by_hand else "🖼")
            f = it.figures[0]
            c.setToolTip(f"Soal bergambar → gambar/{it.filename} ({f['w']}×{f['h']}px)")
            c.setForeground(QColor("#6f42c1"))
        elif it.figure_manual:
            c = QTableWidgetItem("✂ manual")
            c.setToolTip("Gambar ada di pilihan jawaban — potong manual (🖼 Gambar ▾ → Potong manual)")
            c.setForeground(QColor("#b35c00"))
        else:
            c = QTableWidgetItem("—" if it.figures_checked else "?")
        return c

    def _figures_for(self, item: Item):
        try:
            figs = self.pkg.update_figures(item.id)
        except ManagerError:
            return
        if figs:
            self.log_event(f"🖼 {item.display_name}: soal bergambar → gambar/{item.filename}", "ok")
        elif item.figure_manual:
            self.log_event(f"✂ {item.display_name}: gambar di pilihan jawaban — perlu dipotong manual", "warn")

    def set_figural(self, on: bool):
        sel = self.selected_items()
        if not sel:
            return self.error("Pilih baris di daftar terlebih dahulu")
        for it in sel:
            figs = self.pkg.set_figural(it.id, on)
            self.log_event(f"{it.display_name}: " + (("gambar terdeteksi" if figs else "tidak ada gambar") if on
                                                      else "ditandai bukan soal bergambar"))
        self._thumbs.clear()
        self.refresh_table()

    def cut_figure_selected(self):
        sel = self.selected_items()
        if not sel or not sel[0].assigned:
            return self.error("Pilih satu soal di daftar terlebih dahulu")
        if FigureBoxDialog.cut(self, self.pkg, sel[0]):
            self.log_event(f"✂ {sel[0].display_name}: gambar dipotong manual", "ok")
            self.refresh_table(select_id=sel[0].id)

    def remove_last_part(self):
        sel = self.selected_items()
        if not sel:
            return self.error("Pilih gambar di daftar terlebih dahulu")
        try:
            item = self.pkg.remove_last_part(sel[0].id)
        except (ManagerError, OSError) as exc:
            return self.error(str(exc))
        self._thumbs.clear()
        self.log_event(f"Bagian terakhir dilepas dari {item.display_name} (sisa {item.parts})", "warn")
        self.set_banner(f"Bagian terakhir dilepas dari {item.display_name} — sisa {item.parts} bagian", "warn")
        self._figures_for(item)
        self.refresh_table(select_id=item.id)

    # ============================================================ crop
    def _refresh_crop_label(self):
        c = self.settings["crop"] or {}
        has = bool(c.get("rect") and c.get("screen"))
        self.chk_crop.blockSignals(True)
        self.chk_crop.setChecked(bool(c.get("enabled")) and has)
        self.chk_crop.setEnabled(has)
        self.chk_crop.blockSignals(False)
        if has:
            x, y, w, h = c["rect"]
            self.lbl_crop.setText(f"Area {w}×{h}px di ({x},{y}) untuk layar {c['screen'][0]}×{c['screen'][1]}. "
                                  "Screenshot berukuran lain tidak dipotong.")
        else:
            self.lbl_crop.setText("Belum diatur. Klik “Atur Area…”.")

    def _on_crop_toggled(self, on: bool):
        c = dict(self.settings["crop"] or {})
        c["enabled"] = on
        self.settings["crop"] = c
        self.log_event("Potong otomatis " + ("aktif" if on else "nonaktif"))

    def setup_crop(self):
        box = QMessageBox(self)
        box.setWindowTitle("Atur Area Potong")
        box.setText("Butuh satu screenshot layar penuh sebagai acuan (halaman soal terbuka di browser).\n\n"
                    "• Ambil Layar Acuan: aplikasi bersembunyi 1 detik lalu memotret layar.\n"
                    "• Tunggu Screenshot: tekan Win+PrtScn sendiri.\n"
                    "Screenshot acuan tidak dimasukkan ke daftar.")
        b_self = box.addButton("Ambil Layar Acuan", QMessageBox.YesRole) if self.screen_grabber else None
        b_wait = box.addButton("Tunggu Screenshot", QMessageBox.AcceptRole)
        b_file = box.addButton("Pilih File…", QMessageBox.ActionRole)
        box.addButton("Batal", QMessageBox.RejectRole)
        box.exec()
        if b_self is not None and box.clickedButton() is b_self:
            self.grab_reference(self._open_crop_dialog)
        elif box.clickedButton() is b_wait:
            self.waiting_crop_reference = True
            self.set_banner("Menunggu screenshot acuan — tekan Win+PrtScn di halaman soal.", "info")
        elif box.clickedButton() is b_file:
            exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
            f, _ = QFileDialog.getOpenFileName(self, "Pilih screenshot layar penuh", self.ed_folder.text(),
                                               f"Gambar ({exts})")
            if f:
                self._open_crop_dialog(f)

    def _open_crop_dialog(self, path: str):
        dlg = CropDialog(self, path, self.settings["crop"])
        if dlg.exec() == QDialog.Accepted:
            self.settings["crop"] = dlg.result_crop()
            self._refresh_crop_label()
            x, y, w, h = self.settings["crop"]["rect"]
            self.set_banner(f"✔ Area potong disimpan: {w}×{h}px. Potong otomatis AKTIF.", "ok")
            self.log_event(f"Area potong: {self.settings['crop']}", "ok")
        else:
            self.set_banner("Pengaturan area potong dibatalkan.", "warn")

    # ============================================================ ambil layar
    def _hidden_grab(self, done, hide=(), delay_ms: int = 250):
        """Sembunyikan jendela, potret layar, tampilkan lagi, lalu panggil done(path)."""
        if self.screen_grabber is None:
            return self.error("Ambil layar otomatis hanya tersedia di Windows. Pakai Win+PrtScn.")
        windows = [self, *hide]
        for w in windows:
            w.hide()

        def shoot():
            err = None
            path = None
            try:
                img = self.screen_grabber()
                d = self.pkg.root / "_tangkapan"
                d.mkdir(exist_ok=True)
                path = d / f"layar-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
                img.save(path, "PNG")
            except Exception as exc:  # noqa: BLE001
                err = exc
            for w in reversed(windows):
                w.show()
            self.raise_()
            if path is None:
                return self.error(f"Gagal memotret layar: {err}")
            done(str(path))
        QTimer.singleShot(delay_ms, shoot)

    def grab_now(self):
        def done(path):
            self.handle_incoming(path, "ambil layar")
            Path(path).unlink(missing_ok=True)
        self._hidden_grab(done)

    def grab_reference(self, callback, hide=(), delay_ms: int = 250):
        def done(path):
            try:
                callback(path)
            finally:
                Path(path).unlink(missing_ok=True)
        self._hidden_grab(done, hide=hide, delay_ms=delay_ms)

    def open_auto_capture(self):
        if self.driver_factory is None:
            return self.error("Tangkap Otomatis hanya tersedia di Windows.")
        dlg = AutoCaptureDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.start_auto_capture(dlg.plan(), dlg.nav, dlg.sp_wait.value())

    def start_auto_capture(self, plan: Plan, nav: NavConfig, wait_load: float, delay_ms: int = 120):
        cfg = RunConfig(crop=dict(self.settings["crop"] or {}), nav=nav, wait_load=wait_load)
        self.auto_worker = AutoWorker(self)
        self.auto_stop = threading.Event()
        try:
            runner = AutoCapture(self.pkg, plan, cfg, self.driver_factory(), self.auto_worker.progress.emit,
                                 stop_event=self.auto_stop)
        except AutoCaptureError as exc:
            self.showNormal()
            self.raise_()
            return self.error(str(exc))
        self.disarm(silent=True)
        self.auto_running = True
        self.watcher.stop()
        self.centralWidget().setEnabled(False)
        self.log_event(f"Tangkap Otomatis dimulai: {len(plan.entries())} soal", "ok")
        self.auto_worker.progress.connect(self._on_auto_progress)
        self.auto_worker.finished.connect(self._on_auto_finished)
        self.auto_worker.failed.connect(lambda m: self._on_auto_finished(None, m))
        self.hide()                                   # langsung hilang (tanpa animasi minimize)
        QTimer.singleShot(delay_ms, lambda: self.auto_worker.start(runner))

    def _setup_categories(self) -> list[str]:
        saved = (self.settings["auto"] or {}).get("sections") or []
        cats = [c for c, _ in saved if c in self.pkg.categories] or \
            [c for c in ("TWK", "TIU", "TKP") if c in self.pkg.categories]
        return cats

    def run_auto_setup(self, wait_load: float | None = None, delay_ms: int = 120):
        if self.driver_factory is None:
            return self.error("Atur Otomatis hanya tersedia di Windows.")
        if self.setup_running or self.auto_running:
            return
        wait = float(wait_load if wait_load is not None else (self.settings["auto"] or {}).get("wait_load", 1.5))
        self.setup_running = True
        self.auto_stop = threading.Event()
        self.centralWidget().setEnabled(False)
        self.log_event("Atur Otomatis: mendeteksi tata letak halaman…", "ok")
        self.setup_worker = SetupWorker(self)
        self.setup_worker.progress.connect(lambda m: (self.log_event(m),
                                                      self.setWindowTitle(f"{APP_NAME} — ATUR OTOMATIS {m[:50]}")))
        self.setup_worker.finished.connect(self._on_setup_done)
        self.setup_worker.failed.connect(self._on_setup_failed)
        self.hide()                                   # langsung hilang (tanpa animasi minimize)
        driver = self.driver_factory()
        QTimer.singleShot(delay_ms, lambda: self.setup_worker.start(driver, self._setup_categories(), wait,
                                                                      self.auto_stop))

    def _restore_after_setup(self):
        self.setup_running = False
        self.centralWidget().setEnabled(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._update_capture_labels()

    def _on_setup_failed(self, msg: str):
        self._restore_after_setup()
        self.error(f"Atur Otomatis gagal: {msg}")
        QMessageBox.warning(self, "Atur Otomatis", f"Atur Otomatis gagal:\n\n{msg}\n\n"
                            "Pastikan halaman PEMBAHASAN terbuka di browser (layar penuh) dengan Tipe Soal dan "
                            "seluruh Daftar Soal terlihat, lalu coba lagi.")

    def _on_setup_done(self, res):
        self._restore_after_setup()
        from dataclasses import asdict
        dlg = SetupResultDialog(self, res)
        if dlg.exec() != QDialog.Accepted or dlg.choice is None:
            self.log_event("Hasil Atur Otomatis tidak dipakai", "warn")
            return
        prev = self.settings["auto"] or {}
        self.settings["crop"] = dict(res.crop)
        self.settings["auto"] = {"sections": [[c, n] for c, n in res.counts.items()],
                                 "global": bool(prev.get("global")), "nav": asdict(res.nav),
                                 "wait_load": float(prev.get("wait_load", 1.5))}
        self._refresh_crop_label()
        total = sum(res.counts.values())
        self.set_banner(f"✔ Atur Otomatis tersimpan: {total} soal. Tekan F10 untuk mulai/berhenti.", "ok")
        self.log_event(f"Atur Otomatis tersimpan: {res.counts}", "ok")
        if dlg.choice == "start":
            self.toggle_auto()

    def toggle_auto(self):
        """F10: mulai Tangkap Otomatis dengan pengaturan terakhir, atau hentikan bila sedang berjalan.

        Belum pernah diatur -> jalankan Atur Otomatis dulu."""
        if self.auto_running or self.setup_running:
            self.auto_stop.set()
            self.log_event("F10: menghentikan…", "warn")
            return
        if self.driver_factory is None:
            return self.error("Tangkap Otomatis hanya tersedia di Windows.")
        saved = self.settings["auto"] or {}
        try:
            nav = NavConfig(**{k: v for k, v in (saved.get("nav") or {}).items()
                               if k in NavConfig.__dataclass_fields__})
            sections = [s_ for s_ in (saved.get("sections") or []) if s_[1]]
            plan = Plan(sections=sections, global_numbering=bool(saved.get("global")))   # semua soal
            if not sections or not plan.entries():
                raise AutoCaptureError("rencana belum diatur")
            nav.validate([c for c, _ in sections])
        except (AutoCaptureError, TypeError, ValueError) as exc:
            self.log_event(f"F10: pengaturan belum lengkap ({exc}) — menjalankan Atur Otomatis", "warn")
            return self.run_auto_setup()
        c = self.settings["crop"] or {}
        if not (c.get("rect") and c.get("screen")):
            self.log_event("F10: area belum diatur — menjalankan Atur Otomatis", "warn")
            return self.run_auto_setup()
        self.log_event("F10: Tangkap Otomatis dimulai", "ok")
        self.start_auto_capture(plan, nav, float(saved.get("wait_load", 1.5)))

    # ---------- hotkey global F10 (Windows)
    HOTKEY_ID = 0xB10

    def _register_hotkey(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            if getattr(self, "_hotkey_hwnd", None):
                u.UnregisterHotKey(self._hotkey_hwnd, self.HOTKEY_ID)
            hwnd = int(self.winId())
            ok = u.RegisterHotKey(hwnd, self.HOTKEY_ID, 0x4000, 0x79)   # MOD_NOREPEAT, VK_F10
            self._hotkey_hwnd = hwnd if ok else None
            if not ok:
                self.log_event("F10 tidak bisa didaftarkan (dipakai aplikasi lain). Pakai tombol di aplikasi.",
                               "warn")
        except Exception as exc:  # noqa: BLE001
            self._hotkey_hwnd = None
            log.warning("Gagal mendaftarkan F10: %s", exc)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) == b"windows_generic_MSG":
            try:
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and msg.wParam == self.HOTKEY_ID:   # WM_HOTKEY
                    QTimer.singleShot(0, self.toggle_auto)
                    return True, 0
            except Exception:  # noqa: BLE001
                pass
        return super().nativeEvent(event_type, message)

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32" and getattr(self, "_hotkey_hwnd", None) != int(self.winId()):
            self._register_hotkey()

    def _on_auto_progress(self, msg: str):
        self.log_event(msg)
        self.setWindowTitle(f"{APP_NAME} — OTOMATIS {msg.strip()[:60]}")

    def _on_auto_finished(self, rep, crash: str | None = None):
        self.auto_running = False
        if self._pending_installer:
            QTimer.singleShot(5000, self._install_when_idle)
        self.centralWidget().setEnabled(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.watcher.start(self.ed_folder.text(), reset=False)
        self._thumbs.clear()
        self.refresh_table()
        if rep is None:
            self.error(f"Tangkap Otomatis berhenti karena kesalahan: {crash}")
            return
        if rep.crop:                                   # area diperlebar agar tidak terpotong: simpan
            self.settings["crop"] = dict(rep.crop)
            self._refresh_crop_label()
            self.log_event(f"Area potong diperbaiki & disimpan: {rep.crop['rect']}", "ok")
        speed = (f" · {rep.seconds / rep.captured:.2f} dtk/soal" if rep.captured else "")
        if rep.captured:
            n = rep.captured
            self.log_event(f"Rincian per soal: website memuat {rep.t_load / n:.2f} dtk · scroll "
                           f"{rep.t_scroll / n:.2f} dtk · aplikasi {rep.t_app / n:.2f} dtk "
                           f"(total {rep.seconds:.0f} dtk untuk {n} soal)", "ok")
        status = ("dihentikan (ESC / pojok layar)" if rep.stopped else
                  f"BERHENTI: {rep.aborted}" if rep.aborted else "SELESAI")
        kind = "ok" if not rep.aborted and not rep.stopped else "warn"
        self.set_banner(f"Tangkap Otomatis {status} — {len(rep.done)} soal tersimpan"
                        + (f", {len(rep.problems)} perlu dicek" if rep.problems else ""), kind)
        self.log_event(f"Tangkap Otomatis {status}: {len(rep.done)} soal", kind)
        for name, msg in rep.problems:
            self.log_event(f"Perlu dicek {name}: {msg}", "warn")
        text = f"Status: {status}\nTersimpan: {len(rep.done)} soal ({rep.captured} diambil sesi ini{speed})"
        if rep.captured:
            n = rep.captured
            text += (f"\nWaktu: {rep.seconds:.0f} dtk total — per soal: website memuat {rep.t_load / n:.2f} · "
                     f"scroll {rep.t_scroll / n:.2f} · aplikasi {rep.t_app / n:.2f} dtk")
        if rep.done:
            text += f" ({rep.done[0]} … {rep.done[-1]})"
        if rep.problems:
            text += "\n\nPerlu dicek:\n" + "\n".join(f"• {n}: {m}" for n, m in rep.problems[:25])
        QMessageBox.information(self, "Tangkap Otomatis", text)

    # ============================================================ sources
    def _on_watch_status(self, active: bool, msg: str):
        self.lbl_watch.setText("● MEMANTAU" if active else "● BERHENTI")
        self.lbl_watch.setStyleSheet("font-weight:bold; font-size:14px; color:%s"
                                     % ("#0a8a2a" if active else "#b00"))
        self.log_event(msg, "info" if active else "err")
        if not active and "tidak ditemukan" in msg:
            self.set_banner(f"⚠ {msg}. Klik “Ganti Folder…” untuk memilih folder Screenshots.", "warn")

    def start_watching(self, folder: str):
        self.ed_folder.setText(folder)
        self.settings["watch_folder"] = folder
        if not Path(folder).is_dir():
            ans = QMessageBox.question(
                self, APP_NAME, f"Folder belum ada:\n{folder}\n\nBuat folder ini sekarang?")
            if ans == QMessageBox.Yes:
                try:
                    Path(folder).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    self.error(f"Tidak bisa membuat folder: {exc}")
        self.watcher.start(folder)

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Pilih folder Screenshots", self.ed_folder.text())
        if d:
            self.start_watching(os.path.normpath(d))

    def refresh_folder(self):
        n = self.watcher.refresh()
        self.log_event(f"Refresh: {n} file baru ditemukan" if n else "Refresh: tidak ada file baru")
        if n == 0:
            self.set_banner("Refresh selesai — tidak ada screenshot baru di folder.", "info")

    def pick_files(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih screenshot", self.ed_folder.text(),
                                                f"Gambar ({exts})")
        for f in files:
            self.watcher.mark_seen(f)
            self.handle_incoming(f, "manual")

    def paste_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            return self.error("Clipboard tidak berisi gambar")
        d = self.pkg.root / "_clipboard"
        d.mkdir(exist_ok=True)
        path = d / f"clipboard-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
        if not img.save(str(path), "PNG"):
            return self.error("Gagal menyimpan gambar dari clipboard")
        self.handle_incoming(str(path), "clipboard")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and Path(p).suffix.lower() in IMAGE_EXTS:
                self.watcher.mark_seen(p)
                self.handle_incoming(p, "drag&drop")

    def set_on_top(self, on: bool):
        self.settings["always_on_top"] = on
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)   # membuat ulang jendela (hwnd baru)
        self.show()
        self._register_hotkey()

    # ============================================================ list
    def _thumb(self, item: Item) -> QPixmap:
        pm = self._thumbs.get(item.id + item.relpath)
        if pm is None:
            reader = QImageReader(str(self.pkg.path_of(item)))
            sz = reader.size()
            if sz.isValid():
                reader.setScaledSize(sz.scaled(THUMB, Qt.KeepAspectRatio))
            pm = QPixmap.fromImage(reader.read())
            self._thumbs[item.id + item.relpath] = pm
        return pm

    def refresh_table(self, select_id: str | None = None):
        keep = {i.id for i in self.selected_items()} if select_id is None else {select_id}
        items = self.pkg.sorted_items()
        self.table.setRowCount(len(items))
        missing = {i.id for i in self.pkg.missing_files()}
        for r, it in enumerate(items):
            c0 = QTableWidgetItem()
            if it.id not in missing:
                c0.setIcon(QIcon(self._thumb(it)))
            else:
                c0.setText("HILANG")
            c0.setData(Qt.UserRole, it.id)
            cells = [c0, QTableWidgetItem(it.category or "—"),
                     QTableWidgetItem(str(it.number) if it.number else "—"),
                     QTableWidgetItem(it.display_name),
                     QTableWidgetItem(str(it.parts)),
                     self._figure_cell(it),
                     QTableWidgetItem(Path(it.source).name),
                     QTableWidgetItem(it.received_at.replace("T", " "))]
            cells[6].setToolTip(it.source)
            f = QFont()
            f.setBold(True)
            cells[3].setFont(f)
            if not it.assigned:
                for c in cells:
                    c.setBackground(QColor("#fff1c9"))
            for col, c in enumerate(cells):
                self.table.setItem(r, col, c)
        self.table.clearSelection()
        for r, it in enumerate(items):
            if it.id in keep:
                self.table.selectRow(r)
                if it.id == select_id:
                    self.table.scrollToItem(self.table.item(r, 0))
        counts = self.pkg.counts()
        unassigned = sum(1 for i in self.pkg.items if not i.assigned)
        parts = " · ".join(f"{c} {n}" for c, n in counts.items())
        figural = sum(1 for i in self.pkg.items if i.assigned and i.figures)
        self.lbl_counts.setText(parts + (f" · belum: {unassigned}" if unassigned else "")
                                + (f" · 🖼 {figural}" if figural else ""))
        self.lbl_list.setText(f"Screenshot diterima — {self.pkg.name} ({len(items)} gambar)")
        self._update_capture_labels()
        self._update_preview()

    def selected_items(self) -> list[Item]:
        if self.pkg is None:
            return []
        out = []
        for r in sorted({i.row() for i in self.table.selectedIndexes()}):
            cell = self.table.item(r, 0)
            if cell is None:
                continue
            try:
                out.append(self.pkg.get(cell.data(Qt.UserRole)))
            except ManagerError:
                pass
        return out

    def _update_preview(self):
        sel = self.selected_items()
        if not sel:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Pilih baris untuk melihat preview")
            self.preview_info.setText("")
            return
        it = sel[0]
        path = self.pkg.path_of(it)
        pm = QPixmap(str(path))
        if pm.isNull():
            self.preview.setText("File tidak ditemukan")
        else:
            if it.figures or it.figure_hint:               # tandai potongan gambar
                p = QPainter(pm)
                for f, col, style in ([(it.figures[0], "#6f42c1", Qt.SolidLine)] if it.figures else
                                      [(it.figure_hint, "#b35c00", Qt.DashLine)]):
                    p.setPen(QPen(QColor(col), max(3, pm.width() // 250), style))
                    p.drawRect(QRect(f["x"], f["y"], f["w"], f["h"]))
                p.end()
            self.preview.setPixmap(pm.scaled(self.preview.size() - QSize(8, 8),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation))
        figs = (f"<br>🖼 <b>Soal bergambar</b> → gambar/{it.filename} (kotak ungu)" if it.figures else
                "<br>✂ <b>Perlu dipotong manual</b> (gambar di pilihan jawaban)" if it.figure_manual else "")
        self.preview_info.setText(f"<b>{it.display_name}</b><br>{it.width}×{it.height}px{figs}<br>"
                                  f"Workspace: {path}<br>Asli: {it.source}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._update_preview)

    def _on_double_click(self, row: int, col: int):
        items = self.selected_items()
        if not items:
            return
        if col == 0:
            PreviewDialog(self, self.pkg.path_of(items[0]), items[0].display_name).exec()
        else:
            self.edit_selected()

    def edit_selected(self):
        sel = self.selected_items()
        if not sel:
            return self.error("Pilih satu baris di daftar terlebih dahulu")
        item = sel[0]
        dlg = EditItemDialog(self, self.pkg, item)
        if dlg.exec() != QDialog.Accepted:
            return
        cat, num = dlg.values()
        old = item.display_name
        try:
            try:
                self.pkg.assign(item.id, cat, num)
            except SlotTakenError as exc:
                box = QMessageBox(self)
                box.setWindowTitle("Nomor sudah dipakai")
                box.setText(f"{exc.occupant.filename} sudah dipakai gambar lain.\n\n"
                            "Tukar: kedua gambar bertukar nomor.\n"
                            "Ganti: gambar lama dikeluarkan dari daftar (dicadangkan di _diganti).")
                b_swap = box.addButton("Tukar", QMessageBox.AcceptRole)
                b_rep = box.addButton("Ganti", QMessageBox.DestructiveRole)
                box.addButton("Batal", QMessageBox.RejectRole)
                box.exec()
                clicked = box.clickedButton()
                if clicked is b_swap:
                    self.pkg.assign(item.id, cat, num, on_conflict="swap")
                elif clicked is b_rep:
                    self.pkg.assign(item.id, cat, num, on_conflict="replace")
                else:
                    return
        except (ManagerError, OSError) as exc:
            return self.error(f"Gagal mengubah: {exc}")
        self.log_event(f"Diubah: {old} → {item.filename}", "ok")
        self.set_banner(f"✔ Diubah: {old} → {item.filename}", "ok")
        self.refresh_table(select_id=item.id)

    def delete_selected(self):
        sel = self.selected_items()
        if not sel:
            return
        names = ", ".join(i.display_name for i in sel[:6]) + ("…" if len(sel) > 6 else "")
        if QMessageBox.question(self, "Hapus dari daftar",
                                f"Hapus {len(sel)} gambar dari daftar?\n{names}\n\n"
                                "Salinan di workspace dihapus. File screenshot ASLI tetap aman.") \
                != QMessageBox.Yes:
            return
        for it in sel:
            self.pkg.remove(it.id)
            self.watcher.mark_seen(it.source)
            self.log_event(f"Dihapus dari daftar: {it.display_name}", "warn")
        self.refresh_table()

    def renumber(self):
        cats = ["Semua kategori"] + self.pkg.categories
        choice, ok = QInputDialog.getItem(
            self, "Ulangi Penamaan",
            "Nomori ulang menjadi 1, 2, 3, … sesuai urutan nomor saat ini.\nKategori:", cats, 0, False)
        if not ok:
            return
        try:
            n = self.pkg.renumber(None if choice == cats[0] else choice)
        except (ManagerError, OSError) as exc:
            return self.error(f"Gagal menomori ulang: {exc}")
        self._thumbs.clear()
        self.select_category(self.current_category())
        self.refresh_table()
        self.log_event(f"Ulangi penamaan ({choice}): {n} file diganti namanya", "ok")
        self.set_banner(f"✔ Penamaan diulang ({choice}): {n} file diganti namanya", "ok")

    # ============================================================ zip
    def make_zip(self):
        unassigned = sum(1 for i in self.pkg.items if not i.assigned)
        if unassigned and QMessageBox.question(
                self, "BUAT ZIP", f"{unassigned} gambar belum punya kategori/nomor dan TIDAK akan "
                                  "masuk ZIP.\nLanjutkan?") != QMessageBox.Yes:
            return
        if self.chk_figural.isChecked():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for it in self.pkg.items:
                    if it.assigned:
                        self.pkg.update_figures(it.id)
            finally:
                QApplication.restoreOverrideCursor()
            if any(it.assigned and (it.figures or it.figure_manual) for it in self.pkg.items):
                if FigurePreviewDialog(self, for_export=True).exec() != QDialog.Accepted:
                    return
                self._thumbs.clear()
                self.refresh_table()
        start_dir = self.settings["zip_dir"] or str(Path.home() / "Downloads")
        dest, _ = QFileDialog.getSaveFileName(self, "Simpan ZIP",
                                              str(Path(start_dir) / f"{self.pkg.name}.zip"),
                                              "Arsip ZIP (*.zip)")
        if not dest:
            return
        try:
            self.settings["zip_figural"] = self.chk_figural.isChecked()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                res = self.pkg.export_zip(dest, figural=self.chk_figural.isChecked())
            finally:
                QApplication.restoreOverrideCursor()
        except (ManagerError, OSError) as exc:
            return self.error(f"ZIP gagal: {exc}")
        self.settings["zip_dir"] = str(res.path.parent)
        detail = ", ".join(f"{c}: {n}" for c, n in res.counts.items())
        self.set_banner(f"✔ ZIP dibuat: {res.path.name} — {res.total} gambar ({detail})", "ok")
        self.log_event(f"ZIP dibuat: {res.path} ({detail})", "ok")
        box = QMessageBox(self)
        box.setWindowTitle("ZIP berhasil dibuat")
        box.setText(f"{res.path}\n\n{res.total} gambar: {detail}"
                    + ("\n📄 PROMPT.txt + daftar.json ikut di dalam ZIP — kirim ZIP + isi PROMPT.txt ke ChatGPT"
                       if self.chk_figural.isChecked() else "")
                    + (f"\n🖼 {res.figural} soal bergambar → gambar/" if res.figural else "")
                    + (f"\n⚠ {res.manual_pending} soal perlu dipotong manual (belum masuk gambar/)"
                       if res.manual_pending else "")
                    + (f"\n{res.skipped_unassigned} gambar tanpa nomor dilewati." if res.skipped_unassigned else ""))
        b_open = box.addButton("Buka Folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is b_open:
            self.open_path(res.path.parent)

    # ============================================================ update
    def check_updates(self, silent: bool):
        if not silent:
            self.btn_update.setEnabled(False)
            self.btn_update.setText("Memeriksa…")
        self.updates.check(silent)

    def _reset_update_button(self):
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Periksa Update")

    def _on_update_failed(self, msg: str, silent: bool):
        self._reset_update_button()
        self.log_event(f"Cek update gagal: {msg}", "warn" if not silent else "info")
        if not silent:
            QMessageBox.warning(self, "Periksa Update", f"Tidak bisa memeriksa update.\n\n{msg}")

    def _auto_update_on(self) -> bool:
        return self.settings["auto_update"] is not False

    def _on_update_checked(self, info, silent: bool):
        self._reset_update_button()
        if not updater.is_newer(info.version):
            self.log_event(f"Aplikasi sudah versi terbaru ({__version__})")
            if not silent:
                QMessageBox.information(self, "Periksa Update",
                                        f"Anda sudah memakai versi terbaru ({__version__}).")
            return
        can_install = updater.can_self_install() and info.asset_url
        if can_install and self._auto_update_on():
            # update otomatis: unduh di latar belakang, pasang saat aplikasi menganggur — tanpa dialog
            if self._update_downloading or self._pending_installer:
                return
            self._update_downloading = True
            self._update_version = info.version
            self.btn_update.setText(f"Mengunduh {info.version}…")
            self.log_event(f"Versi baru {info.version}: diunduh & dipasang otomatis", "ok")
            self.updates.download(info)
            return
        if silent and self.settings["skip_version"] == info.version:
            return
        self.btn_update.setText(f"Update {info.version} tersedia!")
        self.btn_update.setStyleSheet("background:#d9a400; font-weight:bold")
        self.log_event(f"Versi baru tersedia: {info.version}", "warn")
        notes = info.notes[:1500] or "(tanpa catatan rilis)"
        box = QMessageBox(self)
        box.setWindowTitle("Update tersedia")
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>Screenshot Manager {info.version}</b> tersedia "
                    f"(terpasang: {__version__}).<br><br>Data paket & screenshot Anda tetap aman.")
        box.setDetailedText(notes)
        b_install = box.addButton("Unduh && Pasang" if can_install else "Buka Halaman Unduhan",
                                  QMessageBox.AcceptRole)
        box.addButton("Nanti", QMessageBox.RejectRole)
        b_skip = box.addButton("Lewati Versi Ini", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_skip:
            self.settings["skip_version"] = info.version
        elif clicked is b_install:
            if can_install:
                self._start_update_download(info)
            else:
                QDesktopServices.openUrl(QUrl(info.page_url))

    def _busy(self) -> bool:
        return bool(self.auto_running or self.setup_running or QApplication.activeModalWidget()
                    or QApplication.activePopupWidget())

    def _install_when_idle(self):
        """Pasang installer yang sudah diunduh begitu aplikasi tidak sedang bekerja."""
        path = self._pending_installer
        if not path:
            return
        if self._busy():
            QTimer.singleShot(30_000, self._install_when_idle)
            return
        self.set_banner(f"⟳ Memasang update {self._update_version}… aplikasi akan terbuka lagi sendiri.", "info")
        self.log_event(f"Memasang update {self._update_version} otomatis", "ok")

        def go():
            if self._busy():                       # mulai bekerja dalam 3 detik terakhir: tunda lagi
                QTimer.singleShot(30_000, self._install_when_idle)
                return
            try:
                updater.launch_installer(Path(path))
            except OSError as exc:
                self._pending_installer = None
                return self.error(f"Tidak bisa menjalankan installer: {exc}")
            self.close()
            QApplication.instance().quit()
        QTimer.singleShot(3000, go)

    def _start_update_download(self, info):
        dlg = QProgressDialog(f"Mengunduh {info.asset_name}…", "Batal", 0, 100, self)
        dlg.setWindowTitle("Update")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.canceled.connect(lambda: setattr(self.updates, "cancel_flag", True))
        dlg.show()
        self._update_dialog = dlg
        self.updates.download(info)

    def _on_update_progress(self, done: int, total: int):
        if self._update_dialog is not None and total:
            self._update_dialog.setValue(int(done * 100 / total))
            self._update_dialog.setLabelText(f"Mengunduh… {done / 1e6:.1f} / {total / 1e6:.1f} MB")

    def _close_update_dialog(self):
        if self._update_dialog is not None:
            self._update_dialog.reset()
            self._update_dialog.close()
            self._update_dialog = None

    def _on_update_download_failed(self, msg: str):
        self._close_update_dialog()
        if self._update_downloading:               # mode otomatis: coba lagi pada pengecekan berikutnya
            self._update_downloading = False
            self._reset_update_button()
            self.log_event(f"Unduh update gagal, dicoba lagi nanti: {msg}", "warn")
            return
        self.error(f"Update gagal: {msg}")

    def _on_update_downloaded(self, path: str):
        self._close_update_dialog()
        self.log_event(f"Installer diunduh: {path}", "ok")
        if self._update_downloading:               # mode otomatis: pasang saat menganggur, tanpa bertanya
            self._update_downloading = False
            self._pending_installer = path
            self.btn_update.setText(f"Update {self._update_version} siap")
            self._install_when_idle()
            return
        if QMessageBox.question(self, "Pasang update",
                                "Installer siap. Aplikasi akan ditutup, update dipasang, lalu "
                                "aplikasi dibuka kembali otomatis.\n\nLanjutkan sekarang?") \
                != QMessageBox.Yes:
            return
        try:
            updater.launch_installer(Path(path))
        except OSError as exc:
            return self.error(f"Tidak bisa menjalankan installer: {exc}")
        self.close()
        QApplication.instance().quit()

    def open_import_dialog(self):
        ImportDialog(self).exec()

    def closeEvent(self, e):
        if self.auto_running:
            self.auto_stop.set()
        if sys.platform == "win32" and getattr(self, "_hotkey_hwnd", None):
            try:
                import ctypes
                ctypes.windll.user32.UnregisterHotKey(self._hotkey_hwnd, self.HOTKEY_ID)
            except Exception:  # noqa: BLE001
                pass
        self.watcher.stop()
        super().closeEvent(e)


# ---------------------------------------------------------------- entry

def _setup_logging():
    logfile = config_dir() / "screenshot-manager.log"
    handler = logging.FileHandler(logfile, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    # selalu tema terang: warna status/log dirancang untuk latar terang (mode gelap Windows
    # membuat teks log & nama target sulit dibaca)
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:   # Qt < 6.8
        pass
    app.setPalette(app.style().standardPalette())
    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        log.error("Unhandled error:\n%s", text)
        QMessageBox.critical(None, APP_NAME, f"Terjadi kesalahan tak terduga:\n{value}\n\n"
                             f"Detail tercatat di {config_dir() / 'screenshot-manager.log'}")
    sys.excepthook = excepthook

    win = MainWindow()
    win.show()
    return app.exec()
