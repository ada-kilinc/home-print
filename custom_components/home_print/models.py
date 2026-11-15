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
class Capabilities:
    """What the printer says it can do."""

    document_formats: frozenset[str]
    sides: frozenset[str]
    color_modes: frozenset[str]
    copies_max: int
    page_ranges: bool


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
class LastJob:
    """The most recent job submitted through Home Assistant."""

    file_name: str
    job_id: int | None
    state: str
    user: str | None
    time: datetime
