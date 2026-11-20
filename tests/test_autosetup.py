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
