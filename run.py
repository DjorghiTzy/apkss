"""Titik masuk aplikasi (dipakai juga oleh PyInstaller)."""
import sys

from screenshot_manager.app import main

if __name__ == "__main__":
    sys.exit(main())
