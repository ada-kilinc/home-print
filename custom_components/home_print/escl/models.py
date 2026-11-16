"""eSCL data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCaps:
    """Capabilities of one input source. Lengths are 1/300 inch."""

    min_width: int
    max_width: int
    min_height: int
    max_height: int
    color_modes: tuple[str, ...]  # "color" | "gray" | "bw"
    resolutions: tuple[int, ...]
    formats: tuple[str, ...]  # MIME types


@dataclass(frozen=True)
class ScannerCaps:
    """Scanner capabilities; source keys are platen, adf, adf_duplex."""

    version: str
    make_model: str | None
    uuid: str | None
    sources: dict[str, SourceCaps]


@dataclass(frozen=True)
class ScannerStatus:
    """Scanner state: idle, processing, testing, stopped or down."""

    state: str
    adf_loaded: bool | None


@dataclass(frozen=True)
class ScanSettings:
    """Requested scan settings, in internal names."""

    source: str
    color_mode: str
    resolution: int
    mime: str
