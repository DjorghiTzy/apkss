"""'Buat ZIP siap impor': soal.json dari ChatGPT + gambar/ -> <paket>-siap-impor.zip untuk SKD Intelligence."""
from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUBTOPIK = {
    "TWK": ["Nasionalisme", "Integritas", "Bela Negara", "Pilar Negara", "Bahasa Indonesia"],
    "TIU": ["Analogi Verbal", "Silogisme", "Analitis", "Berhitung", "Deret Angka", "Perbandingan Kuantitatif",
            "Soal Cerita", "Analogi Figural", "Ketidaksamaan Figural", "Serial Figural"],
    "TKP": ["Pelayanan Publik", "Jejaring Kerja", "Sosial Budaya", "Teknologi Informasi dan Komunikasi",
            "Profesionalisme", "Anti Radikalisme"],
}
MAKS_NOMOR = {"TWK": 30, "TIU": 35, "TKP": 45}
HURUF = ["A", "B", "C", "D", "E"]
PENANDA = re.compile(r"\s*\[\s*gambar(?:\s*:[^\]]*)?\s*\]\s*", re.IGNORECASE)


class ImportError_(ValueError):
    pass


def parse_soal_json(text: str) -> Any:
    """Baca soal.json (file atau teks tempelan); toleran terhadap ```json ... ``` dan teks di sekitarnya."""
    t = text.strip().lstrip("﻿")
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S | re.I)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
        if not starts:
            raise ImportError_("Teks tidak berisi JSON")
        end = max(t.rfind("}"), t.rfind("]"))
        try:
            return json.loads(t[min(starts):end + 1])
        except ValueError as exc:
            raise ImportError_(f"JSON tidak valid: {exc}") from exc


def _strip_markers(v):
    if isinstance(v, str):
        out = PENANDA.sub(" ", v)
        out = re.sub(r"[ \t]{2,}", " ", out).strip()
        return out
    if isinstance(v, dict):
        return {k: _strip_markers(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strip_markers(x) for x in v]
    return v


def clean(doc: Any) -> tuple[dict, list[str]]:
    """Bersihkan otomatis: [gambar]/[GAMBAR:…] dihapus, opsi->pilihan, jawaban->kunci."""
    changes = []
    if isinstance(doc, list):
        doc = {"paket": None, "soal": doc}
        changes.append("JSON berupa daftar: dibungkus menjadi {\"paket\", \"soal\"}")
    if not isinstance(doc, dict) or not isinstance(doc.get("soal"), list):
        raise ImportError_("soal.json harus berisi {\"paket\": ..., \"soal\": [...]}")
    renamed = {"opsi": 0, "jawaban": 0}
    markers = 0
    soal = []
    for s in doc["soal"]:
        if not isinstance(s, dict):
            soal.append(s)
            continue
        s = dict(s)
        if "opsi" in s and "pilihan" not in s:
            s["pilihan"] = s.pop("opsi")
            renamed["opsi"] += 1
        if "jawaban" in s and "kunci" not in s:
            s["kunci"] = s.pop("jawaban")
            renamed["jawaban"] += 1
        before = json.dumps(s, ensure_ascii=False)
        for key in ("pertanyaan", "pilihan", "pembahasan", "catatan"):
            if key in s:
                s[key] = _strip_markers(s[key])
        if json.dumps(s, ensure_ascii=False) != before:
            markers += 1
        soal.append(s)
    doc = dict(doc)
    doc["soal"] = soal
    if renamed["opsi"]:
        changes.append(f"kolom \"opsi\" → \"pilihan\" ({renamed['opsi']} soal)")
    if renamed["jawaban"]:
        changes.append(f"kolom \"jawaban\" → \"kunci\" ({renamed['jawaban']} soal)")
    if markers:
        changes.append(f"penanda [gambar] dihapus ({markers} soal)")
    return doc, changes


@dataclass
class Validation:
    issues: list = field(default_factory=list)       # (id soal / "umum", pesan)
    total: int = 0
    gambar: int = 0

    def add(self, who: str, msg: str):
        self.issues.append((who, msg))


def validate(doc: dict, available: set[str], expected: int, figural: set[str]) -> Validation:
    """available: path gambar yang ada (mis. "gambar/TIU-027.png"); figural: id soal bergambar ("TIU-027")."""
    v = Validation(total=len(doc.get("soal", [])))
    if not str(doc.get("paket") or "").strip():
        v.add("umum", "\"paket\" kosong")
    if v.total != expected:
        v.add("umum", f"jumlah soal {v.total}, padahal screenshot {expected}")
    seen = set()
    for i, s in enumerate(doc.get("soal", []), start=1):
        if not isinstance(s, dict):
            v.add(f"soal ke-{i}", "bukan objek JSON")
            continue
        kat = str(s.get("kategori") or "").upper()
        nomor = s.get("nomor")
        who = f"{kat or '?'} {nomor if nomor is not None else '?'}"
        if kat not in MAKS_NOMOR:
            v.add(who, f"kategori \"{s.get('kategori')}\" bukan TWK/TIU/TKP")
        if not isinstance(nomor, int) or isinstance(nomor, bool):
            v.add(who, "nomor bukan angka")
        elif kat in MAKS_NOMOR and not 1 <= nomor <= MAKS_NOMOR[kat]:
            v.add(who, f"nomor di luar 1–{MAKS_NOMOR[kat]}")
        key = (kat, nomor)
        if key in seen:
            v.add(who, "nomor ganda")
        seen.add(key)
        if kat in SUBTOPIK and s.get("subtopik") not in SUBTOPIK[kat]:
            v.add(who, f"subtopik \"{s.get('subtopik')}\" tidak ada di daftar {kat}")
        pil = s.get("pilihan")
        if not isinstance(pil, dict) or any(h not in pil for h in HURUF):
            v.add(who, "pilihan A–E tidak lengkap")
        if kat in ("TWK", "TIU"):
            if s.get("kunci") not in HURUF:
                v.add(who, f"kunci \"{s.get('kunci')}\" bukan A–E")
        elif kat == "TKP":
            skor = s.get("skor")
            if (not isinstance(skor, dict) or any(h not in skor for h in HURUF)
                    or any(not isinstance(skor[h], int) or not 1 <= skor[h] <= 5 for h in HURUF if h in skor)):
                v.add(who, "skor TKP 1–5 untuk A–E tidak lengkap")
        sid = f"{kat}-{nomor:03d}" if isinstance(nomor, int) else None
        gb = s.get("gambar")
        if gb:
            v.gambar += 1
            if gb not in available:
                v.add(who, f"gambar \"{gb}\" tidak ada di folder gambar/")
        if sid in figural and not gb:
            v.add(who, "soal bergambar tetapi \"gambar\" kosong")
        if s.get("bergambar") and not gb:
            v.add(who, "\"bergambar\": true tanpa \"gambar\"")
    return v


def build_import_zip(dest: str | os.PathLike, doc: dict, images: dict[str, bytes]) -> Path:
    """<paket>-siap-impor.zip berisi HANYA soal.json + gambar/*.png (yang dirujuk)."""
    dest = Path(dest)
    if dest.suffix.lower() != ".zip":
        dest = dest.with_suffix(".zip")
    used = sorted({s.get("gambar") for s in doc["soal"] if isinstance(s, dict) and s.get("gambar") in images})
    names = ["soal.json"] + used
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".zip", dir=dest.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("soal.json", json.dumps(doc, ensure_ascii=False, indent=1))
            for path in used:
                zf.writestr(path, images[path])
        with zipfile.ZipFile(tmp) as zf:
            if zf.testzip() is not None or sorted(zf.namelist()) != sorted(names):
                raise ImportError_("ZIP siap impor tidak valid")
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest
