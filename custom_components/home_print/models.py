"""Data models for Home Print."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def normalize_uuid(value: str) -> str:
    """Return a printer UUID without ``urn:uuid:`` prefix, lowercased."""
    value = value.strip()
    if value.lower().startswith("urn:uuid:"):
        value = value[len("urn:uuid:") :]
    return value.strip().lower()


@dataclass(frozen=True)
class Marker:
    """A consumable (ink, toner, waste container)."""

    name: str
    color: str | None
    level: int | None  # 0-100, None when the printer reports -1/-2/-3
    kind: str


@dataclass(frozen=True)
class RasterCaps:
    """Raster formats the printer accepts (PWG raster and Apple URF)."""

    pwg_types: frozenset[str]
    pwg_resolutions: tuple[int, ...]  # dpi, only entries with x == y
    pwg_sheet_back: str | None
    urf: frozenset[str]  # raw urf-supported keywords, e.g. "W8-16", "RS300"


@dataclass(frozen=True)
class MediaCaps:
    """Default media: name, size and margins, all in 1/100 mm."""

    default_name: str
    width_hmm: int
    height_hmm: int
    margins_hmm: tuple[int, int, int, int]  # top, right, bottom, left


@dataclass(frozen=True)
class JpegLimits:
    """Upper limits for JPEG documents; None when not reported."""

    max_x: int | None
    max_y: int | None
    max_kb: int | None


@dataclass(frozen=True)
class Capabilities:
    """What the printer says it can do."""

    document_formats: frozenset[str]
    sides: frozenset[str]
    color_modes: frozenset[str]
    copies_max: int
    page_ranges: bool
    raster: RasterCaps | None = None
    media: MediaCaps | None = None
    jpeg: JpegLimits | None = None


@dataclass(frozen=True)
class PrinterInfo:
    """Snapshot of a printer's identity, state and capabilities."""

    uuid: str  # normalized, see normalize_uuid()
    make_model: str
    serial: str | None
    state: str  # "idle" | "processing" | "stopped"
    state_reasons: tuple[str, ...]
    markers: tuple[Marker, ...]
    capabilities: Capabilities


@dataclass(frozen=True)
class PrintOptions:
    """Per-job print options. ``page_ranges`` looks like ``"1-3,5"``."""

    copies: int = 1
    sides: str = "one-sided"
    color_mode: str | None = None
    page_ranges: str | None = None


@dataclass(frozen=True)
class JobResult:
    """Outcome of a submitted print job."""

    job_id: int
    state: str


@dataclass(frozen=True)
class JobStatus:
    """Live state of one job, from Get-Job-Attributes.

    ``state`` is one of pending, held, processing, stopped, canceled, aborted
    or completed. Counters are ``None`` when the printer does not report them.
    """

    job_id: int
    state: str
    reasons: tuple[str, ...]
    impressions: int | None
    sheets: int | None


@dataclass(frozen=True)
class LastJob:
    """The most recent job submitted through Home Assistant."""

    file_name: str
    job_id: int | None
    state: str
    user: str | None
    time: datetime
