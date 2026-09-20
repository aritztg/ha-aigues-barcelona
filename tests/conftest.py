"""Shared fixtures.

`pytest-homeassistant-custom-component` brings the Home Assistant test harness;
everything here is only about making this repository's `custom_components`
package importable and letting Home Assistant load it.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant see `custom_components/` in every test.

    Home Assistant refuses to load custom integrations in tests unless this
    fixture is requested, and forgetting it produces a confusing
    "Integration not found" rather than a useful failure.
    """
    yield
