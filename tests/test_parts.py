"""Potong otomatis + bagian lanjutan (soal sampai pembahasan yang panjang)."""
import random
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from screenshot_manager.core import (DuplicateImageError, ManagerError, Package, apply_crop,
                                     find_overlap, stitch)

SCREEN = (1366, 768)
AREA = [300, 100, 760, 600]          # x, y, w, h area soal di layar
CROP = {"enabled": True, "rect": AREA, "screen": list(SCREEN)}


def long_page(height=1700, seed=1):
    """Halaman soal+pembahasan panjang dengan konten unik per baris teks."""
    rnd = random.Random(seed)
    page = Image.new("RGB", (AREA[2], height), "white")
    d = ImageDraw.Draw(page)
    for y in range(10, height - 20, 22):
        d.text((10, y), f"baris {y} " + "x" * rnd.randint(5, 60), fill="black")
    return page


def screen_of(page, scroll):
    """Screenshot layar penuh (Win+PrtScn) saat halaman di-scroll `scroll` piksel."""
    scr = Image.new("RGB", SCREEN, "#334")              # taskbar, tab browser, dll.
    ImageDraw.Draw(scr).rectangle([0, 0, SCREEN[0], 40], fill="#888")
    scr.paste(page.crop((0, scroll, AREA[2], scroll + AREA[3])), (AREA[0], AREA[1]))
    return scr


def save(img, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def test_apply_crop_only_full_screen():
    scr = Image.new("RGB", SCREEN, "red")
    out, ok = apply_crop(scr, CROP)
    assert ok and out.size == (760, 600)
    small = Image.new("RGB", (500, 400), "red")             # potongan Snipping Tool
    assert apply_crop(small, CROP) == (small, False)
    assert apply_crop(scr, {**CROP, "enabled": False})[1] is False


def test_find_overlap_and_stitch():
    page = long_page()
    a, b = page.crop((0, 0, 760, 600)), page.crop((0, 450, 760, 1050))
    assert find_overlap(a, b) == 150
    out, ov = stitch([a, b])
    assert ov == [0, 150] and out.size == (760, 1050)
    assert out.tobytes() == page.crop((0, 0, 760, 1050)).tobytes()
    c = long_page(seed=9).crop((0, 0, 760, 600))           # halaman lain: tanpa tumpang tindih
    assert find_overlap(a, c) < 12 or find_overlap(a, c) == 0


def test_question_with_long_explanation(tmp_path):
    shots, ws = tmp_path / "shots", tmp_path / "ws"
    page = long_page(1700)
    pkg = Package(ws, "Paket-01")
    r = pkg.add_image(save(screen_of(page, 0), shots / "s1.png"), "TWK", 1, crop=CROP)
    assert r.cropped and r.item.height == 600

    # scroll 500 px dua kali, lalu scroll ke paling bawah (sisa 100 px saja)
    for n, scroll in enumerate([500, 1000, 1100], start=2):
        res = pkg.append_part(r.item.id, save(screen_of(page, scroll), shots / f"s{n}.png"), CROP)
        assert res.part_number == n and res.cropped
    item = pkg.get(r.item.id)
    assert item.parts == 4 and item.height == 1700
    with Image.open(pkg.path_of(item)) as im:
        assert im.convert("RGB").tobytes() == page.tobytes()   # rekonstruksi sempurna

    # screenshot yang sama lagi (lupa scroll) ditolak
    with pytest.raises(ManagerError, match="sama persis"):
        pkg.append_part(item.id, shots / "s4.png", CROP)
    # bagian yang sudah dipakai tidak bisa jadi soal baru
    with pytest.raises(DuplicateImageError):
        pkg.add_image(shots / "s2.png", "TWK", 2, crop=CROP)

    # hapus bagian terakhir -> kembali ke 3 bagian
    pkg.remove_last_part(item.id)
    assert item.parts == 3 and item.height == 1600
    again = Package(ws, "Paket-01")                         # tersimpan di paket.json
    assert again.get(item.id).parts == 3

    # tetap satu file per nomor di ZIP, bisa dipindah nomor
    pkg.assign(item.id, "TWK", 5)
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    with zipfile.ZipFile(res.path) as zf:
        assert [n for n in zf.namelist() if n.endswith(".png")] == ["TWK/TWK-005.png"]
    pkg.remove(item.id)
    assert not (ws / "Paket-01" / "_bagian" / item.id).exists()


def test_remove_last_part_single_raises(tmp_path):
    pkg = Package(tmp_path / "ws", "P")
    it = pkg.add_image(save(Image.new("RGB", (50, 50), "red"), tmp_path / "a.png"), "TIU", 1).item
    with pytest.raises(ManagerError):
        pkg.remove_last_part(it.id)
