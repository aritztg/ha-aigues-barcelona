"""Shared fixtures.

`pytest-homeassistant-custom-component` brings the Home Assistant test harness;
everything here is only about making this repository's `custom_components`
package importable.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# `enable_custom_integrations` is deliberately not requested here as an autouse
# fixture. It pulls in `hass`, and an autouse fixture would therefore build Home
# Assistant before any test had the chance to set up `recorder_mock` first,
# which this integration needs because it declares `recorder` as a dependency.
# Tests that load the integration ask for the two in the right order themselves.
