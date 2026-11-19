import zipfile

import pytest
from PIL import Image

from screenshot_manager.autocapture import AutoCapture, AutoCaptureError, NavConfig, Plan, RunConfig
from screenshot_manager.core import Package
from tests.fake_browser import AREA, CROP, GRID, FakeBrowser, make_page


def grid_nav():
    x, y = GRID["first"]
    return NavConfig(mode="grid", grid_first=[x, y], grid_second=[x + GRID["dx"], y],
                     grid_below=[x, y + GRID["dy"]], columns=GRID["cols"])


def cfg(nav=None, **kw):
    return RunConfig(crop=CROP, nav=nav or grid_nav(), wait_load=0, stable_interval=0, **kw)


def test_plan_entries():
    p = Plan(sections=[["TWK", 2], ["TIU", 3], ["TKP", 1]])
    assert p.entries() == [(1, "TWK", 1), (2, "TWK", 2), (3, "TIU", 1), (4, "TIU", 2),
                           (5, "TIU", 3), (6, "TKP", 1)]
    assert Plan(sections=[["TWK", 2], ["TIU", 3]], global_numbering=True, start=2, end=4).entries() == \
        [(2, "TWK", 2), (3, "TIU", 3), (4, "TIU", 4)]
    nav = grid_nav()
    assert nav.grid_position(1) == GRID["first"]
    assert nav.grid_position(7) == (GRID["first"][0] + GRID["dx"], GRID["first"][1] + GRID["dy"])


def check_pages(pkg, browser, mapping):
    for fname, q in mapping.items():
        item = next(i for i in pkg.items if i.filename == fname)
        with Image.open(pkg.path_of(item)) as im:
            got = im.convert("RGB")
        want = browser.pages[q]
        if want.height < AREA[3]:                     # halaman pendek: sisa area putih ikut terfoto
            pad = Image.new("RGB", (AREA[2], AREA[3]), "white")
            pad.paste(want, (0, 0))
            want = pad
        assert got.size == want.size, (fname, got.size, want.size)
        if not browser.noise:
            assert got.tobytes() == want.tobytes(), fname


@pytest.mark.parametrize("noise", [False, True])
def test_full_run_grid(tmp_path, noise):
    heights = {1: 400, 2: 1900, 3: 900, 4: 2600, 5: 560, 6: 1300}   # pendek, panjang, sangat panjang
    b = FakeBrowser(heights, px_per_notch=53, noise=noise)
    pkg = Package(tmp_path / "ws", "Paket-01")
    plan = Plan(sections=[["TWK", 2], ["TIU", 3], ["TKP", 1]])
    logs = []
    rep = AutoCapture(pkg, plan, cfg(), b, logs.append).run()
    assert rep.aborted is None and not rep.stopped, rep
    assert rep.done == ["TWK-001.png", "TWK-002.png", "TIU-001.png", "TIU-002.png",
                        "TIU-003.png", "TKP-001.png"]
    assert not [p for p in rep.problems if "celah" in p[1]], rep.problems
    check_pages(pkg, b, {"TWK-001.png": 1, "TWK-002.png": 2, "TIU-001.png": 3,
                         "TIU-002.png": 4, "TIU-003.png": 5, "TKP-001.png": 6})
    assert rep.notches and rep.notches * 53 <= AREA[3]          # tiap langkah pasti tumpang tindih
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    with zipfile.ZipFile(res.path) as zf:
        assert len(zf.namelist()) == 6
    assert not list((tmp_path).glob("sm-auto-*"))


def test_key_navigation_and_resume(tmp_path):
    b = FakeBrowser({1: 500, 2: 1000, 3: 700}, px_per_notch=100)
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[["TWK", 3]]), cfg(NavConfig(mode="key")), b).run()
    assert rep.done == ["TWK-001.png", "TWK-002.png", "TWK-003.png"]
    check_pages(pkg, b, {"TWK-001.png": 1, "TWK-002.png": 2, "TWK-003.png": 3})


def test_navigation_failure_aborts(tmp_path):
    b = FakeBrowser({1: 500, 2: 600}, broken_nav=True)
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[["TWK", 2]]), cfg(), b).run()
    assert rep.done == ["TWK-001.png"] and "gagal" in rep.aborted


def test_stop_and_wrong_screen(tmp_path):
    b = FakeBrowser({q: 1500 for q in range(1, 6)}, stop_after_grabs=12)
    pkg = Package(tmp_path / "ws", "P")
    rep = AutoCapture(pkg, Plan(sections=[["TWK", 5]]), cfg(), b).run()
    assert rep.stopped and len(rep.done) < 5

    bad = {**CROP, "screen": [1920, 1080]}
    rep = AutoCapture(Package(tmp_path / "ws", "Q"), Plan(sections=[["TWK", 1]]),
                      RunConfig(crop=bad, nav=grid_nav(), wait_load=0, stable_interval=0),
                      FakeBrowser({1: 500})).run()
    assert "berbeda dengan acuan" in rep.aborted
    with pytest.raises(AutoCaptureError):
        AutoCapture(pkg, Plan(), RunConfig(crop=CROP, nav=NavConfig(mode="grid")), b)


def test_resume_skips_already_captured(tmp_path):
    heights = {1: 500, 2: 1200, 3: 800}
    pkg = Package(tmp_path / "ws", "P")
    plan = Plan(sections=[["TWK", 3]])
    b = FakeBrowser(heights, stop_after_grabs=6)
    rep = AutoCapture(pkg, plan, cfg(), b).run()
    assert rep.stopped
    first = len(pkg.items)
    rep = AutoCapture(pkg, plan, cfg(), FakeBrowser(heights)).run()     # lanjutkan
    assert rep.aborted is None and rep.done == ["TWK-001.png", "TWK-002.png", "TWK-003.png"]
    assert len(pkg.items) == 3 and first >= 1
    check_pages(pkg, FakeBrowser(heights), {"TWK-001.png": 1, "TWK-002.png": 2, "TWK-003.png": 3})


@pytest.mark.parametrize("stop_at", [3, 5, 8, 11, 14])
def test_stop_mid_question_never_leaves_partial(tmp_path, stop_at):
    heights = {1: 1500, 2: 1900}
    pkg = Package(tmp_path / "ws", "P")
    plan = Plan(sections=[["TWK", 2]])
    AutoCapture(pkg, plan, cfg(), FakeBrowser(heights, stop_after_grabs=stop_at)).run()
    for it in pkg.items:                                   # yang tersisa harus lengkap
        assert it.height == heights[it.number], (it.filename, it.height)
    rep = AutoCapture(pkg, plan, cfg(), FakeBrowser(heights)).run()
    assert rep.aborted is None
    check_pages(pkg, FakeBrowser(heights), {"TWK-001.png": 1, "TWK-002.png": 2})
