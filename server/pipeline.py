"""Image pipeline: load -> EXIF normalize -> cover-crop -> tone map ->
dynamic-range compress -> dither -> pack 4bpp.

Pure functions, no I/O except where noted. Panel-native output for
PROTOCOL.md v1: 2 px/byte, high nibble first, rows top->bottom.

Algorithm notes (evaluated Oct 2026 against the GDEB0709E01 Spectra 6 panel):

- Default dither is Floyd-Steinberg error diffusion (Pillow's C
  implementation). For photographic content on a 6-ink panel this remains
  the best choice: error diffusion is content-adaptive and the reference
  library we studied (paperlesspaper/epdoptimize) also selects it for
  photos via its auto classifier.
- The ``ordered`` mode is coverage-based Bayer dithering, ported from the
  approach in epdoptimize's ``src/utils/coverage.ts``. Instead of
  perturbing a colour and snapping to the nearest ink (whose local average
  does not reconstruct the target on a sparse 6-ink palette), it solves
  for the ink proportions whose linear-light mix *is* the target colour
  (barycentric solve over 4-ink tetrahedra) and spends the Bayer
  threshold on inverse-CDF sampling of that mixture. Their measurements
  on a Spectra 6 palette: peak neutral-ramp lightness error 19.0 -> 1.1
  Oklab L, peak chroma-circle hue error 88.9 -> 2.1 degrees, versus the
  perturb-and-snap kernel this replaces.
- Before dithering, an optional tone stage (saturation/contrast/exposure)
  and dynamic-range compression remap the photo's lightness into the
  palette's *actual* measured luminance range in LAB, with chroma
  protection for saturated colours and optional white preservation.
  Photos are mastered for emissive displays; without this the e-ink
  output looks washed out or crushed.
- Deliberately not done: serpentine error diffusion (Pillow's C
  Floyd-Steinberg has no serpentine mode and a pure-Python loop over
  1.9 M pixels takes minutes), and shelling out to a Node.js ditherer
  (the two algorithms that matter here are ported above, keeping the
  Docker image to Python + Pillow + numpy).
"""
import epaper_dithering as _ed
import hashlib
import itertools
from io import BytesIO

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

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
_INK_NIBBLES = np.array([n for n, _ in PALETTE], dtype=np.uint8)

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
_BAYER8 = np.array(BAYER8, dtype=np.float64)

# sRGB -> linear light lookup (per-channel, 0-255 in).
_SRGB2LIN = np.array(
    [(v / 255.0 / 12.92 if (v / 255.0) <= 0.04045
      else ((v / 255.0 + 0.055) / 1.055) ** 2.4)
     for v in range(256)],
    dtype=np.float64,
)

# Conservative photo-friendly defaults. Tune in config.json under "tone".
DEFAULT_TONE = {
    "saturation": 1.15,     # e-ink mutes chroma; gentle boost back
    "contrast": 1.06,
    "exposure": 0.0,        # stops; 0 = off
    "drc": "display",       # "display" | "auto" | "off"
    "drc_strength": 0.9,    # 0..1 blend toward the compressed range
    "preserve_white": True,
}


def _tone_cfg(cfg):
    merged = dict(DEFAULT_TONE)
    if cfg:
        merged.update(cfg)
    return merged


def _palette_lab_lightness(rgb):
    """LAB L (0-100) of an sRGB triple, via Pillow."""
    px = Image.new("RGB", (1, 1), tuple(rgb)).convert("LAB").getpixel((0, 0))
    return px[0] * 100.0 / 255.0


_PALETTE_LS = [_palette_lab_lightness(c) for _, c in PALETTE]
_PALETTE_BLACK_L = min(_PALETTE_LS)
_PALETTE_WHITE_L = max(_PALETTE_LS)


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


def apply_tone(img: Image.Image, cfg=None) -> Image.Image:
    """Saturation / contrast / exposure, all in Pillow C code."""
    c = _tone_cfg(cfg)
    if c["saturation"] != 1:
        img = ImageEnhance.Color(img).enhance(c["saturation"])
    if c["contrast"] != 1:
        img = ImageEnhance.Contrast(img).enhance(c["contrast"])
    if c["exposure"] != 0:
        mult = 2.0 ** c["exposure"]
        lut = [min(255, int(round(i * mult))) for i in range(256)]
        img = img.point(lut * 3)
    return img


def apply_drc(img: Image.Image, cfg=None) -> Image.Image:
    """Dynamic-range compression: remap LAB lightness into the palette's
    measured luminance range.

    ``display`` mode maps the full 0-100 source range; ``auto`` maps the
    1st-99th percentile range (better for faded/low-contrast photos).
    Saturated colours get chroma protection (less compression), and with
    ``preserve_white`` bright near-neutral pixels are pinned back up to
    the palette's white point instead of being darkened.
    """
    c = _tone_cfg(cfg)
    mode = c["drc"]
    strength = max(0.0, min(1.0, c["drc_strength"]))
    if mode == "off" or strength <= 0:
        return img

    lab = img.convert("LAB")
    l_ch, a_ch, b_ch = lab.split()
    L = np.asarray(l_ch, dtype=np.float64) * (100.0 / 255.0)
    a = np.asarray(a_ch, dtype=np.float64) - 128.0
    b = np.asarray(b_ch, dtype=np.float64) - 128.0

    if mode == "auto":
        lo, hi = np.percentile(L, (1, 99))
        if hi - lo < 0.5:  # degenerate; nothing to compress
            return img
    else:  # "display"
        lo, hi = 0.0, 100.0

    target = _PALETTE_WHITE_L - _PALETTE_BLACK_L
    compressed = _PALETTE_BLACK_L + np.clip((L - lo) / (hi - lo), 0, 1) * target

    chroma = np.sqrt(a * a + b * b)
    protection = np.clip(chroma / 60.0, 0, 1)  # vivid colours: keep their L
    eff = strength * (1.0 - protection)
    newL = L + eff * (compressed - L)

    if c["preserve_white"]:
        rgb = np.asarray(img, dtype=np.float64)
        mx = rgb.max(axis=2)
        mn = rgb.min(axis=2)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
        white_mask = (L > 92.0) & (sat < 0.12)
        newL = np.where(white_mask, np.maximum(newL, _PALETTE_WHITE_L), newL)

    l8 = np.clip(newL * 2.55, 0, 255).astype(np.uint8)
    out = Image.merge("LAB", (Image.fromarray(l8, "L"), a_ch, b_ch))
    return out.convert("RGB")


def apply_preprocessing(img: Image.Image, cfg=None) -> Image.Image:
    """Tone mapping + dynamic-range compression, in that order."""
    return apply_drc(apply_tone(img, cfg), cfg)


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
    pixels = list(dithered.getdata())
    return bytearray(_LIB_TO_NATIVE[p] for p in pixels)


def dither_floyd_steinberg(img: Image.Image) -> bytearray:
    """Floyd-Steinberg error diffusion using epaper-dithering library.

    Returns a bytearray of native color codes, row-major.
    Native codes: 0x0 black, 0x1 white, 0x2 yellow, 0x3 red, 0x5 blue, 0x6 green.
    """
    return _dither_with_library(img, _ed.DitherMode.FLOYD_STEINBERG)
def _coverage_solver():
    """Barycentric solvers for every non-degenerate 4-ink tetrahedron.

    Returns (linear_inks (6,3), squared_lengths (6,), simplices) where each
    simplex is (ink_indices tuple, inverse 4x4). Cached per process: the
    palette is a module constant.
    """
    global _coverage_solver_cache
    if _coverage_solver_cache is not None:
        return _coverage_solver_cache
    rgbs = np.array([c for _, c in PALETTE], dtype=np.uint8)
    linear = _SRGB2LIN[rgbs]  # (6,3) linear light
    lengths = (linear ** 2).sum(axis=1)
    simplices = []
    for combo in itertools.combinations(range(len(PALETTE)), 4):
        cols = linear[list(combo)]  # (4,3)
        M = np.vstack([cols.T, np.ones(4)])  # rows: r,g,b,1; cols: inks
        if abs(np.linalg.det(M)) < 1e-12:
            continue  # coplanar inks span nothing
        inv = np.linalg.inv(M)
        if not np.all(np.isfinite(inv)):
            continue
        simplices.append((combo, inv))
    _coverage_solver_cache = (linear, lengths, simplices)
    return _coverage_solver_cache


def dither_ordered(img: Image.Image) -> bytearray:
    """Ordered Bayer dithering using epaper-dithering library.

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
            dither: str = "floyd", tone_cfg=None) -> bytes:
    """Full pipeline: bytes in -> packed 4bpp frame out."""
    return process_image(load_image(data), width, height, dither, tone_cfg)


def process_image(img: Image.Image, width: int, height: int,
                  dither: str = "floyd", tone_cfg=None) -> bytes:
    """Full pipeline: PIL image in -> packed 4bpp frame out.

    ``dither``: "floyd" (error diffusion, default, best for photos) or
    "ordered" (coverage-based Bayer). ``tone_cfg``: dict overriding
    DEFAULT_TONE, or None for defaults.
    """
    img = cover(img, width, height)
    # Note: epaper-dithering handles tone mapping and gamut compression
    # internally via tone="auto" and gamut="auto". Our legacy
    # apply_preprocessing is skipped to avoid double-processing.
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
