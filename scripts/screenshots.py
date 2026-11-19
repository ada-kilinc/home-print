"""Render the README screenshots in docs/images/ from the real card.

The card runs in a headless Chromium against a fake `hass`
(scripts/screenshots/fake-hass.js), in Home Assistant's dark theme, at
360 px wide (a phone), saved 600 px wide. Previews get a drawn
sample page, so no printer is needed.

    pip install playwright pillow
    python -m playwright install chromium   # or pass --chrome /path/to/chrome
    python scripts/screenshots.py
"""

from __future__ import annotations

import argparse
import functools
import http.server
import io
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
WIDTH = 360
SHEET_HEIGHT = 500
# 600 px wide images, as the README shows them.
SCALE = 600 / WIDTH


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


@functools.cache
def sample_page() -> bytes:
    """An A4-ish page: a title, text lines and a bar chart."""
    w, h = 620, 877
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), "Monthly report", fill="#111111", font=_font(26, bold=True))
    y = 110
    for i in range(14):
        length = 360 if i % 4 == 0 else 520
        draw.rectangle((50, y, 50 + length, y + 7), fill="#c8c8c8")
        y += 22
    box = (50, y + 20, 570, y + 300)
    draw.rectangle(box, outline="#4a86d8", width=2)
    bars = [0.35, 0.7, 0.55, 0.9, 0.65]
    step = (box[2] - box[0]) / len(bars)
    for i, value in enumerate(bars):
        x0 = box[0] + step * i + step * 0.25
        top = box[3] - (box[3] - box[1] - 20) * value
        draw.rectangle((x0, top, x0 + step * 0.5, box[3]), fill="#4a86d8")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(root)
    )
    handler.log_message = lambda *args: None  # type: ignore[method-assign]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def shadow(page: Page, role: str) -> str:
    return f'home-print-card [data-role="{role}"]'


def open_card(page: Page, base: str, *, several: bool = False) -> None:
    query = "?several" if several else ""
    page.goto(f"{base}/scripts/screenshots/harness.html{query}")
    page.wait_for_function("window.ready === true")
    page.locator(shadow(page, "title")).filter(has_text="HP").wait_for()
    page.wait_for_timeout(200)


def card_shot(page: Page, name: str) -> None:
    page.locator("home-print-card ha-card").screenshot(path=str(OUT / name))
    print("wrote", OUT / name)


def page_shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / name))
    print("wrote", OUT / name)


def run(chrome: str | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    server, base = serve(ROOT)
    demo = Path(tempfile.mkdtemp()) / "monthly-report.pdf"
    demo.write_bytes(b"%PDF-1.4\n" + b"0" * 246_000)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
            context = browser.new_context(
                viewport={"width": WIDTH, "height": 900},
                device_scale_factor=SCALE,
                color_scheme="dark",
                locale="en-US",
                timezone_id="Europe/Amsterdam",
            )
            context.route(
                "**/api/home_print/**",
                lambda route: route.fulfill(
                    content_type="image/png", body=sample_page()
                ),
            )
            page = context.new_page()

            # Print tab with a file picked.
            open_card(page, base)
            page.set_input_files(shadow(page, "input-file"), str(demo))
            page.wait_for_timeout(200)
            card_shot(page, "card.png")

            # Scan tab with a finished two-page scan.
            open_card(page, base)
            page.click(shadow(page, "body-tab-scan"))
            page.click(shadow(page, "scan-start"))
            page.locator("home-print-card .scan-page img").wait_for()
            page.wait_for_timeout(300)
            card_shot(page, "scan.png")

            # Several printers: the switcher list open.
            open_card(page, base, several=True)
            page.click(shadow(page, "switcher"))
            page.wait_for_timeout(200)
            card_shot(page, "printers.png")

            # History, Scans and a preview: the sheet over the card.
            page.set_viewport_size({"width": WIDTH, "height": SHEET_HEIGHT})
            open_card(page, base)
            page.click(shadow(page, "history-button"))
            page.locator('home-print-card [data-role="history-open"]').first.wait_for()
            page.wait_for_timeout(300)
            page_shot(page, "history.png")
            page.click(shadow(page, "tab-scans"))
            page.locator('home-print-card [data-role="scan-open"]').first.wait_for()
            page.wait_for_timeout(300)
            page_shot(page, "scans.png")
            page.click(shadow(page, "tab-prints"))
            page.locator('home-print-card [data-role="history-open"]').first.click()
            page.locator("home-print-card .preview-body img").first.wait_for()
            page.wait_for_timeout(300)
            page_shot(page, "preview.png")
            browser.close()
    finally:
        server.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--chrome", help="Chrome/Chromium binary (default: Playwright's)"
    )
    run(parser.parse_args().chrome)


if __name__ == "__main__":
    main()
