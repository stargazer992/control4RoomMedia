"""Per-room bass / treble / balance sliders for the Triad AMS 24x24."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    DOMAIN,
    TRIAD_CONNECT_TIMEOUT,
    TRIAD_HOST,
    TRIAD_OUTPUTS,
    TRIAD_POLL_INTERVAL,
    TRIAD_PORT,
    TRIAD_REPLY_TIMEOUT,
)
from .triad import (
    KIND_BALANCE,
    KIND_BASS,
    KIND_TREBLE,
    TriadAms,
    TriadError,
)

_LOGGER = logging.getLogger(__name__)

# kind -> (display name, icon)
KINDS = {
    KIND_BASS: ("Bass", "mdi:speaker"),
    KIND_TREBLE: ("Treble", "mdi:music-clef-treble"),
    KIND_BALANCE: ("Balance", "mdi:tune-vertical"),
}
SLIDER_MIN = -12
SLIDER_MAX = 12
SLIDER_STEP = 1  # the amp stores 0.5 dB steps; whole steps keep read-back unambiguous


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Triad AMS sliders (skipped when no Triad host is configured)."""
    if not TRIAD_HOST or not TRIAD_OUTPUTS:
        return

    ams = TriadAms(TRIAD_HOST, TRIAD_PORT, TRIAD_CONNECT_TIMEOUT, TRIAD_REPLY_TIMEOUT)
    outputs = sorted(TRIAD_OUTPUTS)

    async def _async_update() -> dict[int, dict[str, float | None]]:
        try:
            return await ams.async_read_all(outputs)
        except TriadError as err:
            raise UpdateFailed(f"Triad AMS: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="Control4 Triad AMS",
        update_method=_async_update,
        update_interval=timedelta(seconds=TRIAD_POLL_INTERVAL),
    )
    # A failed first read must not stop the lights and media players from
    # loading, so refresh without raising; entities show unavailable until the
    # amp answers.
    await coordinator.async_refresh()

    controller_id = hass.data[DOMAIN][entry.entry_id].get(
        CONF_CONTROLLER_UNIQUE_ID, entry.entry_id
    )
    entities = [
        TriadSlider(coordinator, ams, controller_id, output, kind)
        for output in outputs
        for kind in KINDS
    ]
    async_add_entities(entities)


class TriadSlider(CoordinatorEntity[DataUpdateCoordinator], NumberEntity):
    """One bass / treble / balance slider for one amp output."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = SLIDER_MIN
    _attr_native_max_value = SLIDER_MAX
    _attr_native_step = SLIDER_STEP
    _attr_native_unit_of_measurement = "dB"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        ams: TriadAms,
        controller_id: str,
        output: int,
        kind: str,
    ) -> None:
        super().__init__(coordinator)
        self._ams = ams
        self._output = output
        self._kind = kind
        room = TRIAD_OUTPUTS[output]
        label, icon = KINDS[kind]
        self._attr_name = f"{room} {label}"
        self._attr_icon = icon
        self._attr_unique_id = f"{controller_id}_triad_out{output}_{kind}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{controller_id}_triad_ams")},
            manufacturer="Triad",
            model="AMS 24x24 Audio Matrix",
            name="Triad AMS 24x24",
        )

    @property
    def native_value(self) -> float | None:
        """Return the last value read from (or sent to) the amp."""
        data = self.coordinator.data or {}
        return data.get(self._output, {}).get(self._kind)

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the amp; keep the displayed value in step."""
        try:
            await self._ams.async_set(self._kind, self._output, value)
        except TriadError as err:
            raise HomeAssistantError(
                f"Could not set {self.name} on the Triad AMS: {err}"
            ) from err
        # The amp's read-back lags a set by a fraction of a second, so show the
        # value we just sent now; the next poll reconciles it with the amp.
        data: dict[Any, Any] = dict(self.coordinator.data or {})
        row = dict(data.get(self._output, {}))
        row[self._kind] = float(value)
        data[self._output] = row
        self.coordinator.async_set_updated_data(data)
