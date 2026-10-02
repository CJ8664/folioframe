"""Image pipeline: load -> EXIF normalize -> cover-crop -> dither -> pack 4bpp.

Pure functions, no I/O except where noted. Panel-native output for
PROTOCOL.md v1: 2 px/byte, high nibble first, rows top->bottom.
"""
import hashlib
from io import BytesIO

from PIL import Image, ImageOps

# Hardware nibble -> measured-ish sRGB (muted toward real e-ink output,
# the aitjcize measured-palette lesson: dither against perceived colors).
PALETTE = [
    (0x0, (242, 242, 238)),  # white
    (0x2, (28, 138, 48)),    # green
    (0x6, (178, 32, 32)),    # red
    (0xB, (228, 198, 28)),   # yellow
    (0xD, (38, 68, 178)),    # blue
    (0xF, (22, 22, 22)),     # black
]
VALID_NIBBLES = frozenset(n for n, _ in PALETTE)

BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]


def load_image(data: bytes) -> Image.Image:
    """Decode bytes -> RGB, applying EXIF orientation."""
    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def cover(img: Image.Image, width: int, height: int) -> Image.Image:
    """Center-crop to the target aspect ratio, then resize (Lanczos)."""
    iw, ih = img.size
    target = width / height
    cur = iw / ih
    if cur > target:  # too wide -> crop sides
        nw = int(ih * target)
        x0 = (iw - nw) // 2
        img = img.crop((x0, 0, x0 + nw, ih))
    else:  # too tall -> crop top/bottom
        nh = int(iw / target)
        y0 = (ih - nh) // 2
        img = img.crop((0, y0, iw, y0 + nh))
    return img.resize((width, height), Image.LANCZOS)


def _nearest(px):
    r, g, b = px
    best, best_d = 0x0, None
    for nib, (pr, pg, pb) in PALETTE:
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if best_d is None or d < best_d:
            best, best_d = nib, d
    return best


def _palette_image():
    """P-mode image carrying our 6 colors in PALETTE order."""
    pal = Image.new("P", (16, 16))
    flat = [c for _, (r, g, b) in PALETTE for c in (r, g, b)]
    flat += [0] * ((256 - len(PALETTE)) * 3)
    pal.putpalette(flat)
    return pal


def dither_floyd_steinberg(img: Image.Image) -> bytearray:
    """Floyd-Steinberg error diffusion -> nibble per pixel.

    Uses Pillow's C implementation against our palette (~0.05 s for a
    1200x1600 frame; a pure-Python loop takes minutes). The returned
    palette may contain duplicate entries, so indices are remapped
    through the actual output colors rather than trusted directly.
    """
    q = img.quantize(palette=_palette_image(), dither=Image.FLOYDSTEINBERG)
    pal = q.getpalette()
    lut = [_nearest((pal[3 * i], pal[3 * i + 1], pal[3 * i + 2]))
           for i in range(256)]
    mapped = q.point(lut)
    return bytearray(mapped.getdata())


def dither_ordered(img: Image.Image) -> bytearray:
    """Bayer 8x8 ordered dither -> nibble per pixel (fast, no error bleed)."""
    w, h = img.size
    px = img.load()
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            t = (BAYER8[y % 8][x % 8] / 64.0 - 0.5) * 64  # threshold offset
            r, g, b = px[x, y]
            out[y * w + x] = _nearest((r + t, g + t, b + t))
    return out


def pack(nibbles: bytearray, width: int, height: int) -> bytes:
    """Nibbles -> packed bytes, high nibble first."""
    assert len(nibbles) == width * height
    assert width % 2 == 0
    out = bytearray(width * height // 2)
    for i in range(0, len(nibbles), 2):
        out[i // 2] = (nibbles[i] << 4) | nibbles[i + 1]
    return bytes(out)


def frame_etag(frame: bytes) -> str:
    return '"' + hashlib.md5(frame).hexdigest() + '"'


def process(data: bytes, width: int, height: int,
            dither: str = "floyd") -> bytes:
    """Full pipeline: bytes in -> packed 4bpp frame out."""
    return process_image(load_image(data), width, height, dither)


def process_image(img: Image.Image, width: int, height: int,
                  dither: str = "floyd") -> bytes:
    """Full pipeline: PIL image in -> packed 4bpp frame out."""
    img = cover(img, width, height)
    nibbles = (dither_floyd_steinberg(img) if dither == "floyd"
               else dither_ordered(img))
    return pack(nibbles, width, height)


def preview_png(frame: bytes, width: int, height: int,
                max_side: int = 400) -> bytes:
    """Packed frame -> small RGB PNG preview (for the web UI)."""
    pal = dict(PALETTE)
    rgb = bytearray()
    for px in frame:
        for nib in (px >> 4, px & 0xF):
            rgb += bytes(pal.get(nib, (0, 0, 0)))
    img = Image.frombytes("RGB", (width, height), bytes(rgb))
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
