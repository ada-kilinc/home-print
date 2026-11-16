"""Tests for the Apple Raster (URF) encoder (independent decoder)."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from custom_components.home_print.convert.render import PageSpec, page_spec_for
from custom_components.home_print.convert.urf import DM_SHEET_BACK, encode_urf

from . import urf_decoder
from .test_pwg import BACK_SIDE_TABLE, SMALL, _noise, _white

A4_COLOR = page_spec_for(None, 300, gray=False)
SMALL_GRAY = PageSpec(50, 70, 300, (2, 3, 4, 5), gray=True)


def _encode(pages, spec, **kwargs) -> bytes:
    kwargs.setdefault("duplex", False)
    kwargs.setdefault("tumble", False)
    if not hasattr(pages, "__len__"):
        kwargs.setdefault("page_count", 1)
    return b"".join(encode_urf(pages, spec, **kwargs))


def test_urf_header():
    data = _encode([_white(A4_COLOR)], A4_COLOR)
    assert data[:8] == b"UNIRAST\0"
    assert data[8:12] == (1).to_bytes(4, "big")
    page_header = data[12:44]
    assert page_header[0] == 24  # bits per pixel
    assert page_header[1] == 1  # sRGB
    assert page_header[2] == 1  # duplex: none
    assert page_header[3] == 0  # quality: printer default
    assert page_header[4:12] == bytes(8)  # media type/position, reserved
    assert page_header[12:16] == (2480).to_bytes(4, "big")
    assert page_header[16:20] == (3508).to_bytes(4, "big")
    assert page_header[20:24] == (300).to_bytes(4, "big")
    assert page_header[24:32] == bytes(8)
    (page,) = urf_decoder.decode(data)
    assert page.header["Width"] == 2480


def test_urf_header_gray():
    data = _encode([_white(SMALL_GRAY)], SMALL_GRAY)
    assert (data[12], data[13]) == (8, 0)  # 8 bpp, sGray


@pytest.mark.parametrize("spec", [SMALL, SMALL_GRAY], ids=["color", "gray"])
def test_urf_roundtrip_gray_color(spec):
    pages = [_noise(spec, seed) for seed in range(3)] + [_white(spec)]
    decoded = urf_decoder.decode(_encode(pages, spec))
    assert len(decoded) == 4
    for got, want in zip(decoded, pages, strict=True):
        assert got.image.mode == spec.mode
        assert got.image.tobytes() == want.tobytes()


def test_urf_uses_white_end_of_line_code():
    """A white page is one 0x80 per distinct line group: tiny, and decodable."""
    data = _encode([_white(A4_COLOR)], A4_COLOR)
    assert len(data) < 200
    assert urf_decoder.decode(data)[0].image.getextrema() == ((255, 255),) * 3


def test_urf_duplex_odd_pages_adds_blank_back():
    pages = [_noise(SMALL, seed) for seed in range(3)]
    data = _encode(pages, SMALL, duplex=True, tumble=False)
    assert data[8:12] == (4).to_bytes(4, "big")  # count includes the blank
    decoded = urf_decoder.decode(data)
    assert len(decoded) == 4
    assert decoded[3].image.tobytes() == _white(SMALL).tobytes()
    assert {p.header["Duplex"] for p in decoded} == {3}  # long edge


def test_urf_even_duplex_and_simplex_add_no_page():
    pages = [_noise(SMALL, 1), _noise(SMALL, 2)]
    assert len(urf_decoder.decode(_encode(pages, SMALL, duplex=True))) == 2
    assert len(urf_decoder.decode(_encode(pages[:1], SMALL))) == 1


@pytest.mark.parametrize(
    ("duplex", "tumble", "rotated", "value"),
    [
        (False, False, False, 1),
        (False, True, False, 1),
        (True, False, False, 3),  # long edge
        (True, True, False, 2),  # short edge
        (True, False, True, 2),  # content turned 90 deg: edge swaps (Ruling O)
        (True, True, True, 3),
    ],
)
def test_urf_duplex_values(duplex, tumble, rotated, value):
    pages = [_noise(SMALL, 1, rotated=rotated), _noise(SMALL, 2, rotated=rotated)]
    decoded = urf_decoder.decode(_encode(pages, SMALL, duplex=duplex, tumble=tumble))
    assert {p.header["Duplex"] for p in decoded} == {value}


def test_urf_page_count_from_iterator_and_validation():
    pages = (_noise(SMALL, s) for s in range(3))
    data = _encode(pages, SMALL, duplex=True, page_count=3)
    assert data[8:12] == (4).to_bytes(4, "big")
    assert len(urf_decoder.decode(data)) == 4
    # No length available and no page_count: refuse before writing anything.
    with pytest.raises(ValueError, match="page_count"):
        encode_urf(iter([_white(SMALL)]), SMALL, duplex=False, tumble=False)
    # Disagreeing counts are caught up front when the length is known ...
    with pytest.raises(ValueError, match="page_count"):
        encode_urf([_white(SMALL)], SMALL, duplex=False, tumble=False, page_count=2)
    with pytest.raises(ValueError, match="page_count"):
        encode_urf([], SMALL, duplex=False, tumble=False)
    # ... and while streaming when it is not (too few / too many pages).
    with pytest.raises(ValueError, match="page_count"):
        _encode(iter([_white(SMALL)]), SMALL, page_count=2)
    with pytest.raises(ValueError, match="page_count"):
        _encode(iter([_white(SMALL)] * 2), SMALL, page_count=1)


def test_urf_dm_mapping():
    """urf-supported DMn -> PWG sheet-back (cfGetBackSideOrientation)."""
    assert DM_SHEET_BACK == {
        "DM1": "normal",
        "DM2": "flipped",
        "DM3": "rotated",
        "DM4": "manual-tumble",
    }


@pytest.mark.parametrize(
    ("dm", "tumble"),
    [(dm, t) for dm in (None, "DM1", "DM2", "DM3", "DM4") for t in (False, True)],
)
def test_urf_back_side_transform(dm, tumble):
    """Back sides get the PWG Table 9 pixel transform for the DM's sheet-back."""
    sheet_back = DM_SHEET_BACK.get(dm)
    transpose = BACK_SIDE_TABLE[(sheet_back, tumble)][2]
    pages = [_noise(SMALL, seed) for seed in range(4)]
    decoded = urf_decoder.decode(
        _encode(pages, SMALL, duplex=True, tumble=tumble, dm=dm)
    )
    for index, (got, want) in enumerate(zip(decoded, pages, strict=True)):
        assert got.header["Duplex"] == (2 if tumble else 3)
        if index % 2 == 0 or transpose is None:
            assert got.image.tobytes() == want.tobytes()
        else:
            assert got.image.tobytes() == want.transpose(transpose).tobytes()


def test_urf_dm3_long_edge_back_is_rotated_180():
    """The DeskJet-style 'rotated' back: mark moves top-left -> bottom-right."""
    spec = PageSpec(40, 60, 300, (0,) * 4, gray=False)
    back = _white(spec)
    ImageDraw.Draw(back).rectangle((0, 0, 9, 9), fill=(255, 0, 0))
    _, got = urf_decoder.decode(
        _encode([_white(spec), back], spec, duplex=True, tumble=False, dm="DM3")
    )
    assert got.image.getpixel((39, 59)) == (255, 0, 0)
    assert got.image.getpixel((0, 0)) == (255, 255, 255)


def test_urf_rotated_content_swaps_back_side_tumble():
    front, back = _noise(SMALL, 1, rotated=True), _noise(SMALL, 2, rotated=True)
    # tumble False XOR rotated -> short edge; with DM3 that is "rotated, tumble"
    # = no transform; with tumble True it is long edge = rotated 180.
    _, got = urf_decoder.decode(
        _encode([front, back], SMALL, duplex=True, tumble=False, dm="DM3")
    )
    assert got.header["Duplex"] == 2
    assert got.image.tobytes() == back.tobytes()
    _, got = urf_decoder.decode(
        _encode([front, back], SMALL, duplex=True, tumble=True, dm="DM3")
    )
    assert got.header["Duplex"] == 3
    assert got.image.tobytes() == back.transpose(Image.Transpose.ROTATE_180).tobytes()


def test_urf_simplex_ignores_dm():
    pages = [_noise(SMALL, 1), _noise(SMALL, 2)]
    decoded = urf_decoder.decode(_encode(pages, SMALL, dm="DM3"))
    assert [p.image.tobytes() for p in decoded] == [p.tobytes() for p in pages]


def test_urf_rejects_bad_arguments():
    with pytest.raises(ValueError, match="DM"):
        _encode([_white(SMALL)], SMALL, duplex=True, dm="DM9")
    with pytest.raises(ValueError, match="copies"):
        _encode([_white(SMALL)], SMALL, copies=2)
    with pytest.raises(ValueError):
        _encode([Image.new("RGB", (10, 10), "white")], SMALL)
    with pytest.raises(ValueError):
        _encode([Image.new("L", (50, 70), "white")], SMALL)


def test_urf_is_streaming():
    consumed = []

    def pages():
        for seed in range(3):
            consumed.append(seed)
            yield _noise(SMALL, seed)

    stream = encode_urf(pages(), SMALL, duplex=False, tumble=False, page_count=3)
    assert not consumed
    assert next(stream)[:8] == b"UNIRAST\0"
    assert not consumed
    next(stream)
    assert consumed == [0]
    assert list(stream)
    assert consumed == [0, 1, 2]
