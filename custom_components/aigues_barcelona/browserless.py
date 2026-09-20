"""Get a reCAPTCHA token for the login, using a browser somewhere else.

The login endpoint checks a reCAPTCHA response against Google server
side, and only the reCAPTCHA script running in a browser on the site's
own domain produces one it accepts. Home Assistant cannot run that
browser: on Home Assistant OS the core container is Alpine, where the
usual stealth browsers will not install, let alone run. So a remote
browser makes the token and this asks for it over HTTPS, which Alpine
has no opinion about.

Only the token comes from there. The login itself is a plain POST that
Home Assistant makes on its own, so the credentials never leave this
machine, and the request arrives from the same address the site is used
to seeing.
"""

from __future__ import annotations

import json
import logging

from aiohttp import ClientError
from aiohttp import ClientTimeout
from homeassistant.exceptions import HomeAssistantError

from .const import BQL_ENDPOINT
from .const import RECAPTCHA_SITEKEY

_LOGGER = logging.getLogger(__name__)

# Any page on the site's domain will do. reCAPTCHA ties the key to the domain,
# not to a particular page, and this one is never actually fetched: the stub
# below is served in its place.
ORIGIN = "https://www.aiguesdebarcelona.cat/es/area-clientes"

# Served instead of the real page, which is a 22 MB single-page application we
# would download only to ignore. The paragraph is not decoration: navigation
# waits for something to paint, and an empty body never does.
STUB = "<!doctype html><html><head><title>.</title></head><body><p>.</p></body></html>"

# Waits for the reCAPTCHA API to arrive, renders an invisible widget with the
# site's own key, and runs it. Driving our own widget instead of their login
# form means nothing here depends on their markup, their cookie banner, or their
# app still working.
READY = "() => typeof window.grecaptcha !== 'undefined' && !!window.grecaptcha.render"
RENDER = f"""
(() => {{
  const box = document.createElement('div');
  document.body.appendChild(box);
  window.__tok = null;
  window.__wid = window.grecaptcha.render(box, {{
    sitekey: '{RECAPTCHA_SITEKEY}', size: 'invisible',
    callback: t => {{ window.__tok = t; }}
  }});
  window.grecaptcha.execute(window.__wid);
  return 'ok';
}})()
"""
GRAB = """
(() => {
  let t = window.__tok;
  try { if (!t) t = window.grecaptcha.getResponse(window.__wid); } catch (e) {}
  return t || '';
})()
"""

# Everything the browser has to do, in one request. Values go in as GraphQL
# variables rather than being formatted into the text, which keeps the braces
# here meaning what they mean in GraphQL.
QUERY = """
mutation Captcha(
  $pattern: [String], $stub: String!, $url: String!
  $ready: String!, $render: String!, $grab: String!
) {
  stub: fulfill(url: $pattern, status: 200, contentType: "text/html", body: $stub) { time }
  goto(url: $url, waitUntil: domContentLoaded) { status }
  api: addScriptTag(url: "https://www.google.com/recaptcha/api.js?render=explicit") { time }
  ready: waitForFunction(fn: $ready, timeout: 20000) { time }
  start: evaluate(content: $render) { value }
  captcha: solve(type: recaptcha, timeout: 60000) { found solved time }
  settle: waitForTimeout(time: 1000) { time }
  grab: evaluate(content: $grab) { value }
}
"""

VARIABLES = {
    "pattern": [f"{ORIGIN}*"],
    "stub": STUB,
    "url": ORIGIN,
    "ready": READY,
    "render": RENDER,
    "grab": GRAB,
}


class ServiceUnavailable(HomeAssistantError):
    """The browser service could not be reached, or refused the key or
    quota."""


class ChallengeUnsolved(HomeAssistantError):
    """Google put a challenge up and it was not solved."""


async def async_fetch_captcha_token(
    session, api_key: str, endpoint: str = BQL_ENDPOINT
) -> str:
    """Return a reCAPTCHA response token, freshly minted and good for two
    minutes."""
    try:
        response = await session.post(
            f"{endpoint}?token={api_key}",
            json={"query": QUERY, "variables": VARIABLES},
            # Solving a challenge has taken anywhere from 17 to 43 seconds. The
            # ceiling is only here so a hung request cannot wedge the coordinator.
            timeout=ClientTimeout(total=180),
        )
        body = await response.text()
    except (ClientError, TimeoutError) as err:
        raise ServiceUnavailable(f"Could not reach the browser service: {err}") from err

    if response.status in (401, 403):
        raise ServiceUnavailable("The browser service rejected the API key")
    if response.status == 429 or "quota" in body.lower():
        raise ServiceUnavailable("The browser service reports no units left")

    try:
        result = json.loads(body)
    except ValueError as err:
        raise ServiceUnavailable(
            f"The browser service answered {response.status}: {body[:120]}"
        ) from err

    for problem in result.get("errors") or []:
        _LOGGER.debug("Step %s: %s", problem.get("path"), problem.get("message"))

    data = result.get("data") or {}
    token = (data.get("grab") or {}).get("value") or ""
    if not token:
        challenge = data.get("captcha") or {}
        raise ChallengeUnsolved(
            f"No reCAPTCHA token came back (challenge found: {challenge.get('found')}, "
            f"solved: {challenge.get('solved')})"
        )

    _LOGGER.debug(
        "reCAPTCHA token ready, %s ms of it spent on a challenge",
        (data.get("captcha") or {}).get("time", 0),
    )
    return token
