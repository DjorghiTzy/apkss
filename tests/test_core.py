import zipfile
from pathlib import Path

import pytest
from PIL import Image

from screenshot_manager.core import (DuplicateImageError, ManagerError, Package, SlotTakenError,
                                     is_image_path, list_packages, make_filename,
                                     sanitize_package_name)


def img(path: Path, color, size=(40, 30), fmt=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


@pytest.fixture
def env(tmp_path):
    shots = tmp_path / "Screenshots"
    ws = tmp_path / "ws"
    return shots, ws


def test_filename_and_names():
    assert make_filename("TWK", 1) == "TWK-001.png"
    assert make_filename("TKP", 45) == "TKP-045.png"
    assert make_filename("TIU", 1234) == "TIU-1234.png"
    assert sanitize_package_name(" Paket:01 ") == "Paket-01"
    with pytest.raises(ManagerError):
        sanitize_package_name("CON")
    assert is_image_path("a.PNG") and is_image_path("b.webp") and is_image_path("c.jpeg")
    assert not is_image_path("a.txt") and not is_image_path("~tmp.png")


def test_add_assign_dedup_and_originals_untouched(env):
    shots, ws = env
    a = img(shots / "Screenshot 1.png", "red")
    b = img(shots / "Screenshot 2.jpg", "blue")
    c = img(shots / "Screenshot 3.webp", "green", fmt="WEBP")
    before = {p: p.read_bytes() for p in (a, b, c)}

    pkg = Package(ws, "Paket-01")
    r1 = pkg.add_image(a, "TWK", 1)
    assert (ws / "Paket-01" / "TWK" / "TWK-001.png").exists()
    pkg.add_image(b, "TWK", 2)
    pkg.add_image(c, "TIU", 1)
    # JPG/WEBP disimpan sebagai PNG sungguhan
    with Image.open(ws / "Paket-01" / "TWK" / "TWK-002.png") as im:
        assert im.format == "PNG"

    # duplikat: file sama (bahkan dengan nama lain) ditolak
    copy = shots / "copy.png"
    copy.write_bytes(a.read_bytes())
    with pytest.raises(DuplicateImageError) as ei:
        pkg.add_image(copy, "TWK", 9)
    assert ei.value.existing.id == r1.item.id
    assert len(pkg.items) == 3

    # slot sudah ada -> diganti, lama dicadangkan
    d = img(shots / "retake.png", "yellow")
    res = pkg.add_image(d, "TWK", 1)
    assert res.replaced is not None and res.replaced.id == r1.item.id
    assert len(list((ws / "Paket-01" / "_diganti").iterdir())) == 1
    assert len(pkg.items) == 3

    # asli tetap utuh
    for p, data in before.items():
        assert p.read_bytes() == data

    # state tersimpan & bisa dimuat ulang
    again = Package(ws, "Paket-01")
    assert sorted(i.filename for i in again.items) == ["TIU-001.png", "TWK-001.png", "TWK-002.png"]
    assert list_packages(ws) == ["Paket-01"]


def test_assign_conflicts_swap_replace(env):
    shots, ws = env
    pkg = Package(ws, "P")
    x = pkg.add_image(img(shots / "x.png", "red"), "TWK", 1).item
    y = pkg.add_image(img(shots / "y.png", "blue"), "TWK", 2).item
    u = pkg.add_image(img(shots / "u.png", "white")).item
    assert not u.assigned and (pkg.root / "_belum" / f"{u.id}.png").exists()

    with pytest.raises(SlotTakenError):
        pkg.assign(x.id, "TWK", 2)
    pkg.assign(x.id, "TWK", 2, on_conflict="swap")
    assert (x.number, y.number) == (2, 1)
    with Image.open(pkg.path_of(x)) as im:
        assert im.getpixel((0, 0)) == (255, 0, 0)

    pkg.assign(u.id, "TKP", 1)
    assert (pkg.root / "TKP" / "TKP-001.png").exists()
    pkg.assign(u.id, "TWK", 1, on_conflict="replace")
    assert len(pkg.items) == 2 and pkg.find_slot("TWK", 1).id == u.id
    assert not (pkg.root / "TKP" / "TKP-001.png").exists()

    pkg.remove(x.id)
    assert not pkg.path_of(x).exists() and (shots / "x.png").exists()


def test_renumber(env):
    shots, ws = env
    pkg = Package(ws, "P")
    for n, col in zip([3, 7, 10], ["red", "green", "blue"]):
        pkg.add_image(img(shots / f"{col}.png", col), "TIU", n)
    pkg.add_image(img(shots / "w.png", "white"), "TWK", 5)
    changed = pkg.renumber("TIU")
    assert changed == 3
    assert sorted(i.filename for i in pkg.items if i.category == "TIU") == \
        ["TIU-001.png", "TIU-002.png", "TIU-003.png"]
    assert pkg.find_slot("TWK", 5) is not None
    assert pkg.next_number_for("TIU") == 4
    pkg.renumber()
    assert pkg.find_slot("TWK", 1) is not None
    assert pkg.missing_files() == []


def test_zip_structure(env, tmp_path):
    shots, ws = env
    pkg = Package(ws, "Paket-01")
    pkg.add_image(img(shots / "1.png", "red"), "TWK", 1)
    pkg.add_image(img(shots / "2.png", "blue"), "TWK", 2)
    pkg.add_image(img(shots / "3.png", "green"), "TIU", 1)
    pkg.add_image(img(shots / "4.png", "black"), "TKP", 1)
    pkg.add_image(img(shots / "5.png", "white"))  # tanpa nomor -> dilewati
    res = pkg.export_zip(tmp_path / "out" / "Paket-01")
    assert res.path.name == "Paket-01.zip"
    assert res.counts == {"TWK": 2, "TIU": 1, "TKP": 1} and res.skipped_unassigned == 1
    with zipfile.ZipFile(res.path) as zf:
        assert zf.testzip() is None
        assert sorted(n for n in zf.namelist() if n.endswith(".png")) == [
            "TIU/TIU-001.png", "TKP/TKP-001.png", "TWK/TWK-001.png", "TWK/TWK-002.png"]
        assert {"daftar.json", "PROMPT.txt"} <= set(zf.namelist())
        out = tmp_path / "extract"
        zf.extractall(out)
    with Image.open(out / "TWK" / "TWK-002.png") as im:
        assert im.format == "PNG" and im.getpixel((0, 0)) == (0, 0, 255)


def test_zip_empty_raises(env, tmp_path):
    _, ws = env
    with pytest.raises(ManagerError):
        Package(ws, "Kosong").export_zip(tmp_path / "x.zip")


def test_corrupt_image_rejected(env):
    shots, ws = env
    shots.mkdir(parents=True)
    bad = shots / "half.png"
    good = img(shots / "full.png", "red", size=(400, 300))
    bad.write_bytes(good.read_bytes()[:200])
    with pytest.raises(ManagerError):
        Package(ws, "P").add_image(bad, "TWK", 1)
