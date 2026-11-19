# Screenshot Manager

Aplikasi desktop Windows untuk mengatur screenshot soal SKD (TWK/TIU/TKP) yang diambil manual
dengan Snipping Tool: memantau folder Screenshots, memberi nama `KATEGORI-NNN.png` sesuai metadata
yang Anda atur, mendeteksi duplikat, lalu membuat ZIP siap impor.

Tanpa login, tanpa internet, tanpa OCR/AI. Aplikasi tidak menyentuh browser, cookie, maupun akun.

## Instalasi di Windows

**Pilihan A — Installer** (jika sudah dibuild): jalankan `ScreenshotManager-Setup-1.0.0.exe`.
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

## Alur kerja Claude

1. Pilih **Paket** (atau **Paket Baru…**, mis. `Paket-01`).
2. Klik kategori soal yang terlihat di website (**TWK / TIU / TKP**).
3. Isi **Nomor soal berikutnya** sesuai nomor di navigasi website (atau **Ubah Nomor…**).
4. Klik **Siapkan Screenshot Berikutnya** (Ctrl+Enter). Status menjadi **● SIAP MENERIMA** dan
   nama target tampil, mis. `TWK-001.png`.
5. Ambil screenshot dengan Snipping Tool. Snipping Tool Windows 11 menyimpan otomatis ke
   `Pictures\Screenshots`; jika tidak, simpan manual ke folder itu.
6. Banner hijau muncul: `✔ DITERIMA: TWK-001.png • Berikutnya: TWK-002.png`.
7. Mode **Otomatis**: nomor naik +1 dan tetap SIAP, jadi langsung ambil screenshot soal berikutnya.
   Mode **Manual**: setelah diterima status kembali BELUM SIAP; atur nomor, lalu Siapkan lagi.
8. Pindah kategori? Klik tombol kategorinya. Nomor berikutnya diingat per kategori.

Tombol lain:
- **Batalkan** (Esc): batalkan persiapan; screenshot berikutnya masuk *tanpa nomor*.
- **Ulangi Nomor**: screenshot berikutnya **menggantikan** screenshot terakhir (atau baris terpilih),
  lalu target kembali ke posisi sebelumnya.
- **Ubah Nomor…**: lompat ke nomor mana pun; nomor tidak harus berurutan.

Aturan penting:
- Screenshot yang masuk saat **BELUM SIAP** tetap ditampilkan (baris kuning, "belum diberi nomor").
  Klik dua kali barisnya untuk menetapkan kategori/nomor.
- Gambar dengan piksel identik dengan yang sudah ada ditolak sebagai **DUPLIKAT**.
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

## Pengembangan

```
pip install -r requirements.txt pytest
python -m pytest -q          # tes inti + simulasi alur kerja di jendela asli
```

Struktur: `screenshot_manager/core.py` (penamaan, duplikat, workspace, ZIP),
`watcher.py` (pemantauan folder), `app.py` (UI PySide6), `run.py` (entry point),
`ScreenshotManager.spec` (PyInstaller), `installer.iss` (Inno Setup), `build_windows.bat`.
