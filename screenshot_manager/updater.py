"""Pemeriksa update dari GitHub Releases.

Alur: ambil rilis terbaru via API GitHub -> bandingkan versi -> unduh
installer (ScreenshotManager-Setup-x.y.z.exe) -> verifikasi ukuran & SHA-256
-> jalankan installer (mode silent) lalu aplikasi menutup diri.
Data workspace & pengaturan tidak tersentuh oleh update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__

GITHUB_REPO = "DjorghiTzy/apkss"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"ScreenshotManager/{__version__}"
TIMEOUT = 15


class UpdateError(Exception):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None
    asset_size: int = 0
    asset_sha256: Optional[str] = None


def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text or "")
    if not m:
        raise UpdateError(f"Format versi tidak dikenal: {text!r}")
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _request(url: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=TIMEOUT)  # noqa: S310 - URL tetap (https)


def parse_release(data: dict) -> ReleaseInfo:
    tag = data.get("tag_name") or ""
    info = ReleaseInfo(version=".".join(map(str, parse_version(tag))), tag=tag,
                       notes=(data.get("body") or "").strip(),
                       page_url=data.get("html_url") or RELEASES_PAGE)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe") and "setup" in name.lower():
            info.asset_name = name
            info.asset_url = asset.get("browser_download_url")
            info.asset_size = int(asset.get("size") or 0)
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                info.asset_sha256 = digest.split(":", 1)[1].lower()
            break
    return info


def fetch_latest() -> ReleaseInfo:
    try:
        with _request(API_LATEST) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Belum ada rilis, atau repository GitHub bersifat private") from exc
        if exc.code == 403:
            raise UpdateError("Batas akses GitHub tercapai, coba lagi nanti") from exc
        raise UpdateError(f"GitHub membalas HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Tidak bisa terhubung ke GitHub: {getattr(exc, 'reason', exc)}") from exc
    except ValueError as exc:
        raise UpdateError("Balasan GitHub tidak valid") from exc
    return parse_release(data)


def download_installer(info: ReleaseInfo, progress: Callable[[int, int], None] | None = None,
                       cancelled: Callable[[], bool] = lambda: False) -> Path:
    if not info.asset_url:
        raise UpdateError("Rilis ini tidak memiliki file installer")
    dest_dir = Path(tempfile.gettempdir()) / "ScreenshotManager-update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info.asset_name
    part = dest.with_suffix(dest.suffix + ".part")
    sha = hashlib.sha256()
    done = 0
    try:
        with _request(info.asset_url, accept="application/octet-stream") as resp, open(part, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            while True:
                if cancelled():
                    raise UpdateError("Unduhan dibatalkan")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Unduhan gagal: {getattr(exc, 'reason', exc)}") from exc
    if info.asset_size and done != info.asset_size:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Ukuran unduhan tidak cocok ({done} dari {info.asset_size} byte)")
    if info.asset_sha256 and sha.hexdigest() != info.asset_sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("Checksum SHA-256 tidak cocok, file tidak dipakai")
    os.replace(part, dest)
    return dest


def can_self_install() -> bool:
    """Instal otomatis hanya untuk versi .exe di Windows (bukan saat jalan dari kode)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def launch_installer(path: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
