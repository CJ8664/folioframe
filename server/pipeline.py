"""Render photos into the device's packed Spectra 6 frame format.

The active path is EXIF normalization, center-crop/resize, dithering and
4bpp packing. Dithering and gamut/tone mapping are provided by
``epaper-dithering``; server-generated preview PNGs use the same
native palette mapping.
"""
import epaper_dithering as _ed
import hashlib
from io import BytesIO

from PIL import Image, ImageOps

# Hard cap on decoded pixel count: a 25 MB upload can hide gigapixels of
# decompressed data. 50 MP is far above anything this pipeline needs
# (the frame itself is 1200x1600 = 1.9 MP); beyond it Pillow raises
# DecompressionBombError instead of just warning.
Image.MAX_IMAGE_PIXELS = 50_000_000

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


def load_image(data: bytes) -> Image.Image:
    """Decode bytes -> RGB, applying EXIF orientation."""
    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def cover(img: Image.Image, width: int, height: int) -> Image.Image:
    """Center-crop to the target aspect ratio, then resize (Lanczos)."""
    iw, ih = img.size
    if iw == 0 or ih == 0:
        raise ValueError("degenerate image (zero width or height)")
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


# Mapping from epaper-dithering palette indices to our PALETTE nibbles.
# Library palette order: 0=black, 1=white, 2=yellow, 3=red, 4=blue, 5=green
# Our PALETTE: 0x0=white, 0x2=green, 0x6=red, 0xB=yellow, 0xD=blue, 0xF=black
_LIB_TO_NATIVE = (0xF, 0x0, 0xB, 0x6, 0xD, 0x2)


def _dither_with_library(img: Image.Image, mode) -> bytearray:
    """Dither using epaper-dithering library, return native color codes."""
    # The library handles tone mapping and gamut compression internally
    # when tone='auto' and gamut='auto' are set.
    dithered = _ed.dither_image(
        img,
        _ed.SPECTRA_7_3_6COLOR_V2,
        mode=mode,
        tone="auto",
        gamut="auto",
    )
    # Convert palette indices to native codes
    return bytearray(_LIB_TO_NATIVE[p] for p in dithered.getdata())


def dither_floyd_steinberg(img: Image.Image) -> bytearray:
    """Floyd-Steinberg error diffusion using epaper-dithering library.

    Returns a bytearray of native color codes, row-major.
    Codes are 0x0 white, 0x2 green, 0x6 red, 0xB yellow, 0xD blue,
    and 0xF black.
    """
    return _dither_with_library(img, _ed.DitherMode.FLOYD_STEINBERG)


def dither_ordered(img: Image.Image) -> bytearray:
    """Ordered dithering using epaper-dithering library.

    Returns a bytearray of native color codes, row-major.
    """
    return _dither_with_library(img, _ed.DitherMode.ORDERED)


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
    """Full pipeline: PIL image in -> packed 4bpp frame out.

    ``dither`` is "floyd" (error diffusion, default) or "ordered".
    """
    img = cover(img, width, height)
    # Note: epaper-dithering handles tone mapping and gamut compression
    # internally via tone="auto" and gamut="auto".
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
