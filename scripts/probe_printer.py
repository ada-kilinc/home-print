#!/usr/bin/env python3
"""Probe an IPP printer and print the attributes Home Print cares about.

Usage:
    python scripts/probe_printer.py <host> [--port 631] [--path /ipp/print]
                                    [--tls] [--save]

Requires ``pyipp`` and ``aiohttp`` (both installed with Home Assistant).
With ``--save`` the full Get-Printer-Attributes response is written to
``tests/fixtures/printer_<model>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import aiohttp

KEYS = [
    "printer-make-and-model",
    "printer-uuid",
    "document-format-supported",
    "sides-supported",
    "print-color-mode-supported",
    "page-ranges-supported",
    "copies-supported",
    "marker-names",
    "marker-levels",
    "marker-colors",
    "marker-types",
    "urf-supported",
    "pwg-raster-document-resolution-supported",
]

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _jsonable(value):
    """Make parsed IPP values JSON serialisable."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def fetch_attributes(args: argparse.Namespace) -> dict:
    from pyipp import IPP
    from pyipp.enums import IppOperation

    async with IPP(
        host=args.host,
        port=args.port,
        base_path=args.path,
        tls=args.tls,
        verify_ssl=False,
    ) as ipp:
        response = await ipp.execute(
            IppOperation.GET_PRINTER_ATTRIBUTES,
            {"operation-attributes-tag": {"requested-attributes": ["all"]}},
        )
    printers = response.get("printers") or []
    return printers[0] if printers else {}


async def check_escl(host: str, tls: bool) -> str:
    scheme = "https" if tls else "http"
    url = f"{scheme}://{host}/eSCL/ScannerCapabilities"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, ssl=False) as resp:
                return (
                    f"eSCL: present ({url} -> HTTP {resp.status})"
                    if (resp.status == 200)
                    else f"eSCL: absent ({url} -> HTTP {resp.status})"
                )
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        return f"eSCL: absent or unreachable ({url}: {err})"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "unknown"


async def main(args: argparse.Namespace) -> int:
    try:
        attrs = await fetch_attributes(args)
    except Exception as err:  # noqa: BLE001
        print(
            f"Connection error: could not query {args.host}:{args.port}"
            f"{args.path}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return 1

    for key in KEYS:
        print(f"{key}: {_jsonable(attrs.get(key, '<not reported>'))}")
    print(await check_escl(args.host, args.tls))

    if args.save:
        model = slug(str(attrs.get("printer-make-and-model", "unknown")))
        FIXTURES.mkdir(parents=True, exist_ok=True)
        out = FIXTURES / f"printer_{model}.json"
        out.write_text(
            json.dumps(_jsonable(attrs), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
        print(f"Saved full response to {out}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("host")
    p.add_argument("--port", type=int, default=631)
    p.add_argument("--path", default="/ipp/print")
    p.add_argument("--tls", action="store_true", help="use ipps (TLS)")
    p.add_argument("--save", action="store_true", help="save fixture JSON")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
