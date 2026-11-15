"""Tests for the home_print.print_file service."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_print.const import (
    CONF_ADMIN_ONLY,
    CONF_DEFAULT_SIDES,
    CONF_MAX_FILE_MB,
    DOMAIN,
    EVENT_JOB,
)
from custom_components.home_print.printing import FileTooLarge

from .common import PDF, make_entry, setup_entry


@pytest.fixture
def allowed_dir(hass, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    hass.config.allowlist_external_dirs = {str(allowed)}
    return allowed


async def call(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "print_file", data, blocking=True, return_response=True
    )


async def test_print_file_from_allowed_path(hass, mock_client, allowed_dir):
    entry = await setup_entry(
        hass, make_entry(**{CONF_DEFAULT_SIDES: "two-sided-long-edge"})
    )
    path = allowed_dir / "öğrenci_belgesi.pdf"
    path.write_bytes(PDF)

    response = await call(
        hass, config_entry_id=entry.entry_id, path=str(path), copies=3
    )

    assert response == {"job_id": 42}
    args, kwargs = mock_client.print_job.call_args
    assert args == (PDF,)
    assert kwargs["job_name"] == "öğrenci_belgesi.pdf"
    assert kwargs["options"].copies == 3
    assert kwargs["options"].sides == "two-sided-long-edge"


async def test_print_file_disallowed_path(hass, mock_client, allowed_dir, tmp_path):
    entry = await setup_entry(hass)
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(PDF)

    with pytest.raises(ServiceValidationError) as exc:
        await call(hass, config_entry_id=entry.entry_id, path=str(outside))
    assert exc.value.translation_key == "path_not_allowed"
    mock_client.print_job.assert_not_called()


async def test_print_file_symlink_escape_rejected(
    hass, mock_client, allowed_dir, tmp_path
):
    entry = await setup_entry(hass)
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(PDF)
    link = allowed_dir / "link.pdf"
    link.symlink_to(outside)

    with pytest.raises(ServiceValidationError):
        await call(hass, config_entry_id=entry.entry_id, path=str(link))
    mock_client.print_job.assert_not_called()


async def test_print_file_missing_file(hass, mock_client, allowed_dir):
    entry = await setup_entry(hass)
    with pytest.raises(ServiceValidationError) as exc:
        await call(
            hass, config_entry_id=entry.entry_id, path=str(allowed_dir / "nope.pdf")
        )
    assert exc.value.translation_key == "file_not_found"


async def test_print_file_too_large_checked_before_read(hass, mock_client, allowed_dir):
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 1}))
    events = async_capture_events(hass, EVENT_JOB)
    path = allowed_dir / "big.pdf"
    path.write_bytes(PDF + b"\x00" * (1024 * 1024))

    with pytest.raises(FileTooLarge):
        await call(hass, config_entry_id=entry.entry_id, path=str(path))
    await hass.async_block_till_done()
    mock_client.print_job.assert_not_called()
    assert events[0].data["error"] == "file_too_large"


async def test_print_file_unknown_entry(hass, mock_client, allowed_dir):
    await setup_entry(hass)
    with pytest.raises(ServiceValidationError) as exc:
        await call(hass, config_entry_id="missing", path=str(allowed_dir / "a.pdf"))
    assert exc.value.translation_key == "entry_not_found"


async def test_print_file_invalid_page_ranges(hass, mock_client, allowed_dir):
    entry = await setup_entry(hass)
    path = allowed_dir / "a.pdf"
    path.write_bytes(PDF)
    with pytest.raises(ServiceValidationError) as exc:
        await call(
            hass, config_entry_id=entry.entry_id, path=str(path), page_ranges="5-2"
        )
    assert exc.value.translation_key == "invalid_option"
    mock_client.print_job.assert_not_called()


async def test_print_file_admin_only_blocks_non_admin(
    hass, mock_client, allowed_dir, hass_read_only_user
):
    entry = await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    path = allowed_dir / "a.pdf"
    path.write_bytes(PDF)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "print_file",
            {"config_entry_id": entry.entry_id, "path": str(path)},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    mock_client.print_job.assert_not_called()


async def test_service_registered_once_and_survives_unload(hass, mock_client):
    entry = await setup_entry(hass)
    assert hass.services.has_service(DOMAIN, "print_file")
    await hass.config_entries.async_unload(entry.entry_id)
    assert hass.services.has_service(DOMAIN, "print_file")


async def test_print_file_unloaded_entry(hass, mock_client, allowed_dir):
    entry = await setup_entry(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as exc:
        await call(
            hass, config_entry_id=entry.entry_id, path=str(allowed_dir / "a.pdf")
        )
    assert exc.value.translation_key == "entry_not_loaded"
