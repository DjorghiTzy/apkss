# Screenshot Manager

Aplikasi desktop Windows untuk mengatur screenshot soal SKD (TWK/TIU/TKP) yang diambil manual
dengan Snipping Tool: memantau folder Screenshots, memberi nama `KATEGORI-NNN.png` sesuai metadata
yang Anda atur, mendeteksi duplikat, lalu membuat ZIP siap impor.

Tanpa login, tanpa internet, tanpa OCR/AI. Aplikasi tidak menyentuh browser, cookie, maupun akun.

## Instalasi di Windows

**Pilihan A — Installer**: unduh `ScreenshotManager-Setup-x.y.z.exe` dari halaman
[Releases](https://github.com/DjorghiTzy/apkss/releases/latest) lalu jalankan.
Tidak butuh hak admin; terpasang di `%LOCALAPPDATA%\Programs\ScreenshotManager`.

**Pilihan B — Build sendiri** (sekali saja):
1. Pasang Python 3.12 64-bit dari python.org, centang **Add python.exe to PATH**.
2. (Opsional, untuk installer) pasang Inno Setup 6 dari jrsoftware.org.
3. Klik dua kali `build_windows.bat`. Skrip memasang dependensi, menjalankan tes, lalu membuat:
   - `dist\ScreenshotManager\ScreenshotManager.exe` (langsung jalan)
   - `dist\ScreenshotManager-portable.zip`
   - `dist\ScreenshotManager-Setup-1.0.0.exe` (jika Inno Setup terpasang)

**Menjalankan dari kode** (tanpa build): `pip install -r requirements.txt` lalu `python run.py`.

## Tampilan (satu halaman)

| Area | Isi |
|---|---|
| Atas | Status **● MEMANTAU**, folder Screenshots, Ganti Folder, Refresh (F5), Pilih File Manual, Tempel dari Clipboard (Ctrl+Shift+V), Selalu di atas |
| Banner | Konfirmasi besar: hijau `✔ DITERIMA: TWK-001.png`, merah `DUPLIKAT`, kuning `MASUK TANPA NOMOR` |
| Kiri | Paket, tombol kategori TWK/TIU/TKP (+ Kategori), nomor berikutnya, mode Otomatis/Manual, nama file target, status SIAP/BELUM SIAP, tombol Siapkan / Batalkan / Ulangi Nomor / Ubah Nomor |
| Tengah | Daftar screenshot: preview, kategori, nomor, nama file, file asli. Ubah Kategori/Nomor, Hapus dari Daftar, Ulangi Penamaan, Buka Workspace |
| Kanan | Preview besar baris terpilih |
| Bawah | Log kejadian, jumlah per kategori, tombol **BUAT ZIP** |

Judul jendela juga menunjukkan status, mis. `Screenshot Manager — SIAP: TWK-005.png [Paket-01]`.

## ⚡ Tangkap Otomatis (semua soal sekaligus)

Aplikasi mengerjakan semuanya sendiri: klik nomor soal di website, scroll ke atas, potret,
scroll ke bawah sambil memotret dan menyambung sampai pembahasan habis, lalu lanjut ke soal
berikutnya. Kategori & nomor mengikuti rencana yang Anda isi (bukan OCR/AI). Aplikasi hanya
menggerakkan mouse/keyboard seperti pengguna; tidak menyentuh login, cookie, atau data browser.

Alurnya mengikuti Privat Alfaiz: pilih **Tipe Soal** TWK → klik nomor 1…30 di **Daftar Soal** →
pilih Tipe Soal TIU → 1…35 → pilih TKP → 1…45. **F10** = mulai / berhenti dari jendela mana pun.

**Cara tercepat (tanpa atur manual):**
1. Buka halaman **pembahasan** tryout di browser, layar penuh, dengan Tipe Soal dan seluruh
   Daftar Soal terlihat.
2. Tekan **F10** (atau klik **🪄 ATUR OTOMATIS**). Aplikasi bersembunyi, mengenali Daftar Soal,
   tombol Tipe Soal, jumlah soal tiap kategori, dan area konten sendiri, lalu menampilkan
   gambar hasil deteksi. Klik **▶ Simpan & Mulai Sekarang**.
3. Tunggu sampai selesai → **BUAT ZIP**. F10 berikutnya langsung mulai/berhenti/melanjutkan.

**Kecepatan (simulasi, website memuat soal 0,3 dtk):** Atur Otomatis ±2,5 detik. Dengan scroll
halus browser dimatikan: setiap soal < 1 detik (rata-rata ±0,5 detik, terlama ±0,6 detik; 110 soal
≈ 1 menit). Dengan scroll halus menyala, soal panjang ±1,05 detik karena animasi scroll browser —
Atur Otomatis mendeteksi hal ini dan menunjukkan cara mematikannya. Tanpa jeda tetap: layar dipantau
tiap 15 ms; scroll difoto begitu pergeserannya tepat satu langkah; ganti Tipe Soal tidak menunggu;
penyimpanan & deteksi gambar berjalan di latar belakang. Laporan akhir merinci waktu per soal.

**Lebih cepat lagi:** matikan scroll halus di browser — buka `brave://flags/#smooth-scrolling`
(Chrome: `chrome://flags/#smooth-scrolling`, Edge: `edge://flags/#smooth-scrolling`) → **Disabled** →
Relaunch. Tanpa itu sekitar 1,5 detik per soal. Zoom browser yang lebih kecil (mis. 80%) juga
mengurangi jumlah scroll per soal. Aplikasi tidak memakai jeda tetap: foto diambil begitu halaman
berganti dan diam, jadi tetap akurat walaupun cepat.

Area potong selalu pas di tepi kartu soal. Jika ada tulisan yang menyentuh tepi (tanda terpotong),
area otomatis diperlebar sampai ruang kosong, soal itu diambil ulang, dan area baru disimpan.

**Atur manual (bila deteksi otomatis gagal):**

1. Di browser: buka halaman **pembahasan** tryout, layar penuh, seluruh Daftar Soal terlihat.
   Perkecil zoom (Ctrl+−) bila perlu.
2. Screenshot Manager → **Atur Area…** → **Ambil Layar Acuan** → seret kotak menutupi area konten
   soal (tanpa grid nomor, tab browser, taskbar, dan header yang menempel saat di-scroll) → OK.
3. **⚡ TANGKAP OTOMATIS…** → isi jumlah soal (TWK 30, TIU 35, TKP 45), pilih penomoran,
   biarkan "Nomor mulai dari 1 di tiap Tipe Soal" tercentang → **Tandai Posisi di Layar…** → klik
   tombol nomor 1, nomor 2, dan nomor 6 (tepat di bawah 1) → jumlah kolom 5 →
   **Tandai Dropdown Tipe Soal…** → klik tombol dropdown (tertutup), lalu dalam 5 detik buka
   dropdown di browser → klik pilihan TWK, TIU, TKP di gambar.
4. **MULAI TANGKAP OTOMATIS** (atau tekan **F10**). Jangan sentuh mouse/keyboard. Berhenti
   kapan saja dengan **F10**, **ESC**, atau mouse ke **pojok kiri atas**. Perkiraan 6–12 detik
   per soal. F10 berikutnya melanjutkan soal yang belum ada.
5. Setelah selesai, jendela muncul lagi dengan laporan; cek baris yang "perlu dicek", lalu
   **BUAT ZIP**.

Menjalankan ulang melanjutkan dari yang belum ada: soal yang sudah tersimpan dilewati, soal yang
terpotong saat dihentikan dibuang dan diambil ulang utuh. Navigasi gagal (halaman tidak
berganti) menghentikan proses dengan pesan yang jelas, tidak menimpa apa pun.

Tombol **📷 Ambil Layar** (Ctrl+Shift+S) memotret satu layar penuh seperti Win+PrtScn, untuk
pemakaian per soal.

## Alur kerja Claude (soal + pembahasan lengkap)

**Sekali di awal: atur area potong**
1. Buka halaman soal (mode pembahasan) di browser.
2. Di Screenshot Manager: **Atur Area…** → **Tunggu Screenshot** → tekan **Win+PrtScn**.
   Screenshot acuan ini tidak masuk daftar.
3. Seret kotak menutupi area konten soal (soal, pilihan, jawaban, pembahasan); jangan sertakan tab
   browser dan taskbar → OK. **Potong otomatis** menjadi aktif.

Tip: perkecil zoom browser (Ctrl+−, mis. 67%) agar soal + pembahasan muat dalam satu layar.

**Untuk setiap soal**
1. Klik nomor soal di navigasi website, baca kategorinya.
2. Di Screenshot Manager: klik kategori (TWK/TIU/TKP), isi **Nomor soal berikutnya**, klik
   **Siapkan Screenshot Berikutnya** (Ctrl+Enter) → status **● SIAP MENERIMA**.
   Pada mode **Otomatis** langkah ini cukup sekali; nomor naik sendiri setelah tiap soal.
3. Tekan **Win+PrtScn** (Windows menyimpan layar penuh ke `Pictures\Screenshots`), lalu aplikasi
   memotong ke area soal → banner hijau `✔ DITERIMA: TWK-001.png (dipotong)`.
4. Pembahasan belum terlihat semua? Scroll halaman ke bawah, klik **+ Tambah Bagian Lanjutan**
   (Ctrl+B), tekan **Win+PrtScn** lagi → `✔ BAGIAN 2 DISAMBUNG ke TWK-001.png`. Bagian yang
   tumpang tindih karena scroll dibuang otomatis. Ulangi sampai pembahasan habis.
5. Lanjut ke soal berikutnya.

Snipping Tool (Win+Shift+S) tetap bisa dipakai: potongan manual yang ukurannya bukan layar penuh
tidak dipotong lagi.

Tombol lain:
- **Batalkan** (Esc): batalkan persiapan / bagian lanjutan; screenshot berikutnya masuk *tanpa nomor*.
- **Ulangi Nomor**: screenshot berikutnya **menggantikan** screenshot terakhir (atau baris terpilih),
  lalu target kembali ke posisi sebelumnya.
- **Ubah Nomor…**: lompat ke nomor mana pun; nomor tidak harus berurutan.
- **Hapus Bagian Terakhir**: lepas sambungan terakhir dari gambar terpilih.

Aturan penting:
- Screenshot yang masuk saat **BELUM SIAP** tetap ditampilkan (baris kuning, "belum diberi nomor").
  Klik dua kali barisnya untuk menetapkan kategori/nomor.
- Gambar dengan piksel identik dengan yang sudah ada ditolak sebagai **DUPLIKAT**. Bagian lanjutan
  yang sama persis (lupa scroll) juga ditolak, dan mode lanjutan tetap aktif untuk dicoba lagi.
- Jika nomor target sudah terisi, screenshot baru **mengganti** yang lama (status menampilkan
  peringatan ⚠ sebelumnya). Salinan lama dicadangkan di `_diganti\`.
- Saat mengubah nomor di daftar ke nomor yang sudah dipakai, Anda memilih **Tukar** atau **Ganti**.

## File & keamanan data

- File screenshot **asli tidak pernah diubah, dipindah, atau dihapus**. Aplikasi hanya membaca lalu
  menyimpan **salinan PNG** (JPG/JPEG/WEBP dikonversi ke PNG).
- Workspace: `Documents\ScreenshotManager\<Paket>\`
  ```
  Paket-01\
    paket.json        state (daftar, nomor berikutnya)
    TWK\TWK-001.png   salinan yang sudah dinamai
    TIU\TIU-001.png
    _belum\           screenshot tanpa nomor
    _bagian\          potongan per bagian (untuk gambar bersambung)
    _diganti\         cadangan salinan yang tergantikan
  ```
- Pengaturan & log: `%APPDATA%\ScreenshotManager\` (`settings.json`, `screenshot-manager.log`).
- Hanya screenshot **baru** (yang muncul setelah aplikasi dibuka) yang diproses; file lama di folder
  diabaikan. File baru diproses setelah selesai ditulis (ukuran stabil & gambar bisa dibaca utuh).
- Deteksi ganda: event watchdog (instan) + pemindaian cadangan tiap ±2 detik, sehingga tetap jalan
  untuk folder OneDrive. **Refresh** memindai ulang sekarang.

## ZIP

**BUAT ZIP** → pilih lokasi (default `Downloads\Paket-01.zip`). Struktur:

```
Paket-01.zip
├── TWK/TWK-001.png, TWK-002.png, …
├── TIU/TIU-001.png, …
└── TKP/TKP-001.png, …
```

Hanya gambar yang punya kategori & nomor yang dimasukkan. ZIP ditulis ke file sementara, diverifikasi
(CRC + daftar isi), baru disimpan, jadi tidak pernah ada ZIP setengah jadi.

## Ekspor untuk SKD Intelligence

### 1. BUAT ZIP (untuk ChatGPT)

```
Paket-01.zip
├─ PROMPT.txt        prompt untuk ChatGPT, terisi otomatis (jumlah soal, daftar soal bergambar, paket)
├─ daftar.json       {"paket", "bergambar": ["TIU-027", …], "screenshot": [{id, kategori, nomor, file}]}
├─ TWK/TWK-001.png … TIU/TIU-001.png … TKP/TKP-045.png   (nomor PER KATEGORI, 3 digit)
└─ gambar/TIU-027.png …                                  (HANYA soal yang benar-benar bergambar)
```

Tanpa base64 di file mana pun. `soal.json` sengaja tidak ada — nama itu untuk hasil ChatGPT.

**Potong gambar soal (otomatis, tanpa OCR):**
1. cari baris jawaban pertama (pita ±40 px, ≥ 30% lebar, abu muda / hijau / merah);
2. cari awal gambar: garis lurus gelap ≥ 45 px di bawah 8% teratas (logo, tombol, teks tidak memenuhi);
3. potong dari awal gambar sampai 10 px di atas baris jawaban, pangkas ke tinta gelap + 12 px;
4. disimpan hanya bila ≥ 300×100 px dan tanpa piksel hijau/merah (kunci tidak bocor).

Gambar di dalam pilihan jawaban ditandai **✂ manual**. Sebelum ekspor muncul **pratinjau semua
potongan** dengan tombol **Buang** dan **Potong Ulang** (kotak bisa digeser / digambar ulang).
Kolom *Gambar*: 🖼 = masuk `gambar/`, ✂ manual = perlu dipotong, — = bukan soal bergambar.

### 2. Kirim ke ChatGPT
Unggah `Paket-01.zip` dan tempel isi `PROMPT.txt`. Hasilnya `soal.json` (semua TWK, TIU, TKP).

### 3. 📦 Buat ZIP siap impor
Tempel / pilih `soal.json` → aplikasi memeriksa (paket, kategori, nomor 1–30/35/45 tanpa ganda,
subtopik, pilihan A–E, kunci TWK/TIU, skor 1–5 TKP, rujukan gambar, jumlah soal) dan menampilkan
masalah per nomor (tetap boleh lanjut), membersihkan `[gambar]`/`[GAMBAR:…]`, mengganti
`opsi`→`pilihan` dan `jawaban`→`kunci`, lalu membuat **Paket-01-siap-impor.zip** berisi HANYA
`soal.json` + `gambar/`. Unggah di **SKD Intelligence → Impor Soal → Unggah ZIP**.

## Catatan folder

Default yang dipantau adalah `C:\Users\djtzy\Pictures\Screenshots`. Jika folder Pictures Anda
dipindah ke OneDrive (`C:\Users\djtzy\OneDrive\Pictures\Screenshots`), aplikasi mencoba mendeteksinya
otomatis; jika tidak, pilih lewat **Ganti Folder…**.

## Update aplikasi (otomatis)

- Aplikasi mengecek rilis terbaru di GitHub saat dibuka dan setiap 2 jam. Versi baru
  **diunduh & dipasang sendiri tanpa dialog**: installer diverifikasi (ukuran + SHA-256), dipasang
  diam-diam, lalu aplikasi terbuka lagi. Pemasangan ditunda selama Tangkap Otomatis / Atur
  Otomatis berjalan atau ada dialog terbuka. Paket, screenshot, dan pengaturan tidak tersentuh.
- Tombol **Periksa Update** mengecek seketika (perilakunya sama: langsung dipasang).
- Matikan bila perlu dengan `"auto_update": false` di `%APPDATA%\ScreenshotManager\settings.json`.

### Menerbitkan versi baru (otomatis)

```
python tools/bump_version.py 1.0.11
git commit -am "Rilis v1.0.11"
git push
```

Push ke `main` dengan versi yang belum pernah dirilis → GitHub Actions menjalankan tes, membuild
`.exe` + installer, dan menerbitkan GitHub Release `v1.0.11` sendiri. Push tanpa naik versi hanya
dites & dibuild. Semua aplikasi terpasang lalu memperbarui diri otomatis.

## Pengembangan

```
pip install -r requirements.txt pytest
python -m pytest -q          # tes inti + simulasi alur kerja di jendela asli
```

Struktur: `screenshot_manager/core.py` (penamaan, duplikat, workspace, ZIP),
`watcher.py` (pemantauan folder), `app.py` (UI PySide6), `run.py` (entry point),
`updater.py` (cek & pasang update dari GitHub Releases), `ScreenshotManager.spec` (PyInstaller),
`installer.iss` (Inno Setup), `build_windows.bat`, `tools/bump_version.py`.
