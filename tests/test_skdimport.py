import json
import zipfile

from screenshot_manager.skdimport import clean, parse_soal_json, validate


def good(kat, n, **kw):
    s = {"kategori": kat, "nomor": n,
         "subtopik": {"TWK": "Nasionalisme", "TIU": "Serial Figural", "TKP": "Pelayanan Publik"}[kat],
         "pertanyaan": "Teks", "pilihan": {h: f"isi {h}" for h in "ABCDE"},
         "kunci": None if kat == "TKP" else "C", "skor": {"A": 3, "B": 5, "C": 2, "D": 1, "E": 4} if kat == "TKP" else None,
         "bergambar": False, "pembahasan": "x", "catatan": None}
    s.update(kw)
    return s


def test_parse_paste_with_code_fence_and_text():
    doc = {"paket": "Paket 01", "soal": [good("TWK", 1)]}
    assert parse_soal_json("Berikut hasilnya:\n```json\n" + json.dumps(doc) + "\n```\nSelesai")["paket"] == "Paket 01"


def test_clean_renames_and_strips_markers():
    s = good("TIU", 27, bergambar=True)
    s["opsi"] = s.pop("pilihan")
    s["jawaban"] = s.pop("kunci")
    s["pertanyaan"] = "Perhatikan gambar berikut! [gambar]"
    s["opsi"]["A"] = "[GAMBAR:TIU-027-2]"
    doc, changes = clean({"paket": "Paket 01", "soal": [s]})
    t = doc["soal"][0]
    assert t["pilihan"]["A"] == "" and t["kunci"] == "C" and "opsi" not in t and "jawaban" not in t
    assert t["pertanyaan"] == "Perhatikan gambar berikut!"
    assert len(changes) == 3


def test_validate_reports_per_question_and_counts():
    soal = [good("TWK", 1), good("TWK", 1), good("TWK", 31), good("TIU", 2, kunci="Z"),
            good("TIU", 3, subtopik="Figural"), good("TKP", 4, skor={"A": 1, "B": 9}),
            good("TWK", 6, bergambar=True), good("TIU", 27, bergambar=True),
            {**good("TWK", 5), "pilihan": {"A": "a"}}]
    v = validate({"paket": "", "soal": soal}, 110)
    joined = "\n".join(f"{w}: {m}" for w, m in v.issues)
    for frag in ["umum: \"paket\" kosong", "umum: jumlah soal 9, padahal screenshot 110", "TWK 1: nomor ganda",
                 "TWK 31: nomor di luar 1–30", "TIU 2: kunci \"Z\" bukan A–E", "TIU 3: subtopik",
                 "TKP 4: skor TKP", "TWK 6: \"bergambar\": true padahal bukan TIU",
                 "TWK 5: pilihan A–E tidak lengkap"]:
        assert frag in joined, (frag, joined)
    assert "TIU 27" not in joined and v.gambar == 2
    ok = validate({"paket": "Paket 01", "soal": [good("TWK", 1), good("TKP", 1)]}, 2)
    assert ok.issues == []
