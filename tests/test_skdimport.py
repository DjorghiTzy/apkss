import json
import zipfile

from screenshot_manager.skdimport import build_import_zip, clean, parse_soal_json, validate


def good(kat, n, **kw):
    s = {"kategori": kat, "nomor": n,
         "subtopik": {"TWK": "Nasionalisme", "TIU": "Serial Figural", "TKP": "Pelayanan Publik"}[kat],
         "pertanyaan": "Teks", "pilihan": {h: f"isi {h}" for h in "ABCDE"},
         "kunci": None if kat == "TKP" else "C", "skor": {"A": 3, "B": 5, "C": 2, "D": 1, "E": 4} if kat == "TKP" else None,
         "bergambar": False, "gambar": None, "pembahasan": "x", "catatan": None}
    s.update(kw)
    return s


def test_parse_paste_with_code_fence_and_text():
    doc = {"paket": "Paket 01", "soal": [good("TWK", 1)]}
    assert parse_soal_json("Berikut hasilnya:\n```json\n" + json.dumps(doc) + "\n```\nSelesai")["paket"] == "Paket 01"


def test_clean_renames_and_strips_markers():
    s = good("TIU", 27, bergambar=True, gambar="gambar/TIU-027.png")
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
            good("TIU", 27, bergambar=True, gambar="gambar/TIU-099.png"), good("TIU", 28),
            {**good("TWK", 5), "pilihan": {"A": "a"}}]
    v = validate({"paket": "", "soal": soal}, {"gambar/TIU-027.png", "gambar/TIU-028.png"}, 110,
                 {"TIU-027", "TIU-028"})
    msgs = [f"{w}: {m}" for w, m in v.issues]
    joined = "\n".join(msgs)
    for frag in ["umum: \"paket\" kosong", "umum: jumlah soal 9, padahal screenshot 110", "TWK 1: nomor ganda",
                 "TWK 31: nomor di luar 1–30", "TIU 2: kunci \"Z\" bukan A–E", "TIU 3: subtopik",
                 "TKP 4: skor TKP", "TIU 27: gambar \"gambar/TIU-099.png\" tidak ada",
                 "TIU 28: soal bergambar tetapi \"gambar\" kosong", "TWK 5: pilihan A–E tidak lengkap"]:
        assert frag in joined, (frag, joined)
    ok = validate({"paket": "Paket 01", "soal": [good("TWK", 1), good("TKP", 1)]}, set(), 2, set())
    assert ok.issues == []


def test_build_import_zip_only_soal_json_and_used_images(tmp_path):
    doc = {"paket": "Paket 01", "soal": [good("TWK", 1), good("TIU", 27, bergambar=True, gambar="gambar/TIU-027.png")]}
    out = build_import_zip(tmp_path / "Paket-01-siap-impor", doc,
                           {"gambar/TIU-027.png": b"PNG27", "gambar/TIU-030.png": b"PNG30"})
    assert out.name == "Paket-01-siap-impor.zip"
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["gambar/TIU-027.png", "soal.json"]
        assert json.loads(zf.read("soal.json")) == doc
        assert zf.read("gambar/TIU-027.png") == b"PNG27"
