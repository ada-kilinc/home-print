"""Fixtures for eSCL tests, which talk to a real local fake scanner."""

import pytest


@pytest.fixture(autouse=True)
def _real_sockets(socket_enabled):
    """Allow real loopback sockets (pytest-socket blocks them by default)."""
