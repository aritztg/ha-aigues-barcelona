"""Tests for the reauthentication step.

Reauth used to accept only a pasted token, which left anyone upgrading from a
version without automatic login no way to adopt a browser service key short of
deleting the config entry and setting it up again. The step now takes either.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_TOKEN
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aigues_barcelona.config_flow import REAUTH_SCHEMA
from custom_components.aigues_barcelona.const import CONF_API_KEY
from custom_components.aigues_barcelona.const import CONF_CONTRACT
from custom_components.aigues_barcelona.const import DOMAIN

STORED = {
    CONF_USERNAME: "12345678Z",
    CONF_PASSWORD: "hunter2",
    CONF_TOKEN: "an.expired.token",
    CONF_CONTRACT: ["629067"],
}


@pytest.fixture
def entry(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> MockConfigEntry:
    """A configured entry whose token has expired.

    The fixture order is load-bearing. pytest resolves them left to right, and
    `recorder_mock` has to be in place before Home Assistant is built, because
    the integration declares `recorder` among its dependencies.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=STORED, unique_id=STORED[CONF_USERNAME])
    entry.add_to_hass(hass)
    return entry


async def start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Kick off the reauth flow the way Home Assistant does when a token dies."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    return result["flow_id"]


class TestReauthSchema:
    def test_accepts_a_token_on_its_own(self):
        assert REAUTH_SCHEMA({CONF_TOKEN: "ey.new.token"})

    def test_accepts_an_api_key_on_its_own(self):
        assert REAUTH_SCHEMA({CONF_API_KEY: "a-browserless-key"})

    def test_both_fields_are_optional(self):
        assert REAUTH_SCHEMA({}) == {}


class TestReauthWithApiKey:
    async def test_an_api_key_alone_is_enough(self, entry, hass):
        """The point of the change: no token needed if a key is supplied."""
        flow_id = await start_reauth(hass, entry)

        target = "custom_components.aigues_barcelona.config_flow.validate_credentials"
        with patch(
            target, new=AsyncMock(return_value={CONF_CONTRACT: ["629067"]})
        ) as validate:
            result = await hass.config_entries.flow.async_configure(
                flow_id, {CONF_API_KEY: "a-browserless-key"}
            )

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_API_KEY] == "a-browserless-key"
        assert validate.called

    async def test_the_spent_token_is_dropped_before_logging_in(self, entry, hass):
        """Otherwise validate_credentials retries the token that just expired.

        The stored data is merged into the form input, so the expired token
        comes along unless it is removed, and the login path never runs.
        """
        flow_id = await start_reauth(hass, entry)

        target = "custom_components.aigues_barcelona.config_flow.validate_credentials"
        with patch(
            target, new=AsyncMock(return_value={CONF_CONTRACT: ["629067"]})
        ) as validate:
            await hass.config_entries.flow.async_configure(
                flow_id, {CONF_API_KEY: "a-browserless-key"}
            )

        passed = validate.call_args.args[1]
        assert CONF_TOKEN not in passed
        assert passed[CONF_API_KEY] == "a-browserless-key"

    async def test_a_token_supplied_with_a_key_is_kept(self, entry, hass):
        flow_id = await start_reauth(hass, entry)

        target = "custom_components.aigues_barcelona.config_flow.validate_credentials"
        with patch(
            target, new=AsyncMock(return_value={CONF_CONTRACT: ["629067"]})
        ) as validate:
            await hass.config_entries.flow.async_configure(
                flow_id,
                {CONF_TOKEN: "ey.fresh.token", CONF_API_KEY: "a-browserless-key"},
            )

        assert validate.call_args.args[1][CONF_TOKEN] == "ey.fresh.token"


class TestReauthWithoutEither:
    async def test_an_empty_form_asks_again(self, entry, hass):
        flow_id = await start_reauth(hass, entry)
        result = await hass.config_entries.flow.async_configure(flow_id, {})

        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "need_token_or_key"}
