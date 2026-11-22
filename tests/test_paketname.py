import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from screenshot_manager import paketname
from screenshot_manager.paketname import detect_part, package_name, part_from_text


@pytest.mark.parametrize("text,part", [
    ("< TRY OUT SKD CASN 2027 - PART 31", 31),
    ("Beranda Mulai Belajar\nTRY OUT SKD CASN 2026 – PART 39\nSoal Nomor 1 (PG)", 39),
    ("TRY OUT SKD CASN 2027 — Part 5", 5),
    ("TRY OUT SKD CASN 2027 -PART:12", 12),
    ("Soal Nomor 57 (PG)\nTes Wawasan Kebangsaan", None),
    ("", None),
])
def test_part_from_text(text, part):
    assert part_from_text(text) == part


def test_package_name_and_detect_with_given_ocr():
    assert package_name(31) == "Paket-31" and package_name(5) == "Paket-05"
    seen = []

    def fake_ocr(img):
        seen.append(img.size)
        return "AL FAIZ Beranda\n< TRY OUT SKD CASN 2027 - PART 31"
    assert detect_part(Image.new("RGB", (1366, 768), "white"), ocr=fake_ocr) == 31
    assert seen == [(1366 * 2, 768)]                        # separuh atas, diperbesar 2×


def render_title(text="< TRY OUT SKD CASN 2027 - PART 31"):
    img = Image.new("RGB", (1366, 768), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1366, 60], fill=(139, 0, 0))
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    d.text((440, 100), text, fill=(139, 0, 0), font=font)
    d.text((460, 170), "Soal Nomor 1 (PG)", fill="black", font=font)
    return img


@pytest.mark.skipif(sys.platform != "win32", reason="OCR Windows hanya ada di Windows")
def test_real_windows_ocr_reads_part_number():
    assert paketname.ocr_available(), "paket winrt OCR tidak terpasang"
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    if OcrEngine.try_create_from_user_profile_languages() is None:
        pytest.skip("tidak ada bahasa OCR terpasang di mesin ini")
    text = asyncio.run(paketname._ocr_async(render_title().crop((0, 0, 1366, 384))))
    print("OCR:", repr(text))
    assert detect_part(render_title()) == 31, text
