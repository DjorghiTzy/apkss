import pytest
from PIL import Image

from screenshot_manager.autocapture import AutoCapture, Plan, RunConfig
from screenshot_manager.autosetup import detect_dropdown, detect_grid, run_autosetup
from screenshot_manager.core import Package
from tests.fake_browser import FakeAlfaiz


def test_detect_grid_and_dropdown():
    b = FakeAlfaiz({"TWK": 30, "TIU": 35, "TKP": 45})
    img = b.grab()
    g = detect_grid(img)
    assert g is not None and g.cols == 5 and g.count == 30
    assert abs(g.first[0] - 1130) <= 1 and abs(g.first[1] - 240) <= 1
    assert abs(g.dx - 46) < 1 and abs(g.dy - 42) < 1
    dd = detect_dropdown(img, g)
    assert dd is not None
    x, y, w, h = dd
    assert 1095 <= x <= 1105 and 123 <= y <= 133 and w >= 190 and 40 <= h <= 50


def test_autosetup_then_full_capture(tmp_path):
    counts = {"TWK": 5, "TIU": 6, "TKP": 7}
    b = FakeAlfaiz(counts, start_cat="TIU")
    logs = []
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], logs.append, wait_load=0)
    assert res.counts == counts, logs
    x, y, w, h = res.crop["rect"]
    cx, cy, cw, ch = FakeAlfaiz.CONTENT
    assert y == cy and y + h == cy + ch, (res.crop, logs)          # tanpa header/taskbar
    assert x <= cx + 12 and cx + cw <= x + w < 1085, res.crop        # tanpa sidebar
    assert res.nav.category_dropdown and set(res.nav.category_options) == {"TWK", "TIU", "TKP"}
    assert isinstance(res.preview, Image.Image)

    pkg = Package(tmp_path / "ws", "Paket-01")
    plan = Plan(sections=[[c, n] for c, n in res.counts.items()])
    cfg = RunConfig(crop=res.crop, nav=res.nav, wait_load=0, stable_interval=0)
    rep = AutoCapture(pkg, plan, cfg, b).run()
    assert rep.aborted is None and len(rep.done) == 18, rep
    assert not [p for p in rep.problems if "celah" in p[1]], rep.problems
    # setiap gambar = halaman soal utuh (lebar kolom konten), soal + pembahasan sampai habis
    for cat, n in counts.items():
        for k in range(1, n + 1):
            it = pkg.find_slot(cat, k)
            page = b.page_of(cat, k)
            with Image.open(pkg.path_of(it)) as im:
                got = im.convert("RGB")
            assert got.height == page.height, (cat, k, got.size, page.size)
            off = cx - x
            assert got.crop((off, 0, off + cw, got.height)).tobytes() == page.tobytes(), (cat, k)


def test_tkp_grid_slightly_different_still_reaches_every_number(tmp_path):
    """Kasus nyata: TKP gagal di nomor 31 (baris ke-7) karena grid TKP sedikit lebih renggang."""
    counts = {"TWK": 10, "TIU": 12, "TKP": 45}
    b = FakeAlfaiz(counts, dy_extra={"TKP": 3}, height_of=lambda c, n: 700 + (n * 37) % 300)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    assert res.counts == counts
    pkg = Package(tmp_path / "ws", "P")
    plan = Plan(sections=[[c, n] for c, n in res.counts.items()])
    rep = AutoCapture(pkg, plan, RunConfig(crop=res.crop, nav=res.nav, wait_load=0, stable_interval=0), b).run()
    assert rep.aborted is None, rep.aborted
    assert len(pkg.items) == 67
    for k in (31, 40, 45):
        with Image.open(pkg.path_of(pkg.find_slot("TKP", k))) as im:
            off = FakeAlfaiz.CONTENT[0] - res.crop["rect"][0]
            got = im.convert("RGB")
            page = b.page_of("TKP", k)
            assert got.crop((off, 0, off + page.width, got.height)).tobytes() == page.tobytes(), k


def test_crop_fits_card_exactly_and_never_cuts_text(tmp_path):
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}
    b = FakeAlfaiz(counts, full_text=True, card_border=True, sidebar_border=False)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    x, y, w, h = res.crop["rect"]
    cx, cy, cw, ch = FakeAlfaiz.CONTENT
    # pas: semua kolom halaman (tulisan sampai tepi) masuk, garis tepi kartu & sidebar tidak
    assert cx - 9 < x <= cx and cx + cw - 1 <= x + w - 1 < cx + cw + 8, res.crop
    assert y == cy and h == ch


def test_runtime_widens_old_cropped_area(tmp_path):
    """Pengaturan lama yang memotong sisi kanan (kasus TKP 30) diperbaiki sendiri saat berjalan."""
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}
    b = FakeAlfaiz(counts, full_text=True, card_border=True, sidebar_border=False)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    bad = dict(res.crop)
    x, y, w, h = bad["rect"]
    bad["rect"] = [x, y, w - 70, h]                                            # terpotong 70px di kanan
    pkg = Package(tmp_path / "ws", "P")
    plan = Plan(sections=[[c, n] for c, n in counts.items()])
    rep = AutoCapture(pkg, plan, RunConfig(crop=bad, nav=res.nav, wait_load=0, stable_interval=0), b).run()
    assert rep.aborted is None, rep.aborted
    assert rep.crop is not None and rep.crop["rect"][2] > w - 70, rep.crop         # diperlebar
    off = FakeAlfaiz.CONTENT[0] - x
    for cat, n in counts.items():
        for k in range(1, n + 1):
            with Image.open(pkg.path_of(pkg.find_slot(cat, k))) as im:
                got = im.convert("RGB")
            page = b.page_of(cat, k)
            wv = min(page.width, got.width - off)                     # bagian halaman yang ikut
            assert got.crop((off, 0, off + wv, got.height)).tobytes() == page.crop((0, 0, wv, page.height)).tobytes()
            rest = page.crop((wv, 0, page.width, page.height))       # yang tidak ikut harus kosong
            assert rest.width == 0 or rest.getextrema() == ((255, 255), (255, 255), (255, 255)), (cat, k, wv)


def test_speed_and_accuracy_with_real_browser_latency(tmp_path):
    """Halaman dimuat 0,3 dtk (soal lama masih tampil selama itu), scroll beranimasi 0,15 dtk."""
    import time
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}
    b = FakeAlfaiz(counts, height_of=lambda c, n: 500 + (n * 211) % 1300, load_s=0.3, anim_s=0.15,
                   start_cat="TIU")
    t = time.monotonic()
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=1.5)
    setup_s = time.monotonic() - t
    assert res.counts == counts
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[[c, n] for c, n in counts.items()]),
                      RunConfig(crop=res.crop, nav=res.nav, wait_load=1.5), b).run()
    assert rep.aborted is None and rep.captured == 18
    per_q = rep.seconds / rep.captured
    off = FakeAlfaiz.CONTENT[0] - res.crop["rect"][0]
    for cat, n in counts.items():
        for k in range(1, n + 1):
            with Image.open(pkg.path_of(pkg.find_slot(cat, k))) as im:
                got = im.convert("RGB")
            page = b.page_of(cat, k)
            wv = min(page.width, got.width - off)
            assert got.crop((off, 0, off + wv, got.height)).tobytes() == page.crop((0, 0, wv, page.height)).tobytes(), (cat, k)
    print(f"Atur Otomatis {setup_s:.1f} dtk, {per_q:.2f} dtk/soal")
    assert setup_s < 5 and per_q < 1.5, (setup_s, per_q)


def test_every_question_under_one_second_without_smooth_scroll(tmp_path):
    import re
    counts = {"TWK": 8, "TIU": 8, "TKP": 8}
    b = FakeAlfaiz(counts, height_of=lambda c, n: 500 + (n * 211) % 1500, load_s=0.3, anim_s=0.0,
                   start_cat="TIU")
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=1.5)
    assert res.crop["smooth_scroll"] is False
    logs = []
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[[c, n] for c, n in counts.items()]),
                      RunConfig(crop=res.crop, nav=res.nav, wait_load=1.5), b, logs.append).run()
    assert rep.aborted is None and rep.captured == 24
    times = [float(re.search(r"([\d.]+) dtk\)", l).group(1)) for l in logs if " dtk)" in l]
    assert len(times) == 24
    print("terlama", max(times), "rata-rata", sum(times) / len(times))
    assert max(times) < 1.0, sorted(times)[-5:]


def _check_all(pkg, b, res, counts):
    off = FakeAlfaiz.CONTENT[0] - res.crop["rect"][0]
    for cat, n in counts.items():
        for k in range(1, n + 1):
            with Image.open(pkg.path_of(pkg.find_slot(cat, k))) as im:
                got = im.convert("RGB")
            page = b.page_of(cat, k)
            wv = min(page.width, got.width - off)
            assert got.height == page.height, (cat, k, got.size, page.size)
            assert got.crop((off, 0, off + wv, got.height)).tobytes() == page.crop((0, 0, wv, page.height)).tobytes(), (cat, k)


def test_black_screen_lagging_scroll_and_blinking_caret(tmp_path):
    """Kasus nyata: TIU 4 tertangkap hitam, TIU 18 hanya A–D (scroll telat), area soal berkedip."""
    from screenshot_manager.quality import option_rows
    from tests.fake_questions import make_long_question
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}
    b = FakeAlfaiz(counts, page_maker=make_long_question, load_s=0.15, anim_s=0.0,
                   black_after_nav={("TIU", 4): 0.4}, scroll_lag={("TIU", 5): 0.2, ("TKP", 2): 0.25},
                   blink=False)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=1.5)
    b.blink = True                                   # kursor berkedip selama Tangkap Otomatis
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[[c, n] for c, n in counts.items()]),
                      RunConfig(crop=res.crop, nav=res.nav, wait_load=1.5), b).run()
    assert rep.aborted is None and rep.captured == 18, rep
    assert rep.seconds / rep.captured < 2.0, rep.seconds          # kedipan tidak membuat menunggu batas waktu
    b.blink = False
    for it in pkg.items:
        with Image.open(pkg.path_of(it)) as im:
            assert option_rows(im) == 5, it.filename                 # tidak ada yang hitam / A–D saja
    assert not [p for p in rep.problems if "hitam" in p[1] or "baris pilihan" in p[1]], rep.problems


def test_scrolling_full_width_header_does_not_widen_area(tmp_path):
    """Kasus pengguna: header situs ikut ter-scroll -> kotak sempat selebar layar (area putih di kiri)."""
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}
    b = FakeAlfaiz(counts, scrolling_header=True)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    x, y, w, h = res.crop["rect"]
    cx = FakeAlfaiz.CONTENT[0]
    assert cx - 20 <= x <= cx, res.crop                     # mulai di tepi konten, bukan tepi layar
    assert x + w < 1085                                      # tanpa sidebar


@pytest.mark.parametrize("ppn", [83.75, 61.3])
def test_fractional_pixel_scrolling_does_not_crash_or_lose_content(tmp_path, ppn):
    """Kasus nyata: zoom browser + skala Windows -> 1 notch = 83,75 px; huruf digambar ulang sub-piksel.
    Dulu: TypeError 'NoneType' * 'float' di soal pertama; lalu (61,3 px) cocok palsu di area kosong
    -> isi tergandakan & soal berikutnya terpotong TANPA peringatan."""
    import numpy as np
    counts = {"TWK": 8, "TIU": 8, "TKP": 8}
    b = FakeAlfaiz(counts, px_per_notch=ppn, subpixel=True)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[[c, n] for c, n in counts.items()]),
                      RunConfig(crop=res.crop, nav=res.nav, wait_load=0.5), b).run()
    assert rep.aborted is None and rep.captured == 24 and rep.problems == [], (rep.aborted, rep.problems)
    cx = res.crop["rect"][0] - b.CONTENT[0]
    for cat, n in counts.items():
        for k in range(1, n + 1):
            it = pkg.find_slot(cat, k)
            page = b.page_of(cat, k)
            assert abs(it.height - page.height) <= 2, (cat, k, it.height, page.height)
            with Image.open(pkg.path_of(it)) as im:
                got = np.asarray(im.convert("L"), dtype=np.int16)
            canvas = Image.new("L", (got.shape[1], page.height), 255)
            canvas.paste(page.convert("L"), (-cx, 0))
            ref = np.asarray(canvas, dtype=np.int16)
            for y in range(0, min(len(got), len(ref)) - 103, 100):      # tiap blok di tempat yang benar
                err = min(np.abs(got[y:y + 100] - ref[y + d:y + d + 100]).mean() for d in range(-3, 4)
                          if y + d >= 0)
                assert err < 8, (cat, k, y, err)                         # 8 > blur render sub-piksel (~6,5)


def test_overlap_bounded_by_scroll_distance():
    """Frame di posisi pecahan (490,4) lalu mentok di dasar (791): tumpang tindih asli 327 baris.
    Tanpa batas pergeseran, area kosong 15 baris dulu dianggap cocok."""
    from screenshot_manager.core import find_overlap
    b = FakeAlfaiz({"TWK": 8, "TIU": 8, "TKP": 8}, px_per_notch=61.3, subpixel=True)
    b.open, b.n = True, 3
    box = (b.CONTENT[0], b.CONTENT[1], b.CONTENT[0] + b.CONTENT[2], b.CONTENT[1] + b.CONTENT[3])
    b.scroll_y = 490.4
    a = b.grab().crop(box)
    b.scroll_y = 791
    c = b.grab().crop(box)
    k = find_overlap(a, c, max_shift=int(8 * 61.3 * 1.06 + 3))
    assert abs(k - (b.CONTENT[3] - 300.6)) <= 1.5, k


def test_subpixel_overlap_unit():
    from screenshot_manager.core import find_overlap
    from tests.fake_browser import make_page
    page = make_page(5, 1600)
    a = page.crop((0, 0, 760, 600))
    shifted = page.crop((0, 300, 760, 901)).transform((760, 601), Image.AFFINE, (1, 0, 0, 0, 1, 0.5),
                                                       resample=Image.BILINEAR).crop((0, 0, 760, 600))
    k = find_overlap(a, shifted)
    assert abs(k - 300) <= 1, k
    other = make_page(77, 1600).crop((0, 0, 760, 600))
    assert find_overlap(a, other) == 0                       # halaman lain: tidak dipaksa cocok


def test_unexpected_error_in_one_question_does_not_stop_the_run(tmp_path):
    """Kesalahan tak terduga (mis. glitch layar) di satu soal: soal itu diulang, sesi tetap jalan."""
    counts = {"TWK": 6, "TIU": 6, "TKP": 6}

    class Glitchy(FakeAlfaiz):
        fired = 0

        def scroll(self, x, y, notches):
            if (self.cat, self.n) == ("TIU", 2) and notches < 0 and not self.fired:
                Glitchy.fired = 1
                raise ValueError("glitch")
            return super().scroll(x, y, notches)

    b = Glitchy(counts)
    res = run_autosetup(b, ["TWK", "TIU", "TKP"], wait_load=0)
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[[c, n] for c, n in counts.items()]),
                      RunConfig(crop=res.crop, nav=res.nav, wait_load=0.5), b).run()
    assert Glitchy.fired and rep.aborted is None and rep.captured == 18, (rep.aborted, rep.problems)
    for cat, n in counts.items():
        for k in range(1, n + 1):
            assert abs(pkg.find_slot(cat, k).height - b.page_of(cat, k).height) <= 1
