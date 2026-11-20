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
        assert {"TIU/TIU-001.png", "TIU/TIU-002.png", "soal.json", "PROMPT.txt"} <= names
        assert {f"figural/TIU-002/{i}.png" for i in range(1, 7)} <= names
        assert not any(n.startswith("figural/TIU-001") for n in names)       # soal teks: tanpa gambar
        man = json.loads(zf.read("soal.json"))
        assert man["jumlah"] == {"TIU": 2, "total": 2, "bergambar": 1}
        assert [e["id"] for e in man["soal"]] == ["TIU-001", "TIU-002"]
        e1, e2 = man["soal"]
        assert e1["bergambar"] is False and "gambar" not in e1
        assert e2["bergambar"] is True and e2["file"] == "TIU/TIU-002.png"
        assert [g["bagian"] for g in e2["gambar"]] == ["soal", "opsi A", "opsi B", "opsi C", "opsi D", "opsi E"]
        g = e2["gambar"][0]
        assert g["id"] == "TIU-002-1" and g["data"].startswith("data:image/png;base64,")
        import base64, io
        raw = base64.b64decode(g["data"].split(",", 1)[1])
        assert Image.open(io.BytesIO(raw)).size == (g["kotak"]["w"], g["kotak"]["h"])
        assert zf.read(g["file"]) == raw
        prompt = zf.read("PROMPT.txt").decode()
        assert "SEKALIGUS" in prompt and "2 soal" in prompt
    # tandai bukan bergambar -> tidak ada gambar
    pkg.set_figural(it.id, False)
    res = pkg.export_zip(tmp_path / "x.zip")
    assert res.figural == 0
    with zipfile.ZipFile(res.path) as zf:
        assert not any(n.startswith("figural/") for n in zf.namelist())
        assert json.loads(zf.read("soal.json"))["soal"][1]["bergambar"] is False
    # tanpa opsi figural di ZIP
    pkg.set_figural(it.id, True)
    res = pkg.export_zip(tmp_path / "y.zip", figural=False)
    with zipfile.ZipFile(res.path) as zf:
        assert sorted(zf.namelist()) == ["TIU/TIU-001.png", "TIU/TIU-002.png"]
