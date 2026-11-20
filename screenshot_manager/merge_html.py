"""Template gabung-gambar.html (alat offline di dalam ZIP). Logika merge() = merge.py."""

TEMPLATE = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gabung Gambar — __PAKET__</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#5b6475; --accent:#1f6feb; --ok:#0b7a32; --warn:#9a6700; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14171c; --card:#1d2129; --ink:#e7eaf0; --muted:#9aa3b2; --accent:#5b9dff; --ok:#4cc27a; --warn:#e3b341; } }
  body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:720px; margin:0 auto; padding:24px 16px 48px; }
  .card { background:var(--card); border-radius:12px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-top:16px; }
  h1 { font-size:22px; margin:0 0 4px; } p { color:var(--muted); margin:6px 0; }
  label.drop { display:block; border:2px dashed var(--accent); border-radius:10px; padding:28px 16px; text-align:center; cursor:pointer; font-weight:600; }
  input[type=file] { display:none; }
  button { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:12px 18px; font-size:16px; font-weight:600; cursor:pointer; width:100%; }
  button:disabled { opacity:.4; cursor:default; }
  pre { white-space:pre-wrap; background:var(--bg); padding:12px; border-radius:8px; font-size:14px; }
  .ok { color:var(--ok); font-weight:600; } .warn { color:var(--warn); }
</style>
</head>
<body>
<main>
  <h1>Gabung Gambar — __PAKET__</h1>
  <p>JSON hasil AI hanya berisi penanda seperti <code>[GAMBAR:TIU-027-2]</code>. Alat ini menanam gambar aslinya
     (sudah tersimpan di file ini) ke setiap soal, sehingga hasilnya <b>satu file JSON lengkap dengan gambar</b>.
     Berjalan offline; tidak ada data yang dikirim ke mana pun.</p>
  <div class="card">
    <label class="drop" for="f">1. Pilih file JSON hasil AI (mis. __PAKET__.json)</label>
    <input id="f" type="file" accept=".json,.txt,application/json">
    <pre id="out">Belum ada file.</pre>
    <button id="dl" disabled>2. Unduh __PAKET__-lengkap.json</button>
  </div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
// MERGE-START
function parseAiJson(text) {
  let t = text.trim();
  if (t.startsWith("```")) { t = t.replace(/^```[a-zA-Z]*\s*/, "").replace(/\s*```\s*$/, ""); }
  try { return JSON.parse(t); } catch (e) {
    const starts = [t.indexOf("{"), t.indexOf("[")].filter(i => i >= 0);
    if (!starts.length) throw e;
    const end = Math.max(t.lastIndexOf("}"), t.lastIndexOf("]"));
    return JSON.parse(t.slice(Math.min(...starts), end + 1));
  }
}
function questionId(s) {
  if (s.id) return String(s.id).toUpperCase();
  const n = parseInt(s.nomor, 10);
  return isNaN(n) ? "" : String(s.kategori || "").toUpperCase() + "-" + String(n).padStart(3, "0");
}
function collectMarkers(value, found, key) {
  if (typeof value === "string") {
    const re = /\[\s*GAMBAR\s*:\s*([A-Za-z]+-\d+-\d+)\s*\]/gi; let m;
    while ((m = re.exec(value)) !== null) { const id = m[1].toUpperCase(); if (!found.includes(id)) found.push(id); }
  } else if (Array.isArray(value)) { value.forEach(v => collectMarkers(v, found)); }
  else if (value && typeof value === "object") {
    for (const k of Object.keys(value)) if (k !== "gambar") collectMarkers(value[k], found, k);
  }
}
function merge(ai, images) {
  const soal = Array.isArray(ai) ? ai : (ai && ai.soal);
  if (!Array.isArray(soal)) throw new Error('JSON tidak berisi daftar soal ({"soal": [...]} atau [...])');
  const byId = {};
  for (const q of Object.keys(images)) for (const g of images[q]) byId[g.id.toUpperCase()] = g;
  const rep = { soal: soal.length, soal_bergambar: 0, gambar: 0, ditambahkan: [], tidak_ditemukan: [], soal_tidak_ada: [] };
  const seen = new Set();
  for (const s of soal) {
    if (!s || typeof s !== "object" || Array.isArray(s)) continue;
    const qid = questionId(s); seen.add(qid);
    const refs = []; collectMarkers(s, refs);
    for (const g of (s.gambar || [])) {
      let gid = (g && typeof g === "object") ? g.id : g;
      if (typeof gid === "string") {
        gid = gid.trim().replace(/^\[|\]$/g, "").replace("GAMBAR:", "").trim().toUpperCase();
        if (gid && !refs.includes(gid)) refs.push(gid);
      }
    }
    for (const g of (images[qid] || [])) {
      const gid = g.id.toUpperCase();
      if (!refs.includes(gid)) { refs.push(gid); rep.ditambahkan.push(g.id); }
    }
    const out = [];
    for (const gid of refs) {
      const g = byId[gid];
      if (!g) { rep.tidak_ditemukan.push(gid); continue; }
      out.push({ id: g.id, bagian: g.bagian || "gambar", data: g.data });
    }
    s.gambar = out;
    if (out.length) { rep.soal_bergambar += 1; rep.gambar += out.length; }
  }
  rep.soal_tidak_ada = Object.keys(images).filter(q => !seen.has(q.toUpperCase()));
  if (!Array.isArray(ai)) ai.gambar_tertanam = true;
  return { merged: ai, report: rep };
}
// MERGE-END
(function () {
  if (typeof document === "undefined") return;
  const IMAGES = JSON.parse(document.getElementById("data").textContent);
  const out = document.getElementById("out"), dl = document.getElementById("dl");
  let result = null;
  document.getElementById("f").addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try {
      const { merged, report } = merge(parseAiJson(await file.text()), IMAGES);
      result = JSON.stringify(merged, null, 1);
      let txt = `✔ ${report.soal} soal · ${report.soal_bergambar} soal bergambar · ${report.gambar} gambar ditanam`;
      if (report.ditambahkan.length) txt += `\nGambar tanpa penanda (tetap dimasukkan): ${report.ditambahkan.join(", ")}`;
      if (report.tidak_ditemukan.length) txt += `\nPenanda tanpa gambar: ${report.tidak_ditemukan.join(", ")}`;
      if (report.soal_tidak_ada.length) txt += `\nSoal bergambar tidak ada di JSON AI: ${report.soal_tidak_ada.join(", ")}`;
      out.textContent = txt; out.className = "ok"; dl.disabled = false;
    } catch (err) { out.textContent = "✖ " + err.message; out.className = "warn"; dl.disabled = true; }
  });
  dl.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([result], { type: "application/json" }));
    a.download = "__PAKET__-lengkap.json"; a.click();
  });
})();
</script>
</body>
</html>
"""
