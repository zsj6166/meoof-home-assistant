from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN


class MeoofCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, client) -> None:
        super().__init__(hass, logger=__import__("logging").getLogger(__name__),
                         name=DOMAIN, update_interval=timedelta(seconds=30))
        self.client = client
        self.left_portions = 1
        self.right_portions = 0

    async def async_feed(self) -> None:
        await self.client.feed(self.left_portions)

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.status()
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            raise UpdateFailed(str(exc)) from exc
