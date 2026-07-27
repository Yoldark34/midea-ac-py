"""Guard rail for the hvac_action_full_feature branch's MINOR_VERSION.

This branch is never opened as a PR upstream - it carries the hvac_action
feature independently of mill1000/main and must keep its own
MINOR_VERSION exactly one ahead of whatever main currently has, with the
hvac_action migration step gated to fire right after main's own latest
migration.

Rather than hand-maintaining a snapshot of main's MINOR_VERSION, this
fetches mill1000/main's config_flow.py live from GitHub's raw content
CDN and regexes it out, so drift is caught automatically instead of
relying on someone remembering to update a constant after every rebase.

pytest_homeassistant_custom_component globally disables real socket/DNS
access from inside every test (via a pytest_runtest_setup hook with no
per-test opt-out), so the fetch below runs eagerly at module import
time instead of lazily inside a test function: collection (importing
test modules) happens before that hook ever runs for the first test, so
a module-level call still reaches the network. Calling httpx.get()
inside a test function here would instead raise
"RuntimeError: DNS resolution disabled in tests".
"""

import re
from unittest.mock import patch

import httpx
import pytest
from homeassistant.core import HomeAssistant
from msmart.const import DeviceType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midea_ac.config_flow import MideaConfigFlow
from custom_components.midea_ac.const import (
    CONF_DEVICE_TYPE, CONF_ENABLE_HVAC_ACTION, CONF_HVAC_ACTION,
    CONF_HVAC_ACTION_DERIVE_FROM_TEMP_FALLBACK,
    CONF_HVAC_ACTION_TEMPERATURE_THRESHOLD, DOMAIN)

_MAIN_CONFIG_FLOW_URL = (
    "https://raw.githubusercontent.com/mill1000/midea-ac-py/main/"
    "custom_components/midea_ac/config_flow.py"
)


def _fetch_main_minor_version() -> int:
    """Fetch mill1000/main's current MINOR_VERSION for config_flow.py."""

    response = httpx.get(_MAIN_CONFIG_FLOW_URL, timeout=10)
    response.raise_for_status()

    match = re.search(r"^\s*MINOR_VERSION\s*=\s*(\d+)",
                      response.text, re.MULTILINE)
    if not match:
        raise ValueError(
            "Could not find MINOR_VERSION in mill1000/main's config_flow.py")

    return int(match.group(1))


# Fetched once at collection time - see module docstring for why this
# can't happen lazily inside a test function.
_MAIN_MINOR_VERSION = _fetch_main_minor_version()


# Hardcoded on purpose (see feedback_test_hardcoded_expectations in
# project memory): must not be read from config_flow._DEFAULT_OPTIONS, or
# a default change would silently pass this test instead of breaking it.
_EXPECTED_ENABLE_HVAC_ACTION_DEFAULT = True
_EXPECTED_HVAC_ACTION_DEFAULT = {
    CONF_HVAC_ACTION_TEMPERATURE_THRESHOLD: 0.5,
    CONF_HVAC_ACTION_DERIVE_FROM_TEMP_FALLBACK: True,
}


def test_branch_minor_version_is_main_plus_one() -> None:
    """This branch's MINOR_VERSION must stay exactly one ahead of main's."""

    assert MideaConfigFlow.MINOR_VERSION == _MAIN_MINOR_VERSION + 1


@pytest.mark.parametrize(
    "device_type", [DeviceType.AIR_CONDITIONER, DeviceType.COMMERCIAL_AC])
async def test_migration_from_main_schema_adds_hvac_action_defaults(
    hass: HomeAssistant,
    device_type: DeviceType,
) -> None:
    """A config entry at main's schema, which has no hvac_action options
    at all, must migrate to this branch's schema with the proper
    default values."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        minor_version=_MAIN_MINOR_VERSION,
        data={CONF_DEVICE_TYPE: device_type},
        options={},
    )

    # Confirm the starting point genuinely has neither option, i.e. this
    # really is main's schema shape and not something already migrated.
    assert CONF_ENABLE_HVAC_ACTION not in mock_config_entry.options
    assert CONF_HVAC_ACTION not in mock_config_entry.options

    with patch(
        "custom_components.midea_ac.async_setup_entry",
        return_value=True,
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.minor_version == _MAIN_MINOR_VERSION + 1
    assert mock_config_entry.options[CONF_ENABLE_HVAC_ACTION] == \
        _EXPECTED_ENABLE_HVAC_ACTION_DEFAULT
    assert mock_config_entry.options[CONF_HVAC_ACTION] == \
        _EXPECTED_HVAC_ACTION_DEFAULT
