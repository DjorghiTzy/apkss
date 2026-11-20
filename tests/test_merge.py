import base64
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from screenshot_manager.core import Package
from screenshot_manager.merge import build_merge_html, images_from_manifest, merge, parse_ai_json
from screenshot_manager.merge_html import TEMPLATE
from tests.fake_questions import make_question

IMAGES = {
    "TIU-027": [{"id": "TIU-027-1", "bagian": "soal", "data": "data:image/png;base64,AAA"},
                {"id": "TIU-027-2", "bagian": "opsi A", "data": "data:image/png;base64,BBB"},
                {"id": "TIU-027-3", "bagian": "opsi B", "data": "data:image/png;base64,CCC"}],
    "TIU-030": [{"id": "TIU-030-1", "bagian": "soal", "data": "data:image/png;base64,DDD"}],
    "TIU-031": [{"id": "TIU-031-1", "bagian": "soal", "data": "data:image/png;base64,EEE"}],
}


def ai_output():
    return {"paket": "Paket-01", "jumlah": 4, "soal": [
        {"id": "TWK-001", "kategori": "TWK", "nomor": 1, "pertanyaan": "Teks biasa", "gambar": []},
        {"id": "TIU-027", "kategori": "TIU", "nomor": 27, "pertanyaan": "Lanjutkan pola [GAMBAR:TIU-027-1]",
         "opsi": {"A": "[GAMBAR:TIU-027-2]", "B": "[ gambar : tiu-027-3 ]"}, "gambar": ["TIU-027-1"]},
        {"kategori": "TIU", "nomor": 30, "pertanyaan": "AI lupa menulis penanda", "gambar": []},
        {"id": "TIU-029", "kategori": "TIU", "nomor": 29, "pertanyaan": "salah id [GAMBAR:TIU-099-1]"},
    ]}


def test_merge_python():
    merged, rep = merge(ai_output(), IMAGES)
    s = {x.get("id", f"{x['kategori']}-{x['nomor']:03d}"): x for x in merged["soal"]}
    assert s["TWK-001"]["gambar"] == []
    assert [g["id"] for g in s["TIU-027"]["gambar"]] == ["TIU-027-1", "TIU-027-2", "TIU-027-3"]
    assert s["TIU-027"]["gambar"][1] == {"id": "TIU-027-2", "bagian": "opsi A", "data": "data:image/png;base64,BBB"}
    assert [g["id"] for g in s["TIU-030"]["gambar"]] == ["TIU-030-1"]           # lupa ditandai -> tetap masuk
    assert rep["ditambahkan"] == ["TIU-030-1"]
    assert rep["tidak_ditemukan"] == ["TIU-099-1"]
    assert rep["soal_tidak_ada"] == ["TIU-031"]
    assert rep["gambar"] == 4 and rep["soal_bergambar"] == 2
    assert merged["gambar_tertanam"] is True
    # teks penanda tetap (aplikasi/web menampilkan gambar di posisinya)
    assert s["TIU-027"]["opsi"]["A"] == "[GAMBAR:TIU-027-2]"


def test_parse_ai_json_tolerant():
    raw = json.dumps(ai_output())
    assert parse_ai_json("```json\n" + raw + "\n```")["paket"] == "Paket-01"
    assert parse_ai_json("Berikut hasilnya:\n" + raw + "\nSelesai.")["jumlah"] == 4
    assert parse_ai_json(json.dumps(ai_output()["soal"]))[0]["id"] == "TWK-001"


def run_js_merge(ai, images):
    js = re.search(r"// MERGE-START(.*)// MERGE-END", TEMPLATE, re.S).group(1)
    prog = js + "\nconst inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));" \
                "\nconst r = merge(parseAiJson(inp.text), inp.images);" \
                "\nprocess.stdout.write(JSON.stringify({merged: r.merged, report: r.report}));"
    out = subprocess.run(["node", "-e", prog], input=json.dumps({"text": json.dumps(ai), "images": images}),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(subprocess.run(["which", "node"], capture_output=True).returncode != 0, reason="node tidak ada")
def test_html_tool_matches_python():
    py_merged, py_rep = merge(ai_output(), IMAGES)
    js = run_js_merge(ai_output(), IMAGES)
    assert js["merged"] == py_merged
    assert js["report"] == py_rep


@pytest.mark.skipif(subprocess.run(["which", "node"], capture_output=True).returncode != 0, reason="node tidak ada")
def test_end_to_end_zip_ai_json_merge(tmp_path):
    pkg = Package(tmp_path / "ws", "Paket-01")
    plain, _ = make_question(1)
    fig, _ = make_question(2, fig_soal=True, fig_opsi=True)
    plain.save(tmp_path / "a.png")
    fig.save(tmp_path / "b.png")
    pkg.add_image(tmp_path / "a.png", "TIU", 1)
    pkg.add_image(tmp_path / "b.png", "TIU", 2)
    res = pkg.export_zip(tmp_path / "Paket-01.zip")
    with zipfile.ZipFile(res.path) as zf:
        html = zf.read("gabung-gambar.html").decode()
        manifest = json.loads(zf.read("soal.json"))
        prompt = zf.read("PROMPT.txt").decode()
        crop_png = zf.read("figural/TIU-002/2.png")
    assert "gabung-gambar.html" in prompt and "JANGAN menyalin data base64" in prompt
    # "hasil AI": hanya penanda, tanpa data
    ai = {"paket": "Paket-01", "soal": [
        {"id": "TIU-001", "kategori": "TIU", "nomor": 1, "pertanyaan": "teks", "gambar": []},
        {"id": "TIU-002", "kategori": "TIU", "nomor": 2, "pertanyaan": "pola [GAMBAR:TIU-002-1]",
         "opsi": {k: f"[GAMBAR:TIU-002-{i + 2}]" for i, k in enumerate("ABCDE")},
         "gambar": [f"TIU-002-{i}" for i in range(1, 7)]}]}
    # data yang tertanam di HTML = gambar dari soal.json
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
                      .group(1).replace("<\\/", "</"))
    assert data == images_from_manifest(manifest)
    js = run_js_merge(ai, data)
    g2 = js["merged"]["soal"][1]["gambar"]
    assert [g["id"] for g in g2] == [f"TIU-002-{i}" for i in range(1, 7)]
    assert base64.b64decode(g2[1]["data"].split(",", 1)[1]) == crop_png                 # gambar asli persis
    assert Image.open(io.BytesIO(crop_png)).size[0] > 20
    assert js["report"]["tidak_ditemukan"] == [] and js["report"]["gambar"] == 6
    # aplikasi menghasilkan hal yang sama dari data paket
    py, _ = merge(json.loads(json.dumps(ai)), pkg.figure_images())
    assert py == js["merged"]


def test_html_tool_in_real_browser(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    html = build_merge_html("Paket-01", IMAGES)
    page_path = tmp_path / "gabung-gambar.html"
    page_path.write_text(html, encoding="utf-8")
    ai_path = tmp_path / "Paket-01.json"
    ai_path.write_text("```json\n" + json.dumps(ai_output()) + "\n```", encoding="utf-8")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium tidak tersedia: {exc}")
        page = browser.new_page(accept_downloads=True)
        page.goto(page_path.as_uri())
        assert page.locator("#dl").is_disabled()
        page.set_input_files("#f", str(ai_path))
        page.wait_for_function("!document.getElementById('dl').disabled")
        txt = page.locator("#out").inner_text()
        assert "4 gambar ditanam" in txt and "TIU-030-1" in txt and "TIU-099-1" in txt
        with page.expect_download() as d:
            page.click("#dl")
        dl = d.value
        assert dl.suggested_filename == "Paket-01-lengkap.json"
        out = json.loads(Path(dl.path()).read_text())
        browser.close()
    assert out == merge(ai_output(), IMAGES)[0]
