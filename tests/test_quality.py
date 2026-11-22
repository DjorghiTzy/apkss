from PIL import Image

from screenshot_manager.quality import is_blank, option_rows
from tests.fake_questions import make_alfaiz_question, make_long_question


def test_blank_and_option_rows():
    assert is_blank(Image.new("RGB", (800, 600), "black"))
    assert is_blank(Image.new("RGB", (800, 600), "white"))
    img, _ = make_alfaiz_question(3, "text")
    assert not is_blank(img) and option_rows(img) == 5
    long = make_long_question(7, 1600)
    assert option_rows(long) == 5
    assert option_rows(long.crop((0, 0, 760, 700))) < 5               # terpotong di tengah pilihan


def test_trim_for_export_title_to_last_sentence():
    import numpy as np
    from screenshot_manager.quality import trim_for_export
    from tests.fake_questions import make_capture_like_user
    img, (left, title_y) = make_capture_like_user(4)
    out = trim_for_export(img)
    a = np.asarray(out, dtype=np.int16)
    # kiri: area putih 500 px dibuang (sisa ≤ margin dari tepi kartu)
    assert out.width < img.width - 450
    # atas: mulai di judul (garis header merah di baris 0 dibuang)
    assert not ((a[0, :, 0] > 120) & (a[0, :, 1] < 40)).any()
    assert out.height < img.height
    # bawah: tidak ada tombol merah (Sebelumnya/Selanjutnya) & berakhir dekat tulisan terakhir
    red = (a[..., 0] > a[..., 1] + 60) & (a[..., 0] > a[..., 2] + 60)
    rows_red = np.flatnonzero(red.sum(axis=1) > 100)
    assert len(rows_red) == 0 or rows_red[-1] < out.height - 60       # pilihan merah boleh, tombol tidak
    dark = (a.max(axis=2) < 130) & (a.max(axis=2) - a.min(axis=2) < 40)
    last_dark = np.flatnonzero(dark.sum(axis=1) >= 2)[-1]
    assert out.height - last_dark <= 12                                # tepat setelah kalimat terakhir
    # tulisan "TRY OUT" dan seluruh isi tetap ada (tidak ada tulisan gelap yang hilang)
    src = np.asarray(img, dtype=np.int16)
    sd = (src.max(axis=2) < 130) & (src.max(axis=2) - src.min(axis=2) < 40)
    assert dark.sum() == sd.sum()


def test_trim_keeps_plain_content_and_export_uses_it(tmp_path):
    import zipfile
    from screenshot_manager.core import Package
    from tests.fake_questions import make_capture_like_user
    img, _ = make_capture_like_user(2)
    img.save(tmp_path / "a.png")
    pkg = Package(tmp_path / "ws", "Paket-31")
    pkg.add_image(tmp_path / "a.png", "TWK", 1)
    res = pkg.export_zip(tmp_path / "Paket-31.zip")
    with zipfile.ZipFile(res.path) as zf, zf.open("TWK/TWK-001.png") as f:
        got = Image.open(f)
        assert got.width < img.width - 450 and got.height < img.height
    with Image.open(pkg.path_of(pkg.find_slot("TWK", 1))) as orig:      # file workspace tetap utuh
        assert orig.size == img.size


def test_option_rows_real_like_long_text_and_shadows():
    """Kasus nyata: semua TWK lengkap tapi tertulis "hanya 1–3 pilihan" (teks panjang & bayangan kartu)."""
    from tests.fake_questions import make_real_like_question
    for s in range(1, 9):
        assert option_rows(make_real_like_question(s)) == 5, s
        assert option_rows(make_real_like_question(s, shadow=False)) == 5, s
        assert option_rows(make_real_like_question(s, n_options=4)) == 4, s


def test_export_check_no_false_alarm_and_four_options_ok(tmp_path):
    from screenshot_manager.core import Package
    from tests.fake_questions import make_real_like_question
    pkg = Package(tmp_path / "ws", "P")
    for n in range(1, 4):
        make_real_like_question(n).save(tmp_path / f"{n}.png")
        pkg.add_image(tmp_path / f"{n}.png", "TWK", n)
    make_real_like_question(9, n_options=4).save(tmp_path / "4.png")
    pkg.add_image(tmp_path / "4.png", "TWK", 4)
    cut = make_real_like_question(7)
    cut.crop((0, 0, cut.width, 230)).save(tmp_path / "cut.png")             # terpotong di pilihan B/C
    pkg.add_image(tmp_path / "cut.png", "TWK", 5)
    issues = pkg.export_check({"TWK": 5})
    assert issues == ["TWK-005.png: hanya 2 pilihan jawaban terlihat (terpotong?)"] or \
        (len(issues) == 1 and issues[0].startswith("TWK-005.png: hanya")), issues
