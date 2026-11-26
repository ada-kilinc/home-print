"""Shared test fixtures."""

import importlib
import importlib.util
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.home_print.client import HomePrintClient, parse_printer
from custom_components.home_print.models import JobResult


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def stub_frontend_component():
    """Stub HA's frontend setup (the hass_frontend wheel is not installed)."""
    from homeassistant.components.frontend import (
        DATA_EXTRA_MODULE_URL,
        UrlManager,
    )

    async def _setup(hass, config):
        hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *args: None, [])
        return True

    with patch("homeassistant.components.frontend.async_setup", _setup):
        yield


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_client():
    """Replace ``HomePrintClient`` with a single mocked instance.

    Yields an ``AsyncMock`` (spec'd on ``HomePrintClient``) that every
    constructor call returns. ``get_printer`` returns the PrinterInfo parsed
    from ``fixtures/printer_generic.json``; ``print_job`` returns
    ``JobResult(job_id=42, state="pending")``.

    The name is patched in ``custom_components.home_print.client`` and in every
    module that exists and imports it with
    ``from .client import HomePrintClient`` (``__init__``, ``config_flow``,
    ``coordinator``, ``services``). Later modules MUST use that import form so
    the patch applies; modules not written yet are skipped.
    """
    instance = AsyncMock(spec=HomePrintClient)
    instance.get_printer.return_value = parse_printer(
        json.loads((FIXTURES / "printer_generic.json").read_text())
    )
    instance.print_job.return_value = JobResult(job_id=42, state="pending")

    with ExitStack() as stack:
        for module in (
            "custom_components.home_print.client",
            "custom_components.home_print",
            "custom_components.home_print.config_flow",
            "custom_components.home_print.coordinator",
            "custom_components.home_print.services",
        ):
            if importlib.util.find_spec(module) is None:
                continue
            if not hasattr(importlib.import_module(module), "HomePrintClient"):
                continue
            stack.enter_context(
                patch(f"{module}.HomePrintClient", return_value=instance)
            )
        yield instance


@pytest.fixture(autouse=True)
def tmp_config_dir(request, tmp_path):
    """Keep stored print files out of the shared test config folder."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("hass").config.config_dir = str(tmp_path)
    yield


@pytest.fixture(autouse=True)
def mock_find_scanner():
    """No scanner by default; tests set ``return_value`` to a URL to add one."""
    with patch(
        "custom_components.home_print.scanner.find_scanner",
        new=AsyncMock(return_value=None),
    ) as find:
        yield find


@pytest.fixture
def mock_escl():
    """Replace the scanner's eSCL client with one mocked instance.

    ``mock_escl`` is the patched class; ``mock_escl.client`` the instance.
    """
    from custom_components.home_print.escl.models import ScannerStatus

    from .common import CAPS

    with patch("custom_components.home_print.scanner.EsclClient") as cls:
        client = AsyncMock()
        client.capabilities.return_value = CAPS
        client.status.return_value = ScannerStatus("idle", False)
        cls.return_value = client
        cls.client = client
        yield cls


@pytest.fixture
def forbid_loop_disk_io(hass, monkeypatch):
    """Fail if a path is resolved/stat-ed or the allowlist read on the event loop.

    HA's own blocking-call detection doesn't cover these; on SD cards and
    network shares each one stalls Home Assistant. Use as a context manager
    around the code under test.
    """
    import contextlib
    import pathlib
    import threading

    loop_thread = threading.get_ident()
    calls: list[str] = []
    active = False

    def guard(name, original):
        def wrapper(*args, **kwargs):
            if active and threading.get_ident() == loop_thread:
                calls.append(name)
            return original(*args, **kwargs)

        return wrapper

    for name in ("resolve", "is_file", "is_dir", "exists", "stat"):
        monkeypatch.setattr(
            pathlib.Path, name, guard(f"Path.{name}", getattr(pathlib.Path, name))
        )
    monkeypatch.setattr(
        hass.config,
        "is_allowed_path",
        guard("is_allowed_path", hass.config.is_allowed_path),
    )

    @contextlib.contextmanager
    def watching():
        nonlocal active
        active = True
        try:
            yield calls
        finally:
            active = False
        assert calls == [], f"blocking disk calls on the event loop: {calls}"

    return watching
