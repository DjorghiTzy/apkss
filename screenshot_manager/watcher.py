"""Pemantau folder screenshot.

Dua lapis deteksi agar tidak ada screenshot yang terlewat:
  1. watchdog (event created/moved/modified) -> respon instan.
  2. pemindaian berkala (polling) sebagai cadangan, mis. folder OneDrive
     atau jaringan yang tidak selalu mengirim event.

Setiap kandidat baru diserahkan setelah file "stabil": ukuran & waktu ubah
tidak berubah di dua pemeriksaan berturut-turut dan gambar bisa di-decode
penuh oleh Pillow. Ini mencegah memproses file yang masih ditulis.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .core import ManagerError, is_image_path, load_image

CHECK_INTERVAL_MS = 350
POLL_EVERY_TICKS = 6          # pemindaian cadangan ~ tiap 2 detik
GIVE_UP_SECONDS = 60          # file yang tidak pernah valid dibuang dari antrean
MIN_AGE_SECONDS = 0.3


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class _Handler(FileSystemEventHandler):
    def __init__(self, sink):
        self._sink = sink

    def on_created(self, event):
        if not event.is_directory:
            self._sink(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._sink(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._sink(event.dest_path)


class FolderWatcher(QObject):
    fileReady = Signal(str)        # path gambar yang sudah selesai disimpan
    fileRejected = Signal(str, str)  # path, alasan
    statusChanged = Signal(bool, str)  # aktif?, pesan

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder: Path | None = None
        self._observer: Observer | None = None
        self._lock = threading.Lock()
        self._incoming: set[str] = set()                 # diisi thread watchdog
        self._pending: dict[str, dict] = {}              # key -> info stabilitas
        self._seen: dict[str, tuple[int, int]] = {}      # key -> (size, mtime_ns) sudah diproses
        self._since = time.time()
        self._ticks = 0
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------ control
    @property
    def active(self) -> bool:
        return self._observer is not None or self._timer.isActive()

    def start(self, folder: str | os.PathLike, reset: bool = True) -> None:
        """Mulai memantau. reset=False: lanjutkan sesi (file yang masuk selama
        pemantauan berhenti tetap dianggap baru)."""
        new_folder = self.folder is None or _key(str(folder)) != _key(str(self.folder))
        self.stop()
        self.folder = Path(folder)
        if not self.folder.is_dir():
            self.statusChanged.emit(False, f"Folder tidak ditemukan: {self.folder}")
            return
        if reset or new_folder:
            self._since = time.time()
            self._snapshot_existing()
        try:
            obs = Observer()
            obs.schedule(_Handler(self._enqueue), str(self.folder), recursive=False)
            obs.daemon = True
            obs.start()
            self._observer = obs
            msg = f"Memantau: {self.folder}"
        except Exception as exc:  # noqa: BLE001
            self._observer = None
            msg = f"Memantau (mode polling): {self.folder} — {exc}"
        self._timer.start()
        self.statusChanged.emit(True, msg)

    def stop(self) -> None:
        self._timer.stop()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            self._observer = None
        with self._lock:
            self._incoming.clear()
        self._pending.clear()
        if self.folder is not None:
            self.statusChanged.emit(False, "Pemantauan berhenti")

    def refresh(self) -> int:
        """Pindai ulang folder sekarang; kembalikan jumlah kandidat baru."""
        if self.folder is None or not self.folder.is_dir():
            return 0
        if not self._timer.isActive():
            self.start(self.folder, reset=False)
        return self._scan()

    def mark_seen(self, path: str) -> None:
        sig = self._signature(path)
        if sig:
            self._seen[_key(path)] = sig

    # ------------------------------------------------------------ internals
    @staticmethod
    def _signature(path: str):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _snapshot_existing(self) -> None:
        """File lama di folder dianggap sudah ada; hanya file baru yang diproses."""
        try:
            with os.scandir(self.folder) as it:
                for entry in it:
                    if entry.is_file() and is_image_path(entry.name):
                        st = entry.stat()
                        self._seen.setdefault(_key(entry.path), (st.st_size, st.st_mtime_ns))
        except OSError:
            pass

    def _enqueue(self, path: str) -> None:  # dipanggil dari thread watchdog
        if is_image_path(path):
            with self._lock:
                self._incoming.add(path)

    def _scan(self) -> int:
        found = 0
        try:
            with os.scandir(self.folder) as it:
                for entry in it:
                    if not entry.is_file() or not is_image_path(entry.name):
                        continue
                    k = _key(entry.path)
                    st = entry.stat()
                    sig = (st.st_size, st.st_mtime_ns)
                    if self._seen.get(k) == sig or k in self._pending:
                        continue
                    if k in self._seen or st.st_mtime >= self._since - 2:
                        self._pending[k] = {"path": entry.path, "sig": None, "first": time.time()}
                        found += 1
        except OSError:
            pass
        return found

    def _tick(self) -> None:
        with self._lock:
            incoming, self._incoming = self._incoming, set()
        for path in incoming:
            k = _key(path)
            if k not in self._pending:
                self._pending[k] = {"path": path, "sig": None, "first": time.time()}

        self._ticks += 1
        if self._ticks % POLL_EVERY_TICKS == 0:
            if self.folder is not None and not self.folder.is_dir():
                self.statusChanged.emit(False, f"Folder hilang: {self.folder}")
            else:
                self._scan()

        now = time.time()
        for k, info in list(self._pending.items()):
            path = info["path"]
            sig = self._signature(path)
            if sig is None:                       # file dihapus/diganti nama
                self._pending.pop(k, None)
                continue
            if self._seen.get(k) == sig:          # sudah diproses, event susulan
                self._pending.pop(k, None)
                continue
            if sig[0] == 0 or sig != info["sig"] or now - sig[1] / 1e9 < MIN_AGE_SECONDS:
                info["sig"] = sig                 # masih ditulis, tunggu tick berikutnya
                if now - info["first"] > GIVE_UP_SECONDS:
                    self._pending.pop(k, None)
                    self.fileRejected.emit(path, "file tidak kunjung selesai disimpan")
                continue
            try:
                load_image(path)
            except ManagerError as exc:
                if now - info["first"] > GIVE_UP_SECONDS:
                    self._pending.pop(k, None)
                    self._seen[k] = sig
                    self.fileRejected.emit(path, str(exc))
                continue
            self._pending.pop(k, None)
            self._seen[k] = sig
            self.fileReady.emit(path)
