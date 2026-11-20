import hashlib
import os
from pathlib import Path

import pytest

from screenshot_manager import __version__, updater

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def release_json(tag="v1.2.0", data=b"", digest=True):
    return {
        "tag_name": tag, "body": "Perbaikan bug", "html_url": "https://github.com/x/y/releases/v",
        "assets": [
            {"name": "ScreenshotManager-1.2.0-portable.zip", "browser_download_url": "zip",
             "size": 1},
            {"name": "ScreenshotManager-Setup-1.2.0.exe", "browser_download_url": "SETUP",
             "size": len(data),
             **({"digest": "sha256:" + hashlib.sha256(data).hexdigest()} if digest else {})},
        ],
    }


def test_versions():
    assert updater.parse_version("v1.2") == (1, 2, 0)
    assert updater.is_newer("v1.0.1", "1.0.0")
    assert updater.is_newer("2.0.0", "1.9.9")
    assert not updater.is_newer("v1.0.0", "1.0.0")
    assert not updater.is_newer("0.9.0", "1.0.0")
    with pytest.raises(updater.UpdateError):
        updater.parse_version("latest")


def test_parse_release_picks_setup_asset():
    info = updater.parse_release(release_json(data=b"abc"))
    assert info.version == "1.2.0"
    assert info.asset_name == "ScreenshotManager-Setup-1.2.0.exe"
    assert info.asset_sha256 == hashlib.sha256(b"abc").hexdigest()


def test_download_verifies(tmp_path, monkeypatch):
    payload = os.urandom(700_000)
    src = tmp_path / "setup.exe"
    src.write_bytes(payload)
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path / "t"))
    info = updater.parse_release(release_json(data=payload))
    info.asset_url = src.as_uri()                    # urllib bisa membaca file://
    seen = []
    path = updater.download_installer(info, lambda d, t: seen.append((d, t)))
    assert path.read_bytes() == payload and seen[-1][0] == len(payload)

    info.asset_sha256 = "0" * 64                     # checksum salah -> ditolak
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download_installer(info)
    info.asset_sha256, info.asset_size = None, 5     # ukuran salah -> ditolak
    with pytest.raises(updater.UpdateError, match="Ukuran"):
        updater.download_installer(info)
    assert not list(Path(tmp_path / "t").rglob("*.part"))
    with pytest.raises(updater.UpdateError, match="dibatalkan"):
        info.asset_size = len(payload)
        updater.download_installer(info, cancelled=lambda: True)


def test_fetch_latest_errors(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "nf", {}, None)
    monkeypatch.setattr(updater, "_request", boom)
    with pytest.raises(updater.UpdateError, match="private"):
        updater.fetch_latest()


def test_ui_update_flow(isolated_home, monkeypatch):
    """Tombol Periksa Update -> dialog muncul untuk versi lebih baru."""
    import time
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from screenshot_manager.app import MainWindow

    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2]) or QMessageBox.Ok)
    w = MainWindow()

    def wait():
        end = time.time() + 5
        while time.time() < end and not shown:
            app.processEvents()
            time.sleep(0.02)

    monkeypatch.setattr(updater, "fetch_latest", lambda: updater.parse_release(release_json("v99.0.0")))
    w.check_updates(silent=False)
    wait()
    assert shown and "99.0.0" in shown[0]
    assert "99.0.0" in w.btn_update.text()

    shown.clear()
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda: updater.parse_release(release_json("v" + __version__)))
    w.check_updates(silent=False)
    wait()
    assert shown and "terbaru" in shown[0]
    w.close()


def test_silent_auto_update_waits_until_idle(isolated_home, monkeypatch, tmp_path):
    import time
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from screenshot_manager.app import MainWindow

    dialogs = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: dialogs.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: dialogs.append(a[2]) or QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: dialogs.append(a[2]))
    inst = tmp_path / "ScreenshotManager-Setup-99.0.0.exe"
    inst.write_bytes(b"MZ")
    launched, quit_called = [], []
    monkeypatch.setattr(updater, "fetch_latest", lambda: updater.parse_release(release_json("v99.0.0", b"MZ")))
    monkeypatch.setattr(updater, "can_self_install", lambda: True)
    monkeypatch.setattr(updater, "download_installer", lambda info, progress=None, cancelled=None: inst)
    monkeypatch.setattr(updater, "launch_installer", lambda p: launched.append(p))
    monkeypatch.setattr(QApplication, "quit", lambda *a: quit_called.append(1))
    w = MainWindow()
    w.show()

    def wait(cond, t=8):
        end = time.time() + t
        while time.time() < end and not cond():
            app.processEvents()
            time.sleep(0.02)
        return cond()

    w.auto_running = True                         # sedang Tangkap Otomatis -> jangan pasang
    w.check_updates(silent=True)
    assert wait(lambda: w._pending_installer is not None)
    app.processEvents()
    time.sleep(3.5)
    app.processEvents()
    assert launched == [] and dialogs == []
    w.auto_running = False                        # selesai -> dipasang sendiri tanpa dialog
    w._install_when_idle()
    assert wait(lambda: launched)
    assert launched == [inst] and quit_called and dialogs == []
    assert "99.0.0" in w.banner.text()
