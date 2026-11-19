"""Jendela utama Screenshot Manager (PySide6)."""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImageReader,
                           QKeySequence, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QRadioButton, QSizePolicy, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
                               QCheckBox)

from . import __version__
from .core import (DuplicateImageError, IMAGE_EXTS, Item, ManagerError, Package,
                   SlotTakenError, list_packages, make_filename, sanitize_package_name)
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
                     "package": "Paket-01", "always_on_top": False, "zip_dir": ""}
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.pkg: Package | None = None
        self.armed = False
        self.redo_restore: tuple[str, int] | None = None   # (kategori, nomor) setelah "Ulangi Nomor"
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
        self.start_watching(self.settings["watch_folder"])
        self.set_banner("Siap. Atur paket, kategori, dan nomor lalu klik “Siapkan Screenshot Berikutnya”.",
                        "info")

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
        top.addWidget(self.lbl_watch)
        top.addWidget(QLabel("Folder Screenshots:"))
        top.addWidget(self.ed_folder, 1)
        for w in (btn_folder, btn_refresh, btn_manual, btn_clip, self.chk_top):
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
        split.addWidget(self._build_capture_panel())
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
        lay.addStretch(1)
        return panel

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 0, 6, 0)
        self.lbl_list = QLabel("Screenshot diterima")
        self.lbl_list.setStyleSheet("font-weight:bold")
        lay.addWidget(self.lbl_list)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Preview", "Kategori", "Nomor", "Nama File",
                                              "File Asli", "Diterima"])
        self.table.setIconSize(THUMB)
        self.table.verticalHeader().setDefaultSectionSize(THUMB.height() + 8)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
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
        b_ws = QPushButton("Buka Workspace")
        b_ws.clicked.connect(lambda: self.open_path(self.pkg.root))
        for b in (b_edit, b_del, b_ren, b_ws):
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
        if self.armed:
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
        was = self.armed
        self.armed = False
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
        try:
            if self.armed:
                cat, num = self.target()
                res = self.pkg.add_image(path, cat, num)
            else:
                res = self.pkg.add_image(path)
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
            msg = f"✔ DITERIMA: {item.filename}{replaced}  ←  {name}"
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
        self.refresh_table(select_id=item.id)

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
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

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
                     QTableWidgetItem(Path(it.source).name),
                     QTableWidgetItem(it.received_at.replace("T", " "))]
            cells[4].setToolTip(it.source)
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
        self.lbl_counts.setText(parts + (f" · belum: {unassigned}" if unassigned else ""))
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
            self.preview.setPixmap(pm.scaled(self.preview.size() - QSize(8, 8),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview_info.setText(f"<b>{it.display_name}</b><br>{it.width}×{it.height}px<br>"
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
        start_dir = self.settings["zip_dir"] or str(Path.home() / "Downloads")
        dest, _ = QFileDialog.getSaveFileName(self, "Simpan ZIP",
                                              str(Path(start_dir) / f"{self.pkg.name}.zip"),
                                              "Arsip ZIP (*.zip)")
        if not dest:
            return
        try:
            res = self.pkg.export_zip(dest)
        except (ManagerError, OSError) as exc:
            return self.error(f"ZIP gagal: {exc}")
        self.settings["zip_dir"] = str(res.path.parent)
        detail = ", ".join(f"{c}: {n}" for c, n in res.counts.items())
        self.set_banner(f"✔ ZIP dibuat: {res.path.name} — {res.total} gambar ({detail})", "ok")
        self.log_event(f"ZIP dibuat: {res.path} ({detail})", "ok")
        box = QMessageBox(self)
        box.setWindowTitle("ZIP berhasil dibuat")
        box.setText(f"{res.path}\n\n{res.total} gambar: {detail}"
                    + (f"\n{res.skipped_unassigned} gambar tanpa nomor dilewati." if res.skipped_unassigned else ""))
        b_open = box.addButton("Buka Folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is b_open:
            self.open_path(res.path.parent)

    def closeEvent(self, e):
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
    app.setStyle("Fusion")
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
