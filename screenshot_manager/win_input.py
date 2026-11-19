"""Driver Windows untuk Tangkap Otomatis: tangkap layar, mouse, keyboard (user32 via ctypes).

Hanya mensimulasikan input seperti pengguna biasa. Tidak membaca data browser apa pun.
"""
from __future__ import annotations

import sys
import time

from PIL import Image, ImageGrab

KEYS = {"right": 0x27, "left": 0x25, "down": 0x28, "pagedown": 0x22, "enter": 0x0D, "n": 0x4E}
VK_ESCAPE = 0x1B
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x0002, 0x0004, 0x0800
KEYEVENTF_KEYUP = 0x0002
WHEEL_DELTA = 120


def available() -> bool:
    return sys.platform == "win32"


def grab_screen() -> Image.Image:
    """Tangkap layar utama dalam piksel fisik (sama seperti Win+PrtScn)."""
    return ImageGrab.grab(all_screens=False).convert("RGB")


class WindowsDriver:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.u = ctypes.windll.user32
        self._pt = wintypes.POINT()
        self._ctypes = ctypes
        self.u.GetAsyncKeyState(VK_ESCAPE)   # reset status "pernah ditekan"

    def grab(self) -> Image.Image:
        return grab_screen()

    def move(self, x: int, y: int) -> None:
        self.u.SetCursorPos(int(x), int(y))

    def click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.05)
        self.u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        self.u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def scroll(self, x: int, y: int, notches: int) -> None:
        self.move(x, y)
        time.sleep(0.03)
        step = 1 if notches > 0 else -1
        for _ in range(abs(int(notches))):   # satu per satu agar halus & konsisten
            self.u.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, step * WHEEL_DELTA, 0)  # bertanda
            time.sleep(0.015)

    def key(self, name: str) -> None:
        vk = KEYS[name]
        self.u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        self.u.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def stop_requested(self) -> bool:
        if self.u.GetAsyncKeyState(VK_ESCAPE) & 0x8001:
            return True
        self.u.GetCursorPos(self._ctypes.byref(self._pt))
        return self._pt.x <= 2 and self._pt.y <= 2     # pojok kiri atas = berhenti

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
