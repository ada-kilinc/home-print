"""Sample documents generated at test time (no binary files in the repo)."""

from __future__ import annotations

import hashlib
import io

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

A4_PT = (595, 842)
RED = (255, 0, 0)
MARK_FRACTION = 5  # the corner mark is 1/5 of the shorter side


def page_image(
    width: int, height: int, background=(255, 255, 255), mark: bool = True
) -> Image.Image:
    """An RGB page with a red square in its top-left corner."""
    image = Image.new("RGB", (width, height), background)
    if mark:
        side = min(width, height) // MARK_FRACTION
        ImageDraw.Draw(image).rectangle((0, 0, side, side), fill=RED)
    return image


def pdf_from_images(images: list[Image.Image]) -> bytes:
    """A PDF with one page per image, 1 px = 1 pt."""
    out = io.BytesIO()
    images[0].save(out, "PDF", resolution=72.0, save_all=True, append_images=images[1:])
    return out.getvalue()


def blank_pdf(page_count: int, size: tuple[int, int] = A4_PT) -> bytes:
    """A PDF with ``page_count`` empty pages (made with pypdfium2)."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(page_count):
        pdf.new_page(*size)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


def image_bytes(image: Image.Image, fmt: str, **kwargs) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt, **kwargs)
    return out.getvalue()


# --- password protected PDF -------------------------------------------------
# Neither Pillow nor pypdfium2 can write encrypted PDFs, so this builds a
# minimal one by hand: Standard security handler, V=1 R=2 (RC4 40-bit),
# user password "secret". The page has no content stream, so no object data
# needs encrypting; the /O and /U entries are computed per PDF 1.7 §7.6.3.

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")
USER_PASSWORD = "secret"


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _pad(password: str) -> bytes:
    return (password.encode("latin-1") + _PAD)[:32]


def encrypted_pdf(user_password: str = USER_PASSWORD) -> bytes:
    """A one-page PDF that cannot be opened without ``user_password``."""
    file_id = bytes(range(16))
    permissions = -4  # all permissions; signed 32-bit
    owner = _rc4(hashlib.md5(_pad("owner")).digest()[:5], _pad(user_password))
    key = hashlib.md5(
        _pad(user_password)
        + owner
        + permissions.to_bytes(4, "little", signed=True)
        + file_id
    ).digest()[:5]
    user = _rc4(key, _PAD)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        b"<< /Filter /Standard /V 1 /R 2 /O <"
        + owner.hex().encode()
        + b"> /U <"
        + user.hex().encode()
        + b"> /P "
        + str(permissions).encode()
        + b" >>",
    ]
    ids = file_id.hex().encode()
    return build_pdf(objects, b"/Encrypt 4 0 R /ID [<%s> <%s>]" % (ids, ids))


def build_pdf(objects: list[bytes], trailer_extra: bytes = b"") -> bytes:
    """A PDF from raw object bodies (object 1 must be the catalog)."""
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        body += b"%010d 00000 n \n" % offset
    body += b"trailer\n<< /Size %d /Root 1 0 R %s >>\n" % (
        len(objects) + 1,
        trailer_extra,
    )
    body += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(body)


def pdf_with_broken_second_page() -> bytes:
    """Two pages in /Count, but the second page object is a plain string."""
    return build_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
            b"(garbage)",
        ]
    )
