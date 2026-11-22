"""Nama paket otomatis dari judul halaman tryout ("TRY OUT SKD CASN 2027 - PART 31" -> Paket-31).

Memakai OCR bawaan Windows (Windows.Media.Ocr, offline). Hanya untuk nama paket —
kategori & nomor soal tetap dari Tipe Soal dan Daftar Soal, bukan OCR.
"""
from __future__ import annotations

import re
import sys
from typing import Optional

from PIL import Image

PART = re.compile(r"\bPART\s*[-:.]?\s*(\d{1,3})\b", re.IGNORECASE)


def part_from_text(text: str) -> Optional[int]:
    """Nomor PART dari teks judul (prioritas baris yang memuat 'TRY OUT')."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    for line in sorted(lines, key=lambda l: 0 if re.search(r"TRY\s*OUT", l, re.I) else 1):
        m = PART.search(line.replace("—", "-").replace("–", "-"))
        if m:
            return int(m.group(1))
    return None


def package_name(part: int) -> str:
    return f"Paket-{part:02d}"


def ocr_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winrt.windows.media.ocr  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


async def _ocr_async(img: Image.Image) -> str:
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return ""
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                    rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED)
    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def ocr_text(img: Image.Image) -> str:
    """Teks hasil OCR Windows ('' bila tidak tersedia)."""
    if not ocr_available():
        return ""
    import asyncio
    try:
        return asyncio.run(_ocr_async(img))
    except Exception:  # noqa: BLE001 - OCR gagal tidak boleh menghentikan alur
        return ""


def detect_part(screen: Image.Image, ocr=ocr_text) -> Optional[int]:
    """Cari "PART nn" di separuh atas layar (judul tryout)."""
    w, h = screen.size
    top = screen.crop((0, 0, w, max(1, h // 2)))
    top = top.resize((top.width * 2, top.height * 2), Image.LANCZOS)   # teks kecil lebih terbaca
    return part_from_text(ocr(top))
