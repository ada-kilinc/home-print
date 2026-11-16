"""Tests for the PWG Raster encoder (checked with an independent decoder)."""

from __future__ import annotations

import random
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from custom_components.home_print.convert.pwg import encode_bitmap, encode_pwg
from custom_components.home_print.convert.render import PageSpec, page_spec_for

from . import pwg_decoder

A4_COLOR = page_spec_for(None, 300, gray=False)
A4_GRAY = page_spec_for(None, 300, gray=True)
SMALL = PageSpec(
    width_px=50, height_px=70, dpi=300, margins_px=(2, 3, 4, 5), gray=False
)

R180 = Image.Transpose.ROTATE_180
FLIP_V = Image.Transpose.FLIP_TOP_BOTTOM  # FeedTransform = -1
FLIP_H = Image.Transpose.FLIP_LEFT_RIGHT  # CrossFeedTransform = -1


def _encode(pages, spec, **kwargs) -> bytes:
    kwargs.setdefault("duplex", False)
    kwargs.setdefault("tumble", False)
    kwargs.setdefault("sheet_back", None)
    return b"".join(encode_pwg(pages, spec, **kwargs))


def _noise(spec: PageSpec, seed: int, rotated: bool = False) -> Image.Image:
    """A random page, with runs mixed in so all run kinds are exercised."""
    rng = np.random.default_rng(seed)
    shape = (spec.height_px, spec.width_px) + (() if spec.gray else (3,))
    data = rng.integers(0, 256, size=shape, dtype=np.uint8)
    # Some repeated pixels, some identical rows, some white rows.
    data[:, 5:200] = data[:, 5:6]
    data[10:14] = data[9]
    data[20:300] = 255
    data[-1] = 255
    image = Image.fromarray(data, spec.mode)
    image.info["home_print_rotated"] = rotated
    return image


def _white(spec: PageSpec) -> Image.Image:
    return Image.new(spec.mode, (spec.width_px, spec.height_px), "white")


def _text_page(spec: PageSpec) -> Image.Image:
    """Black "words" on text lines, white background."""
    rnd = random.Random(1)
    image = _white(spec)
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = spec.printable
    for y in range(top + 100, bottom - 100, 50):
        x = left + 100
        while x < right - 200:
            width = rnd.randint(20, 160)
            for cx in range(x, x + width, 14):  # glyph-like stems
                draw.rectangle((cx, y, cx + 8, y + rnd.randint(22, 34)), fill="black")
            x += width + 25
    return image


def test_header_fields():
    data = _encode([_white(A4_COLOR)], A4_COLOR, page_size_name="iso_a4_210x297mm")
    assert data[:4] == b"RaS2"
    (page,) = pwg_decoder.decode(data)
    h = page.header
    assert h["PwgRaster"] == "PwgRaster"
    assert h["Width"] == 2480
    assert h["Height"] == 3508
    assert h["HWResolution"] == (300, 300)
    assert h["ColorSpace"] == 19
    assert h["NumColors"] == 3
    assert h["BitsPerColor"] == 8
    assert h["BitsPerPixel"] == 24
    assert h["BytesPerLine"] == 7440
    assert h["ColorOrder"] == 0
    assert h["PageSize"] == (595, 842)
    assert h["TotalPageCount"] == 1
    assert (h["Duplex"], h["Tumble"]) == (0, 0)
    assert (h["CrossFeedTransform"], h["FeedTransform"]) == (1, 1)
    # A4 300 dpi, 3 mm (35 px) margins; right/bottom inclusive as in CUPS.
    assert h["ImageBox"] == (35, 35, 2480 - 35 - 1, 3508 - 35 - 1)
    assert h["NumCopies"] == 1
    assert h["PrintQuality"] == 0
    assert h["MediaType"] == "" and h["RenderingIntent"] == ""
    assert h["PageSizeName"] == "iso_a4_210x297mm"
    assert h["VendorIdentifier"] == 0 and h["VendorLength"] == 0
    assert h["VendorData"] == bytes(1088)


def test_header_gray_and_copies():
    (page,) = pwg_decoder.decode(_encode([_white(A4_GRAY)], A4_GRAY, copies=3))
    h = page.header
    assert (h["ColorSpace"], h["NumColors"], h["BitsPerPixel"]) == (18, 1, 8)
    assert h["BytesPerLine"] == 2480
    assert h["NumCopies"] == 3


@pytest.mark.parametrize("spec", [SMALL, PageSpec(37, 23, 300, (0,) * 4, True)])
def test_roundtrip_small(spec):
    pages = [_noise(spec, seed) for seed in range(3)]
    decoded = pwg_decoder.decode(_encode(pages, spec))
    assert [p.image.tobytes() for p in decoded] == [p.tobytes() for p in pages]


@pytest.mark.parametrize("spec", [A4_GRAY, A4_COLOR], ids=["gray", "color"])
def test_roundtrip_gray_and_color(spec):
    pages = [_noise(spec, 7), _text_page(spec)]
    decoded = pwg_decoder.decode(_encode(pages, spec))
    assert len(decoded) == 2
    for got, want in zip(decoded, pages, strict=True):
        assert got.image.mode == want.mode
        assert got.image.tobytes() == want.tobytes()


def test_compression_white_page_is_small():
    data = _encode([_white(A4_COLOR)], A4_COLOR)
    assert len(data) < 20 * 1024


def test_encode_bitmap_runs():
    """Literal, repeat and single-pixel runs, split at 128; line repeats."""
    # 1-byte pixels: [5]*130 + [1, 2, 3] + [9] -> repeat 128, repeat 2, literal 3,
    # single (encoded as a repeat of 1).
    row = [5] * 130 + [1, 2, 3, 9, 9, 9, 4]
    rows = np.array([row, row, row], dtype=np.uint8)
    assert encode_bitmap(rows, 1) == bytes([2, 127, 5, 1, 5, 254, 1, 2, 3, 2, 9, 0, 4])
    # 256 identical lines need two line-repeat groups.
    rows = np.full((300, 2, 3), 255, dtype=np.uint8)
    assert encode_bitmap(rows, 3) == bytes(
        [255, 1, 255, 255, 255, 43, 1, 255, 255, 255]
    )


def test_encode_bitmap_white_end_of_line_is_opt_in():
    """0x80 is not in PWG 5102.4; only URF (Apple raster) may use it."""
    row = [0, 1, 255, 255, 255]
    rows = np.array([row], dtype=np.uint8)
    assert encode_bitmap(rows, 1) == bytes([0, 255, 0, 1, 2, 255])
    assert encode_bitmap(rows, 1, white_eol=True) == bytes([0, 255, 0, 1, 128])
    # Not white at the end: no 0x80.
    assert encode_bitmap(rows[:, :2], 1, white_eol=True) == bytes([0, 255, 0, 1])


def test_duplex_odd_pages_adds_blank_back():
    pages = [_noise(SMALL, seed) for seed in range(3)]
    decoded = pwg_decoder.decode(
        _encode(pages, SMALL, duplex=True, tumble=False, sheet_back="normal")
    )
    assert len(decoded) == 4
    assert decoded[3].image.tobytes() == _white(SMALL).tobytes()
    assert {p.header["TotalPageCount"] for p in decoded} == {4}
    assert {p.header["Duplex"] for p in decoded} == {1}


def test_duplex_page_count_from_iterator():
    """A lazy iterator gives no length: page_count fills TotalPageCount."""
    pages = (_noise(SMALL, seed) for seed in range(3))
    decoded = pwg_decoder.decode(
        _encode(pages, SMALL, duplex=True, sheet_back="normal", page_count=3)
    )
    assert {p.header["TotalPageCount"] for p in decoded} == {4}
    # Unknown count -> 0, as PWG 5102.4 allows.
    decoded = pwg_decoder.decode(_encode(iter([_white(SMALL)]), SMALL))
    assert decoded[0].header["TotalPageCount"] == 0


def test_even_duplex_and_simplex_add_no_page():
    pages = [_noise(SMALL, 1), _noise(SMALL, 2)]
    assert len(pwg_decoder.decode(_encode(pages, SMALL, duplex=True))) == 2
    assert len(pwg_decoder.decode(_encode(pages[:1], SMALL))) == 1


# PWG 5102.4 Table 9 ("Transform Values for Backside Images") and section
# 5.1.1 (pwg-raster-document-sheet-back). tumble=False is two-sided-long-edge.
# (sheet_back, tumble) -> (CrossFeedTransform, FeedTransform, pixel transform)
BACK_SIDE_TABLE = {
    ("normal", False): (1, 1, None),
    ("normal", True): (1, 1, None),
    ("manual-tumble", False): (1, 1, None),
    ("manual-tumble", True): (-1, -1, R180),
    ("rotated", False): (-1, -1, R180),  # HP DeskJet 4670, long edge
    ("rotated", True): (1, 1, None),
    ("flipped", False): (1, -1, FLIP_V),
    ("flipped", True): (-1, 1, FLIP_H),
    (None, False): (1, 1, None),  # printer did not say: like normal
    (None, True): (1, 1, None),
}


@pytest.mark.parametrize(("sheet_back", "tumble"), list(BACK_SIDE_TABLE))
def test_back_side_transform_table(sheet_back, tumble):
    cross, feed, transpose = BACK_SIDE_TABLE[(sheet_back, tumble)]
    pages = [_noise(SMALL, seed) for seed in range(4)]
    decoded = pwg_decoder.decode(
        _encode(pages, SMALL, duplex=True, tumble=tumble, sheet_back=sheet_back)
    )
    for index, (got, want) in enumerate(zip(decoded, pages, strict=True)):
        h = got.header
        assert h["Tumble"] == int(tumble)
        if index % 2 == 0:  # front sides are never transformed
            assert (h["CrossFeedTransform"], h["FeedTransform"]) == (1, 1)
            assert got.image.tobytes() == want.tobytes()
        else:
            assert (h["CrossFeedTransform"], h["FeedTransform"]) == (cross, feed)
            expected = want if transpose is None else want.transpose(transpose)
            assert got.image.tobytes() == expected.tobytes()


def test_deskjet_rotated_long_edge_back_is_rotated_180():
    """The user's printer: sheet-back rotated, two-sided-long-edge."""
    spec = PageSpec(40, 60, 300, (0,) * 4, gray=False)
    front, back = _white(spec), _white(spec)
    ImageDraw.Draw(back).rectangle((0, 0, 9, 9), fill=(255, 0, 0))  # top-left mark
    _, decoded_back = pwg_decoder.decode(
        _encode([front, back], spec, duplex=True, tumble=False, sheet_back="rotated")
    )
    image = decoded_back.image
    assert image.getpixel((39, 59)) == (255, 0, 0)  # now bottom-right
    assert image.getpixel((0, 0)) == (255, 255, 255)
    h = decoded_back.header
    assert (h["CrossFeedTransform"], h["FeedTransform"]) == (-1, -1)
    # The image box follows the transform (PWG 5102.4: "reflecting the
    # transform orientation"): left/top margins swap with right/bottom.
    _, decoded_back = pwg_decoder.decode(
        _encode(
            [_white(SMALL), _white(SMALL)],
            SMALL,
            duplex=True,
            tumble=False,
            sheet_back="rotated",
        )
    )
    # SMALL margins: top 2, right 3, bottom 4, left 5 -> rotated: left 3, top 4.
    assert decoded_back.header["ImageBox"] == (3, 4, 50 - 5 - 1, 70 - 2 - 1)


@pytest.mark.parametrize(
    ("sheet_back", "tumble", "rotated_back", "cross", "feed", "transpose", "hdr"),
    [
        # Landscape content turned onto portrait paper flips the binding
        # edge: effective tumble = tumble XOR home_print_rotated (Ruling O).
        ("rotated", False, True, 1, 1, None, 1),
        ("rotated", True, True, -1, -1, R180, 0),
        ("manual-tumble", False, True, -1, -1, R180, 1),
        ("flipped", False, True, -1, 1, FLIP_H, 1),
        ("flipped", True, True, 1, -1, FLIP_V, 0),
        ("rotated", False, False, -1, -1, R180, 0),
    ],
)
def test_rotated_content_swaps_back_side_tumble(
    sheet_back, tumble, rotated_back, cross, feed, transpose, hdr
):
    front = _noise(SMALL, 1, rotated=rotated_back)
    back = _noise(SMALL, 2, rotated=rotated_back)
    _, got = pwg_decoder.decode(
        _encode([front, back], SMALL, duplex=True, tumble=tumble, sheet_back=sheet_back)
    )
    assert (got.header["CrossFeedTransform"], got.header["FeedTransform"]) == (
        cross,
        feed,
    )
    assert got.header["Tumble"] == hdr
    expected = back if transpose is None else back.transpose(transpose)
    assert got.image.tobytes() == expected.tobytes()


def test_simplex_ignores_sheet_back():
    pages = [_noise(SMALL, 1), _noise(SMALL, 2)]
    decoded = pwg_decoder.decode(
        _encode(pages, SMALL, duplex=False, tumble=False, sheet_back="rotated")
    )
    assert [p.image.tobytes() for p in decoded] == [p.tobytes() for p in pages]
    assert {
        (p.header["CrossFeedTransform"], p.header["FeedTransform"]) for p in decoded
    } == {(1, 1)}


def test_unknown_sheet_back_raises():
    with pytest.raises(ValueError):
        _encode([_white(SMALL)], SMALL, duplex=True, sheet_back="sideways")


def test_page_size_mismatch_raises():
    with pytest.raises(ValueError):
        _encode([Image.new("RGB", (10, 10), "white")], SMALL)
    with pytest.raises(ValueError):
        _encode([Image.new("L", (50, 70), "white")], SMALL)


def test_encode_is_streaming():
    consumed = []

    def pages():
        for seed in range(3):
            consumed.append(seed)
            yield _noise(SMALL, seed)

    stream = encode_pwg(pages(), SMALL, duplex=False, tumble=False, sheet_back=None)
    assert not consumed  # generator: nothing done before the first next()
    assert next(stream) == b"RaS2"
    assert not consumed
    next(stream)
    assert consumed == [0]
    rest = list(stream)
    assert consumed == [0, 1, 2]
    assert rest


@pytest.mark.parametrize("spec", [A4_COLOR, A4_GRAY], ids=["color", "gray"])
def test_encode_speed(spec):
    page = _text_page(spec)
    start = time.perf_counter()
    data = _encode([page], spec)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{elapsed:.2f} s"
    assert len(data) < 2 * 1024 * 1024
