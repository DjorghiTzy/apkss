"""'Buat ZIP siap impor': isi ZIP ekspor + soal.json dari ChatGPT -> <paket>-siap-impor.zip untuk SKD Intelligence."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


def validate(doc: dict, expected: int) -> Validation:
    """expected: jumlah screenshot di paket."""
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
        if s.get("bergambar") is True:
            v.gambar += 1
            if kat != "TIU":
                v.add(who, "\"bergambar\": true padahal bukan TIU (TWK & TKP harus false)")
        for k in ("pertanyaan", "pembahasan"):
            if k not in s:
                v.add(who, f"kolom \"{k}\" tidak ada")
    return v
