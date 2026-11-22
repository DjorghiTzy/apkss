import json
import zipfile

import pytest
from PIL import Image

from screenshot_manager.core import Package
from screenshot_manager.figures import detect_question_figure
from tests.fake_questions import make_alfaiz_question


@pytest.mark.parametrize("header", [True, False])
@pytest.mark.parametrize("seed", range(1, 7))
def test_text_and_table_questions_are_not_figural(seed, header):
    """Logo AL FAIZ, tombol Tampilkan/Selanjutnya, badge Salah, tabel bergaris tipis: bukan gambar."""
    for kind in ("text", "table"):
        img, _ = make_alfaiz_question(seed, kind, header)
        assert detect_question_figure(img).status == "none", kind


@pytest.mark.parametrize("header", [True, False])
@pytest.mark.parametrize("seed", range(1, 7))
def test_figural_question_cropped_exactly(seed, header):
    img, truth = make_alfaiz_question(seed, "figural", header)
    r = detect_question_figure(img)
    assert r.status == "ok", r.reason
    b = r.box
    x, y, w, h = truth
    # panel + margin 12 px, tidak lebih
    assert abs(b["x"] - (x + 4 - 12)) <= 2 and abs(b["y"] - (y - 12)) <= 2
    assert abs(b["x"] + b["w"] - (x + w - 4 + 12)) <= 3 and abs(b["y"] + b["h"] - (y + h + 12)) <= 3
    assert b["w"] >= 300 and b["h"] >= 100
    crop = img.crop((b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])).convert("RGB")
    import numpy as np
    a = np.asarray(crop, dtype=np.int16)
    px = a.reshape(-1, 3).tolist()
    assert not any(g > r_ + 40 and g > bb + 40 for r_, g, bb in px), "ada hijau"
    assert not any(r_ > g + 60 and r_ > bb + 60 for r_, g, bb in px), "ada merah"


@pytest.mark.parametrize("seed", range(1, 5))
def test_images_inside_options_need_manual_cut(seed):
    img, _ = make_alfaiz_question(seed, "opsi")
    assert detect_question_figure(img).status == "manual"


def build_package(tmp_path):
    pkg = Package(tmp_path / "ws", "Paket-01")
    plan = [("TWK", 1, "text"), ("TIU", 27, "figural"), ("TIU", 28, "figural"), ("TIU", 29, "opsi"),
            ("TIU", 30, "table"), ("TKP", 1, "text")]
    for i, (cat, n, kind) in enumerate(plan):
        img, _ = make_alfaiz_question(i + 1, kind)
        p = tmp_path / f"s{i}.png"
        img.save(p)
        pkg.add_image(p, cat, n)
    return pkg


def test_export_zip_structure_for_chatgpt(tmp_path):
    pkg = build_package(tmp_path)
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    assert res.path.name == "Paket-01.zip" and res.figural == 2 and res.manual_pending == 1
    with zipfile.ZipFile(res.path) as zf:
        names = sorted(zf.namelist())
        assert names == sorted(["PROMPT.txt", "daftar.json", "TWK/TWK-001.png", "TIU/TIU-027.png",
                                "TIU/TIU-028.png", "TIU/TIU-029.png", "TIU/TIU-030.png", "TKP/TKP-001.png",
                                "gambar/TIU-027.png", "gambar/TIU-028.png"])
        daftar = json.loads(zf.read("daftar.json"))
        assert daftar["paket"] == "Paket 01"
        assert daftar["bergambar"] == ["TIU-027", "TIU-028"]
        assert daftar["screenshot"][0] == {"id": "TWK-001", "kategori": "TWK", "nomor": 1, "file": "TWK/TWK-001.png"}
        assert len(daftar["screenshot"]) == 6
        prompt = zf.read("PROMPT.txt").decode()
        assert "Kerjakan SEMUA 6 soal" in prompt
        assert "Hanya soal ini yang bergambar: TIU 27 (gambar/TIU-027.png), TIU 28 (gambar/TIU-028.png)." in prompt
        assert '"paket": "Paket 01"' in prompt and "{{" not in prompt
        for n in zf.namelist():                                   # tidak ada base64 di mana pun
            if n.endswith((".txt", ".json")):
                assert "data:image" not in zf.read(n).decode() and ";base64," not in zf.read(n).decode()
        with zf.open("gambar/TIU-027.png") as f:
            g = Image.open(f)
            assert g.size[0] >= 300 and g.size[1] >= 100


def test_manual_cut_and_drop(tmp_path):
    pkg = build_package(tmp_path)
    opsi = pkg.find_slot("TIU", 29)
    pkg.update_figures(opsi.id)
    assert opsi.figure_manual and not opsi.figures
    pkg.set_figure_box(opsi.id, {"x": 20, "y": 120, "w": 400, "h": 150})
    assert opsi.figures == [{"x": 20, "y": 120, "w": 400, "h": 150}] and not opsi.figure_manual
    assert opsi.figure_by_hand
    pkg.update_figures(opsi.id)                                    # potongan manual tidak ditimpa
    assert opsi.figures[0]["w"] == 400
    pkg.set_figural(pkg.find_slot("TIU", 28).id, False)            # buang
    res = pkg.export_zip(tmp_path / "x.zip")
    with zipfile.ZipFile(res.path) as zf:
        assert sorted(n for n in zf.namelist() if n.startswith("gambar/")) == ["gambar/TIU-027.png",
                                                                               "gambar/TIU-029.png"]
        assert json.loads(zf.read("daftar.json"))["bergambar"] == ["TIU-027", "TIU-029"]
    assert res.manual_pending == 0
