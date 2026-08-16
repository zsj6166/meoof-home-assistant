from homeassistant.components.number import NumberEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    registry = er.async_get(hass)
    obsolete = registry.async_get_entity_id(
        "number", DOMAIN, entry.entry_id + "-right-portions"
    )
    if obsolete:
        registry.async_remove(obsolete)
    async_add_entities([
        MeoofPortions(coordinator, entry, "left", "出粮份数"),
    ])


class MeoofPortions(MeoofEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = "box"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry, side, name):
        super().__init__(coordinator, entry)
        self._side = side
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}-{side}-portions"

    @property
    def native_value(self):
        return getattr(self.coordinator, f"{self._side}_portions")

    async def async_set_native_value(self, value):
        setattr(self.coordinator, f"{self._side}_portions", int(value))
        self.async_write_ha_state()
