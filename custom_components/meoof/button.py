from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeoofFeedButton(coordinator, entry),
                        MeoofPlaybackButton(coordinator, entry),
                        MeoofSmartFeedTestButton(coordinator, entry),
                        MeoofClassifyPendingButton(coordinator, entry),
                        MeoofSkipPendingButton(coordinator, entry),
                        MeoofCatProfileButton(coordinator, entry, False),
                        MeoofCatProfileButton(coordinator, entry, True)])


class MeoofSmartFeedTestButton(MeoofEntity, ButtonEntity):
    _attr_name = "测试余粮识别（不修改计划）"
    _attr_icon = "mdi:camera-check-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-smart-feed-test"

    async def async_press(self):
        try:
            await self.coordinator.client.test_smart_feed_check()
            await self.coordinator.async_request_refresh()
        except Exception as exc:
            raise HomeAssistantError(f"余粮识别测试失败: {type(exc).__name__}") from exc


class MeoofClassifyPendingButton(MeoofEntity, ButtonEntity):
    _attr_name = "将最新未知记录归类"
    _attr_icon = "mdi:tag-check"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-classify-pending"

    async def async_press(self):
        if not self.coordinator.client.cat_name.strip():
            raise HomeAssistantError("请先填写猫咪档案名称")
        try:
            await self.coordinator.client.classify_latest_pending()
            await self.coordinator.async_request_refresh()
        except Exception as exc:
            raise HomeAssistantError(f"归类失败: {exc}") from exc


class MeoofSkipPendingButton(MeoofEntity, ButtonEntity):
    _attr_name = "跳过最新待分类记录"
    _attr_icon = "mdi:cat-off"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-skip-pending"

    async def async_press(self):
        try:
            await self.coordinator.client.skip_latest_pending()
            await self.coordinator.async_request_refresh()
        except Exception as exc:
            raise HomeAssistantError(f"跳过失败: {exc}") from exc


class MeoofFeedButton(MeoofEntity, ButtonEntity):
    _attr_name = "手动出粮"
    _attr_icon = "mdi:food-drumstick"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-manual-feed"

    async def async_press(self):
        if self.coordinator.left_portions == 0:
            raise HomeAssistantError("出粮份数不能为 0")
        try:
            await self.coordinator.async_feed()
        except Exception as exc:
            raise HomeAssistantError(f"手动出粮失败: {exc}") from exc


class MeoofPlaybackButton(MeoofEntity, ButtonEntity):
    _attr_name = "下载最近觅食回放"
    _attr_icon = "mdi:download-circle-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-download-latest-playback"

    async def async_press(self):
        try:
            await self.coordinator.client.download_latest_playback()
            await self.coordinator.async_request_refresh()
        except Exception as exc:
            raise HomeAssistantError(f"下载觅食回放失败: {exc}") from exc


class MeoofCatProfileButton(MeoofEntity, ButtonEntity):
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry, delete):
        super().__init__(coordinator, entry)
        self._delete = delete
        self._attr_name = "删除猫咪档案" if delete else "采集猫咪档案样本"
        self._attr_unique_id = entry.entry_id + ("-delete-cat" if delete else "-add-cat")

    async def async_press(self):
        if not self.coordinator.client.cat_name.strip():
            raise HomeAssistantError("请先填写猫咪档案名称")
        try:
            if self._delete:
                await self.coordinator.client.delete_cat_profile()
            else:
                await self.coordinator.client.add_cat_profile()
            await self.coordinator.async_request_refresh()
        except Exception as exc:
            raise HomeAssistantError(f"猫咪档案操作失败: {exc}") from exc
