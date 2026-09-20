import logging

from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def handle_reset_and_refresh_data(call: ServiceCall) -> None:
        # hass.data[DOMAIN] is keyed by contract, but the automatic login keeps
        # its own state under AUTH_STATE in the same dict. Picking the first key
        # therefore landed on "auth_state" and the service gave up. Select the
        # entries that actually carry a coordinator instead, which also covers
        # an account holding more than one contract.
        coordinators = [
            value["coordinator"]
            for value in hass.data.get(DOMAIN, {}).values()
            if isinstance(value, dict) and "coordinator" in value
        ]

        if not coordinators:
            _LOGGER.error("No contract coordinators available")
            return

        for coordinator in coordinators:
            _LOGGER.warning("Performing reset and refresh for %s", coordinator.contract)
            # TODO: Not working - Detected unsafe call not in recorder thread
            # await clear_stored_data(hass, coordinator)
            await fetch_historic_data(hass, coordinator)

    hass.services.async_register(
        DOMAIN, "reset_and_refresh_data", handle_reset_and_refresh_data
    )
    return True


async def clear_stored_data(hass: HomeAssistant, coordinator) -> None:
    await coordinator._clear_statistics()


async def fetch_historic_data(hass: HomeAssistant, coordinator) -> None:
    await coordinator.import_old_consumptions(days=365)
