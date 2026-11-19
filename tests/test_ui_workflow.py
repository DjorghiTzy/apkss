"""Simulasi alur kerja Claude end-to-end pada jendela asli (Qt offscreen)."""
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402


def png_bytes(color, size=(800, 500)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def slow_write(path: Path, data: bytes, chunks=5, delay=0.15):
    """Meniru Snipping Tool yang menulis file bertahap."""
    with open(path, "wb") as fh:
        step = len(data) // chunks + 1
        for i in range(0, len(data), step):
            fh.write(data[i:i + step])
            fh.flush()
            os.fsync(fh.fileno())
            time.sleep(delay)


def wait_until(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return False


@pytest.fixture
def win(tmp_path, monkeypatch):
    home = tmp_path / "home"
    shots = home / "Pictures" / "Screenshots"
    shots.mkdir(parents=True)
    Image.new("RGB", (10, 10), "gray").save(shots / "old-existing.png")  # file lama: diabaikan
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    cfg = home / ".config" / "ScreenshotManager"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text(json.dumps({"watch_folder": str(shots),
                                                   "workspace": str(home / "ws")}))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    app = QApplication.instance() or QApplication([])
    from screenshot_manager.app import MainWindow
    w = MainWindow()
    w.show()
    w._shots = shots
    yield w
    w.close()
    app.processEvents()


def names(w):
    return sorted(i.filename for i in w.pkg.items)


def test_claude_workflow(win, tmp_path, monkeypatch):
    w, shots = win, win._shots
    assert w.watcher.active and w.lbl_watch.text() == "● MEMANTAU"
    assert w.pkg.name == "Paket-01"

    # Paket-01, TWK, nomor 1, otomatis
    w.select_category("TWK")
    w.set_number(1)
    assert w.rb_auto.isChecked()
    w.arm()
    assert w.armed and w.lbl_target.text() == "TWK-001.png"

    slow_write(shots / "Screenshot 2026-11-19 100001.png", png_bytes("red"))
    assert wait_until(lambda: len(w.pkg.items) == 1)
    assert names(w) == ["TWK-001.png"]
    assert "DITERIMA: TWK-001.png" in w.banner.text()
    assert w.spin.value() == 2 and w.armed                      # nomor otomatis jadi 2

    slow_write(shots / "Screenshot 2026-11-19 100002.png", png_bytes("blue"))
    assert wait_until(lambda: len(w.pkg.items) == 2)

    # pindah kategori TIU -> nomor TIU mulai 1, TWK diingat 3
    w.select_category("TIU")
    assert w.spin.value() == 1
    (shots / "Screenshot 2026-11-19 100003.jpg").write_bytes(b"")  # file kosong dulu
    time.sleep(0.2)
    Image.new("RGB", (600, 400), "green").save(shots / "Screenshot 2026-11-19 100003.jpg", "JPEG")
    assert wait_until(lambda: len(w.pkg.items) == 3)
    assert names(w) == ["TIU-001.png", "TWK-001.png", "TWK-002.png"]
    w.select_category("TWK")
    assert w.spin.value() == 3

    # duplikat ditolak
    (shots / "duplikat.png").write_bytes(png_bytes("red"))
    assert wait_until(lambda: "DUPLIKAT" in w.banner.text())
    assert len(w.pkg.items) == 3

    # Ulangi Nomor: screenshot berikutnya mengganti TIU-001, lalu kembali ke TWK-003
    w.last_item_id = w.pkg.find_slot("TIU", 1).id
    w.redo_last()
    assert w.lbl_target.text() == "TIU-001.png"
    (shots / "retake.png").write_bytes(png_bytes("yellow"))
    assert wait_until(lambda: "menggantikan" in w.banner.text())
    assert names(w) == ["TIU-001.png", "TWK-001.png", "TWK-002.png"]
    assert w.target() == ("TWK", 3) and w.armed

    # Mode manual + Ubah Nomor: lompat ke TKP-010, tidak auto +1, butuh Siapkan lagi
    w.rb_manual.setChecked(True)
    w.select_category("TKP")
    w.set_number(10)
    w.arm()
    (shots / "tkp.webp").write_bytes(b"")
    Image.new("RGB", (300, 300), "purple").save(shots / "tkp.webp", "WEBP")
    assert wait_until(lambda: w.pkg.find_slot("TKP", 10) is not None)
    assert not w.armed and w.spin.value() == 10

    # tidak siap -> masuk tanpa nomor, lalu ditetapkan
    (shots / "lupa.png").write_bytes(png_bytes("orange"))
    assert wait_until(lambda: "TANPA NOMOR" in w.banner.text())
    un = [i for i in w.pkg.items if not i.assigned]
    assert len(un) == 1
    w.pkg.assign(un[0].id, "TKP", 11)

    # Batalkan
    w.arm()
    w.disarm_clicked()
    assert not w.armed

    # tabel & ZIP
    w.refresh_table()
    assert w.table.rowCount() == 5
    dest = tmp_path / "out" / "Paket-01.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    w.make_zip()
    with zipfile.ZipFile(dest) as zf:
        assert zf.testzip() is None
        assert sorted(zf.namelist()) == ["TIU/TIU-001.png", "TKP/TKP-010.png", "TKP/TKP-011.png",
                                         "TWK/TWK-001.png", "TWK/TWK-002.png"]
        with Image.open(zf.open("TIU/TIU-001.png")) as im:
            assert im.getpixel((0, 0)) == (255, 255, 0)      # hasil ulangi, bukan yang lama

    # file asli tetap ada & tidak berubah jumlahnya
    assert len(list(shots.iterdir())) == 8
    # file lama di folder tidak ikut diimpor
    assert all("old-existing" not in i.source for i in w.pkg.items)


def test_refresh_and_manual_pick(win, monkeypatch):
    w, shots = win, win._shots
    w.watcher.stop()                    # simulasikan event terlewat
    (shots / "terlewat.png").write_bytes(png_bytes("cyan"))
    w.arm()
    w.refresh_folder()
    assert wait_until(lambda: len(w.pkg.items) == 1)
    assert names(w) == ["TWK-001.png"]

    other = shots.parent / "lain.jpg"
    Image.new("RGB", (50, 50), "pink").save(other, "JPEG")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(other)], ""))
    w.pick_files()
    assert names(w) == ["TWK-001.png", "TWK-002.png"]
