"""eSCL errors."""

from __future__ import annotations


class EsclError(Exception):
    """Base eSCL error; ``code`` is a stable machine-readable identifier."""

    code = "escl_error"

    def __init__(self, code: str | None = None, message: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(message or self.code)


class ScannerUnavailable(EsclError):
    """The scanner could not be reached."""

    code = "scanner_unavailable"


class ScannerBusy(EsclError):
    """The scanner refused a new job because it is busy."""

    code = "scanner_busy"


class AdfEmpty(EsclError):
    """The document feeder has no paper."""

    code = "adf_empty"
