import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Arahkan home & folder pengaturan ke tmp, di Linux maupun Windows.

    Windows memakai USERPROFILE (Path.home) dan APPDATA (pengaturan), bukan HOME.
    """
    home = tmp_path / "home"
    shots = home / "Pictures" / "Screenshots"
    shots.mkdir(parents=True)
    cfg_base = home / ".config"
    for var, val in {"HOME": home, "USERPROFILE": home, "APPDATA": cfg_base,
                     "XDG_CONFIG_HOME": cfg_base}.items():
        monkeypatch.setenv(var, str(val))
    cfg = cfg_base / "ScreenshotManager"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text(json.dumps({
        "watch_folder": str(shots), "workspace": str(home / "ws"),
        "auto_update_check": False}))
    assert Path.home() == home
    return home, shots
