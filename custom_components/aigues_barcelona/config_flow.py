"""Config flow for integration."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_TOKEN
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api import AiguesApiClient
from .auth import LoginFailed
from .auth import TooSoon
from .auth import async_login
from .browserless import ChallengeUnsolved
from .browserless import ServiceUnavailable
from .const import API_ERROR_TOKEN_REVOKED
from .const import CONF_API_KEY
from .const import CONF_CONTRACT
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ACCOUNT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        # Left empty, the token has to be pasted by hand every hour, which is
        # how this integration worked before.
        vol.Optional(CONF_API_KEY): cv.string,
    }
)
TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): cv.string})
# Reauth takes either: a token to carry on by hand, or a browser service key so
# the integration can mint its own from now on. Someone upgrading from a version
# without automatic login reaches this form within the hour, which makes it the
# one place where the key can be adopted without tearing the entry down.
REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_API_KEY): cv.string,
    }
)


def redacted(data) -> dict:
    """A copy of a config dict with the secrets replaced by a marker.

    These end up in the log at debug level, which is exactly what
    someone turns on before pasting the output into an issue.
    """
    if not isinstance(data, dict):
        return data
    secret = (CONF_PASSWORD, CONF_TOKEN, CONF_API_KEY)
    return {k: ("***" if k in secret and v else v) for k, v in data.items()}


def check_valid_nif(username: str) -> bool:
    """Quick check for NIF/DNI/NIE and return if valid."""

    if len(username) != 9:
        return False

    # DNI 12341234D
    if username[0:8].isnumeric() and not username[-1].isnumeric():
        return True

    # NIF X2341234H
    return bool(
        username[0].upper() in ["X", "Y", "Z"]
        and username[1:8].isnumeric()
        and not username[-1].isnumeric()
    )


async def validate_credentials(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    token = data.get(CONF_TOKEN)

    if not check_valid_nif(username):
        raise InvalidUsername

    api = AiguesApiClient(username, password)

    if not token:
        api_key = data.get(CONF_API_KEY)
        if not api_key:
            raise RecaptchaAppeared
        _LOGGER.info("Attempting to login")
        try:
            token = await async_login(hass, api_key, username, password, force=True)
        except ServiceUnavailable as err:
            _LOGGER.warning("Browser service unavailable: %s", err)
            raise CaptchaServiceFailed(str(err)) from err
        except ChallengeUnsolved as err:
            _LOGGER.warning("Challenge not solved: %s", err)
            raise ChallengeLost(str(err)) from err
        except TooSoon as err:
            _LOGGER.warning("Login paced out: %s", err)
            raise WaitingItOut(str(err)) from err
        except LoginFailed as err:
            _LOGGER.warning("Login refused: %s", err)
            raise InvalidAuth from err
        _LOGGER.info("Login succeeded!")

    api.set_token(token)

    try:
        contracts = await hass.async_add_executor_job(api.contracts, username)

        available_contracts = [x["contractDetail"]["contractNumber"] for x in contracts]
        return {CONF_CONTRACT: available_contracts, CONF_TOKEN: token}

    except Exception:
        _LOGGER.debug(f"Last data: {api.last_response}")
        if not api.last_response:
            return False

        if (
            isinstance(api.last_response, dict)
            and api.last_response.get("path") == "recaptchaClientResponse"
        ):
            raise RecaptchaAppeared from None

        if (
            isinstance(api.last_response, str)
            and api.last_response == API_ERROR_TOKEN_REVOKED
        ):
            raise TokenExpired from None

        return False


class AiguesBarcelonaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        # Was a class attribute, which every config flow instance shared: one
        # user's half-finished setup leaked into the next one's.
        super().__init__()
        self.stored_input: dict = {}

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Return to user step with stored input (previous user creds) and the
        current provided token."""
        return await self.async_step_user({**self.stored_input, **user_input})

    async def async_step_reauth(self, entry) -> FlowResult:
        """Request OAuth Token again when expired."""
        # get previous entity content back to flow
        self.entry = entry
        if hasattr(entry, "data"):
            self.stored_input = entry.data
        else:
            self.stored_input = entry

            # WHAT: for DataUpdateCoordinator, entry is not valid,
            # as it contains only sensor data. Missing entry_id.
            # This recovers the entry_id data.
            if entry := self.hass.config_entries.async_get_entry(
                self.context["entry_id"]
            ):
                self.entry = entry
        return await self.async_step_reauth_confirm(None)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Return to user step with stored input (previous user creds) and the
        current provided token."""

        # `is None` rather than falsy: an empty dict means the form came back
        # with both fields blank, which deserves an error rather than silently
        # redrawing the same form.
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=REAUTH_SCHEMA
            )

        errors = {}
        _LOGGER.debug(
            "Current values on reauth_confirm: %s --> %s",
            redacted(getattr(self.entry, "data", None)),
            redacted(user_input),
        )

        # Read both out before merging. After the merge the stored token is back
        # in the dict, and testing it there cannot tell a token the user just
        # typed from the expired one that sent us here.
        given_key = user_input.get(CONF_API_KEY)
        given_token = user_input.get(CONF_TOKEN)

        if not given_key and not given_token:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=REAUTH_SCHEMA,
                errors={"base": "need_token_or_key"},
            )

        user_input = {**self.stored_input, **user_input}
        if given_key and not given_token:
            # Drop the spent token so validate_credentials logs in with the key
            # instead of retrying what already failed.
            user_input.pop(CONF_TOKEN, None)

        try:
            info = await validate_credentials(self.hass, user_input)
            _LOGGER.debug(f"Result is {redacted(info)}")
            if not info:  # invalid oauth token
                raise InvalidAuth

            contracts = info[CONF_CONTRACT]
            if contracts != self.stored_input.get(CONF_CONTRACT):
                _LOGGER.error("Reauth failed, contract does not match stored one")
                raise InvalidAuth

            self.hass.config_entries.async_update_entry(self.entry, data=user_input)
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        except CaptchaServiceFailed:
            errors["base"] = "captcha_service"
        except ChallengeLost:
            errors["base"] = "captcha_unsolved"
        except WaitingItOut:
            errors["base"] = "too_soon"
        except RecaptchaAppeared:
            errors["base"] = "need_token_or_key"
        except InvalidUsername:
            errors["base"] = "invalid_auth"
        except InvalidAuth:
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle configuration step from UI."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=ACCOUNT_CONFIG_SCHEMA
            )

        errors = {}

        try:
            self.stored_input = user_input
            info = await validate_credentials(self.hass, user_input)
            _LOGGER.debug(f"Result is {redacted(info)}")
            if not info:
                raise InvalidAuth
            contracts = info[CONF_CONTRACT]

            await self.async_set_unique_id(user_input["username"])
            self._abort_if_unique_id_configured()
        except NotImplementedError:
            errors["base"] = "not_implemented"
        except TokenExpired:
            errors["base"] = "token_expired"
            return self.async_show_form(
                step_id="token", data_schema=TOKEN_SCHEMA, errors=errors
            )
        except CaptchaServiceFailed:
            errors["base"] = "captcha_service"
        except ChallengeLost:
            errors["base"] = "captcha_unsolved"
        except WaitingItOut:
            errors["base"] = "too_soon"
        except RecaptchaAppeared:
            # Ask for OAuth Token to login.
            return self.async_show_form(step_id="token", data_schema=TOKEN_SCHEMA)
        except InvalidUsername:
            errors["base"] = "invalid_auth"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except AlreadyConfigured:
            errors["base"] = "already_configured"
        else:
            _LOGGER.debug(
                f"Creating entity with {redacted(user_input)} and {contracts=}"
            )
            nif_oculto = user_input[CONF_USERNAME][-3:][0:2]

            return self.async_create_entry(
                title=f"Aigua ****{nif_oculto}", data={**user_input, **info}
            )

        return self.async_show_form(
            step_id="user", data_schema=ACCOUNT_CONFIG_SCHEMA, errors=errors
        )


class AlreadyConfigured(HomeAssistantError):
    """Error to indicate integration is already configured."""


class CaptchaServiceFailed(HomeAssistantError):
    """Error to indicate the browser service was unreachable, would not take
    the key, or has no units left this month."""


class ChallengeLost(HomeAssistantError):
    """Error to indicate Google put up a challenge that was not solved."""


class WaitingItOut(HomeAssistantError):
    """Error to indicate a login was attempted too recently to try again."""


class RecaptchaAppeared(HomeAssistantError):
    """Error to indicate a Recaptcha appeared and requires an OAuth token
    issued."""


class TokenExpired(HomeAssistantError):
    """Error to indicate the OAuth token has expired."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate credentials are invalid."""


class InvalidUsername(HomeAssistantError):
    """Error to indicate invalid username."""
