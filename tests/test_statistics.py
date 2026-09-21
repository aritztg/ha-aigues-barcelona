"""Tests for the long-term statistics the coordinator imports."""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.core import HomeAssistant

from custom_components.aigues_barcelona.const import DOMAIN
from custom_components.aigues_barcelona.sensor import ContadorAgua
from custom_components.aigues_barcelona.sensor import ContratoAgua


def reading(when: str, value: float) -> dict:
    return {"datetime": when, "accumulatedConsumption": value}


@pytest.fixture
def coordinator(hass: HomeAssistant) -> ContratoAgua:
    hass.data.setdefault(DOMAIN, {})
    return ContratoAgua(hass, "12345678Z", "hunter2", "629067")


async def import_stats(
    coordinator: ContratoAgua, consumptions: list[dict], stored_sum: float | None = None
):
    """Run the import and hand back the statistics rows it would have written.

    `stored_sum` stands in for what the series already holds just before the
    batch, which the coordinator reads from the recorder to carry the running
    total across imports.
    """
    prefix = "custom_components.aigues_barcelona.sensor."
    with (
        patch(prefix + "async_import_statistics") as imported,
        patch.object(
            ContratoAgua, "_stored_sum_before", new=AsyncMock(return_value=stored_sum)
        ),
    ):
        await coordinator._async_import_statistics(consumptions)
    assert imported.called, "no statistics were imported"
    _hass, metadata, stats = imported.call_args.args
    return metadata, stats


class TestImportedSum:
    async def test_sum_never_goes_down_when_a_reading_does(self, coordinator):
        """A stale, lower reading must not become negative consumption.

        Home Assistant derives consumption from the difference between
        consecutive `sum` values, so a `sum` that drops by 2 m³ is reported as
        -2 m³ of water used. Holding the previous value keeps the series
        monotonic, which is what a meter's total actually is.
        """
        _meta, stats = await import_stats(
            coordinator,
            [
                reading("2026-09-16T01:00:00", 954.800),
                reading("2026-09-17T01:00:00", 957.423),
                reading("2026-09-18T01:00:00", 955.113),  # the API going backwards
                reading("2026-09-19T01:00:00", 957.900),
            ],
        )

        sums = [row["sum"] for row in stats]
        assert sums == sorted(sums), f"sum is not monotonic: {sums}"
        # The 18th held at the 17th's value instead of dropping to 955.113.
        assert sums == [954.800, 957.423, 957.423, 957.900]

    async def test_state_still_reports_the_reading_as_received(self, coordinator):
        """Only `sum` is clamped; `state` stays the meter's actual reading."""
        _meta, stats = await import_stats(
            coordinator,
            [
                reading("2026-09-17T01:00:00", 957.423),
                reading("2026-09-18T01:00:00", 955.113),
            ],
        )
        assert [row["state"] for row in stats] == [957.423, 955.113]
        assert [row["sum"] for row in stats] == [957.423, 957.423]

    async def test_rows_are_ordered_even_when_the_api_is_not(self, coordinator):
        _meta, stats = await import_stats(
            coordinator,
            [
                reading("2026-09-19T01:00:00", 3.0),
                reading("2026-09-17T01:00:00", 1.0),
                reading("2026-09-18T01:00:00", 2.0),
            ],
        )
        assert [row["state"] for row in stats] == [1.0, 2.0, 3.0]

    async def test_readings_are_rounded(self, coordinator):
        """The API sends floats with 20 digits of noise."""
        _meta, stats = await import_stats(
            coordinator, [reading("2026-09-17T01:00:00", 1.23456789)]
        )
        assert stats[0]["state"] == 1.2346

    async def test_metadata_marks_the_series_as_a_sum(self, coordinator):
        meta, _stats = await import_stats(
            coordinator, [reading("2026-09-17T01:00:00", 1.0)]
        )
        assert meta["has_sum"] is True
        assert meta["has_mean"] is False
        assert meta["statistic_id"] == "sensor.contador_629067"


class TestNoStateClass:
    def test_entity_declares_no_state_class(self, coordinator):
        """Guards against the double-writing that corrupted the series.

        Home Assistant's recorder compiles statistics for every sensor that
        declares a `state_class`. This coordinator imports the same
        `sensor.contador_*` series itself, so declaring one would put two
        writers on it with different meanings for `sum`.
        """
        sensor = ContadorAgua(coordinator)
        assert getattr(sensor, "_attr_state_class", None) is None
        assert sensor.state_class is None

    def test_still_a_water_sensor_in_cubic_metres(self, coordinator):
        """Dropping state_class must not cost the Energy dashboard its units."""
        sensor = ContadorAgua(coordinator)
        assert sensor.device_class == "water"
        assert sensor.native_unit_of_measurement == "m³"
        assert SensorStateClass  # imported to document what is deliberately absent


class TestSumCarriesAcrossImports:
    """Each poll imports a window; the total has to continue, not restart.

    Seeding only from the batch meant a window whose readings all sat below the
    stored total rewrote those hours lower, and Home Assistant read the drop as
    negative consumption.
    """

    async def test_a_lower_window_does_not_pull_the_total_down(self, coordinator):
        _meta, stats = await import_stats(
            coordinator,
            [
                reading("2026-09-20T01:00:00", 956.049),
                reading("2026-09-20T02:00:00", 956.529),
            ],
            stored_sum=958.302,
        )
        assert [row["sum"] for row in stats] == [958.302, 958.302]

    async def test_the_total_still_grows_past_what_was_stored(self, coordinator):
        _meta, stats = await import_stats(
            coordinator,
            [
                reading("2026-09-20T01:00:00", 958.500),
                reading("2026-09-20T02:00:00", 958.900),
            ],
            stored_sum=958.302,
        )
        assert [row["sum"] for row in stats] == [958.5, 958.9]

    async def test_an_empty_series_starts_from_the_first_reading(self, coordinator):
        _meta, stats = await import_stats(
            coordinator, [reading("2026-09-20T01:00:00", 100.0)], stored_sum=None
        )
        assert stats[0]["sum"] == 100.0

    async def test_nothing_is_imported_for_an_empty_batch(self, coordinator):
        prefix = "custom_components.aigues_barcelona.sensor."
        with (
            patch(prefix + "async_import_statistics") as imported,
            patch.object(
                ContratoAgua, "_stored_sum_before", new=AsyncMock(return_value=None)
            ),
        ):
            await coordinator._async_import_statistics([])
        assert not imported.called
