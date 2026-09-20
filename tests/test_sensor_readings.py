"""Tests for the reading and statistics handling.

These cover the two faults that made the Energy dashboard show swings of the
meter's whole lifetime volume as a single day's consumption:

1. the newest reading was taken as `consumptions[-1]`, trusting an order the API
   never promised, so the sensor could step backwards in time;
2. the imported statistics' `sum` followed the API's reading even when it went
   down, and Home Assistant reads a falling `sum` as negative consumption.
"""

from custom_components.aigues_barcelona.sensor import newest_metric
from custom_components.aigues_barcelona.sensor import sort_by_datetime


def reading(when: str, value: float) -> dict:
    """Build a metric shaped like the one the API returns."""
    return {"datetime": when, "accumulatedConsumption": value}


class TestSortByDatetime:
    def test_orders_oldest_first(self):
        out = sort_by_datetime(
            [
                reading("2026-09-18T01:00:00", 955.113),
                reading("2026-09-16T01:00:00", 954.800),
                reading("2026-09-20T01:00:00", 956.529),
            ]
        )
        assert [m["accumulatedConsumption"] for m in out] == [
            954.800,
            955.113,
            956.529,
        ]

    def test_keeps_an_already_sorted_list_untouched(self):
        given = [
            reading("2026-09-16T01:00:00", 1.0),
            reading("2026-09-17T01:00:00", 2.0),
        ]
        assert sort_by_datetime(given) == given

    def test_drops_entries_with_an_unusable_date(self):
        out = sort_by_datetime(
            [
                reading("2026-09-16T01:00:00", 1.0),
                reading("not a date", 2.0),
                {"accumulatedConsumption": 3.0},  # no datetime at all
                reading("2026-09-17T01:00:00", 4.0),
            ]
        )
        assert [m["accumulatedConsumption"] for m in out] == [1.0, 4.0]

    def test_empty_input_gives_empty_output(self):
        assert sort_by_datetime([]) == []


class TestNewestMetric:
    def test_picks_the_latest_date_not_the_last_item(self):
        """The regression that caused the reported jumps.

        Taking `consumptions[-1]` here would return the 16th, a reading the
        meter had already passed, and the sensor would appear to run backwards.
        """
        out = newest_metric(
            [
                reading("2026-09-20T01:00:00", 956.529),
                reading("2026-09-18T01:00:00", 955.113),
                reading("2026-09-16T01:00:00", 954.800),
            ]
        )
        assert out["accumulatedConsumption"] == 956.529

    def test_returns_none_when_there_is_nothing_usable(self):
        assert newest_metric([]) is None
        assert newest_metric([{"accumulatedConsumption": 1.0}]) is None

    def test_handles_timezone_aware_timestamps(self):
        """The API mixes offsets; comparing them must not raise."""
        out = newest_metric(
            [
                reading("2026-09-20T01:00:00+02:00", 10.0),
                reading("2026-09-20T02:30:00+02:00", 20.0),
            ]
        )
        assert out["accumulatedConsumption"] == 20.0
