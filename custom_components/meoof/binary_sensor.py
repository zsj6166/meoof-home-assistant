from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    registry = er.async_get(hass)
    obsolete = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, entry.entry_id + "-right_bin_food"
    )
    if obsolete:
        registry.async_remove(obsolete)
    async_add_entities([
        MeoofOnline(coordinator, entry),
        MeoofStatusBinary(coordinator, entry, "powered", "供电状态", "mdi:power-plug"),
        MeoofStatusBinary(coordinator, entry, "left_bin_food", "粮仓有粮", "mdi:bowl-mix"),
        MeoofStatusBinary(coordinator, entry, "food_blocked", "出粮堵塞", "mdi:alert-circle"),
        MeoofStatusBinary(coordinator, entry, "child_lock", "童锁", "mdi:lock"),
        MeoofStatusBinary(coordinator, entry, "voice_enabled", "设备声音", "mdi:volume-high"),
        MeoofStatusBinary(coordinator, entry, "led_enabled", "指示灯", "mdi:led-on"),
        MeoofStatusBinary(coordinator, entry, "camera_live", "实时监控开启", "mdi:cctv"),
        MeoofStatusBinary(coordinator, entry, "power_save", "省电模式", "mdi:leaf"),
        MeoofStatusBinary(coordinator, entry, "feed_voice", "出粮语音", "mdi:account-voice"),
    ])


class MeoofStatusBinary(MeoofEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, key, name, icon):
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = entry.entry_id + "-" + key

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get("status", {}).get(self._key))


class MeoofOnline(MeoofEntity, BinarySensorEntity):
    _attr_name = "连接状态"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-online"

    @property
    def is_on(self):
        return bool(self.coordinator.data and self.coordinator.data.get("ok"))
