"""Tests for moving old statistics off the entity id.

Versions up to 0.5 wrote long-term statistics onto `sensor.contador_*`, which
Home Assistant treats as the recorder's own series. Left in place they raise a
repair issue offering to delete the history, so setup moves them to the
external series and drops the old one.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.aigues_barcelona.const import DOMAIN
from custom_components.aigues_barcelona.sensor import ContratoAgua

ENTITY_ID = "sensor.contador_629067"
EXTERNAL_ID = "aigues_barcelona:water_meter_629067"
PREFIX = "custom_components.aigues_barcelona.sensor."


@pytest.fixture
def coordinator(hass: HomeAssistant) -> ContratoAgua:
    hass.data.setdefault(DOMAIN, {})
    return ContratoAgua(hass, "12345678Z", "hunter2", "629067")


def row(start: float, state: float, total: float) -> dict:
    return {"start": start, "state": state, "sum": total}


async def run_migration(coordinator: ContratoAgua, listed: list, rows: list):
    """Drive the migration with canned recorder answers."""
    executor = AsyncMock()
    calls: dict = {"imported": None, "cleared": None}

    async def fake_job(func, *args):
        name = getattr(func, "__name__", "")
        if name == "list_statistic_ids":
            return listed
        if name == "statistics_during_period":
            return {ENTITY_ID: rows}
        if name == "clear_statistics":
            calls["cleared"] = args[1]
        return None

    executor.side_effect = fake_job
    instance = AsyncMock()
    instance.async_add_executor_job = fake_job

    def capture(_hass, metadata, stats):
        calls["imported"] = (metadata, stats)

    with (
        patch(PREFIX + "get_db_instance", return_value=instance),
        patch(PREFIX + "async_add_external_statistics", side_effect=capture),
    ):
        await coordinator.async_migrate_entity_statistics()
    return calls


async def test_does_nothing_when_there_is_no_old_series(coordinator):
    """The normal case on a fresh install, and on every later startup."""
    calls = await run_migration(coordinator, listed=[], rows=[])

    assert calls["imported"] is None
    assert calls["cleared"] is None


async def test_ignores_a_series_this_integration_already_owns(coordinator):
    """An external series must not be mistaken for one to migrate."""
    listed = [{"statistic_id": EXTERNAL_ID, "source": DOMAIN}]
    calls = await run_migration(coordinator, listed=listed, rows=[])

    assert calls["imported"] is None
    assert calls["cleared"] is None


async def test_copies_the_rows_across_then_drops_the_old_series(coordinator):
    listed = [{"statistic_id": ENTITY_ID, "source": "recorder"}]
    rows = [row(1000.0, 950.0, 950.0), row(4600.0, 951.0, 951.0)]

    calls = await run_migration(coordinator, listed=listed, rows=rows)

    metadata, stats = calls["imported"]
    assert metadata["statistic_id"] == EXTERNAL_ID
    assert [s["sum"] for s in stats] == [950.0, 951.0]
    assert [s["state"] for s in stats] == [950.0, 951.0]
    assert calls["cleared"] == [ENTITY_ID]


async def test_the_carried_total_never_steps_backwards(coordinator):
    """The old series is exactly the one that could dip; do not carry that over."""
    listed = [{"statistic_id": ENTITY_ID, "source": "recorder"}]
    rows = [
        row(1000.0, 950.0, 950.0),
        row(4600.0, 948.0, 948.0),  # the dip that made migration worthwhile
        row(8200.0, 952.0, 952.0),
    ]

    calls = await run_migration(coordinator, listed=listed, rows=rows)

    sums = [s["sum"] for s in calls["imported"][1]]
    assert sums == [950.0, 950.0, 952.0]
    assert sums == sorted(sums)


async def test_the_old_series_goes_even_when_it_holds_nothing_usable(coordinator):
    """Rows without a sum cannot be carried, but the series must still go."""
    listed = [{"statistic_id": ENTITY_ID, "source": "recorder"}]
    rows = [{"start": 1000.0, "state": 950.0, "sum": None}]

    calls = await run_migration(coordinator, listed=listed, rows=rows)

    assert calls["imported"] is None
    assert calls["cleared"] == [ENTITY_ID]
