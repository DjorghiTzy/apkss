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
def win(isolated_home, monkeypatch):
    home, shots = isolated_home
    Image.new("RGB", (10, 10), "gray").save(shots / "old-existing.png")  # file lama: diabaikan
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    app = QApplication.instance() or QApplication([])
    from screenshot_manager.app import MainWindow
    w = MainWindow()
    w.show()
    assert Path(w.ed_folder.text()) == shots
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


def test_full_screen_crop_and_parts(win, monkeypatch):
    """Alur v1.0.1: Win+PrtScn layar penuh -> dipotong -> pembahasan panjang disambung."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QDialog

    from screenshot_manager import app as appmod
    from tests.test_parts import AREA, long_page, screen_of

    w, shots = win, win._shots

    # 1) atur area dari screenshot acuan (tidak masuk daftar)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    w.waiting_crop_reference = True

    def fake_exec(dlg):
        dlg.canvas.sel = QRect(*AREA)
        return QDialog.Accepted
    monkeypatch.setattr(appmod.CropDialog, "exec", fake_exec)
    screen_of(long_page(seed=3), 0).save(shots / "acuan.png")
    assert wait_until(lambda: w.settings["crop"].get("rect") == AREA)
    assert w.chk_crop.isChecked() and len(w.pkg.items) == 0

    # 2) soal TWK-001: layar penuh -> dipotong
    page = long_page(1500, seed=4)
    w.select_category("TWK")
    w.set_number(1)
    w.arm()
    screen_of(page, 0).save(shots / "p1.png")
    assert wait_until(lambda: len(w.pkg.items) == 1)
    item = w.pkg.items[0]
    assert (item.width, item.height) == (AREA[2], AREA[3]) and "(dipotong)" in w.banner.text()
    assert w.lbl_target.text() == "TWK-002.png"

    # 3) scroll + Tambah Bagian Lanjutan dua kali
    for n, scroll in enumerate([550, 900], start=2):
        w.append_next()
        assert w.lbl_target.text() == f"TWK-001.png + bagian {n}"
        screen_of(page, scroll).save(shots / f"p{n}.png")
        assert wait_until(lambda n=n: item.parts == n)
        assert f"BAGIAN {n} DISAMBUNG" in w.banner.text()
    assert item.height == 1500 and len(w.pkg.items) == 1
    assert w.armed and w.lbl_target.text() == "TWK-002.png"     # kembali ke soal berikutnya

    # 4) lupa scroll -> ditolak, mode lanjutan tetap aktif
    w.append_next()
    screen_of(page, 900).save(shots / "p3-lagi.png")
    assert wait_until(lambda: "sama persis" in w.banner.text())
    assert w.append_target == item.id
    w.disarm_clicked()

    # 5) hapus bagian terakhir dari tabel
    w.refresh_table(select_id=item.id)
    assert w.table.item(0, 4).text() == "3"
    w.remove_last_part()
    assert item.parts == 2 and w.table.item(0, 4).text() == "2"


def test_grab_button_and_auto_capture_in_window(win, monkeypatch):
    from screenshot_manager.autocapture import NavConfig, Plan
    from tests.fake_browser import CROP, GRID, FakeBrowser

    w = win
    b = FakeBrowser({1: 700, 2: 1600, 3: 500, 4: 1200, 5: 600}, px_per_notch=60)
    b.q = 5                                   # halaman lain untuk tes Ambil Layar
    w.screen_grabber = b.grab
    w.driver_factory = lambda: b
    w.settings["crop"] = dict(CROP)
    w._refresh_crop_label()
    info = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: info.append(a[2]))

    # tombol Ambil Layar: jendela sembunyi, layar dipotret, diproses seperti biasa
    w.select_category("TKP")
    w.set_number(9)
    w.arm()
    w._hidden_grab(lambda p: (w.handle_incoming(p, "ambil layar"), Path(p).unlink()), delay_ms=0)
    assert wait_until(lambda: w.pkg.find_slot("TKP", 9) is not None)
    assert w.isVisible() and "(dipotong)" in w.banner.text()

    # Tangkap Otomatis 4 soal lewat grid
    x, y = GRID["first"]
    nav = NavConfig(mode="grid", grid_first=[x, y], grid_second=[x + GRID["dx"], y],
                    grid_below=[x, y + GRID["dy"]], columns=GRID["cols"], per_category=False)
    w.start_auto_capture(Plan(sections=[["TWK", 2], ["TIU", 2]]), nav, 0.0, delay_ms=0)
    assert w.auto_running and not w.centralWidget().isEnabled()
    assert wait_until(lambda: not w.auto_running, timeout=120)
    assert info and "SELESAI" in info[0], info
    assert w.centralWidget().isEnabled() and w.watcher.active
    names_now = sorted(i.filename for i in w.pkg.items)
    assert names_now == ["TIU-001.png", "TIU-002.png", "TKP-009.png", "TWK-001.png", "TWK-002.png"]
    assert w.pkg.find_slot("TWK", 2).height == 1600
    assert w.table.rowCount() == 5


def test_f10_toggle_starts_with_saved_settings_and_stops(win, monkeypatch):
    from dataclasses import asdict

    from tests.fake_browser import CAT_GRID, CROP, DROPDOWN, OPTIONS, FakeCategoryBrowser
    from screenshot_manager.autocapture import NavConfig

    w = win
    counts = {"TWK": 3, "TIU": 3, "TKP": 3}
    b = FakeCategoryBrowser(counts, px_per_notch=60)
    w.driver_factory = lambda: b
    w.settings["crop"] = dict(CROP)
    info = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: info.append(a[2]))
    opened = []
    monkeypatch.setattr(type(w), "run_auto_setup", lambda self, *a, **k: opened.append(1))

    # tanpa pengaturan -> F10 membuka dialog, tidak berjalan
    w.settings["auto"] = {}
    w.toggle_auto()
    assert opened and not w.auto_running

    x, y = CAT_GRID["first"]
    nav = NavConfig(mode="grid", grid_first=[x, y], grid_second=[x + CAT_GRID["dx"], y],
                    grid_below=[x, y + CAT_GRID["dy"]], columns=5, per_category=True,
                    category_dropdown=list(DROPDOWN), category_options={k: list(v) for k, v in OPTIONS.items()})
    w.settings["auto"] = {"sections": [[c, n] for c, n in counts.items()], "global": False,
                          "nav": asdict(nav), "wait_load": 0.0}
    w.toggle_auto()                                  # F10 -> mulai
    assert w.auto_running
    assert wait_until(lambda: len(w.pkg.items) >= 4, timeout=120)
    w.toggle_auto()                                  # F10 -> berhenti
    assert wait_until(lambda: not w.auto_running, timeout=30)
    assert info and "dihentikan" in info[-1]
    partial = len(w.pkg.items)
    assert 3 <= partial < 9                      # soal yang sedang diambil dibuang
    w.toggle_auto()                                  # F10 lagi -> melanjutkan sampai selesai
    assert wait_until(lambda: not w.auto_running, timeout=180)
    assert "SELESAI" in info[-1], info[-1]
    assert sorted(i.filename for i in w.pkg.items) == [f"{c}-00{n}.png" for c in ("TIU", "TKP", "TWK")
                                                       for n in (1, 2, 3)]


def test_point_pick_dialog_grid_preview(win, tmp_path):
    from PySide6.QtCore import QPoint

    from screenshot_manager.app import PointPickDialog
    from tests.fake_browser import GRID, FakeBrowser

    path = tmp_path / "ref.png"
    FakeBrowser({1: 500}).grab().save(path)
    dlg = PointPickDialog(win, str(path), ["1", "2", "bawah"], grid=(GRID["cols"], 45))
    ok_btn = dlg.bb.button(dlg.bb.StandardButton.Ok)
    x, y = GRID["first"]
    for pts, expect_ok in [([(x, y), (x, y + GRID["dy"]), (x + GRID["dx"], y)], False),
                           ([(x, y), (x + GRID["dx"], y), (x, y + GRID["dy"])], True)]:
        dlg._reset()
        dlg.canvas.points = [QPoint(*p) for p in pts]
        dlg._upd()
        assert ok_btn.isEnabled() is expect_ok, dlg.info.text()
    assert "lingkaran biru 1–45" in dlg.info.text()
    assert dlg.canvas.grid_nav is not None and dlg.canvas.grid_nav.grid_position(45) == (x + 4 * GRID["dx"],
                                                                                      y + 8 * GRID["dy"])
    dlg.show()
    dlg.grab().save(str(tmp_path / "preview.png"))


def test_f10_without_settings_runs_auto_setup_then_capture(win, monkeypatch):
    from screenshot_manager import app as appmod
    from tests.fake_browser import FakeAlfaiz

    w = win
    counts = {"TWK": 6, "TIU": 7, "TKP": 6}
    b = FakeAlfaiz(counts, start_cat="TKP")
    w.driver_factory = lambda: b
    w.settings["auto"] = {"wait_load": 0.0}
    w.settings["crop"] = {"enabled": False, "rect": None, "screen": None}
    info = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: info.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: info.append("WARN " + a[2]))
    shown = []

    def fake_exec(dlg):
        shown.append(dlg)
        dlg.choice = "start"
        return QDialog.Accepted
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(appmod.SetupResultDialog, "exec", fake_exec)

    w.toggle_auto()                                     # F10 pertama kali
    assert w.setup_running
    assert wait_until(lambda: shown, timeout=120), info
    assert w.settings["auto"]["sections"] == [["TWK", 6], ["TIU", 7], ["TKP", 6]]
    assert w.settings["crop"]["rect"][1] == FakeAlfaiz.CONTENT[1]
    assert wait_until(lambda: w.auto_running, timeout=10)
    assert wait_until(lambda: not w.auto_running, timeout=240)
    assert info and "SELESAI" in info[-1], info
    assert len(w.pkg.items) == 19
    for cat, n in counts.items():
        for k in range(1, n + 1):
            assert w.pkg.find_slot(cat, k).height == b.page_of(cat, k).height


def test_figural_question_in_window_and_zip(win, tmp_path, monkeypatch):
    from tests.fake_questions import make_question

    w, shots = win, win._shots
    w.select_category("TIU")
    w.set_number(7)
    w.arm()
    fig, _ = make_question(4, fig_soal=True, fig_opsi=True)
    fig.save(shots / "figural.png")
    plain, _ = make_question(5)
    assert wait_until(lambda: w.pkg.find_slot("TIU", 7) is not None)
    plain.save(shots / "teks.png")
    assert wait_until(lambda: w.pkg.find_slot("TIU", 8) is not None)
    w.refresh_table()
    cells = {w.table.item(r, 3).text(): w.table.item(r, 5).text() for r in range(w.table.rowCount())}
    assert cells["TIU-007.png"] == "🖼 6" and cells["TIU-008.png"] == "—", cells
    assert "🖼 1" in w.lbl_counts.text()

    dest = tmp_path / "Paket-01.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    w.make_zip()
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    assert "figural/TIU-007.json" in names and "figural/index.json" in names
    assert not any("TIU-008" in n for n in names if n.startswith("figural/"))

    # tandai bukan bergambar dari menu
    r = next(r for r in range(w.table.rowCount()) if w.table.item(r, 3).text() == "TIU-007.png")
    w.table.selectRow(r)
    w.set_figural(False)
    assert w.pkg.find_slot("TIU", 7).figures == []
    w.chk_figural.setChecked(False)
    w.make_zip()
    with zipfile.ZipFile(dest) as zf:
        assert not any(n.startswith("figural/") for n in zf.namelist())
