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

## Catatan folder

Default yang dipantau adalah `C:\Users\djtzy\Pictures\Screenshots`. Jika folder Pictures Anda
dipindah ke OneDrive (`C:\Users\djtzy\OneDrive\Pictures\Screenshots`), aplikasi mencoba mendeteksinya
otomatis; jika tidak, pilih lewat **Ganti Folder…**.

## Update aplikasi

- Saat dibuka, aplikasi diam-diam mengecek rilis terbaru di GitHub
  (`github.com/DjorghiTzy/apkss/releases`). Tombol **Periksa Update** di kanan atas mengecek manual.
- Jika ada versi baru: **Unduh & Pasang** → installer diunduh, ukuran & SHA-256 diverifikasi,
  aplikasi menutup, update terpasang diam-diam, lalu aplikasi terbuka lagi. Paket, screenshot,
  dan pengaturan tidak tersentuh. Ada juga pilihan **Nanti** dan **Lewati Versi Ini**.
- Cek update butuh repo GitHub **public** (aplikasi tidak menyimpan token). Fungsi utama tetap
  berjalan offline.

### Menerbitkan versi baru

1. Naikkan versi lalu push ke `main`:
   ```
   python tools/bump_version.py 1.0.1
   git commit -am "Rilis v1.0.1"
   git push
   ```
2. Di GitHub: **Actions → Build Windows → Run workflow** (biarkan "Terbitkan release" tercentang).
   Cara lain: push tag `v1.0.1`.

GitHub Actions lalu menjalankan tes, membuild `.exe` + installer, dan menerbitkan GitHub Release
`v1.0.1` berisi `ScreenshotManager-Setup-1.0.1.exe` dan versi portable. Semua aplikasi yang
terpasang akan menawarkan update tersebut.

## Pengembangan

```
pip install -r requirements.txt pytest
python -m pytest -q          # tes inti + simulasi alur kerja di jendela asli
```

Struktur: `screenshot_manager/core.py` (penamaan, duplikat, workspace, ZIP),
`watcher.py` (pemantauan folder), `app.py` (UI PySide6), `run.py` (entry point),
`updater.py` (cek & pasang update dari GitHub Releases), `ScreenshotManager.spec` (PyInstaller),
`installer.iss` (Inno Setup), `build_windows.bat`, `tools/bump_version.py`.
