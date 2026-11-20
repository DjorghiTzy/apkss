import json
import zipfile

import pytest
from PIL import Image

from screenshot_manager.core import Package
from screenshot_manager.figures import detect_figures
from tests.fake_questions import make_question


@pytest.mark.parametrize("seed", range(1, 9))
def test_text_question_has_no_figures(seed):
    img, truth = make_question(seed)
    assert truth == []
    assert detect_figures(img) == []


def covers(fig, box, tol=12):
    x, y, w, h = box
    return (fig["x"] <= x + tol and fig["y"] <= y + tol and fig["x"] + fig["w"] >= x + w - tol
            and fig["y"] + fig["h"] >= y + h - tol)


@pytest.mark.parametrize("seed", range(1, 6))
def test_figural_question_all_parts(seed):
    img, truth = make_question(seed, fig_soal=True, fig_opsi=True, fig_pembahasan=True)
    figs = detect_figures(img)
    assert [f["bagian"] for f in figs] == [t[0] for t in truth], figs
    for f, (_, box) in zip(figs, truth):
        assert covers(f, box), (f, box)
        assert f["w"] < box[2] + 40 and f["h"] < box[3] + 40, (f, box)     # tidak kebesaran


def test_only_question_figure():
    img, truth = make_question(3, fig_soal=True)
    figs = detect_figures(img)
    assert [f["bagian"] for f in figs] == ["soal"]


def test_zip_contains_figural_json_with_embedded_images(tmp_path):
    pkg = Package(tmp_path / "ws", "Paket-01")
    plain, _ = make_question(1)
    fig, truth = make_question(2, fig_soal=True, fig_opsi=True)
    plain.save(tmp_path / "a.png")
    fig.save(tmp_path / "b.png")
    pkg.add_image(tmp_path / "a.png", "TIU", 1)
    it = pkg.add_image(tmp_path / "b.png", "TIU", 2).item
    assert not it.figures_checked
    assert len(pkg.update_figures(it.id)) == 6
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    assert res.figural == 1
    with zipfile.ZipFile(res.path) as zf:
        names = set(zf.namelist())
        assert {"TIU/TIU-001.png", "TIU/TIU-002.png", "figural/index.json", "figural/TIU-002.json"} <= names
        assert {f"figural/TIU-002/{i}.png" for i in range(1, 7)} <= names
        assert not any(n.startswith("figural/TIU-001") for n in names)       # soal teks: tanpa JSON
        doc = json.loads(zf.read("figural/TIU-002.json"))
        assert doc["kategori"] == "TIU" and doc["nomor"] == 2 and doc["file_soal"] == "TIU/TIU-002.png"
        assert [g["bagian"] for g in doc["gambar"]] == ["soal", "opsi A", "opsi B", "opsi C", "opsi D", "opsi E"]
        g = doc["gambar"][0]
        assert g["data"].startswith("data:image/png;base64,")
        import base64, io
        emb = Image.open(io.BytesIO(base64.b64decode(g["data"].split(",", 1)[1])))
        assert emb.size == (g["lebar"], g["tinggi"])
        assert zf.read(g["file"]) == base64.b64decode(g["data"].split(",", 1)[1])
        idx = json.loads(zf.read("figural/index.json"))
        assert idx["soal_bergambar"][0]["id"] == "TIU-002"
    # tandai bukan bergambar -> tidak ada JSON
    pkg.set_figural(it.id, False)
    res = pkg.export_zip(tmp_path / "x.zip")
    assert res.figural == 0
    with zipfile.ZipFile(res.path) as zf:
        assert not any(n.startswith("figural/") for n in zf.namelist())
    # tanpa opsi figural di ZIP
    pkg.set_figural(it.id, True)
    res = pkg.export_zip(tmp_path / "y.zip", figural=False)
    with zipfile.ZipFile(res.path) as zf:
        assert sorted(zf.namelist()) == ["TIU/TIU-001.png", "TIU/TIU-002.png"]
