import asyncio

from homeassistant.components.camera import Camera
from aiohttp import web

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeoofCamera(coordinator, entry),
                        MeoofPendingReviewCamera(coordinator, entry),
                        MeoofLatestEatingCamera(coordinator, entry),
                        *(MeoofProfileSampleCamera(coordinator, entry, index)
                          for index in range(10))])


class MeoofCamera(MeoofEntity, Camera):
    _attr_name = "实时监控"
    _attr_icon = "mdi:cctv"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, entry):
        MeoofEntity.__init__(self, coordinator, entry)
        Camera.__init__(self)
        self._attr_unique_id = entry.entry_id + "-camera"

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get("status", {}).get("camera_live", True))

    async def async_camera_image(self, width=None, height=None):
        return await self.coordinator.client.camera_image()

    async def handle_async_mjpeg_stream(self, request):
        await self.coordinator.client.acquire_camera()
        response = web.StreamResponse(headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache",
        })
        await response.prepare(request)
        sequence = -1
        try:
            while True:
                frame, sequence = await self.coordinator.client.wait_camera_frame(sequence, 15)
                if frame:
                    await response.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        except (ConnectionError, asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            await self.coordinator.client.release_camera()
        return response


class MeoofPendingReviewCamera(MeoofEntity, Camera):
    _attr_name = "最新待分类截图"
    _attr_icon = "mdi:cat"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, entry):
        MeoofEntity.__init__(self, coordinator, entry)
        Camera.__init__(self)
        self._attr_unique_id = entry.entry_id + "-pending-review-camera"

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get("cats", {}).get("pending_review"))

    @property
    def extra_state_attributes(self):
        pending = (self.coordinator.data or {}).get("cats", {}).get("pending_review", [])
        latest = pending[-1] if pending else {}
        return {"pending_count": len(pending),
                "event_id": latest.get("event_id"),
                "event_time": latest.get("time")}

    async def async_camera_image(self, width=None, height=None):
        return await self.coordinator.client.pending_review_image()


class MeoofLatestEatingCamera(MeoofEntity, Camera):
    _attr_name = "最近进食截图"
    _attr_icon = "mdi:cat"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, entry):
        MeoofEntity.__init__(self, coordinator, entry)
        Camera.__init__(self)
        self._attr_unique_id = entry.entry_id + "-latest-eating-camera"

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get("cats", {}).get("latest"))

    @property
    def extra_state_attributes(self):
        latest = (self.coordinator.data or {}).get("cats", {}).get("latest") or {}
        return {"cat": latest.get("cat"), "event_time": latest.get("time"),
                "meoof_card_role": "latest_eating_camera"}

    async def async_camera_image(self, width=None, height=None):
        return await self.coordinator.client.latest_eating_image()


class MeoofProfileSampleCamera(MeoofEntity, Camera):
    _attr_icon = "mdi:image-multiple"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, entry, index):
        MeoofEntity.__init__(self, coordinator, entry)
        Camera.__init__(self)
        self._index = index
        self._attr_name = f"档案样本 {index + 1}"
        self._attr_unique_id = f"{entry.entry_id}-profile-sample-{index + 1}"

    @property
    def is_on(self):
        profiles = (self.coordinator.data or {}).get("cats", {}).get("profiles", {})
        return profiles.get(self.coordinator.client.cat_name, 0) > self._index

    @property
    def extra_state_attributes(self):
        return {"cat": self.coordinator.client.cat_name,
                "sample_number": self._index + 1}

    async def async_camera_image(self, width=None, height=None):
        return await self.coordinator.client.profile_sample_image(self._index)
