from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components.frontend import add_extra_js_url
from aiohttp import web
import asyncio
import pathlib
import base64
import io
from PIL import Image

from .const import DOMAIN, PLATFORMS
from .coordinator import MeoofCoordinator
from .runtime_client import MeoofRuntimeClient


FRONTEND_URL = "/meoof_static/meoof-card.js?v=1.0.0-rc.1-2"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register bundled Lovelace cards before config entries start refreshing."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    frontend_path = pathlib.Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths([
        StaticPathConfig("/meoof_static", str(frontend_path), False)
    ])
    add_extra_js_url(hass, FRONTEND_URL)
    domain_data["frontend_registered"] = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration-level resources before config entry setup can block."""
    await _async_register_frontend(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class MeoofEatingSnapshotView(HomeAssistantView):
    """Serve archived eating snapshots to authenticated HA users."""

    url = "/api/meoof/eating_snapshot/{filename}"
    name = "api:meoof:eating_snapshot"
    requires_auth = False

    async def get(self, request, filename):
        if pathlib.Path(filename).name != filename or not filename.lower().endswith(".jpg"):
            raise web.HTTPNotFound()
        hass = request.app["hass"]
        for coordinator in hass.data.get(DOMAIN, {}).values():
            client = getattr(coordinator, "client", None)
            profiles = getattr(client, "cat_profiles", None)
            if profiles is None:
                continue
            if not profiles.valid_snapshot_token(filename, request.query.get("token")):
                continue
            if not any(event.get("snapshot") == filename
                       for event in profiles.data.get("events", [])):
                continue
            path = profiles.root / "snapshots" / filename
            try:
                image = await asyncio.to_thread(path.read_bytes)
            except OSError:
                raise web.HTTPNotFound() from None
            return web.Response(body=image, content_type="image/jpeg",
                                headers={"Cache-Control": "private, max-age=3600"})
        raise web.HTTPNotFound()


def _coordinator(hass):
    return next((value for value in hass.data.get(DOMAIN, {}).values()
                 if getattr(value, "client", None)), None)


class MeoofProfileImageView(HomeAssistantView):
    url = "/api/meoof/profile_image/{name}/{filename}"
    name = "api:meoof:profile_image"
    requires_auth = False

    async def get(self, request, name, filename):
        coordinator = _coordinator(request.app["hass"])
        if coordinator is None:
            raise web.HTTPNotFound()
        if not coordinator.client.cat_profiles.valid_profile_token(
                name, filename, request.query.get("token")):
            raise web.HTTPNotFound()
        image = await asyncio.to_thread(
            coordinator.client.cat_profiles.profile_image, name, filename)
        if image is None:
            raise web.HTTPNotFound()
        return web.Response(body=image, content_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=300"})


class MeoofSmartFeedSnapshotView(HomeAssistantView):
    """Serve signed smart-feed snapshots without exposing /config/www."""

    url = "/api/meoof/smart_feed_snapshot/{filename}"
    name = "api:meoof:smart_feed_snapshot"
    requires_auth = False

    async def get(self, request, filename):
        if pathlib.Path(filename).name != filename or not filename.lower().endswith(".jpg"):
            raise web.HTTPNotFound()
        hass = request.app["hass"]
        for coordinator in hass.data.get(DOMAIN, {}).values():
            client = getattr(coordinator, "client", None)
            if client is None or not client.cat_profiles.valid_smart_feed_snapshot_token(
                    filename, request.query.get("token")):
                continue
            if not any(record.get("snapshot_file") == filename
                       for record in client._smart_feed_state.get("records", [])):
                continue
            try:
                image = await asyncio.to_thread(
                    (client._smart_feed_snapshot_dir / filename).read_bytes)
            except OSError:
                raise web.HTTPNotFound() from None
            return web.Response(body=image, content_type="image/jpeg",
                                headers={"Cache-Control": "private, max-age=300"})
        raise web.HTTPNotFound()


class MeoofManageView(HomeAssistantView):
    url = "/api/meoof/manage"
    name = "api:meoof:manage"
    requires_auth = True

    async def get(self, request):
        coordinator = _coordinator(request.app["hass"])
        if coordinator is None:
            raise web.HTTPServiceUnavailable()
        data = await asyncio.to_thread(coordinator.client.cat_profiles.manage_data)
        return self.json(data)

    async def post(self, request):
        coordinator = _coordinator(request.app["hass"])
        if coordinator is None:
            raise web.HTTPServiceUnavailable()
        body = await request.json()
        action = body.get("action")
        profiles = coordinator.client.cat_profiles
        try:
            if action == "reclassify":
                await asyncio.to_thread(profiles.reclassify_event,
                                        body["snapshot"], body["cat"],
                                        bool(body.get("learn")))
            elif action == "delete_event":
                await asyncio.to_thread(profiles.delete_event, body["snapshot"])
            elif action == "delete_sample":
                await asyncio.to_thread(profiles.delete_profile_sample,
                                        body["cat"], body["filename"])
            elif action == "upload_sample":
                raw = body["image"].split(",", 1)[-1]
                image_bytes = base64.b64decode(raw, validate=True)
                with Image.open(io.BytesIO(image_bytes)) as image:
                    image.thumbnail((1600, 1600))
                    image = image.convert("RGB")
                    output = io.BytesIO()
                    image.save(output, "JPEG", quality=90)
                await asyncio.to_thread(profiles.add_profile_sample,
                                        body["cat"], output.getvalue())
            else:
                raise ValueError("unknown action")
        except (KeyError, ValueError, OSError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        await coordinator.async_request_refresh()
        return self.json({"ok": True})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    # Keep this idempotent fallback for config-entry reloads and test harnesses
    # that call async_setup_entry directly without running async_setup first.
    await _async_register_frontend(hass)
    if not domain_data.get("snapshot_view_registered"):
        hass.http.register_view(MeoofEatingSnapshotView)
        hass.http.register_view(MeoofProfileImageView)
        hass.http.register_view(MeoofSmartFeedSnapshotView)
        hass.http.register_view(MeoofManageView)
        domain_data["snapshot_view_registered"] = True
    coordinator = MeoofCoordinator(hass, MeoofRuntimeClient(hass, entry))
    await asyncio.to_thread(coordinator.client.cat_profiles.load)
    await coordinator.async_config_entry_first_refresh()
    domain_data[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.client.start_event_monitor(coordinator.async_request_refresh)
    await coordinator.client.start_smart_feed_monitor()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.data[DOMAIN][entry.entry_id].client.stop_camera()
        await hass.data[DOMAIN][entry.entry_id].client.stop_event_monitor()
        await hass.data[DOMAIN][entry.entry_id].client.stop_smart_feed_monitor()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
