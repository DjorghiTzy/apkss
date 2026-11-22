import json
import zipfile

from PIL import Image

from screenshot_manager.core import Package, build_prompt
from tests.fake_questions import make_alfaiz_question


def build(tmp_path, plan):
    pkg = Package(tmp_path / "ws", "Paket-01")
    for i, (cat, n) in enumerate(plan):
        p = tmp_path / f"s{i}.png"
        make_alfaiz_question(i + 1, "figural" if cat == "TIU" else "text")[0].save(p)
        pkg.add_image(p, cat, n)
    return pkg


def test_export_zip_exact_structure(tmp_path):
    pkg = build(tmp_path, [("TWK", 1), ("TWK", 2), ("TIU", 27), ("TKP", 1)])
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    assert res.path.name == "Paket-01.zip"
    with zipfile.ZipFile(res.path) as zf:
        assert sorted(zf.namelist()) == ["PROMPT.txt", "TIU/TIU-027.png", "TKP/TKP-001.png", "TWK/TWK-001.png",
                                         "TWK/TWK-002.png", "daftar.json"]
        daftar = json.loads(zf.read("daftar.json"))
        assert daftar == {"paket": "Paket 01", "jumlah": 4, "screenshot": [
            {"kategori": "TWK", "nomor": 1, "file": "TWK/TWK-001.png"},
            {"kategori": "TWK", "nomor": 2, "file": "TWK/TWK-002.png"},
            {"kategori": "TIU", "nomor": 27, "file": "TIU/TIU-027.png"},
            {"kategori": "TKP", "nomor": 1, "file": "TKP/TKP-001.png"}]}
        prompt = zf.read("PROMPT.txt").decode()
        assert prompt == build_prompt("Paket 01", 4)
        for n in zf.namelist():
            if n.endswith((".txt", ".json")):
                t = zf.read(n).decode()
                assert "data:image" not in t and ";base64," not in t and "gambar/" not in t


def test_prompt_template_filled_exactly():
    p = build_prompt("Paket 01", 110)
    assert p.startswith("Kerjakan SEMUANYA dalam SATU jawaban.")
    assert "TUGAS: salin 110 soal SKD CPNS" in p and "jumlah soal = 110;" in p
    assert "6. Buat Paket 01-siap-impor.zip = SEMUA isi ZIP asli + soal.json" in p
    assert '{"paket": "Paket 01", "soal": [' in p
    assert '"| Kuantitas P | Kuantitas Q |\\n|---|---|\\n| 2/3 dari 90 | 65 |"' in p
    assert "{{" not in p and '"gambar"' not in p


def test_export_check_blank_black_missing_duplicate(tmp_path):
    pkg = build(tmp_path, [("TWK", 1), ("TWK", 3), ("TIU", 1)])
    for name, color in (("hitam.png", "black"), ("kosong.png", "white")):
        Image.new("RGB", (800, 600), color).save(tmp_path / name)
    pkg.add_image(tmp_path / "hitam.png", "TWK", 2)
    pkg.add_image(tmp_path / "kosong.png", "TKP", 1)
    issues = pkg.export_check({"TWK": 4, "TIU": 1, "TKP": 1})
    joined = "\n".join(issues)
    assert "TWK-002.png: screenshot hitam" in joined
    assert "TKP-001.png: screenshot kosong" in joined
    assert "TWK: nomor hilang 4 (seharusnya 1–4)" in joined
    assert not any(i.startswith("TIU") for i in issues)
    # isi ganda (gambar sama di dua nomor) tetap terdeteksi walau slot berbeda
    it = pkg.find_slot("TWK", 3)
    it.fingerprint = pkg.find_slot("TWK", 1).fingerprint
    assert any("isinya sama dengan TWK-001.png" in i for i in pkg.export_check({"TWK": 3, "TIU": 1, "TKP": 1}))
    assert pkg.export_check({"TWK": 3, "TIU": 1, "TKP": 1, "X": 0}) != []
    default = pkg.export_check()                                  # 30 / 35 / 45
    assert any("TKP: nomor hilang 2–45" in i for i in default)


def test_ready_to_import_zip_is_export_plus_soal_json(tmp_path):
    pkg = build(tmp_path, [("TWK", 1), ("TIU", 27)])
    doc = {"paket": "Paket 01", "soal": []}
    res = pkg.export_zip(tmp_path / "Paket-01-siap-impor.zip", extra={"soal.json": json.dumps(doc).encode()})
    with zipfile.ZipFile(res.path) as zf:
        assert sorted(zf.namelist()) == ["PROMPT.txt", "TIU/TIU-027.png", "TWK/TWK-001.png", "daftar.json",
                                         "soal.json"]
        assert json.loads(zf.read("soal.json")) == doc
