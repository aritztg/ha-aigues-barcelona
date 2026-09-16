"""Constants definition."""

from datetime import timedelta

DOMAIN = "aigues_barcelona"

CONF_CONTRACT = "contract"
CONF_API_KEY = "api_key"
CONF_VALUE = "value"

ATTR_LAST_MEASURE = "Last measure"

# Once a day. The readings arrive one to four days late, so asking more often
# tells you nothing new, and each poll that finds the hour-long token expired
# costs a login: about 11 units of the 1000 a free Browserless account gets per
# month, which is 330 a month at this rate and would not fit at four hours.
DEFAULT_SCAN_PERIOD = 86400

API_HOST = "api.aiguesdebarcelona.cat"
API_COOKIE_TOKEN = "ofexTokenJwt"

API_ERROR_TOKEN_REVOKED = "JWT Token Revoked"

# Real Chrome, and out through London. The site sits behind a WAF that turns
# some datacenter ranges away; London got through where San Francisco and
# Amsterdam did not. Only the reCAPTCHA token comes from there, so a range that
# stops working costs a token, never the credentials.
BQL_ENDPOINT = "https://production-lon.browserless.io/chrome/bql"

# Hardcoded in the site's own bundle, as recaptchaSiteCode.
RECAPTCHA_SITEKEY = "6LfPoasUAAAAAL5M1txzF5PJ91udHgE5PMm0JWWS"

# Where the login state lives inside hass.data[DOMAIN].
AUTH_STATE = "auth_state"

# Renew a little before the hour is up, so a poll does not start with a
# credential that dies halfway through.
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

# Polling once a day never comes near this. It is here for restarts: setting up
# the entry renews the token, so without a floor a handful of restarts in one
# evening would spend a handful of logins.
LOGIN_COOLDOWN = timedelta(hours=11)

# After a failure that only waiting can fix, stay away rather than spending a
# login discovering the same thing at the next poll.
LOGIN_BACKOFF = timedelta(hours=6)
