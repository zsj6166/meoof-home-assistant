import voluptuous as vol
import io

from homeassistant import config_entries
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.helpers import selector
from PIL import Image

from . import cloud_auth
from .const import DOMAIN


class LoginFlowMixin:
    async def _request_code(self, userid):
        return await self.hass.async_add_executor_job(cloud_auth.request_code, userid, 0)

    async def _login(self, userid, code):
        login = await self.hass.async_add_executor_job(cloud_auth.login_with_code, userid, code, 0)
        if not login["devices"]:
            raise LookupError("no_devices")
        path = self.hass.config.path("meoof-device-secrets.json")
        await self.hass.async_add_executor_job(cloud_auth.save_login, path, login)
        return login


class MeoofConfigFlow(LoginFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._userid = ""

    @staticmethod
    def async_get_options_flow(config_entry):
        return MeoofOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._userid = user_input["userid"].replace(" ", "")
            try:
                await self._request_code(self._userid)
                return await self.async_step_code()
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user",
            data_schema=vol.Schema({vol.Required("userid"): str}), errors=errors)

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._login(self._userid, user_input["code"])
                await self.async_set_unique_id("meoof-" + self._userid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="觅凹自动喂食器", data={})
            except LookupError:
                errors["base"] = "no_devices"
            except Exception:
                errors["base"] = "invalid_auth"
        return self.async_show_form(step_id="code",
            data_schema=vol.Schema({vol.Required("code"): str}), errors=errors)


class MeoofOptionsFlow(LoginFlowMixin, config_entries.OptionsFlow):
    def __init__(self, entry):
        self.entry = entry
        self._userid = ""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=[
            "cat_profile", "delete_cat_profile", "recognition", "smart_feed", "reauth"])

    def _profile_manager(self):
        from .const import DOMAIN
        return self.hass.data[DOMAIN][self.entry.entry_id].client.cat_profiles

    def _current_options(self):
        entry = self.hass.config_entries.async_get_entry(self.entry.entry_id)
        return dict(entry.options if entry else self.entry.options)

    def _process_cat_upload(self, upload_id):
        with process_uploaded_file(self.hass, upload_id) as path:
            with Image.open(path) as image:
                image.thumbnail((1600, 1600))
                if image.mode != "RGB":
                    image = image.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                return output.getvalue()

    async def async_step_cat_profile(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                jpeg = await self.hass.async_add_executor_job(
                    self._process_cat_upload, user_input["image"])
                await self.hass.async_add_executor_job(
                    self._profile_manager().add_profile_sample,
                    user_input["name"], jpeg)
                coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
                await coordinator.async_request_refresh()
                return self.async_create_entry(title="", data=self._current_options())
            except Exception:
                errors["base"] = "invalid_image"
        return self.async_show_form(step_id="cat_profile", data_schema=vol.Schema({
            vol.Required("name"): str,
            vol.Required("image"): selector.FileSelector(
                selector.FileSelectorConfig(accept="image/jpeg,image/png,image/webp")),
        }), errors=errors)

    async def async_step_delete_cat_profile(self, user_input=None):
        profiles = self._profile_manager().data.get("profiles", {})
        if user_input is not None:
            await self.hass.async_add_executor_job(
                self._profile_manager().delete_profile, user_input["name"])
            coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
            await coordinator.async_request_refresh()
            return self.async_create_entry(title="", data=self._current_options())
        if not profiles:
            return self.async_abort(reason="no_cat_profiles")
        return self.async_show_form(step_id="delete_cat_profile", data_schema=vol.Schema({
            vol.Required("name"): vol.In(sorted(profiles)),
        }))

    async def async_step_recognition(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=self._current_options() | user_input)
        current = self._current_options()
        return self.async_show_form(step_id="recognition", data_schema=vol.Schema({
            vol.Required("recognition_enabled", default=current.get("recognition_enabled", False)): bool,
            vol.Optional("recognition_url", default=current.get("recognition_url", "")): str,
            vol.Optional("recognition_api_key", default=current.get("recognition_api_key", "")):
                selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Optional("recognition_model", default=current.get("recognition_model", "gpt-4.1-mini")): str,
            vol.Optional("recognition_prompt", default=current.get("recognition_prompt", "")): str,
        }))

    async def async_step_smart_feed(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=self._current_options() | user_input)
        current = self._current_options()
        return self.async_show_form(step_id="smart_feed", data_schema=vol.Schema({
            vol.Required("smart_feed_enabled",
                         default=current.get("smart_feed_enabled", False)): bool,
            vol.Required("smart_feed_lead_minutes",
                         default=current.get("smart_feed_lead_minutes", 5)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required("smart_feed_confidence",
                         default=current.get("smart_feed_confidence", 0.8)):
                vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
            vol.Optional("smart_feed_notify_service",
                         default=current.get("smart_feed_notify_service", "")): str,
            vol.Optional("smart_feed_prompt",
                         default=current.get("smart_feed_prompt", "")): str,
        }))

    async def async_step_reauth(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._userid = user_input["userid"].replace(" ", "")
            try:
                await self._request_code(self._userid)
                return await self.async_step_code()
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="reauth",
            data_schema=vol.Schema({vol.Required("userid"): str}), errors=errors)

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._login(self._userid, user_input["code"])
                coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
                coordinator.client.invalidate_history()
                await coordinator.async_request_refresh()
                return self.async_create_entry(title="", data=self._current_options())
            except LookupError:
                errors["base"] = "no_devices"
            except Exception:
                errors["base"] = "invalid_auth"
        return self.async_show_form(step_id="code",
            data_schema=vol.Schema({vol.Required("code"): str}), errors=errors)
