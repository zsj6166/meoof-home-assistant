from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeoofReviewCatSelect(coordinator, entry)])


class MeoofReviewCatSelect(MeoofEntity, SelectEntity):
    _attr_name = "待分类猫咪选择"
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-review-cat-select"
        profiles = list((coordinator.data or {}).get("cats", {}).get("profiles", {}))
        if profiles and coordinator.client.cat_name not in profiles:
            coordinator.client.cat_name = profiles[0]

    @property
    def options(self):
        return list((self.coordinator.data or {}).get("cats", {}).get("profiles", {}))

    @property
    def current_option(self):
        selected = self.coordinator.client.cat_name
        options = self.options
        return selected if selected in options else (options[0] if options else None)

    async def async_select_option(self, option):
        if option not in self.options:
            raise ValueError("猫咪档案不存在")
        self.coordinator.client.cat_name = option
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
