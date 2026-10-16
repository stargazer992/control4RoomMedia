"""The Control4 integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import client_exceptions
from pyControl4.account import C4Account
from pyControl4.director import C4Director
from pyControl4.error_handling import BadCredentials

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_ACCOUNT,
    CONF_CONFIG_LISTENER,
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_DIRECTOR_MODEL,
    CONF_DIRECTOR_SW_VERSION,
    CONF_UI_CONFIGURATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.MEDIA_PLAYER]

API_RETRY_TMES = 5

# Seconds to wait between cloud API retries (multiplied by attempt number).
API_RETRY_DELAY = 3

# Transient failures seen in the wild (cloud timeout, empty/garbled reply).
# These must trigger ConfigEntryNotReady so HA retries on its own, instead of
# leaving the entry in a permanent "setup error" state.
TRANSIENT_ERRORS = (
    client_exceptions.ClientError,
    asyncio.TimeoutError,
    TimeoutError,
    json.JSONDecodeError,
    ValueError,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Control4 from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    account_session = aiohttp_client.async_get_clientsession(hass)

    config = entry.data
    account = C4Account(config[CONF_USERNAME], config[CONF_PASSWORD], account_session)
    try:
        await account.getAccountBearerToken()
    except TRANSIENT_ERRORS as exception:
        _LOGGER.error(
            "Error connecting to Control4 account API (will retry): %r", exception
        )
        raise ConfigEntryNotReady from exception
    except BadCredentials as exception:
        _LOGGER.error(
            (
                "Error authenticating with Control4 account API, incorrect username or"
                " password: %s"
            ),
            exception,
        )
        return False
    entry_data[CONF_ACCOUNT] = account

    controller_unique_id = config[CONF_CONTROLLER_UNIQUE_ID]
    entry_data[CONF_CONTROLLER_UNIQUE_ID] = controller_unique_id

    # Add retry for C4 Account API due to instability
    for i in range(API_RETRY_TMES):
        try:
            director_token_dict = await account.getDirectorBearerToken(
                controller_unique_id
            )
            break
        except TRANSIENT_ERRORS as exception:
            _LOGGER.error(
                "Error getting Control4 director token (attempt %s/%s): %r",
                i + 1,
                API_RETRY_TMES,
                exception,
            )
            if i == API_RETRY_TMES - 1:
                raise ConfigEntryNotReady(exception) from exception
            await asyncio.sleep(API_RETRY_DELAY * (i + 1))

    director_session = aiohttp_client.async_get_clientsession(hass, verify_ssl=False)
    director = C4Director(
        config[CONF_HOST], director_token_dict[CONF_TOKEN], director_session
    )
    entry_data[CONF_DIRECTOR] = director

    # The OS version is only cosmetic (device registry sw_version). Never let
    # a failure here block setup: retry a few times, then carry on without it.
    entry_data[CONF_DIRECTOR_SW_VERSION] = None
    for i in range(API_RETRY_TMES):
        try:
            controller_href = (await account.getAccountControllers())["href"]
            entry_data[CONF_DIRECTOR_SW_VERSION] = await account.getControllerOSVersion(
                controller_href
            )
            break
        except Exception as exception:  # noqa: BLE001 - non-fatal by design
            _LOGGER.warning(
                "Could not read Control4 OS version (attempt %s/%s): %r",
                i + 1,
                API_RETRY_TMES,
                exception,
            )
            if i < API_RETRY_TMES - 1:
                await asyncio.sleep(API_RETRY_DELAY * (i + 1))

    _, model, mac_address = controller_unique_id.split("_", 3)
    entry_data[CONF_DIRECTOR_MODEL] = model.upper()

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, controller_unique_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, mac_address)},
        manufacturer="Control4",
        name=controller_unique_id,
        model=entry_data[CONF_DIRECTOR_MODEL],
        sw_version=entry_data[CONF_DIRECTOR_SW_VERSION],
    )

    # Store all items found on controller for platforms to use
    try:
        director_all_items = await director.getAllItemInfo()
        director_all_items = json.loads(director_all_items)
        entry_data[CONF_DIRECTOR_ALL_ITEMS] = director_all_items

        entry_data[CONF_UI_CONFIGURATION] = json.loads(
            await director.getUiConfiguration()
        )
    except TRANSIENT_ERRORS as exception:
        _LOGGER.error(
            "Error reading items from Control4 controller (will retry): %r",
            exception,
        )
        raise ConfigEntryNotReady from exception

    # Load options from config entry
    entry_data[CONF_SCAN_INTERVAL] = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )

    entry_data[CONF_CONFIG_LISTENER] = entry.add_update_listener(update_listener)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update when config_entry options update."""
    _LOGGER.debug("Config entry was updated, rerunning setup")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN][entry.entry_id][CONF_CONFIG_LISTENER]()
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Unloaded entry for %s", entry.entry_id)

    return unload_ok


async def get_items_of_category(hass: HomeAssistant, entry: ConfigEntry, category: str):
    """Return a list of all Control4 items with the specified category."""
    director_all_items = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR_ALL_ITEMS]
    return [
        item
        for item in director_all_items
        if "categories" in item and category in item["categories"]
    ]


class Control4Entity(CoordinatorEntity[Any]):
    """Base entity for Control4."""

    def __init__(
        self,
        entry_data: dict,
        coordinator: DataUpdateCoordinator[Any],
        name: str,
        idx: int,
        device_name: str | None,
        device_manufacturer: str | None,
        device_model: str | None,
        device_id: int,
    ) -> None:
        """Initialize a Control4 entity."""
        super().__init__(coordinator)
        self.entry_data = entry_data
        self._attr_name = name
        self._attr_unique_id = str(idx)
        self._idx = idx
        self._controller_unique_id = entry_data[CONF_CONTROLLER_UNIQUE_ID]
        self._device_name = device_name
        self._device_manufacturer = device_manufacturer
        self._device_model = device_model
        self._device_id = device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return info of parent Control4 device of entity."""
        # HA deprecated DeviceInfo/async_get_or_create "via_device" (identifier
        # tuple) in favour of "via_device_id" (the device registry's own id),
        # removed in HA 2027.8.0. The controller device is created in
        # async_setup_entry before any platform loads, so look its id up here.
        # If it is ever missing, leave the link out rather than fail the entity.
        # async_get_device() is itself deprecated (identifiers are only unique
        # per config entry); async_get_device_by_identifier() is scoped to one.
        controller = None
        platform = getattr(self, "platform", None)
        config_entry = getattr(platform, "config_entry", None)
        if config_entry is not None:
            controller = dr.async_get(self.hass).async_get_device_by_identifier(
                (DOMAIN, self._controller_unique_id), config_entry.entry_id
            )
        info = DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            manufacturer=self._device_manufacturer,
            model=self._device_model,
            name=self._device_name,
        )
        if controller is not None:
            info["via_device_id"] = controller.id
        return info
