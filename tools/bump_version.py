"""Naikkan versi aplikasi di semua tempat sekaligus.

Pemakaian:  python tools/bump_version.py 1.0.1
Lalu:       git commit -am "Rilis v1.0.1" && git tag v1.0.1 && git push --follow-tags
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path: str, pattern: str, repl: str) -> None:
    f = ROOT / path
    text = f.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text)
    if n == 0:
        sys.exit(f"Pola versi tidak ditemukan di {path}")
    f.write_text(new, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("Pemakaian: python tools/bump_version.py X.Y.Z")
    v = sys.argv[1]
    t = ", ".join(v.split(".")) + ", 0"
    sub("screenshot_manager/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{v}"')
    sub("version_info.txt", r"filevers=\([^)]*\)", f"filevers=({t})")
    sub("version_info.txt", r"prodvers=\([^)]*\)", f"prodvers=({t})")
    sub("version_info.txt", r'(StringStruct\("(?:File|Product)Version", ")[^"]+', rf"\g<1>{v}")
    sub("installer.iss", r'#define AppVersion "[^"]+"', f'#define AppVersion "{v}"')
    print(f"Versi diubah ke {v}")


if __name__ == "__main__":
    main()
