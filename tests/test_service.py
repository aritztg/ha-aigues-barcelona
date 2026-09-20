"""Tests for the reset_and_refresh_data service.

The service looks up coordinators in hass.data[DOMAIN], which is keyed by
contract. The automatic login also keeps its state in that dict under
AUTH_STATE, so taking whichever key came first found "auth_state" and the
backfill never ran.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.aigues_barcelona import service
from custom_components.aigues_barcelona.const import AUTH_STATE
from custom_components.aigues_barcelona.const import DOMAIN


def fake_coordinator(contract: str) -> MagicMock:
    coordinator = MagicMock()
    coordinator.contract = contract
    coordinator.import_old_consumptions = AsyncMock()
    return coordinator


async def call_service(hass: HomeAssistant) -> None:
    await service.async_setup(hass, {})
    await hass.services.async_call(DOMAIN, "reset_and_refresh_data", blocking=True)


async def test_finds_the_coordinator_past_the_auth_state(hass: HomeAssistant):
    """The regression: auth_state is inserted first and is not a contract."""
    coordinator = fake_coordinator("629067")
    hass.data[DOMAIN] = {
        AUTH_STATE: {"some": "login state"},
        "629067": {"coordinator": coordinator},
    }

    await call_service(hass)

    coordinator.import_old_consumptions.assert_awaited_once_with(days=365)


async def test_refreshes_every_contract(hass: HomeAssistant):
    """An account can hold more than one; the old code only ever took one."""
    first, second = fake_coordinator("629067"), fake_coordinator("112233")
    hass.data[DOMAIN] = {
        AUTH_STATE: {},
        "629067": {"coordinator": first},
        "112233": {"coordinator": second},
    }

    await call_service(hass)

    first.import_old_consumptions.assert_awaited_once_with(days=365)
    second.import_old_consumptions.assert_awaited_once_with(days=365)


async def test_says_so_when_there_is_nothing_to_refresh(hass: HomeAssistant, caplog):
    hass.data[DOMAIN] = {AUTH_STATE: {}}

    await call_service(hass)

    assert "No contract coordinators available" in caplog.text


async def test_survives_an_empty_domain(hass: HomeAssistant, caplog):
    """Calling the service before any contract is set up must not raise."""
    hass.data.pop(DOMAIN, None)

    await call_service(hass)

    assert "No contract coordinators available" in caplog.text
