@echo off
REM ==========================================================
REM  Build Screenshot Manager untuk Windows
REM  Syarat: Python 3.10-3.13 (64-bit) terpasang, centang "Add to PATH".
REM  Hasil : dist\ScreenshotManager\ScreenshotManager.exe
REM          dist\ScreenshotManager-portable.zip
REM          dist\ScreenshotManager-Setup-1.0.0.exe (jika Inno Setup 6 terpasang)
REM ==========================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

echo [1/5] Membuat virtual environment...
if not exist .venv (%PY% -m venv .venv || goto :err)
call .venv\Scripts\activate.bat || goto :err

echo [2/5] Memasang dependensi...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller pytest || goto :err

echo [3/5] Menjalankan tes...
set QT_QPA_PLATFORM=offscreen
python -m pytest -q || goto :err
set QT_QPA_PLATFORM=

echo [4/5] Membuat executable...
pyinstaller --noconfirm --clean ScreenshotManager.spec || goto :err
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\ScreenshotManager' -DestinationPath 'dist\ScreenshotManager-portable.zip'" || goto :err

echo [5/5] Membuat installer (opsional)...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% installer.iss || goto :err
) else (
  echo   Inno Setup 6 tidak ditemukan - installer dilewati.
  echo   Pasang dari https://jrsoftware.org/isdl.php lalu jalankan build_windows.bat lagi.
)

echo.
echo SELESAI. Jalankan: dist\ScreenshotManager\ScreenshotManager.exe
exit /b 0

:err
echo.
echo BUILD GAGAL - lihat pesan di atas.
exit /b 1
