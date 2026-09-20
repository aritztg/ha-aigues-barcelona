"""Integration for Aigues de Barcelona."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .auth import async_renew_token
from .const import DOMAIN
from .service import async_setup as setup_service

# from homeassistant.exceptions import ConfigEntryNotReady

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:

    # Reuses the stored token while it lasts, so a restart does not cost a login.
    if not await async_renew_token(hass, entry):
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH},
            data=entry,
        )
        return False

    # try:
    #    await hass.async_add_executor_job(api.login)
    # except:
    #    raise ConfigEntryNotReady

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await setup_service(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN].keys():
            hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data[DOMAIN]:
        del hass.data[DOMAIN]

    return unload_ok
