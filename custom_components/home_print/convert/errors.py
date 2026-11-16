"""Errors raised while converting documents for printing."""

from __future__ import annotations


class ConvertError(Exception):
    """Base class for conversion errors."""


class InvalidDocument(ConvertError):
    """The document is corrupt, encrypted, empty or selects no pages.

    ``str(err)`` is a short reason code: ``corrupt``, ``encrypted``,
    ``empty``, ``too_large``, ``unsupported_format``, ``no_pages`` or
    ``invalid_page_ranges``.
    """


class TooManyPages(ConvertError):
    """The document has more pages than we are willing to render."""

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(f"{count} pages exceed the limit of {limit}")
        self.count = count
        self.limit = limit
