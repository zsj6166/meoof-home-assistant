from homeassistant.components.text import TextEntity

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeoofCatName(coordinator, entry)])


class MeoofCatName(MeoofEntity, TextEntity):
    _attr_name = "猫咪档案名称"
    _attr_icon = "mdi:form-textbox"
    _attr_native_min = 0
    _attr_native_max = 40

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-cat-name"

    @property
    def native_value(self):
        return self.coordinator.client.cat_name

    async def async_set_value(self, value):
        self.coordinator.client.cat_name = value.strip()
        self.async_write_ha_state()
