"""Browser tiruan untuk menguji Tangkap Otomatis tanpa Windows."""
import random

from PIL import Image, ImageDraw

SCREEN = (1366, 768)
AREA = [300, 120, 760, 560]                    # area konten soal
GRID = {"first": (1150, 200), "dx": 40, "dy": 36, "cols": 5}
CROP = {"enabled": True, "rect": AREA, "screen": list(SCREEN)}


def make_page(q: int, height: int) -> Image.Image:
    rnd = random.Random(q)
    page = Image.new("RGB", (AREA[2], height), "white")
    d = ImageDraw.Draw(page)
    d.rectangle([0, 0, AREA[2], 40], fill=(rnd.randint(0, 200), 80, 160))
    d.text((10, 12), f"SOAL NOMOR {q}", fill="white")
    for y in range(60, height - 20, 24):
        d.text((12, y), f"q{q} baris {y} " + "w" * rnd.randint(3, 70), fill="black")
    d.text((12, height - 18), f"AKHIR PEMBAHASAN {q}", fill="red")
    return page


class FakeBrowser:
    def __init__(self, heights, px_per_notch=53, noise=False, stop_after_grabs=None, broken_nav=False):
        self.pages = {q: make_page(q, h) for q, h in heights.items()}
        self.q = 1
        self.scroll_y = 0
        self.px = px_per_notch
        self.noise = noise
        self.grabs = 0
        self.stop_after = stop_after_grabs
        self.broken_nav = broken_nav
        self.clicks = []
        self.mouse = (600, 400)

    # Driver API
    def grab(self):
        self.grabs += 1
        scr = Image.new("RGB", SCREEN, "#2b2b3b")
        d = ImageDraw.Draw(scr)
        d.rectangle([0, 0, SCREEN[0], 60], fill="#888")             # tab browser
        page = self.pages[self.q]
        part = page.crop((0, self.scroll_y, AREA[2], min(page.height, self.scroll_y + AREA[3])))
        view = Image.new("RGB", (AREA[2], AREA[3]), "white")
        view.paste(part, (0, 0))
        if self.noise and self.scroll_y:                              # render sub-piksel
            px = view.load()
            for x in range(0, view.width, 7):
                for y in range(0, view.height, 5):
                    r, g, b = px[x, y]
                    px[x, y] = (min(255, r + 1), g, max(0, b - 1))
        scr.paste(view, (AREA[0], AREA[1]))
        for n in range(1, 111):                                       # grid navigasi
            row, col = divmod(n - 1, GRID["cols"])
            x = GRID["first"][0] + col * GRID["dx"]
            y = GRID["first"][1] + row * GRID["dy"]
            if y < SCREEN[1] - 10:
                d.rectangle([x - 12, y - 10, x + 12, y + 10], outline="white")
        return scr

    def move(self, x, y):
        self.mouse = (x, y)

    def click(self, x, y):
        self.clicks.append((x, y))
        col = round((x - GRID["first"][0]) / GRID["dx"])
        row = round((y - GRID["first"][1]) / GRID["dy"])
        n = row * GRID["cols"] + col + 1
        if n in self.pages and not self.broken_nav:
            self.q, self.scroll_y = n, 0

    def scroll(self, x, y, notches):
        assert AREA[0] <= x <= AREA[0] + AREA[2] and AREA[1] <= y <= AREA[1] + AREA[3]
        max_y = max(0, self.pages[self.q].height - AREA[3])
        self.scroll_y = min(max_y, max(0, self.scroll_y - notches * self.px))

    def key(self, name):
        if name == "right" and self.q + 1 in self.pages:
            self.q, self.scroll_y = self.q + 1, 0

    def stop_requested(self):
        return self.stop_after is not None and self.grabs >= self.stop_after

    def sleep(self, s):
        pass


# ---------------------------------------------------------------- mirip Privat Alfaiz
DROPDOWN = (1200, 110)                                   # tombol "Tipe Soal"
OPTIONS = {"TWK": (1200, 160), "TIU": (1200, 220), "TKP": (1200, 280)}
CAT_GRID = {"first": (1130, 200), "dx": 46, "dy": 42, "cols": 5}


class FakeCategoryBrowser(FakeBrowser):
    """Dropdown Tipe Soal + grid 'Daftar Soal' yang mulai dari 1 di tiap kategori."""

    def __init__(self, counts, height_of=lambda cat, n: 700 + (n * 137) % 1300, start_cat="TWK", **kw):
        offs = {"TWK": 0, "TIU": 100, "TKP": 200}
        heights = {offs[c] + n: height_of(c, n) for c, cnt in counts.items() for n in range(1, cnt + 1)}
        super().__init__(heights, **kw)
        self.counts = counts
        self.offs = offs
        self.cat = start_cat
        self.local = 1
        self.q = offs[start_cat] + 1
        self.open = False
        self.cat_switches = []

    def page_of(self, cat, n):
        return self.pages[self.offs[cat] + n]

    def click(self, x, y):
        self.clicks.append((x, y))
        if abs(x - DROPDOWN[0]) < 40 and abs(y - DROPDOWN[1]) < 15:
            self.open = not self.open
            return
        if self.open:
            for cat, (ox, oy) in OPTIONS.items():
                if abs(x - ox) < 60 and abs(y - oy) < 20:
                    self.cat, self.local, self.q, self.scroll_y = cat, 1, self.offs[cat] + 1, 0
                    self.cat_switches.append(cat)
            self.open = False             # klik di mana pun menutup dropdown
            return
        col = round((x - CAT_GRID["first"][0]) / CAT_GRID["dx"])
        row = round((y - CAT_GRID["first"][1]) / CAT_GRID["dy"])
        n = row * CAT_GRID["cols"] + col + 1
        if 0 <= col < CAT_GRID["cols"] and 1 <= n <= self.counts[self.cat]:
            self.local, self.q, self.scroll_y = n, self.offs[self.cat] + n, 0

    def key(self, name):
        pass


# ---------------------------------------------------------------- tampilan penuh mirip Privat Alfaiz
class FakeAlfaiz:
    """Layar lengkap: toolbar browser, header situs (menempel), kolom konten, sidebar
    (kapsul Tipe Soal + grid Daftar Soal merah), menu dropdown, taskbar."""

    W, H = 1366, 768
    CONTENT = [300, 100, 760, 628]             # area yang ter-scroll
    PILL = (1100, 128, 1300, 172)
    MENU = (1100, 175, 1300, 355)
    SEPS = (235, 295)
    GRID0, DX, DY, COLS, BOX = (1130, 240), 46, 42, 5, 30
    CATS = ["TWK", "TIU", "TKP"]

    def __init__(self, counts, height_of=lambda cat, n: 900 + (n * 173) % 1500, start_cat="TWK",
                 px_per_notch=53, dy_extra=None):
        self.counts = counts
        self.dy_extra = dy_extra or {}          # grid kategori tertentu sedikit lebih renggang
        self.pages = {(c, n): make_page(1000 * (i + 1) + n, height_of(c, n))
                      for i, c in enumerate(self.CATS) if c in counts for n in range(1, counts[c] + 1)}
        self.cat, self.n, self.scroll_y, self.open = start_cat, 1, 0, False
        self.px = px_per_notch
        self.clicks, self.cat_switches, self.grabs = [], [], 0

    def page_of(self, cat, n):
        return self.pages[(cat, n)]

    # ---- render
    def grab(self):
        self.grabs += 1
        W, H = self.W, self.H
        scr = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(scr)
        x, y, w, h = self.CONTENT
        page = self.pages[(self.cat, self.n)]
        part = page.crop((0, self.scroll_y, w, min(page.height, self.scroll_y + h)))
        scr.paste(part, (x, y))
        d.rectangle([0, 0, W, 60], fill="#202124")                     # toolbar browser
        d.text((300, 25), "casn.privatalfaiz.id/#!/ujian/pembahasan", fill="#ddd")
        d.rectangle([0, 60, W, 99], fill="#8b0000")                    # header situs menempel
        d.text((600, 75), "AL FAIZ   Beranda   Mulai Belajar", fill="white")
        d.rectangle([0, H - 40, W, H], fill="#1b1b2b")                  # taskbar
        for i in range(8):
            d.rectangle([500 + i * 48, H - 32, 524 + i * 48, H - 8], fill=(60 + 20 * i, 120, 200))
        d.rounded_rectangle([1085, 110, 1345, 640], radius=12, outline=(225, 225, 225), fill="white")
        open_ = self.open
        d.rounded_rectangle(self.PILL, radius=20, fill=(139, 0, 0) if open_ else (255, 236, 236),
                            outline=(240, 150, 150), width=2)
        d.text((1150, 145), {"TWK": "Wawasan", "TIU": "Intelegensi", "TKP": "Karakteristik"}[self.cat],
               fill="white" if open_ else (139, 0, 0))
        d.text((1100, 200), "Daftar Soal", fill="black")
        for k in range(1, self.counts[self.cat] + 1):
            gx, gy = self.pos(k)
            col = (255, 152, 0) if k == self.n else (244, 67, 54)
            d.rectangle([gx - 15, gy - 15, gx + 15, gy + 15], fill=col)
            d.text((gx - 5, gy - 6), str(k), fill="white")
        if open_:
            d.rectangle(self.MENU, fill="white", outline=(200, 200, 200))
            for sy in self.SEPS:
                d.line([self.MENU[0] + 1, sy, self.MENU[2] - 1, sy], fill=(210, 210, 210))
            for i, label in enumerate(["Tes Wawasan Kebangsaan", "Tes Intelegensi Umum", "Tes Karakteristik"]):
                d.text((1110, 195 + i * 60), label, fill="black")
        return scr

    def pos(self, k):
        r, c = divmod(k - 1, self.COLS)
        return self.GRID0[0] + c * self.DX, self.GRID0[1] + r * (self.DY + self.dy_extra.get(self.cat, 0))

    # ---- input
    def move(self, x, y):
        pass

    def click(self, x, y):
        self.clicks.append((x, y))
        x0, y0, x1, y1 = self.PILL
        if x0 <= x <= x1 and y0 <= y <= y1:
            self.open = not self.open
            return
        if self.open:
            mx0, my0, mx1, my1 = self.MENU
            if mx0 <= x <= mx1 and my0 <= y <= my1:
                bounds = [my0, *self.SEPS, my1]
                for i, cat in enumerate(self.CATS):
                    if bounds[i] < y < bounds[i + 1] and cat in self.counts:
                        self.cat, self.n, self.scroll_y = cat, 1, 0
                        self.cat_switches.append(cat)
            self.open = False
            return
        for k in range(1, self.counts[self.cat] + 1):
            gx, gy = self.pos(k)
            if abs(x - gx) <= 15 and abs(y - gy) <= 15:
                self.n, self.scroll_y = k, 0

    def scroll(self, x, y, notches):
        page = self.pages[(self.cat, self.n)]
        max_y = max(0, page.height - self.CONTENT[3])
        self.scroll_y = min(max_y, max(0, self.scroll_y - notches * self.px))

    def key(self, name):
        pass

    def stop_requested(self):
        return False

    def sleep(self, s):
        pass
