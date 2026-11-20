"""Gabungkan gambar soal figural ke JSON hasil AI.

AI menulis penanda [GAMBAR:TIU-027-2] (dan/atau daftar id di "gambar") — bukan data gambar,
karena menyalin base64 lewat AI lambat & rawan rusak. Di sini setiap penanda diganti dengan
gambar asli (base64) dari soal.json / paket, sehingga hasilnya SATU file JSON lengkap.

Logika yang sama dipakai di gabung-gambar.html (JavaScript) di dalam ZIP.
"""
from __future__ import annotations

import json
import re
from typing import Any

MARKER = re.compile(r"\[\s*GAMBAR\s*:\s*([A-Za-z]+-\d+-\d+)\s*\]", re.IGNORECASE)


def parse_ai_json(text: str) -> Any:
    """Baca JSON hasil AI; toleran terhadap ```json ... ``` dan teks di luar JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
        if not starts:
            raise
        start = min(starts)
        end = max(t.rfind("}"), t.rfind("]"))
        return json.loads(t[start:end + 1])


def images_from_manifest(manifest: dict) -> dict:
    """soal.json -> {id_soal: [{id, bagian, data}, ...]}"""
    out = {}
    for s in manifest.get("soal", []):
        if s.get("gambar"):
            out[s["id"]] = [{"id": g["id"], "bagian": g.get("bagian", "gambar"), "data": g["data"]}
                            for g in s["gambar"]]
    return out


def _question_id(s: dict) -> str:
    if s.get("id"):
        return str(s["id"]).upper()
    try:
        return f"{str(s.get('kategori', '')).upper()}-{int(s.get('nomor')):03d}"
    except (TypeError, ValueError):
        return ""


def _markers(value, found: list):
    if isinstance(value, str):
        for m in MARKER.finditer(value):
            gid = m.group(1).upper()
            if gid not in found:
                found.append(gid)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k != "gambar":
                _markers(v, found)
    elif isinstance(value, list):
        for v in value:
            _markers(v, found)


def merge(ai: Any, images: dict) -> tuple[Any, dict]:
    """Kembalikan (json_lengkap, laporan). `images` = {id_soal: [{id, bagian, data}]}."""
    soal_list = ai.get("soal") if isinstance(ai, dict) else ai
    if not isinstance(soal_list, list):
        raise ValueError("JSON tidak berisi daftar soal (harus berupa {\"soal\": [...]} atau [...])")
    by_id = {g["id"].upper(): dict(g) for gs in images.values() for g in gs}
    report = {"soal": len(soal_list), "soal_bergambar": 0, "gambar": 0, "ditambahkan": [],
              "tidak_ditemukan": [], "soal_tidak_ada": []}
    seen_q = set()
    for s in soal_list:
        if not isinstance(s, dict):
            continue
        qid = _question_id(s)
        seen_q.add(qid)
        refs: list = []
        _markers(s, refs)
        for g in s.get("gambar") or []:              # daftar id dari AI
            gid = (g.get("id") if isinstance(g, dict) else g)
            if isinstance(gid, str):
                gid = gid.strip().strip("[]").replace("GAMBAR:", "").strip().upper()
                if gid and gid not in refs:
                    refs.append(gid)
        for g in images.get(qid, []):                # gambar yang lupa ditandai AI tetap masuk
            if g["id"].upper() not in refs:
                refs.append(g["id"].upper())
                report["ditambahkan"].append(g["id"])
        out = []
        for gid in refs:
            g = by_id.get(gid)
            if g is None:
                report["tidak_ditemukan"].append(gid)
                continue
            out.append({"id": g["id"], "bagian": g.get("bagian", "gambar"), "data": g["data"]})
        s["gambar"] = out
        if out:
            report["soal_bergambar"] += 1
            report["gambar"] += len(out)
    report["soal_tidak_ada"] = [q for q in images if q.upper() not in seen_q]
    if isinstance(ai, dict):
        ai["gambar_tertanam"] = True
    return ai, report


def report_text(rep: dict) -> str:
    lines = [f"{rep['soal']} soal · {rep['soal_bergambar']} soal bergambar · {rep['gambar']} gambar ditanam"]
    if rep["ditambahkan"]:
        lines.append(f"Gambar tanpa penanda (tetap dimasukkan ke soalnya): {', '.join(rep['ditambahkan'])}")
    if rep["tidak_ditemukan"]:
        lines.append(f"Penanda tanpa gambar (periksa id): {', '.join(rep['tidak_ditemukan'])}")
    if rep["soal_tidak_ada"]:
        lines.append(f"Soal bergambar yang tidak ada di JSON AI: {', '.join(rep['soal_tidak_ada'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------- alat HTML di dalam ZIP

def build_merge_html(package: str, images: dict) -> str:
    from .merge_html import TEMPLATE
    data = json.dumps(images, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__PAKET__", package).replace("__DATA__", data)
