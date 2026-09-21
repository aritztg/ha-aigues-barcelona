"""Platform for sensor integration."""

# from __future__ import annotations
import logging
from datetime import datetime
from datetime import timedelta

import homeassistant.components.recorder.util as recorder_util
import homeassistant.util.dt as dt_util
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.components.recorder.statistics import list_statistic_ids
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_STATE
from homeassistant.const import CONF_TOKEN
from homeassistant.const import CONF_USERNAME
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.const import UnitOfVolume
from homeassistant.core import CoreState
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator

from .api import AiguesApiClient
from .auth import async_renew_token
from .const import API_ERROR_TOKEN_REVOKED
from .const import ATTR_LAST_MEASURE
from .const import CONF_CONTRACT
from .const import CONF_VALUE
from .const import DEFAULT_SCAN_PERIOD
from .const import DOMAIN
from .const import SUM_LOOKBACK_DAYS

_LOGGER = logging.getLogger(__name__)


def get_db_instance(hass):
    """Workaround for older HA versions."""
    try:
        return recorder_util.get_instance(hass)
    except AttributeError:
        return hass


def _metric_datetime(metric) -> datetime | None:
    """Parse a metric's timestamp, or None when it is missing or malformed."""
    try:
        return datetime.fromisoformat(metric["datetime"])
    except KeyError, TypeError, ValueError:
        return None


def sort_by_datetime(consumptions) -> list:
    """Return the readings oldest first, dropping any with an unusable date."""
    dated = [(dt, m) for m in consumptions if (dt := _metric_datetime(m)) is not None]
    return [m for _, m in sorted(dated, key=lambda pair: pair[0])]


def newest_metric(consumptions):
    """Return the most recent reading, or None when there is none to use."""
    ordered = sort_by_datetime(consumptions)
    return ordered[-1] if ordered else None


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up entry."""
    hass.data.setdefault(DOMAIN, {})

    _LOGGER.info("calling async_setup_entry")

    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    contracts = config_entry.data[CONF_CONTRACT]
    token = config_entry.data.get(CONF_TOKEN)

    contadores = []

    for contract in contracts:
        coordinator = ContratoAgua(
            hass, username, password, contract, token=token, entry=config_entry
        )
        contadores.append(ContadorAgua(coordinator))

    # postpone first refresh to speed up startup
    @callback
    async def async_first_refresh(*args):
        for sensor in contadores:
            await sensor.coordinator.async_migrate_entity_statistics()
            await sensor.coordinator.async_refresh()

    # ------

    if hass.state == CoreState.running:
        await async_first_refresh()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, async_first_refresh)

    _LOGGER.info("about to add entities")
    async_add_entities(contadores)

    return True


class ContratoAgua(TimestampDataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        contract: str,
        token: str | None = None,
        prev_data=None,
        entry=None,
    ) -> None:
        """Initialize the data handler."""
        self.reset = prev_data is None
        self.entry = entry

        self.contract = contract.upper()
        self.id = contract.lower()
        self.internal_sensor_id = f"sensor.contador_{self.id}"
        # Long-term statistics live under an external id rather than the
        # entity's own. Readings arrive days late and belong at past
        # timestamps, which is what external statistics are for; writing them
        # onto the entity id put this integration and Home Assistant's recorder
        # on the same series, each with its own idea of what `sum` meant.
        self.external_statistic_id = f"{DOMAIN}:water_meter_{self.id}"

        if not hass.data[DOMAIN].get(self.contract):
            # init data shared store
            hass.data[DOMAIN][self.contract] = {}

        # create alias
        self._data = hass.data[DOMAIN][self.contract]

        # WARN define a pointer to this object
        hass.data[DOMAIN][self.contract]["coordinator"] = self

        # the api object
        self._api = AiguesApiClient(username, password, contract)
        if token:
            self._api.set_token(token)

        super().__init__(
            hass,
            _LOGGER,
            name=self.id,
            update_interval=timedelta(seconds=DEFAULT_SCAN_PERIOD),
        )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.contract}>"

    async def _async_update_data(self):
        _LOGGER.info(f"Updating coordinator data for {self.contract}")
        TODAY = datetime.now()
        LAST_WEEK = TODAY - timedelta(days=7)
        LAST_TIME_DAYS = None

        # last_measurement = await self.get_last_measurement_stored()
        # _LOGGER.info("Last stored measurement: %s", last_measurement)

        try:
            previous = datetime.fromisoformat(self._data.get(CONF_STATE, ""))
            # FIX: TypeError: can't subtract offset-naive and offset-aware datetimes
            previous = previous.replace(tzinfo=None)
            if previous:
                LAST_TIME_DAYS = (TODAY - previous).days
        except ValueError:
            previous = None

        if previous and (TODAY - previous) <= timedelta(minutes=60):
            _LOGGER.warning("Skipping request update data - too early")
            return

        consumptions = None
        try:
            await self._async_ensure_token()
            consumptions = await self.hass.async_add_executor_job(
                self._api.consumptions, LAST_WEEK, TODAY, self.contract
            )
        except ConfigEntryAuthFailed as exp:
            _LOGGER.error("Token has expired, cannot check consumptions.")
            raise ConfigEntryAuthFailed from exp
        except Exception as exp:
            self.async_set_update_error(exp)
            if API_ERROR_TOKEN_REVOKED in str(exp):
                raise ConfigEntryAuthFailed from exp

        if not consumptions:
            _LOGGER.error("No consumptions available")
            return False

        self._data["consumptions"] = consumptions

        # The API does not promise the window comes back in chronological order,
        # so the newest entry is the one with the highest datetime, not the last
        # item of the list. Taking consumptions[-1] made the sensor jump back to
        # a reading from days earlier, which a water meter can never do.
        metric = newest_metric(consumptions)
        if metric is None:
            _LOGGER.warning("No usable consumption entry in the API response")
            return False

        self._data[CONF_VALUE] = metric["accumulatedConsumption"]
        self._data[CONF_STATE] = metric["datetime"]

        # await self._clear_statistics()
        try:
            await self._async_import_statistics(consumptions)
        except Exception:
            # A failed import must not take the whole refresh down with it, but
            # it used to be swallowed by a bare `except: pass`, so statistics
            # could quietly stop updating with nothing in the log to show for it.
            _LOGGER.exception("Could not import statistics for %s", self.contract)

        if LAST_TIME_DAYS and LAST_TIME_DAYS >= 7:
            await self.import_old_consumptions(days=LAST_TIME_DAYS)

        return True

    async def _async_ensure_token(self) -> None:
        """Make sure the client holds a token that is still good.

        Only reaches for a new one once the stored token is spent,
        because getting one costs a login.
        """
        if self.entry is None:
            if self._api.is_token_expired():
                raise ConfigEntryAuthFailed
            return

        token = await async_renew_token(self.hass, self.entry)
        if not token:
            raise ConfigEntryAuthFailed("No valid token available")
        self._api.set_token(token)

    async def async_migrate_entity_statistics(self) -> None:
        """Move statistics recorded against the entity to the external series.

        Versions up to 0.5 wrote long-term statistics onto `sensor.contador_*`,
        an id Home Assistant treats as the recorder's own. Left there they
        raise a repair issue whose only offered remedy is deleting the history,
        so the rows are copied to the external series first and the old one is
        dropped afterwards. Finding nothing to move is the normal case and
        costs one query.
        """
        instance = get_db_instance(self.hass)
        all_ids = await instance.async_add_executor_job(list_statistic_ids, self.hass)
        stale = next(
            (
                x
                for x in all_ids
                if x["statistic_id"] == self.internal_sensor_id
                and x.get("source") == "recorder"
            ),
            None,
        )
        if stale is None:
            return

        _LOGGER.warning(
            "Migrating statistics from %s to %s",
            self.internal_sensor_id,
            self.external_statistic_id,
        )
        stats = await instance.async_add_executor_job(
            statistics_during_period,
            self.hass,
            dt_util.utc_from_timestamp(0),
            None,
            {self.internal_sensor_id},
            "hour",
            None,
            {"state", "sum"},
        )
        rows = stats.get(self.internal_sensor_id) or []
        if rows:
            running = None
            migrated = []
            for row in rows:
                total = row.get("sum")
                if total is None:
                    continue
                # The old series could step backwards, which is what made it
                # worth leaving behind. Carry the highest total across.
                running = total if running is None else max(running, total)
                migrated.append(
                    {
                        "start": dt_util.utc_from_timestamp(row["start"]),
                        "state": row.get("state"),
                        "sum": running,
                    }
                )
            if migrated:
                async_add_external_statistics(
                    self.hass, self._statistics_metadata(), migrated
                )
                _LOGGER.warning("Migrated %s statistics rows", len(migrated))

        # Queued on the recorder's own thread. Running clear_statistics in an
        # executor job instead looks like it works and silently leaves the rows
        # in place, which is what the "does not seem to work" note in earlier
        # versions was about.
        instance.async_clear_statistics([self.internal_sensor_id])

    async def _clear_statistics(self) -> None:
        all_ids = await get_db_instance(self.hass).async_add_executor_job(
            list_statistic_ids, self.hass
        )
        to_clear = [
            x["statistic_id"]
            for x in all_ids
            if x["statistic_id"].startswith(self.internal_sensor_id)
        ]

        if to_clear:
            _LOGGER.warn(
                f"About to delete {len(to_clear)} entries from {self.contract}"
            )
            get_db_instance(self.hass).async_clear_statistics(to_clear)

    async def get_last_measurement_stored(self) -> datetime | None:
        last_stored = None

        all_ids = await get_db_instance(self.hass).async_add_executor_job(
            list_statistic_ids, self.hass
        )

        for stat_id in all_ids:
            # `last_stored` starts as None, so the previous version subscripted
            # None on the first match and raised TypeError. Nothing called this
            # method, so the crash stayed hidden.
            if stat_id["statistic_id"] != self.internal_sensor_id:
                continue
            if stat_id.get("sum") is None:
                continue
            if last_stored is None or stat_id["sum"] > last_stored["sum"]:
                last_stored = stat_id

        if last_stored:
            _LOGGER.debug(f"Found last stored value: {last_stored}")
            return datetime.fromtimestamp(last_stored.get("start_ts"))

        return None

    async def _stored_sum_before(self, when: datetime) -> float | None:
        """The cumulative total already recorded just before `when`.

        Each import has to carry on from what the series already holds. Seeding
        from the batch alone only keeps that batch monotonic: a window whose
        readings all sit below the stored total would rewrite those hours lower
        and Home Assistant would report the drop as negative consumption.
        """
        window_start = when - timedelta(days=SUM_LOOKBACK_DAYS)
        stats = await get_db_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            window_start,
            when,
            {self.external_statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = stats.get(self.external_statistic_id) or []
        return rows[-1].get("sum") if rows else None

    async def _async_import_statistics(self, consumptions) -> None:
        consumptions = sort_by_datetime(consumptions)
        if not consumptions:
            return

        first = _metric_datetime(consumptions[0]).replace(
            minute=0, second=0, microsecond=0
        )
        running_sum = await self._stored_sum_before(first)

        stats = []
        for metric in consumptions:
            start_ts = _metric_datetime(metric)
            start_ts = start_ts.replace(minute=0, second=0, microsecond=0)  # required

            # round: fixes decimal with 20 digits precision
            state = round(metric["accumulatedConsumption"], 4)

            # `accumulatedConsumption` is the meter's absolute reading, which is
            # already cumulative, so it doubles as the statistics sum. What it is
            # not is guaranteed to grow: the API serves stale, lower readings,
            # and out of order. Home Assistant turns any drop in `sum` into
            # negative consumption, so never step back from the highest total
            # seen, whether that came from this batch or from what was already
            # stored.
            running_sum = state if running_sum is None else max(running_sum, state)

            stats.append(
                {
                    "start": start_ts,
                    "state": state,
                    "sum": running_sum,
                }
            )
        async_add_external_statistics(self.hass, self._statistics_metadata(), stats)

    def _statistics_metadata(self) -> dict:
        return {
            "has_mean": False,
            "has_sum": True,
            "name": f"Water meter {self.contract}",
            "source": DOMAIN,
            "statistic_id": self.external_statistic_id,
            "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        }

    async def clear_all_stored_data(self) -> None:
        await self._clear_statistics()

    async def import_old_consumptions(self, days: int = 365) -> None:
        """Walk the history a week at a time and store what comes back.

        A long window means a long run, so a week that fails is logged and
        skipped rather than thrown away along with every week after it. The
        statistics already written stay written.
        """
        today = datetime.now()
        start = today - timedelta(days=days)

        await self._async_ensure_token()

        failures = 0
        current_date = start
        while current_date < today:
            try:
                consumptions = await self.hass.async_add_executor_job(
                    self._api.consumptions_week, current_date, self.contract
                )
            except Exception as err:  # one bad week must not sink the rest
                failures += 1
                _LOGGER.warning(
                    "Could not read the week of %s: %s", current_date.date(), err
                )
            else:
                if consumptions:
                    await self._async_import_statistics(consumptions)
                else:
                    _LOGGER.debug("No data available for %s", current_date.date())

            current_date += timedelta(weeks=1)

        if failures:
            _LOGGER.warning(
                "Finished the backfill with %s week(s) unread; run it again to "
                "fill the gaps",
                failures,
            )


class ContadorAgua(CoordinatorEntity, SensorEntity):
    """Representation of a sensor."""

    _attr_has_entity_name = True
    # The name comes from the translations rather than being written here in
    # Spanish, matching how the core water integrations name their entities.
    _attr_translation_key = "water_meter"

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.id
        self._attr_icon = "mdi:water-pump"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.contract)},
            manufacturer="Aigües de Barcelona",
            name=f"Aigües de Barcelona {coordinator.contract}",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_should_poll = False
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    # Deliberately no `state_class`. The coordinator imports this entity's
    # long-term statistics itself, timestamped when the water was actually used
    # rather than when the reading reached us, since the API runs days behind.
    #
    # Home Assistant's recorder compiles statistics for every sensor that
    # declares a `state_class` (see `_get_sensor_states` in
    # homeassistant/components/sensor/recorder.py). With one set, the recorder
    # and this integration both wrote the same `sensor.contador_*` series with
    # different meanings for `sum`: the recorder's consumption since it started
    # watching, ours the meter's absolute reading. They overwrote each other
    # hourly and the Energy dashboard showed swings of the meter's whole
    # lifetime volume as if it were a single day's use.

    @property
    def native_value(self):
        return self.coordinator._data.get(CONF_VALUE, None)

    @property
    def last_measurement(self):
        try:
            last_measure = datetime.fromisoformat(
                self.coordinator._data.get(CONF_STATE, "")
            )
        except ValueError:
            last_measure = None
        return last_measure

    @property
    def extra_state_attributes(self):
        attrs = {ATTR_LAST_MEASURE: self.last_measurement}
        return attrs
