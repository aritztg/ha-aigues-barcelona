"""Tests for walking a long history.

The window used to be fixed at a year. Asking for three years turned out to
send enough requests to trip the API's rate limiter, and a single refusal
ended the run, discarding every week that had not been read yet.
"""

import inspect
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.aigues_barcelona.const import DOMAIN
from custom_components.aigues_barcelona.sensor import ContratoAgua


@pytest.fixture
def coordinator(hass: HomeAssistant) -> ContratoAgua:
    hass.data.setdefault(DOMAIN, {})
    return ContratoAgua(hass, "12345678Z", "hunter2", "629067")


async def run_backfill(coordinator: ContratoAgua, weeks: list, days: int):
    """Drive the loop with one canned answer per week."""
    remaining = list(weeks)
    imported = []

    def fetch(*args):
        reply = remaining.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    with (
        patch.object(coordinator, "_async_ensure_token", new=AsyncMock()),
        patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(side_effect=fetch)
        ),
        patch.object(
            coordinator,
            "_async_import_statistics",
            new=AsyncMock(side_effect=lambda c: imported.append(c)),
        ),
    ):
        await coordinator.import_old_consumptions(days=days)
    return remaining, imported


async def test_reads_one_week_at_a_time(coordinator):
    remaining, imported = await run_backfill(coordinator, [[1], [2], [3]], days=21)

    assert remaining == []
    assert imported == [[1], [2], [3]]


async def test_a_refused_week_does_not_end_the_run(coordinator):
    """The regression: the rate limiter used to abort everything after it."""
    weeks = [[1], Exception("Rate-Limited"), [3]]

    remaining, imported = await run_backfill(coordinator, weeks, days=21)

    assert remaining == [], "the run stopped at the first failure"
    assert imported == [[1], [3]]


async def test_says_how_many_weeks_it_could_not_read(coordinator, caplog):
    weeks = [Exception("Rate-Limited"), Exception("Rate-Limited"), [3]]

    await run_backfill(coordinator, weeks, days=21)

    assert "2 week(s) unread" in caplog.text


async def test_an_empty_week_is_not_a_failure(coordinator, caplog):
    """Before the meter was installed there is simply nothing to read."""
    remaining, imported = await run_backfill(coordinator, [[], [], [3]], days=21)

    assert remaining == []
    assert imported == [[3]]
    assert "unread" not in caplog.text


async def test_asks_for_hourly_detail(coordinator):
    """Daily totals land in a single hourly bucket, flattening the day.

    The same request costs the same either way, and the API answers with
    daily totals of its own accord once the hourly detail has aged out.
    """
    with (
        patch.object(coordinator, "_async_ensure_token", new=AsyncMock()),
        patch.object(
            coordinator.hass, "async_add_executor_job", new=AsyncMock(return_value=[])
        ) as job,
    ):
        await coordinator.import_old_consumptions(days=7)

    assert job.await_args.args[0] == coordinator._api.consumptions_week
    assert (
        inspect.signature(coordinator._api.consumptions_week)
        .parameters["frequency"]
        .default
        == "HOURLY"
    )
