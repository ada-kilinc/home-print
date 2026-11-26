"""Tests for the home_print.print_file service."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
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


async def scan_call(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "scan", data, blocking=True, return_response=True
    )


@pytest.fixture
async def scan_entry(hass, tmp_path, mock_client, mock_escl, mock_find_scanner):
    from .common import scan_jpeg, setup_scanner_entry

    mock_escl.client.scan.return_value = [scan_jpeg()]
    return await setup_scanner_entry(hass, tmp_path, mock_find_scanner)


async def test_scan_service_returns_path(hass, tmp_path, scan_entry):
    response = await scan_call(
        hass, config_entry_id=scan_entry.entry_id, file_name="fatura"
    )
    assert response["name"] == "fatura"
    assert response["pages"] == 1
    assert response["copy"] is None
    path = tmp_path / "media" / "home_print" / "scans"
    assert response["path"].startswith(str(path))
    assert response["path"].endswith("fatura.pdf")
    assert open(response["path"], "rb").read().startswith(b"%PDF-")


async def test_scan_service_without_response(hass, scan_entry):
    await hass.services.async_call(
        DOMAIN, "scan", {"config_entry_id": scan_entry.entry_id}, blocking=True
    )
    assert len(scan_entry.runtime_data.scanner.archive.entries()) == 1


async def test_scan_service_folder_not_allowed(hass, tmp_path, scan_entry, allowed_dir):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ServiceValidationError):
        await scan_call(hass, config_entry_id=scan_entry.entry_id, folder=str(outside))
    scan_entry.runtime_data.scanner.client.scan.assert_not_called()
    # A symlink inside the allowlist that points outside is refused too.
    link = allowed_dir / "link"
    link.symlink_to(outside)
    with pytest.raises(ServiceValidationError):
        await scan_call(hass, config_entry_id=scan_entry.entry_id, folder=str(link))
    scan_entry.runtime_data.scanner.client.scan.assert_not_called()


async def test_scan_service_copy_to_allowed_folder(hass, scan_entry, allowed_dir):
    first = await scan_call(
        hass,
        config_entry_id=scan_entry.entry_id,
        file_name="ğ",
        folder=str(allowed_dir),
    )
    assert first["copy"] == str(allowed_dir / "ğ.pdf")
    assert (allowed_dir / "ğ.pdf").read_bytes() == open(first["path"], "rb").read()
    # An existing file in the folder is never overwritten.
    (allowed_dir / "x.pdf").write_bytes(b"mine")
    second = await scan_call(
        hass,
        config_entry_id=scan_entry.entry_id,
        file_name="x",
        folder=str(allowed_dir),
    )
    assert second["copy"] == str(allowed_dir / "x.pdf").replace("x.pdf", "x (2).pdf")
    assert (allowed_dir / "x.pdf").read_bytes() == b"mine"


async def test_scan_service_folder_must_exist(hass, scan_entry, allowed_dir):
    with pytest.raises(ServiceValidationError):
        await scan_call(
            hass,
            config_entry_id=scan_entry.entry_id,
            folder=str(allowed_dir / "missing"),
        )


async def test_scan_service_errors(hass, scan_entry):
    from custom_components.home_print.escl.errors import AdfEmpty

    with pytest.raises(ServiceValidationError):
        await scan_call(hass, config_entry_id=scan_entry.entry_id, resolution=600)
    scan_entry.runtime_data.scanner.client.scan.side_effect = AdfEmpty()
    with pytest.raises(HomeAssistantError) as err:
        await scan_call(hass, config_entry_id=scan_entry.entry_id)
    assert err.value.translation_key == "scan_error_adf_empty"


async def test_scan_service_without_scanner(hass, mock_client):
    entry = await setup_entry(hass)
    with pytest.raises(ServiceValidationError):
        await scan_call(hass, config_entry_id=entry.entry_id)


async def test_scan_service_admin_only_blocks_non_admin(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner, hass_read_only_user
):
    from .common import setup_scanner_entry

    entry = await setup_scanner_entry(
        hass, tmp_path, mock_find_scanner, **{CONF_ADMIN_ONLY: True}
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "scan",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    mock_escl.client.scan.assert_not_called()


async def test_scan_service_does_no_disk_io_on_the_event_loop(
    hass, scan_entry, allowed_dir, forbid_loop_disk_io
):
    with forbid_loop_disk_io():
        result = await scan_call(
            hass, config_entry_id=scan_entry.entry_id, folder=str(allowed_dir)
        )
        with pytest.raises(ServiceValidationError):
            await scan_call(
                hass, config_entry_id=scan_entry.entry_id, folder="/not/allowed"
            )
    assert result["copy"]
