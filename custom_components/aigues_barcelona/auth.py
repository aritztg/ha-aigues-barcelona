"""Getting a token, and deciding when it is worth getting a new one.

A login costs something in two currencies: units on the account that runs the
remote browser, and a session on the site that nobody ever closes. So the token
in hand is used until it lapses, and a failure that only waiting can fix is left
alone for a while rather than retried at every poll.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime
from functools import partial

from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_TOKEN
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import AiguesApiClient
from .browserless import ChallengeUnsolved
from .browserless import ServiceUnavailable
from .browserless import async_fetch_captcha_token
from .const import AUTH_STATE
from .const import CONF_API_KEY
from .const import DOMAIN
from .const import LOGIN_BACKOFF
from .const import LOGIN_COOLDOWN
from .const import TOKEN_REFRESH_MARGIN

_LOGGER = logging.getLogger(__name__)


class LoginFailed(HomeAssistantError):
    """The site would not hand back a token."""


class TooSoon(HomeAssistantError):
    """Another login was attempted recently, or one just failed."""


def _explain(error: str, last_response) -> str:
    """Turn whatever the site said into something worth reading in a log."""
    blob = f"{error} {last_response}"
    if "MAX_SESSIONS" in blob:
        return (
            "The account has too many sessions open. Each login opens one that "
            "nobody closes; they time out after about an hour idle."
        )
    if "LOGIN_ERROR" in blob or "incorrect" in blob.lower():
        return "The site rejected the username or the password"
    return (error or str(last_response) or "the site refused the login")[:200]


def token_expiry(token: str) -> float:
    """Return the `exp` claim of a JWT, or an hour out if it has none."""
    try:
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        return float(claims["exp"])
    except IndexError, ValueError, KeyError, TypeError:
        _LOGGER.debug("Token carries no readable exp claim, assuming one hour")
        return time.time() + 3600


def token_needs_renewal(token: str) -> bool:
    """True when the token has expired, or is about to."""
    expires = dt_util.utc_from_timestamp(token_expiry(token))
    return dt_util.utcnow() + TOKEN_REFRESH_MARGIN >= expires


async def async_login(
    hass: HomeAssistant,
    api_key: str,
    username: str,
    password: str,
    force: bool = False,
) -> str:
    """Fetch a reCAPTCHA token elsewhere, then log in from here.

    The credentials go straight to the site from this machine. Only the
    reCAPTCHA token is made remotely, and it carries nothing about the account.

    `force` is for someone sitting in front of the setup dialog: the pacing
    below exists to stop unattended retries from spending the month's units, not
    to make a person wait eleven hours because they mistyped their password.
    """
    state = hass.data.setdefault(DOMAIN, {}).setdefault(AUTH_STATE, {})
    now = dt_util.utcnow()

    if not force:
        blocked_until: datetime | None = state.get("blocked_until")
        if blocked_until and now < blocked_until:
            raise TooSoon(
                f"Not logging in again until {blocked_until:%Y-%m-%d %H:%M} UTC"
            )

        last: datetime | None = state.get("last_attempt")
        if last and now - last < LOGIN_COOLDOWN:
            raise TooSoon(
                f"Last login was {(now - last).seconds // 3600} hours ago; "
                "too soon for another"
            )

    # Counted before anything can fail, so a setup that cannot work is not
    # retried on every poll and every restart.
    state["last_attempt"] = now

    try:
        captcha = await async_fetch_captcha_token(
            async_get_clientsession(hass), api_key
        )
    except ServiceUnavailable, ChallengeUnsolved:
        state["blocked_until"] = now + LOGIN_BACKOFF
        raise

    client = AiguesApiClient(username, password)
    try:
        token = await hass.async_add_executor_job(
            partial(client.login, username, password, captcha)
        )
    except Exception as err:
        raise LoginFailed(_explain(str(err), client.last_response)) from err

    if not token:
        raise LoginFailed(_explain("", client.last_response))

    state.pop("blocked_until", None)
    _LOGGER.info(
        "Logged in, token valid until %s",
        dt_util.utc_from_timestamp(token_expiry(token)),
    )
    return token


async def async_renew_token(hass: HomeAssistant, entry) -> str | None:
    """Return a token to use, logging in only when the stored one is spent.

    None means one could not be had and the user has to step in.
    """
    token = entry.data.get(CONF_TOKEN)
    if token and not token_needs_renewal(token):
        return token

    api_key = entry.data.get(CONF_API_KEY)
    if not api_key:
        _LOGGER.debug("No browser service key configured, cannot log in unattended")
        return None

    try:
        token = await async_login(
            hass, api_key, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
    except (ServiceUnavailable, ChallengeUnsolved, LoginFailed, TooSoon) as err:
        _LOGGER.warning("Could not renew the token: %s", err)
        return None

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN: token}
    )
    return token
