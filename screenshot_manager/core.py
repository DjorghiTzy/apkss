"""Logika inti Screenshot Manager (tanpa UI).

Workspace satu paket:
    <workspace_root>/<Paket>/
        paket.json            -> state paket (daftar item + pengaturan capture)
        TWK/TWK-001.png       -> salinan yang sudah diberi nama
        TIU/TIU-001.png
        _belum/<id>.png       -> screenshot yang masuk tanpa metadata
        _diganti/...          -> cadangan salinan yang tergantikan

File screenshot asli TIDAK pernah diubah, dipindah, atau dihapus.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

DEFAULT_CATEGORIES = ["TWK", "TIU", "TKP"]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
UNASSIGNED_DIR = "_belum"
REPLACED_DIR = "_diganti"
PARTS_DIR = "_bagian"
MIN_OVERLAP_ROWS = 12
OVERLAP_KEY = "sm_overlap"           # Image.info: tumpang tindih dengan bagian sebelumnya
STATE_FILE = "paket.json"
STATE_VERSION = 1

_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


class ManagerError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


class DuplicateImageError(ManagerError):
    def __init__(self, existing: "Item"):
        self.existing = existing
        super().__init__(f"Gambar duplikat: sama dengan {existing.display_name}")


class SlotTakenError(ManagerError):
    def __init__(self, occupant: "Item"):
        self.occupant = occupant
        super().__init__(f"{occupant.filename} sudah dipakai oleh gambar lain")


# ---------------------------------------------------------------- helpers

def is_image_path(path: str | os.PathLike) -> bool:
    p = Path(path)
    name = p.name
    if name.startswith(("~", ".")) or name.lower().endswith((".tmp", ".crdownload", ".part")):
        return False
    return p.suffix.lower() in IMAGE_EXTS


def sanitize_package_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        raise ManagerError("Nama paket tidak boleh kosong")
    if name.upper() in _WIN_RESERVED or name.startswith("_"):
        raise ManagerError(f"Nama paket '{name}' tidak diperbolehkan")
    return name[:80]


def normalize_category(name: str) -> str:
    cat = (name or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,10}", cat):
        raise ManagerError("Kategori hanya boleh huruf/angka (maks. 10 karakter), mis. TWK")
    if cat in _WIN_RESERVED:
        raise ManagerError(f"Kategori '{cat}' tidak diperbolehkan")
    return cat


def make_filename(category: str, number: int) -> str:
    return f"{category}-{int(number):03d}.png"


def image_fingerprint(img: Image.Image) -> str:
    """Hash isi piksel: gambar identik terdeteksi meskipun nama/metadata file berbeda."""
    rgba = img.convert("RGBA")
    h = hashlib.sha256()
    h.update(f"{rgba.width}x{rgba.height}".encode())
    h.update(rgba.tobytes())
    return h.hexdigest()


def load_image(path: str | os.PathLike) -> Image.Image:
    """Buka & decode penuh gambar. Gagal jika file rusak / belum selesai ditulis."""
    try:
        with Image.open(path) as im:
            im.load()
            if im.width < 1 or im.height < 1:
                raise ManagerError("Ukuran gambar tidak valid")
            return im.copy()
    except ManagerError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow melempar banyak tipe
        raise ManagerError(f"Bukan gambar yang valid: {Path(path).name} ({exc})") from exc


def _save_png_atomic(img: Image.Image, dest: Path, compress_level: int = 6) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGBA")
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".png", dir=dest.parent)
    os.close(fd)
    try:
        img.save(tmp, format="PNG", optimize=False, compress_level=compress_level)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_json_atomic(data: dict, dest: Path) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- crop & stitch

def apply_crop(img: Image.Image, crop: Optional[dict]) -> tuple[Image.Image, bool]:
    """Potong gambar ke area yang diatur pengguna.

    crop = {"enabled": bool, "rect": [x, y, w, h], "screen": [W, H]}.
    Hanya diterapkan pada gambar seukuran layar referensi (screenshot layar penuh);
    potongan manual dari Snipping Tool dibiarkan apa adanya.
    """
    if not crop or not crop.get("enabled") or not crop.get("rect") or not crop.get("screen"):
        return img, False
    sw, sh = crop["screen"]
    if (img.width, img.height) != (int(sw), int(sh)):
        return img, False
    x, y, w, h = (int(v) for v in crop["rect"])
    x, y = max(0, x), max(0, y)
    w, h = min(w, img.width - x), min(h, img.height - y)
    if w < 10 or h < 10:
        return img, False
    return img.crop((x, y, x + w, y + h)), True


def _row_hashes(img: Image.Image) -> list[int]:
    rgb = img.convert("RGB")
    stride = rgb.width * 3
    data = rgb.tobytes()
    return [hash(data[i * stride:(i + 1) * stride]) for i in range(rgb.height)]


def find_overlap(top: Image.Image, bottom: Image.Image, min_rows: int = MIN_OVERLAP_ROWS,
                 max_shift: Optional[int] = None) -> int:
    """Jumlah baris di bawah `top` yang sama dengan baris teratas `bottom`
    (terjadi saat halaman di-scroll kurang dari satu layar). 0 jika tidak ada.

    Coba pencocokan persis dulu; jika gagal (mis. browser di-zoom sehingga
    hasil render bergeser sub-piksel), pakai pencocokan toleran.

    `max_shift`: pergeseran terbesar yang MUNGKIN (jumlah notch × px per notch). Tumpang tindih yang
    lebih kecil dari itu mustahil, jadi tidak dicari — mencegah cocok palsu di area kosong
    (yang dulu membuat isi tergandakan dan soal berikutnya terpotong).
    """
    if top.width != bottom.width:
        return 0
    h = min(top.height, bottom.height)
    lo = min_rows if not max_shift else max(min_rows, h - int(max_shift))
    if lo >= h:
        return 0
    ra, rb = _row_hashes(top), _row_hashes(bottom)
    for k in range(h - 1, lo - 1, -1):
        if ra[-k] == rb[0] and ra[-1] == rb[k - 1] and ra[-k:] == rb[:k]:
            return k
    k = _fuzzy_overlap(top, bottom, lo)
    return k if k else _subpixel_overlap(top, bottom, lo)


def _subpixel_overlap(top: Image.Image, bottom: Image.Image, min_rows: int,
                      max_score: float = 4.0) -> int:
    """Tumpang tindih untuk scroll PECAHAN piksel (zoom browser + skala Windows): huruf digambar
    ulang sedikit berbeda, jadi yang dibandingkan rata-rata blok per baris (dihaluskan 3 baris).

    Dipilih pergeseran dengan selisih terkecil; bila beberapa hampir sama (area kosong), dipilih
    tumpang tindih TERBESAR — yang dibuang hanya baris kosong, isi tidak pernah hilang."""
    import numpy as np

    a = np.asarray(top.convert("L"), dtype=np.float32)
    b = np.asarray(bottom.convert("L"), dtype=np.float32)
    h = min(a.shape[0], b.shape[0])
    w = a.shape[1]
    if h <= min_rows or w < 8:
        return 0
    blocks = max(1, min(24, w // 16))
    bw = w // blocks

    def sig(m):
        s_ = m[:, :blocks * bw].reshape(m.shape[0], blocks, bw).mean(axis=2)
        out = s_.copy()
        out[1:-1] = (s_[:-2] + s_[1:-1] + s_[2:]) / 3.0
        return out
    sa, sb = sig(a), sig(b)
    ks = np.arange(min_rows, h)
    scores = np.array([np.abs(sa[-k:] - sb[:k]).mean() for k in ks])
    best = float(scores.min())
    if best > max_score:
        return 0
    near = ks[scores <= best + 0.15]
    k = int(near.max())
    # isi area tumpang tindih harus benar-benar cocok (bukan kebetulan pada area kosong)
    region = sb[:k]
    if len(ks) >= 10 and region.std() >= 2.0 and best > 0.5 * float(np.median(scores)):
        return 0
    if _envelope_bad(a[-k:], b[:k]) > 0.10:
        return 0                                   # rata-rata blok mirip, tapi pikselnya halaman lain
    return k


def _envelope_bad(A, B, tol: int = 40) -> float:
    """Bagian piksel bertinta di B yang TIDAK berada di antara nilai baris tetangganya di A.

    Pada scroll pecahan, tiap piksel baru = campuran baris di sekitarnya, jadi nilainya selalu di
    rentang min..max baris atas/tengah/bawah (±tol). Halaman lain yang tata letaknya mirip melanggar
    ini di banyak tempat (≈25%), tumpang tindih asli hanya sedikit (≤ 4%)."""
    import numpy as np
    up = np.vstack([A[:1], A[:-1]])
    dn = np.vstack([A[1:], A[-1:]])
    lo = np.minimum(np.minimum(A, up), dn) - tol
    hi = np.maximum(np.maximum(A, up), dn) + tol
    bad = int(((B < lo) | (B > hi)).sum())
    ink = int((np.minimum(A, B) < 200).sum())
    return bad / max(1, ink) if ink else 0.0


def _fuzzy_overlap(top: Image.Image, bottom: Image.Image, min_rows: int,
                   sig_tol: float = 2.0, px_tol: int = 48, bad_frac: float = 0.002) -> int:
    import numpy as np

    a = np.asarray(top.convert("L"), dtype=np.int16)
    b = np.asarray(bottom.convert("L"), dtype=np.int16)
    h, w = min(a.shape[0], b.shape[0]), a.shape[1]
    blocks = max(1, min(32, w // 8))
    bw = w // blocks

    def sig(m):
        return m[:, :blocks * bw].reshape(m.shape[0], blocks, bw).mean(axis=2)
    sa, sb = sig(a), sig(b)
    for k in range(h - 1, min_rows - 1, -1):
        if np.abs(sa[-k:] - sb[:k]).mean() >= sig_tol:
            continue
        if (np.abs(a[-k:] - b[:k]) > px_tol).mean() <= bad_frac:
            return k
    return 0


def stitch(parts: list[Image.Image]) -> tuple[Image.Image, list[int]]:
    """Sambung gambar dari atas ke bawah, membuang baris tumpang tindih akibat scroll."""
    if not parts:
        raise ManagerError("Tidak ada bagian untuk disambung")
    overlaps = [0]
    crops = [parts[0]]
    for prev, cur in zip(parts, parts[1:]):
        # Tangkap Otomatis sudah menghitung tumpang tindih dengan batas pergeseran scroll: pakai itu
        k = cur.info.get(OVERLAP_KEY)
        if k is None:
            k = find_overlap(prev, cur)
        overlaps.append(k)
        crops.append(cur.crop((0, k, cur.width, cur.height)) if k else cur)
    width = max(c.width for c in crops)
    height = sum(c.height for c in crops)
    out = Image.new("RGB", (width, height), "white")
    y = 0
    for c in crops:
        if c.mode in ("RGBA", "LA", "P"):
            c = c.convert("RGBA")
            out.paste(c, (0, y), c)
        else:
            out.paste(c.convert("RGB"), (0, y))
        y += c.height
    return out, overlaps


# ---------------------------------------------------------------- model

@dataclass
class Item:
    id: str
    fingerprint: str
    source: str
    received_at: str
    category: Optional[str] = None
    number: Optional[int] = None
    width: int = 0
    height: int = 0
    parts: int = 1
    part_fps: list = field(default_factory=list)

    @property
    def assigned(self) -> bool:
        return self.category is not None and self.number is not None

    @property
    def filename(self) -> str:
        return make_filename(self.category, self.number) if self.assigned else f"{self.id}.png"

    @property
    def display_name(self) -> str:
        return self.filename if self.assigned else "(belum diberi nomor)"

    @property
    def relpath(self) -> str:
        return f"{self.category}/{self.filename}" if self.assigned else f"{UNASSIGNED_DIR}/{self.filename}"


@dataclass
class AddResult:
    item: Item
    replaced: Optional[Item] = None
    cropped: bool = False


@dataclass
class CaptureResult:
    item: Item
    image: Image.Image
    replaced: Optional[Item] = None


@dataclass
class AppendResult:
    item: Item
    part_number: int
    overlap_rows: int
    cropped: bool = False


@dataclass
class ZipResult:
    path: Path
    counts: dict[str, int]
    skipped_unassigned: int
    total: int



@dataclass
class CaptureSettings:
    category: str = "TWK"
    auto_number: bool = True
    next_number: dict[str, int] = field(default_factory=dict)


class Package:
    """Satu paket soal (mis. Paket-01) beserta workspace-nya."""

    def __init__(self, workspace_root: str | os.PathLike, name: str):
        self.name = sanitize_package_name(name)
        self.root = Path(workspace_root) / self.name
        self.items: list[Item] = []
        self.categories: list[str] = list(DEFAULT_CATEGORIES)
        self.capture = CaptureSettings()
        self.root.mkdir(parents=True, exist_ok=True)
        self._load()

    # ---------- persistence
    @property
    def state_path(self) -> Path:
        return self.root / STATE_FILE

    def _load(self) -> None:
        if not self.state_path.exists():
            self.save()
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            backup = self.state_path.with_suffix(f".rusak-{datetime.now():%Y%m%d%H%M%S}.json")
            shutil.copy2(self.state_path, backup)
            raise ManagerError(f"paket.json rusak, cadangan disimpan di {backup.name}: {exc}") from exc
        self.categories = [normalize_category(c) for c in data.get("categories", DEFAULT_CATEGORIES)]
        for c in DEFAULT_CATEGORIES:
            if c not in self.categories:
                self.categories.insert(DEFAULT_CATEGORIES.index(c), c)
        cap = data.get("capture", {})
        self.capture = CaptureSettings(
            category=cap.get("category", "TWK") if cap.get("category") in self.categories else "TWK",
            auto_number=bool(cap.get("auto_number", True)),
            next_number={k: int(v) for k, v in cap.get("next_number", {}).items()},
        )
        known = {f.name for f in Item.__dataclass_fields__.values()}
        self.items = [Item(**{k: v for k, v in raw.items() if k in known}) for raw in data.get("items", [])]

    def save(self) -> None:
        data = {
            "version": STATE_VERSION,
            "package": self.name,
            "updated_at": _now(),
            "categories": self.categories,
            "capture": asdict(self.capture),
            "items": [asdict(i) for i in self.items],
        }
        _write_json_atomic(data, self.state_path)

    # ---------- queries
    def path_of(self, item: Item) -> Path:
        return self.root / item.relpath

    def get(self, item_id: str) -> Item:
        for it in self.items:
            if it.id == item_id:
                return it
        raise ManagerError("Item tidak ditemukan")

    def find_by_fingerprint(self, fp: str) -> Optional[Item]:
        return next((i for i in self.items if i.fingerprint == fp or fp in i.part_fps), None)

    def find_slot(self, category: str, number: int) -> Optional[Item]:
        return next((i for i in self.items if i.category == category and i.number == number), None)

    def missing_files(self) -> list[Item]:
        return [i for i in self.items if not self.path_of(i).exists()]

    def sorted_items(self) -> list[Item]:
        order = {c: n for n, c in enumerate(self.categories)}
        return sorted(self.items, key=lambda i: (
            0 if i.assigned else 1, order.get(i.category, 999), i.number or 0, i.received_at))

    def max_number(self, category: str) -> int:
        return max((i.number for i in self.items if i.category == category and i.number), default=0)

    def next_number_for(self, category: str) -> int:
        return self.capture.next_number.get(category) or (self.max_number(category) + 1)

    def counts(self) -> dict[str, int]:
        out = {c: 0 for c in self.categories}
        for i in self.items:
            if i.assigned:
                out[i.category] = out.get(i.category, 0) + 1
        return out

    # ---------- categories
    def add_category(self, name: str) -> str:
        cat = normalize_category(name)
        if cat not in self.categories:
            self.categories.append(cat)
            self.save()
        return cat

    def set_next_number(self, category: str, number: int) -> None:
        if int(number) < 1:
            raise ManagerError("Nomor harus >= 1")
        self.capture.next_number[category] = int(number)
        self.save()

    # ---------- mutations
    def _check_target(self, category: Optional[str], number: Optional[int]) -> None:
        if (category is None) != (number is None):
            raise ManagerError("Kategori dan nomor harus diisi bersamaan")
        if category is not None:
            if category not in self.categories:
                raise ManagerError(f"Kategori tidak dikenal: {category}")
            if int(number) < 1:
                raise ManagerError("Nomor harus >= 1")

    def parts_dir(self, item: Item) -> Path:
        return self.root / PARTS_DIR / item.id

    def _backup_replaced(self, item: Item) -> None:
        src = self.path_of(item)
        if src.exists():
            dest_dir = self.root / REPLACED_DIR
            dest_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(src, dest_dir / f"{Path(item.filename).stem}_{stamp}_{item.id[:6]}.png")
        shutil.rmtree(self.parts_dir(item), ignore_errors=True)

    def add_image(self, source: str | os.PathLike, category: Optional[str] = None,
                  number: Optional[int] = None, crop: Optional[dict] = None) -> AddResult:
        """Salin screenshot ke workspace (sebagai PNG) dengan metadata yang diberikan.

        - Duplikat (piksel identik) -> DuplicateImageError, tidak ada yang berubah.
        - Slot kategori+nomor sudah terisi -> salinan lama diganti (dicadangkan ke _diganti/).
        """
        self._check_target(category, number)
        img, cropped = apply_crop(load_image(source), crop)
        fp = image_fingerprint(img)
        dup = self.find_by_fingerprint(fp)
        if dup is not None:
            raise DuplicateImageError(dup)

        item = Item(id=uuid.uuid4().hex, fingerprint=fp, source=str(Path(source).resolve()),
                    received_at=_now(), category=category,
                    number=int(number) if number is not None else None,
                    width=img.width, height=img.height, part_fps=[fp])
        replaced = self.find_slot(category, item.number) if item.assigned else None
        _save_png_atomic(img, self.root / (item.relpath + ".new"))  # tulis dulu, baru ganti
        if replaced is not None:
            self._backup_replaced(replaced)
            self.items.remove(replaced)
        os.replace(self.root / (item.relpath + ".new"), self.path_of(item))
        self.items.append(item)
        self.save()
        return AddResult(item, replaced, cropped)

    def add_capture(self, parts: list, category: str, number: int, source: str = "otomatis") -> CaptureResult:
        """Simpan hasil Tangkap Otomatis (bagian-bagian di memori) sekaligus: disambung & ditulis sekali."""
        self._check_target(category, number)
        fp_first = image_fingerprint(parts[0])
        dup = self.find_by_fingerprint(fp_first)
        if dup is not None:
            raise DuplicateImageError(dup)
        img = stitch(parts)[0] if len(parts) > 1 else parts[0].convert("RGB")
        item = Item(id=uuid.uuid4().hex, fingerprint=image_fingerprint(img), source=source,
                    received_at=_now(), category=category, number=int(number),
                    width=img.width, height=img.height, parts=len(parts), part_fps=[fp_first])
        replaced = self.find_slot(category, item.number)
        _save_png_atomic(img, self.root / (item.relpath + ".new"), compress_level=3)
        if replaced is not None:
            self._backup_replaced(replaced)
            self.items.remove(replaced)
        os.replace(self.root / (item.relpath + ".new"), self.path_of(item))
        self.items.append(item)
        self.save()
        return CaptureResult(item, img, replaced)

    # ---------- bagian lanjutan (soal + pembahasan yang panjang)
    def _part_files(self, item: Item) -> list[Path]:
        d = self.parts_dir(item)
        return sorted(d.glob("[0-9][0-9][0-9].png")) if d.is_dir() else []

    def _rebuild(self, item: Item, files: list[Path]) -> list[int]:
        images = [load_image(f) for f in files]
        img, overlaps = stitch(images)
        _save_png_atomic(img, self.path_of(item))
        item.width, item.height = img.width, img.height
        item.fingerprint = image_fingerprint(img)
        item.parts = len(files)
        return overlaps

    def append_part(self, item_id: str, source: str | os.PathLike,
                    crop: Optional[dict] = None) -> AppendResult:
        """Sambungkan screenshot baru ke bawah gambar item (mis. lanjutan pembahasan)."""
        item = self.get(item_id)
        img, cropped = apply_crop(load_image(source), crop)
        fp = image_fingerprint(img)
        if not item.part_fps:
            item.part_fps = [item.fingerprint]
        if fp in item.part_fps:
            raise ManagerError(f"Bagian ini sama persis dengan bagian {item.display_name} sebelumnya "
                               "(halaman belum di-scroll?)")
        dup = self.find_by_fingerprint(fp)
        if dup is not None:
            raise DuplicateImageError(dup)
        files = self._part_files(item)
        d = self.parts_dir(item)
        d.mkdir(parents=True, exist_ok=True)
        if not files:  # bagian pertama = gambar saat ini
            first = d / "001.png"
            shutil.copy2(self.path_of(item), first)
            files = [first]
        new = d / f"{len(files) + 1:03d}.png"
        _save_png_atomic(img, new)
        try:
            overlaps = self._rebuild(item, files + [new])
        except BaseException:
            new.unlink(missing_ok=True)
            raise
        item.part_fps.append(fp)
        self.save()
        return AppendResult(item, item.parts, overlaps[-1], cropped)

    def remove_last_part(self, item_id: str) -> Item:
        item = self.get(item_id)
        files = self._part_files(item)
        if len(files) < 2:
            raise ManagerError(f"{item.display_name} hanya punya satu bagian")
        files[-1].unlink()
        self._rebuild(item, files[:-1])
        if len(item.part_fps) > 1:
            item.part_fps.pop()
        if item.parts == 1:
            shutil.rmtree(self.parts_dir(item), ignore_errors=True)
        self.save()
        return item

    def assign(self, item_id: str, category: Optional[str], number: Optional[int],
               on_conflict: str = "error") -> Optional[Item]:
        """Ubah kategori/nomor item. on_conflict: 'error' | 'swap' | 'replace'.

        Mengembalikan item lain yang terdampak (ditukar/diganti), jika ada.
        """
        self._check_target(category, number)
        item = self.get(item_id)
        number = int(number) if number is not None else None
        if item.category == category and item.number == number:
            return None
        occupant = self.find_slot(category, number) if category is not None else None
        if occupant is not None and occupant.id == item.id:
            occupant = None
        if occupant is not None and on_conflict == "error":
            raise SlotTakenError(occupant)

        old_cat, old_num = item.category, item.number
        old_path = self.path_of(item)
        tmp_path = self.root / f".move-{item.id}.png"
        os.replace(old_path, tmp_path)
        try:
            if occupant is not None:
                if on_conflict == "replace":
                    self._backup_replaced(occupant)
                    self.items.remove(occupant)
                elif on_conflict == "swap":
                    occ_old = self.path_of(occupant)
                    occupant.category, occupant.number = old_cat, old_num
                    occ_new = self.path_of(occupant)
                    occ_new.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(occ_old, occ_new)
                else:
                    raise ManagerError(f"Mode konflik tidak dikenal: {on_conflict}")
            item.category, item.number = category, number
            new_path = self.path_of(item)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, new_path)
        except BaseException:
            if tmp_path.exists():
                item.category, item.number = old_cat, old_num
                os.replace(tmp_path, self.path_of(item))
            raise
        finally:
            self.save()
        return occupant

    def remove(self, item_id: str) -> Item:
        """Hapus item dari daftar (dan salinan workspace). File asli tidak disentuh."""
        item = self.get(item_id)
        self.path_of(item).unlink(missing_ok=True)
        shutil.rmtree(self.parts_dir(item), ignore_errors=True)
        self.items.remove(item)
        self.save()
        return item

    def renumber(self, category: Optional[str] = None) -> int:
        """Ulangi penamaan: nomori ulang 1..n per kategori sesuai urutan nomor saat ini."""
        cats = [category] if category else list(self.categories)
        changed = 0
        for cat in cats:
            members = sorted((i for i in self.items if i.category == cat),
                             key=lambda i: (i.number, i.received_at))
            plan = [(it, n) for n, it in enumerate(members, start=1) if it.number != n]
            if not plan:
                continue
            # fase 1: pindah ke nama sementara agar tidak bertabrakan
            for it, _ in plan:
                os.replace(self.path_of(it), self.root / f".renum-{it.id}.png")
            for it, n in plan:
                it.number = n
                os.replace(self.root / f".renum-{it.id}.png", self.path_of(it))
            changed += len(plan)
            self.capture.next_number[cat] = len(members) + 1
        self.save()
        return changed

    def repair(self) -> int:
        """Samakan nama file di workspace dengan metadata (jika ada yang tidak cocok)."""
        fixed = 0
        for it in self.items:
            expected = self.path_of(it)
            if expected.exists():
                continue
            for cand in (self.root / UNASSIGNED_DIR / f"{it.id}.png",
                         *(self.root / c / f".renum-{it.id}.png" for c in self.categories),
                         self.root / f".move-{it.id}.png", self.root / f".renum-{it.id}.png"):
                if cand.exists():
                    expected.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(cand, expected)
                    fixed += 1
                    break
        return fixed

    # ---------- export
    def display_name(self) -> str:
        return self.name.replace("-", " ").replace("_", " ")

    # ---------- pemeriksaan sebelum ekspor
    def export_check(self, expected: Optional[dict] = None) -> list[str]:
        """Peringatan: screenshot kosong/hitam, nomor hilang (dibanding jumlah per kategori), isi ganda."""
        expected = expected or {"TWK": 30, "TIU": 35, "TKP": 45}
        issues = []
        assigned = [i for i in self.sorted_items() if i.assigned]
        for it in assigned:
            try:
                with Image.open(self.path_of(it)) as im:
                    small = im.convert("L").resize((64, max(1, 64 * im.height // max(1, im.width))))
            except Exception:  # noqa: BLE001
                issues.append(f"{it.filename}: file tidak bisa dibaca")
                continue
            lo, hi = small.getextrema()
            if hi - lo < 12:
                issues.append(f"{it.filename}: screenshot {'hitam' if hi < 40 else 'kosong'} (tanpa isi)")
                continue
            from .quality import option_rows
            try:
                with Image.open(self.path_of(it)) as im:
                    rows = option_rows(im)
            except Exception:  # noqa: BLE001
                rows = 5
            if 0 < rows < 4:                       # 4 pilihan = wajar; 1–3 = pasti terpotong
                issues.append(f"{it.filename}: hanya {rows} pilihan jawaban terlihat (terpotong?)")
        for cat in self.categories:
            nums = sorted(i.number for i in assigned if i.category == cat)
            want = expected.get(cat, max(nums, default=0))
            hilang = [n for n in range(1, want + 1) if n not in nums]
            if hilang:
                issues.append(f"{cat}: nomor hilang {_ranges(hilang)} (seharusnya 1–{want})")
            lebih = [n for n in nums if n > want]
            if lebih:
                issues.append(f"{cat}: nomor di luar 1–{want}: {_ranges(lebih)}")
        seen = {}
        for it in assigned:
            if it.fingerprint in seen:
                issues.append(f"{it.filename}: isinya sama dengan {seen[it.fingerprint]} (ganda)")
            else:
                seen[it.fingerprint] = it.filename
        return issues

    def trimmed_png(self, item: Item) -> bytes:
        """Screenshot untuk ekspor: tanpa area putih di samping, tanpa tombol & ruang kosong di bawah."""
        import io as _io
        from .quality import trim_for_export
        with Image.open(self.path_of(item)) as im:
            out = trim_for_export(im)
        buf = _io.BytesIO()
        out.save(buf, "PNG", compress_level=3)
        return buf.getvalue()

    def export_zip(self, dest: str | os.PathLike, figural: bool = True,
                   extra: Optional[dict] = None, trim: bool = True) -> ZipResult:
        """ZIP untuk ChatGPT: PROMPT.txt, daftar.json, TWK/TIU/TKP/*.png.

        extra: file tambahan di akar ZIP (mis. {"soal.json": bytes} untuk ZIP siap impor).
        `figural` dipertahankan untuk kompatibilitas: False = tanpa PROMPT.txt & daftar.json."""
        dest = Path(dest)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        assigned = [i for i in self.sorted_items() if i.assigned]
        if not assigned:
            raise ManagerError("Belum ada screenshot dengan kategori & nomor untuk dimasukkan ke ZIP")
        missing = [i.filename for i in assigned if not self.path_of(i).exists()]
        if missing:
            raise ManagerError("File workspace hilang: " + ", ".join(missing[:10]))
        names = [i.relpath for i in assigned]
        if len(set(names)) != len(names):
            raise ManagerError("Ada nama file ganda; periksa daftar")
        counts: dict[str, int] = {}
        for it in assigned:
            counts[it.category] = counts.get(it.category, 0) + 1

        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".zip", dir=dest.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if figural:
                    zf.writestr("PROMPT.txt", build_prompt(self.display_name(), len(assigned)))
                    daftar = {"paket": self.display_name(), "jumlah": len(assigned),
                              "screenshot": [{"kategori": it.category, "nomor": it.number, "file": it.relpath}
                                             for it in assigned]}
                    zf.writestr("daftar.json", json.dumps(daftar, ensure_ascii=False, indent=1))
                    names += ["PROMPT.txt", "daftar.json"]
                for it in assigned:
                    if trim:                                   # judul "TRY OUT …" s.d. kalimat terakhir
                        zf.writestr(it.relpath, self.trimmed_png(it))
                    else:
                        zf.write(self.path_of(it), arcname=it.relpath)
                for name, data in (extra or {}).items():
                    zf.writestr(name, data)
                    names.append(name)
            with zipfile.ZipFile(tmp) as zf:  # verifikasi hasil
                bad = zf.testzip()
                if bad is not None:
                    raise ManagerError(f"ZIP rusak pada {bad}")
                if sorted(zf.namelist()) != sorted(names):
                    raise ManagerError("Isi ZIP tidak sesuai daftar")
            os.replace(tmp, dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return ZipResult(dest, counts, sum(1 for i in self.items if not i.assigned), len(assigned))


def _ranges(nums: list[int]) -> str:
    """[1,2,3,7,9,10] -> '1–3, 7, 9–10'"""
    out, start, prev = [], None, None
    for n in sorted(nums) + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            out.append(f"{start}–{prev}" if prev != start else f"{start}")
            start = prev = n
    return ", ".join(out)


PROMPT_TEMPLATE = """Kerjakan SEMUANYA dalam SATU jawaban. Jangan bertanya, jangan berhenti di tengah, jangan menunggu aku mengetik "lanjut".

TUGAS: salin {{JUMLAH}} soal SKD CPNS dari screenshot di ZIP ini menjadi file soal.json, lalu kembalikan ZIP ini dengan soal.json di dalamnya. Tugasmu MENYALIN, bukan mengarang. JANGAN memotong atau membuat gambar: aplikasi SKD memotong sendiri gambar soal figural dari screenshot.

CARA KERJA (pakai Python)
1. Ekstrak ZIP. Pakai hanya screenshot di TWK/, TIU/, TKP/. Abaikan daftar.json dan PROMPT.txt.
2. Kategori dan nomor dari nama file: TIU/TIU-027.png = TIU nomor 27.
3. Untuk SETIAP screenshot, urut TWK → TIU → TKP: LIHAT gambarnya langsung (jangan pakai OCR seperti pytesseract), lalu tambahkan objek soalnya ke soal.json. Simpan file setiap 10 soal supaya tidak hilang.
4. Tulis JSON ke FILE, bukan ke chat, agar tidak ada batas panjang. Karena itu tidak ada alasan meringkas.
5. Setelah selesai, periksa:
   - jumlah soal = {{JUMLAH}};
   - tidak ada nomor ganda;
   - setiap pembahasan disalin UTUH (TKP juga), tidak diringkas.
   Perbaiki dulu jika ada yang kurang.
6. Buat {{PAKET}}-siap-impor.zip = SEMUA isi ZIP asli + soal.json di akar ZIP. Berikan satu link unduh, ditambah satu baris ringkasan: "110 soal, bergambar: TIU 27–35, catatan: …".

ATURAN MENYALIN
- Salin teks soal, pilihan A–E, dan pembahasan PERSIS, kata per kata. DILARANG meringkas.
- Tidak terbaca: null dan jelaskan di "catatan". Jangan menebak.
- Pembahasan hanya dari screenshot. Jika tidak ada: null.
- Abaikan logo, menu, judul "TRY OUT …", tombol "Tampilkan", "Sebelumnya", "Selanjutnya", "Pembahasan Soal", dan baris "Jawaban kamu".
- Pertahankan angka dan simbol (2/3, x², √49, ×, ÷, ≥). Tabel ditulis sebagai teks: "| Kuantitas P | Kuantitas Q |\\n|---|---|\\n| 2/3 dari 90 | 65 |".

KUNCI
- TWK/TIU: dari "Jawaban: X" di pembahasan, atau pilihan berlatar HIJAU (MERAH bukan kunci). "skor": null.
- TKP: "kunci": null, "skor": bobot A–E dari pembahasan, contoh {"A":3,"B":5,"C":2,"D":1,"E":4}.

SUBTOPIK (tulis persis)
- TWK: Nasionalisme, Integritas, Bela Negara, Pilar Negara, Bahasa Indonesia
- TIU: Analogi Verbal, Silogisme, Analitis, Berhitung, Deret Angka, Perbandingan Kuantitatif, Soal Cerita, Analogi Figural, Ketidaksamaan Figural, Serial Figural
- TKP: Pelayanan Publik, Jejaring Kerja, Sosial Budaya, Teknologi Informasi dan Komunikasi, Profesionalisme, Anti Radikalisme

SOAL BERGAMBAR
- "bergambar": true HANYA untuk TIU Analogi Figural, Ketidaksamaan Figural, Serial Figural, atau soal yang isinya grafik/diagram. Pilihan yang berupa gambar diisi "". "pertanyaan" berisi teksnya saja, misalnya "Perhatikan gambar berikut!".
- Semua soal lain (termasuk SEMUA TWK dan TKP): "bergambar": false.
- Jangan menulis [gambar], [GAMBAR:…], atau base64.

FORMAT soal.json
{"paket": "{{PAKET}}", "soal": [
  {"kategori": "TWK", "nomor": 1, "subtopik": "Nasionalisme",
   "pertanyaan": "...", "pilihan": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."},
   "kunci": "C", "skor": null, "bergambar": false,
   "pembahasan": "...", "catatan": null}
]}
"""


def build_prompt(paket: str, jumlah: int) -> str:
    """PROMPT.txt untuk ChatGPT dengan {{PAKET}} dan {{JUMLAH}} terisi."""
    return PROMPT_TEMPLATE.replace("{{JUMLAH}}", str(jumlah)).replace("{{PAKET}}", paket)


def list_packages(workspace_root: str | os.PathLike) -> list[str]:
    root = Path(workspace_root)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / STATE_FILE).is_file())
