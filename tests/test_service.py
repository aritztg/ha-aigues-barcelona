"""Tests for the reset_and_refresh_data service.

The service looks up coordinators in hass.data[DOMAIN], which is keyed by
contract. The automatic login also keeps its state in that dict under
AUTH_STATE, so taking whichever key came first found "auth_state" and the
backfill never ran.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant

from custom_components.aigues_barcelona import service
from custom_components.aigues_barcelona.const import AUTH_STATE
from custom_components.aigues_barcelona.const import DOMAIN


def fake_coordinator(contract: str) -> MagicMock:
    coordinator = MagicMock()
    coordinator.contract = contract
    coordinator.import_old_consumptions = AsyncMock()
    return coordinator


async def call_service(hass: HomeAssistant, **data) -> None:
    await service.async_setup(hass, {})
    await hass.services.async_call(
        DOMAIN, "reset_and_refresh_data", data or None, blocking=True
    )


async def test_finds_the_coordinator_past_the_auth_state(hass: HomeAssistant):
    """The regression: auth_state is inserted first and is not a contract."""
    coordinator = fake_coordinator("629067")
    hass.data[DOMAIN] = {
        AUTH_STATE: {"some": "login state"},
        "629067": {"coordinator": coordinator},
    }

    await call_service(hass)

    coordinator.import_old_consumptions.assert_awaited_once_with(days=730)


async def test_refreshes_every_contract(hass: HomeAssistant):
    """An account can hold more than one; the old code only ever took one."""
    first, second = fake_coordinator("629067"), fake_coordinator("112233")
    hass.data[DOMAIN] = {
        AUTH_STATE: {},
        "629067": {"coordinator": first},
        "112233": {"coordinator": second},
    }

    await call_service(hass)

    first.import_old_consumptions.assert_awaited_once_with(days=730)
    second.import_old_consumptions.assert_awaited_once_with(days=730)


async def test_says_so_when_there_is_nothing_to_refresh(hass: HomeAssistant, caplog):
    hass.data[DOMAIN] = {AUTH_STATE: {}}

    await call_service(hass)

    assert "No contract coordinators available" in caplog.text


async def test_survives_an_empty_domain(hass: HomeAssistant, caplog):
    """Calling the service before any contract is set up must not raise."""
    hass.data.pop(DOMAIN, None)

    await call_service(hass)

    assert "No contract coordinators available" in caplog.text


class TestHowFarBack:
    """The window is a service parameter, not a fixed year.

    The water company serves an arbitrary date range, so the one-year default
    was only ever our own choice. Anyone wanting more history can ask for it.
    """

    async def test_defaults_to_two_years(self, hass: HomeAssistant):
        coordinator = fake_coordinator("629067")
        hass.data[DOMAIN] = {"629067": {"coordinator": coordinator}}

        await call_service(hass)

        coordinator.import_old_consumptions.assert_awaited_once_with(days=730)

    async def test_goes_back_as_far_as_asked(self, hass: HomeAssistant):
        coordinator = fake_coordinator("629067")
        hass.data[DOMAIN] = {"629067": {"coordinator": coordinator}}

        await call_service(hass, days=1095)

        coordinator.import_old_consumptions.assert_awaited_once_with(days=1095)

    async def test_rejects_a_window_shorter_than_one_step(self, hass: HomeAssistant):
        """The backfill walks week by week, so fewer than seven days is a no-op."""
        coordinator = fake_coordinator("629067")
        hass.data[DOMAIN] = {"629067": {"coordinator": coordinator}}

        with pytest.raises(vol.Invalid):
            await call_service(hass, days=3)

        coordinator.import_old_consumptions.assert_not_awaited()
