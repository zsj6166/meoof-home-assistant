import asyncio
import base64
import collections
import json
import os
import pathlib
import platform
import re
import shutil
import tempfile
import time
import urllib.request
import logging
import uuid
from datetime import datetime, timedelta
from http import HTTPMethod

from . import cloud_auth
from .cat_profiles import CatProfiles
from .feed_plan import parse_feed_plan_response

_LOGGER = logging.getLogger(__name__)


FIELDS = re.compile(r"^([a-z_]+)=(.*)$")


class SmartFeedCheckError(RuntimeError):
    """A user-safe smart-feed failure with a machine-readable stage."""

    def __init__(self, stage, user_message, detail="", error_name=None):
        super().__init__(user_message)
        self.stage = stage
        self.detail = detail or user_message
        self.error_name = error_name or type(self).__name__


class MeoofRuntimeClient:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.base = pathlib.Path(__file__).resolve().parent
        self.runtime = self.base / "runtime"
        machine = platform.machine().lower()
        runtime_arch = {"x86_64": "amd64", "amd64": "amd64",
                        "aarch64": "arm64", "arm64": "arm64",
                        "armv7l": "arm"}.get(machine, machine)
        self.bundled_open_runtime = (self.runtime / "open" /
                                     f"meoof-open-runtime-linux-{runtime_arch}")
        self.open_runtime = (pathlib.Path(tempfile.gettempdir()) /
                             f"meoof-open-runtime-linux-{runtime_arch}")
        self._open_runtime_ready = False
        self._open_runtime_lock = asyncio.Lock()
        self._open_host = None
        self.secrets_path = pathlib.Path(hass.config.path("meoof-device-secrets.json"))
        self._camera_lock = asyncio.Lock()
        self._camera_active = False
        self._camera_process = None
        self._ffmpeg_process = None
        self._camera_reader_task = None
        self._camera_frame = None
        self._camera_sequence = 0
        self._camera_condition = asyncio.Condition()
        self._camera_users = 0
        self._camera_idle_task = None
        self._camera_stderr = {
            "runtime": collections.deque(maxlen=20),
            "ffmpeg": collections.deque(maxlen=20),
        }
        self._camera_stderr_tasks = []
        self._history = None
        self._history_expires = 0.0
        self._foraging = None
        self._foraging_expires = 0.0
        self._petkit_sync_expires = 0.0
        self._petkit_litter_history_expires = 0.0
        self._petkit_litter_history = {}
        self._petkit_litter_backfilled = False
        self._last_eat_trigger = 0.0
        self._recording_jobs = {}
        self._recording_state = {}
        self._recording_lock = asyncio.Lock()
        self.cat_profiles = CatProfiles(hass)
        self.cat_name = ""
        self._event_process = None
        self._event_task = None
        self._event_callback = None
        self._event_status_fields = None
        self._event_status_time = 0.0
        self._feed_plan = None
        self._feed_plan_expires = 0.0
        self._smart_feed_task = None
        self._smart_feed_attempts = {}
        self._smart_feed_path = pathlib.Path(
            hass.config.path(".storage", "meoof-smart-feed.json"))
        self._smart_feed_snapshot_dir = pathlib.Path(
            hass.config.path(".meoof-smart-feed"))
        self._smart_feed_state = {"processed": {}, "records": []}

    def _device(self):
        return json.loads(self.secrets_path.read_text(encoding="utf-8"))["devices"][0]

    def _prepare_open_runtime(self):
        if not self.bundled_open_runtime.is_file():
            return False
        # /config is commonly mounted noexec. Refresh the executable copy once
        # per integration load so same-sized runtime upgrades are not missed.
        # Replace atomically because another config entry may still be running
        # the previous inode; truncating a live executable raises ETXTBSY.
        temporary = self.open_runtime.with_name(
            f".{self.open_runtime.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(self.bundled_open_runtime, temporary)
            temporary.chmod(0o700)
            temporary.replace(self.open_runtime)
        finally:
            temporary.unlink(missing_ok=True)
        return True

    async def _ensure_open_runtime(self):
        if self._open_runtime_ready:
            return
        async with self._open_runtime_lock:
            if self._open_runtime_ready:
                return
            try:
                self._open_runtime_ready = await asyncio.to_thread(
                    self._prepare_open_runtime)
            except OSError as exc:
                _LOGGER.warning("Unable to prepare open Meoof runtime: %s (errno=%s)",
                                type(exc).__name__, exc.errno)

    def _command(self, *args):
        if not self._open_runtime_ready:
            raise RuntimeError(
                f"Open Meoof runtime is unavailable for {platform.machine()}")
        return [str(self.open_runtime), *map(str, args)]

    def _environment(self, device):
        environment = os.environ | {"MEOOF_UID": device["uid"],
            "MEOOF_ACCOUNT": device.get("account", "admin"),
            "MEOOF_PASSWORD": device["password"]}
        host = self._open_host or device.get("host")
        if host:
            environment["MEOOF_HOST"] = str(host)
        return environment

    async def _run(self, *args, timeout=50):
        await self._ensure_open_runtime()
        device = await asyncio.to_thread(self._device)
        process = await asyncio.create_subprocess_exec(
            *self._command(*args), cwd=self.runtime, env=self._environment(device),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        fields = {}
        for line in stdout.decode(errors="replace").splitlines():
            match = FIELDS.match(line)
            if match:
                fields[match.group(1)] = match.group(2)
        if fields.get("resolved_host"):
            self._open_host = fields["resolved_host"]
        if process.returncode:
            raise RuntimeError(f"Meoof runtime exited with {process.returncode}")
        return fields

    async def status(self):
        if time.monotonic() >= self._petkit_sync_expires:
            synced = await self._sync_petkit_profiles()
            self._petkit_sync_expires = time.monotonic() + (3600 if synced else 30)
        await self._sync_petkit_litter_events()
        if (self._event_status_fields and
                (self._camera_active or
                 time.monotonic() - self._event_status_time < 45)):
            fields = dict(self._event_status_fields)
        else:
            fields = await self._run()
        raw = fields.get("status_response_type", "")
        match = re.search(r"data=([0-9a-fA-F]{16})", raw)
        result = {"ok": True, "probe": fields}
        if not match:
            return result
        data = bytes.fromhex(match.group(1))
        one = int.from_bytes(data[:4], "little")
        two = int.from_bytes(data[4:8], "little")
        result["status"] = {
            "word_one": one, "word_two": two,
            "powered": not bool(two & 0x2), "food_blocked": bool(two & 0x40),
            "child_lock": bool(two & 0x100), "left_bin_food": bool(two & 0x800),
            "right_bin_food": bool(two & 0x1000), "voice_enabled": bool(two & 0x2000),
            "led_enabled": bool(two & 0x8000), "battery": (two >> 16) & 0xff,
            "camera_live": not bool(two & 0x01000000),
            "eat_detection": {0: "off", 1: "low", 2: "middle", 3: "high"}[(two >> 26) & 3],
            "power_save": bool(two & 0x10000000), "feed_voice": bool(two & 0x20000000),
        }
        if time.monotonic() >= self._history_expires:
            try:
                login = await asyncio.to_thread(
                    lambda: json.loads(self.secrets_path.read_text(encoding="utf-8")))
                fresh = await asyncio.to_thread(
                    cloud_auth.feed_history, login, 30 if self._history is None else 2, 100)
                self._history = self._merge_cloud_history(self._history, fresh)
            except RuntimeError as exc:
                self._history = {"ok": False, "reauth_required": "reauthentication" in str(exc)}
            except (OSError, ValueError):
                self._history = {"ok": False}
            self._history_expires = time.monotonic() + 30
        result["history"] = self._history
        if time.monotonic() >= self._foraging_expires:
            try:
                login = await asyncio.to_thread(
                    lambda: json.loads(self.secrets_path.read_text(encoding="utf-8")))
                fresh = await asyncio.to_thread(
                    cloud_auth.foraging_history, login,
                    7 if self._foraging is None else 2, 100)
                self._foraging = self._merge_cloud_history(self._foraging, fresh)
                self._observe_foraging_history(self._foraging)
            except RuntimeError as exc:
                self._foraging = {"ok": False, "reauth_required": "reauthentication" in str(exc)}
            except (OSError, ValueError):
                self._foraging = {"ok": False}
            self._foraging_expires = time.monotonic() + 30
        result["foraging"] = self._foraging
        result["recordings"] = self._recording_state
        if time.monotonic() >= self._feed_plan_expires:
            try:
                await self.feed_plan()
            except (OSError, RuntimeError, TimeoutError, ValueError,
                    asyncio.TimeoutError) as exc:
                _LOGGER.debug("Unable to refresh feed plan: %s", type(exc).__name__)
            self._feed_plan_expires = time.monotonic() + 300
        result["feed_plan"] = self._feed_plan or {"ok": False, "days": []}
        result["smart_feed"] = {
            "enabled": bool(self.entry.options.get("smart_feed_enabled", False)),
            "records": list(self._smart_feed_state.get("records", []))[-50:],
            "latest": (self._smart_feed_state.get("records", []) or [None])[-1],
        }
        result["cats"] = {
            "profiles": self.cat_profiles.profiles,
            "latest": self.cat_profiles.latest_valid_event(),
            "pending_review": self.cat_profiles.pending_events(),
            "day": self.cat_profiles.summary("day"),
            "week": self.cat_profiles.summary("week"),
            "month": self.cat_profiles.summary("month"),
            "litter_day": self.cat_profiles.litter_summary("day"),
            "litter_week": self.cat_profiles.litter_summary("week"),
            "litter_month": self.cat_profiles.litter_summary("month"),
            "litter_latest_by_cat": self.cat_profiles.latest_litter_by_cat(),
        }
        return result

    @staticmethod
    def _merge_cloud_history(previous, fresh):
        records = {}
        for payload in (previous or {}, fresh or {}):
            for record in payload.get("records", []):
                records[str(record.get("id") or (record.get("evt"), len(records)))] = record
        values = sorted(records.values(), key=lambda item: int(item.get("evt", 0) or 0), reverse=True)
        return {**fresh, "records": values, "count": len(values)}

    async def _sync_petkit_litter_events(self):
        """Archive every raw Petkit litter event instead of only its latest state."""
        records = []
        for entry in self.hass.config_entries.async_entries("petkit"):
            runtime_data = getattr(entry, "runtime_data", None)
            client = getattr(runtime_data, "client", None)
            entities = list(getattr(client, "petkit_entities", {}).values())
            pets = {getattr(item, "pet_id", None): getattr(item, "name", None)
                    for item in entities if type(item).__name__ == "Pet"}
            for litter in (item for item in entities if type(item).__name__ == "Litter"):
                litter_records = list(getattr(litter, "device_records", None) or [])
                litter_records.extend(await self._petkit_litter_backfill(client, litter))
                seen = set()
                for record in litter_records:
                    content = getattr(record, "content", None)
                    timestamp = int(getattr(record, "timestamp", 0) or 0)
                    if not timestamp:
                        continue
                    record_key = (str(getattr(record, "event_id", "")), timestamp)
                    if record_key in seen:
                        continue
                    seen.add(record_key)
                    weight_g = int(getattr(content, "pet_weight", 0) or 0)
                    cat = (getattr(record, "pet_name", None)
                           or pets.get(getattr(record, "pet_id", None)))
                    inferred = bool(getattr(record, "weight_inferred", False))
                    # Weight-only identity thresholds are household-specific and
                    # must never be guessed in the reusable integration.
                    time_in = int(getattr(content, "time_in", 0) or 0)
                    time_out = int(getattr(content, "time_out", 0) or 0)
                    duration = max(0, time_out - time_in) or int(
                        getattr(record, "duration", 0) or 0)
                    event_id = (getattr(record, "event_id", None)
                                or f"{getattr(litter, 'id', 'litter')}-{timestamp}")
                    records.append({
                        "event_id": str(event_id), "timestamp": timestamp,
                        "time": datetime.fromtimestamp(timestamp).astimezone().isoformat(),
                        "cat": cat or "未知猫咪", "duration": duration,
                        "weight": round(weight_g / 1000, 2) if weight_g else None,
                        "inferred": inferred,
                    })
        if records:
            await asyncio.to_thread(self.cat_profiles.merge_litter_events, records)

    async def _petkit_litter_backfill(self, client, litter):
        """Fetch missed T3/T4 days because pypetkitapi normally requests today only."""
        now = time.monotonic()
        device = getattr(litter, "device_nfo", None)
        if device is None or now < self._petkit_litter_history_expires:
            return list(self._petkit_litter_history.get(getattr(litter, "id", None), []))
        try:
            from pypetkitapi import LitterRecord
            device_type = getattr(device, "device_type", "")
            probe = LitterRecord.query_param(device, litter)
            if not ({"day", "date"} & set(probe)):
                return []
            days = 30 if not self._petkit_litter_backfilled else 2
            fetched = []
            for offset in range(days):
                request_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                response = await client.req.request(
                    method=HTTPMethod.POST,
                    url=f"{device_type}/{LitterRecord.get_endpoint(device_type)}",
                    params=LitterRecord.query_param(
                        device, litter, request_date=request_date),
                    headers=await client.get_session_id(),
                )
                if isinstance(response, dict):
                    response = response.get("list", [])
                if isinstance(response, list):
                    fetched.extend(LitterRecord(**item) for item in response)
            self._petkit_litter_history[getattr(litter, "id", None)] = fetched
            self._petkit_litter_backfilled = True
            self._petkit_litter_history_expires = now + 3600
            return fetched
        except Exception as exc:
            _LOGGER.warning("Unable to backfill Petkit litter history: %s",
                            type(exc).__name__)
            self._petkit_litter_history_expires = now + 300
            return list(self._petkit_litter_history.get(getattr(litter, "id", None), []))

    async def _sync_petkit_profiles(self):
        """Use Petkit pet avatars as Meoof recognition reference samples."""
        candidates = {}
        for state in self.hass.states.async_all("number"):
            picture = state.attributes.get("entity_picture")
            friendly_name = str(state.attributes.get("friendly_name", ""))
            if (state.entity_id.endswith("_weight") and picture
                    and "petkit" in str(picture).lower() and " " in friendly_name):
                candidates[friendly_name.rsplit(" ", 1)[0]] = str(picture)
        def download_avatar(url):
            request = urllib.request.Request(url, headers={"User-Agent": "Home Assistant"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(5 * 1024 * 1024 + 1)
            if not data or len(data) > 5 * 1024 * 1024:
                raise ValueError("invalid Petkit avatar size")
            return data

        items = list(candidates.items())
        downloads = await asyncio.gather(
            *(asyncio.to_thread(download_avatar, url) for _, url in items),
            return_exceptions=True)
        for (name, url), avatar in zip(items, downloads):
            try:
                if isinstance(avatar, BaseException):
                    raise avatar
                await asyncio.to_thread(
                    self.cat_profiles.import_external_profile, name, avatar, url)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                _LOGGER.warning("Unable to sync Petkit profile %s: %s",
                                name, type(exc).__name__)
        return len(candidates)

    async def feed(self, portions):
        return await self._run("feed", int(portions), 0)

    async def feed_plan(self):
        fields = await self._run("feed-plan")
        self._feed_plan = parse_feed_plan_response(
            fields.get("feed_plan_response_type", ""))
        self._feed_plan_expires = time.monotonic() + 300
        return self._feed_plan

    async def set_today_plan_status(self, item, enabled):
        fields = await self._run(
            "today-status", item["index"], int(enabled), item["hour"],
            item["minute"], timeout=70)
        if fields.get("feed_plan_verified") != "1":
            raise RuntimeError("device did not verify the feed plan update")
        return await self.feed_plan()

    def _load_smart_feed_state(self):
        try:
            state = json.loads(self._smart_feed_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                self._smart_feed_state = {
                    "processed": dict(state.get("processed", {})),
                    "records": list(state.get("records", []))[-200:],
                }
                migrated = False
                self._smart_feed_snapshot_dir.mkdir(parents=True, exist_ok=True)
                legacy_dir = pathlib.Path(
                    self.hass.config.path("www", "meoof-smart-feed"))
                for record in self._smart_feed_state["records"]:
                    filename = record.get("snapshot_file")
                    snapshot = str(record.get("snapshot", ""))
                    if not filename and snapshot.startswith("/local/meoof-smart-feed/"):
                        filename = pathlib.Path(snapshot.split("?", 1)[0]).name
                    if not filename or pathlib.Path(filename).name != filename:
                        continue
                    source = legacy_dir / filename
                    destination = self._smart_feed_snapshot_dir / filename
                    if source.is_file() and not destination.exists():
                        try:
                            source.replace(destination)
                        except OSError:
                            _LOGGER.warning("Unable to migrate a legacy smart-feed snapshot")
                    if not destination.is_file():
                        continue
                    signed_url = self.cat_profiles.smart_feed_snapshot_url(filename)
                    if (record.get("snapshot_file") != filename or
                            record.get("snapshot") != signed_url):
                        record["snapshot_file"] = filename
                        record["snapshot"] = signed_url
                        migrated = True
                if migrated:
                    self._save_smart_feed_state()
        except (OSError, ValueError, TypeError):
            self._smart_feed_state = {"processed": {}, "records": []}

    def _save_smart_feed_state(self):
        self._smart_feed_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._smart_feed_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._smart_feed_state,
                                         ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(self._smart_feed_path)

    def _recognize_food_level(self, jpeg):
        options = self._recognition_options()
        if not options.get("recognition_url") or not options.get("recognition_api_key"):
            raise RuntimeError("vision API is not configured")
        prompt = options.get("smart_feed_prompt") or (
            "判断自动喂食器碗中剩余猫粮的量。只输出 JSON，字段为 "
            "food_level、confidence、reason。food_level 只能是 empty、some、many；"
            "只有碗中已有较多猫粮、继续出粮明显没有必要时才选择 many。")
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url":
                "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
        ]
        payload = json.dumps({
            "model": options.get("recognition_model", "gpt-4.1-mini"),
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode()
        url = options["recognition_url"].rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        request = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + options["recognition_api_key"],
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
        text = result["choices"][0]["message"]["content"]
        parsed = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        level = str(parsed.get("food_level", "")).lower()
        if level not in {"empty", "some", "many"}:
            raise ValueError("vision API returned an invalid food_level")
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0))))
        return level, confidence, str(parsed.get("reason", ""))

    def _camera_failure_detail(self, timeout):
        details = []
        for source in ("runtime", "ffmpeg"):
            lines = list(self._camera_stderr[source])[-3:]
            if lines:
                details.append(f"{source}: {' | '.join(lines)}")
        return ("; ".join(details)[:1200] if details else
                f"camera pipeline produced no JPEG frame within {timeout} seconds")

    async def _capture_smart_feed_frame(self, timeout=25):
        """Capture a fresh frame, rebuilding a stalled camera pipeline once."""
        for attempt in (1, 2):
            acquired = False
            try:
                await self.acquire_camera()
                acquired = True
                previous = self._camera_sequence
                frame, _ = await self._wait_smart_feed_camera_frame(
                    previous, timeout)
                if not frame:
                    raise SmartFeedCheckError(
                        "camera_frame", "摄像头没有返回画面",
                        self._camera_failure_detail(timeout), "CameraFrameError")
                return frame, attempt
            except asyncio.TimeoutError as exc:
                detail = self._camera_failure_detail(timeout)
                if attempt == 2:
                    raise SmartFeedCheckError(
                        "camera_frame_timeout",
                        f"摄像头连续两次未在 {timeout} 秒内返回画面",
                        detail, "TimeoutError") from exc
                _LOGGER.warning(
                    "Smart-feed camera frame timed out; rebuilding the camera pipeline: %s",
                    detail)
            except SmartFeedCheckError:
                raise
            except (OSError, RuntimeError) as exc:
                detail = str(exc).strip() or type(exc).__name__
                if attempt == 2:
                    raise SmartFeedCheckError(
                        "camera_start", "摄像头视频会话启动失败",
                        detail[:1200], type(exc).__name__) from exc
                _LOGGER.warning(
                    "Smart-feed camera start failed; rebuilding the camera pipeline: %s",
                    detail[:1200])
            finally:
                if acquired:
                    await self.release_camera()
            if self._camera_users == 0:
                await self.stop_camera()
            await asyncio.sleep(1)

        raise SmartFeedCheckError("camera", "摄像头取帧失败")

    async def _wait_smart_feed_camera_frame(self, sequence, timeout):
        """Get a frame, flushing Egg Roll's short idle-camera burst if needed."""
        # The sleeping feeder can take roughly 15 seconds to deliver the IDR.
        burst_timeout = min(timeout, 20)
        try:
            return await self.wait_camera_frame(sequence, timeout=burst_timeout)
        except asyncio.TimeoutError:
            if not await self._finish_camera_writer():
                raise
        remaining = max(2, timeout - burst_timeout)
        async with self._camera_condition:
            if self._camera_sequence == sequence or self._camera_frame is None:
                await asyncio.wait_for(
                    self._camera_condition.wait(), min(remaining, 5))
            return self._camera_frame, self._camera_sequence

    async def _finish_camera_writer(self):
        """Close only the H.264 writer so FFmpeg flushes its buffered IDR."""
        process = self._camera_process
        if not process or process.returncode is not None:
            return False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        self._camera_process = None
        return True

    async def _latest_recorded_smart_feed_frame(self):
        """Use the latest foraging cover when the sleeping live encoder stalls."""
        records = (self._foraging or {}).get("records", [])
        candidates = [record for record in records if int(record.get("evt", 0) or 0)]
        if not candidates:
            raise RuntimeError("no foraging recording is available")
        record = max(candidates, key=lambda item: int(item.get("evt", 0)))
        event_time = datetime.fromtimestamp(int(record["evt"])).astimezone()
        age_minutes = max(0, (datetime.now().astimezone() - event_time).total_seconds() / 60)
        if age_minutes > 24 * 60:
            raise RuntimeError("latest foraging recording is older than 24 hours")
        cover, _ = await self._recording_for_event(record)
        return cover, round(age_minutes, 1)

    async def _analyze_smart_feed_frame(self, frame):
        try:
            return await asyncio.to_thread(self._recognize_food_level, frame)
        except TimeoutError as exc:
            raise SmartFeedCheckError(
                "vision_timeout", "视觉模型在 60 秒内没有响应",
                str(exc).strip() or "vision API request timed out",
                "TimeoutError") from exc

    async def _smart_feed_observation(self, record):
        """Capture and analyze a useful bowl image with a recorded-event fallback."""
        record["stage"] = "camera"
        try:
            frame, attempts = await self._capture_smart_feed_frame()
            record.update(camera_attempts=attempts, frame_source="live_camera")
        except SmartFeedCheckError as live_error:
            await self.stop_camera()
            try:
                frame, age = await self._latest_recorded_smart_feed_frame()
            except Exception:
                raise live_error
            record.update(camera_attempts=2,
                          frame_source="latest_foraging_recording",
                          frame_age_minutes=age,
                          live_camera_error=live_error.error_name)

        record["stage"] = "vision"
        level, confidence, reason = await self._analyze_smart_feed_frame(frame)
        if record["frame_source"] == "live_camera" and confidence < 0.5:
            # A concealed Egg Roll IDR is often a flat grey image. The model's
            # low confidence is a safer quality signal than trusting its label.
            try:
                live_confidence = confidence
                await self.stop_camera()
                fallback, age = await self._latest_recorded_smart_feed_frame()
                fallback_result = await self._analyze_smart_feed_frame(fallback)
                if fallback_result[1] > confidence:
                    frame = fallback
                    level, confidence, reason = fallback_result
                    record.update(frame_source="latest_foraging_recording",
                                  frame_age_minutes=age,
                                  live_camera_confidence=live_confidence)
            except Exception as exc:
                _LOGGER.debug("Recorded smart-feed fallback unavailable: %s",
                              type(exc).__name__)
        return frame, level, confidence, reason

    async def start_smart_feed_monitor(self):
        await asyncio.to_thread(self._load_smart_feed_state)
        if self._event_callback:
            await self._event_callback()
        if not self._smart_feed_task or self._smart_feed_task.done():
            self._smart_feed_task = asyncio.create_task(self._smart_feed_loop())

    async def stop_smart_feed_monitor(self):
        if self._smart_feed_task:
            self._smart_feed_task.cancel()
            try:
                await self._smart_feed_task
            except asyncio.CancelledError:
                pass
        self._smart_feed_task = None

    async def _smart_feed_loop(self):
        while True:
            try:
                if self.entry.options.get("smart_feed_enabled", False):
                    await self._check_upcoming_feed()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.warning("Smart feed precheck failed: %s", type(exc).__name__)
            await asyncio.sleep(30)

    async def _check_upcoming_feed(self):
        now = datetime.now().astimezone()
        plan = await self.feed_plan()
        today = next((day for day in plan["days"] if day["week"] == 8), None)
        if not today or not today["enabled"]:
            return
        lead = max(1, min(30, int(self.entry.options.get("smart_feed_lead_minutes", 5))))
        for item in today["items"]:
            if not item["enabled"] or item["left"] + item["right"] <= 0:
                continue
            scheduled = now.replace(hour=item["hour"], minute=item["minute"],
                                    second=0, microsecond=0)
            seconds = (scheduled - now).total_seconds()
            if not 0 <= seconds <= lead * 60:
                continue
            key = f"{now.date().isoformat()}-{item['index']}-{item['hour']:02d}{item['minute']:02d}"
            if key in self._smart_feed_state["processed"]:
                continue
            last_attempt = self._smart_feed_attempts.get(key, 0)
            if time.monotonic() - last_attempt < 60:
                continue
            self._smart_feed_attempts[key] = time.monotonic()
            await self._perform_smart_feed_check(key, item, scheduled)

    async def _perform_smart_feed_check(self, key, item, scheduled):
        record = {
            "key": key, "checked_at": datetime.now().astimezone().isoformat(),
            "scheduled_at": scheduled.isoformat(), "index": item["index"],
            "left": item["left"], "right": item["right"], "status": "checking",
        }
        try:
            frame, level, confidence, reason = await self._smart_feed_observation(record)
            self._smart_feed_snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot = self._smart_feed_snapshot_dir / f"{key}.jpg"
            await asyncio.to_thread(snapshot.write_bytes, frame)
            record["snapshot_file"] = snapshot.name
            record["snapshot"] = self.cat_profiles.smart_feed_snapshot_url(snapshot.name)
            record.update(food_level=level, confidence=confidence, reason=reason)
            threshold = max(0.5, min(1.0, float(
                self.entry.options.get("smart_feed_confidence", 0.8))))
            if level == "many" and confidence >= threshold:
                await self.set_today_plan_status(item, False)
                record["status"] = "suppressed"
                await self._notify_suppression(record)
            else:
                record["status"] = "allowed"
            record["stage"] = "complete"
            self._smart_feed_state["processed"][key] = record["status"]
        except Exception as exc:
            # Fail open: an unavailable camera/model must never silently starve a pet.
            error_name = getattr(exc, "error_name", type(exc).__name__)
            error_stage = getattr(exc, "stage", record.get("stage", "precheck"))
            error_detail = getattr(exc, "detail", str(exc).strip()) or error_name
            record.update(status="error_allowed", error=error_name,
                          error_stage=error_stage,
                          error_detail=str(error_detail)[:1200])
            _LOGGER.warning(
                "Feed %s was allowed because precheck failed at %s: %s (%s)",
                key, error_stage, error_name, str(error_detail)[:1200])
        finally:
            records = self._smart_feed_state.setdefault("records", [])
            records.append(record)
            self._smart_feed_state["records"] = records[-200:]
            await asyncio.to_thread(self._save_smart_feed_state)
            if self._event_callback:
                await self._event_callback()

    async def _notify_suppression(self, record):
        event_data = dict(record)
        self.hass.bus.async_fire("meoof_feed_suppressed", event_data)
        title = "觅凹已取消本次出粮"
        message = (f"碗中余粮较多，已取消 {record['scheduled_at'][11:16]} 的"
                   f" {record['left'] + record['right']} 份计划。"
                   f"置信度 {record['confidence']:.0%}。{record.get('reason', '')}")
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(
            self.hass, message, title=title,
            notification_id="meoof-smart-feed-" + record["key"])
        service_name = str(self.entry.options.get("smart_feed_notify_service", "")).strip()
        if "." in service_name:
            domain, service = service_name.split(".", 1)
            data = {"title": title, "message": message}
            if record.get("snapshot"):
                data["data"] = {"image": record["snapshot"]}
            await self.hass.services.async_call(domain, service, data, blocking=False)

    async def test_smart_feed_check(self):
        """Run camera and model validation without changing any feed plan."""
        checked_at = datetime.now().astimezone()
        key = "manual-test-" + checked_at.strftime("%Y%m%d-%H%M%S")
        record = {"key": key, "checked_at": checked_at.isoformat(),
                  "status": "test_checking", "test_only": True}
        try:
            frame, level, confidence, reason = await self._smart_feed_observation(record)
            self._smart_feed_snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot = self._smart_feed_snapshot_dir / f"{key}.jpg"
            await asyncio.to_thread(snapshot.write_bytes, frame)
            record["snapshot_file"] = snapshot.name
            record["snapshot"] = self.cat_profiles.smart_feed_snapshot_url(snapshot.name)
            record.update(status="test_only", food_level=level,
                          confidence=confidence, reason=reason, stage="complete")
        except Exception as exc:
            error_name = getattr(exc, "error_name", type(exc).__name__)
            error_stage = getattr(exc, "stage", record.get("stage", "precheck"))
            error_detail = getattr(exc, "detail", str(exc).strip()) or error_name
            record.update(status="test_error", error=error_name,
                          error_stage=error_stage,
                          error_detail=str(error_detail)[:1200])
            raise
        finally:
            records = self._smart_feed_state.setdefault("records", [])
            records.append(record)
            self._smart_feed_state["records"] = records[-200:]
            await asyncio.to_thread(self._save_smart_feed_state)
            if self._event_callback:
                await self._event_callback()
        return record

    def invalidate_history(self):
        """Discard a cached cloud result after credentials are replaced."""
        self._history = None
        self._history_expires = 0.0
        self._foraging = None
        self._foraging_expires = 0.0

    def _observe_foraging_history(self, history):
        records = history.get("records", [])
        recorded = self.cat_profiles.recorded_event_ids
        for record in records:
            if str(record.get("id")) not in recorded:
                self._schedule_eat_event(record)

    def _schedule_eat_event(self, record=None):
        if record is not None:
            event_id = str(record.get("id"))
            task = self._recording_jobs.get(event_id)
            if not task or task.done():
                self._recording_jobs[event_id] = asyncio.create_task(
                    self._handle_recorded_eat_event(dict(record)))
            return
        now = time.monotonic()
        if now - self._last_eat_trigger < 60:
            return
        self._last_eat_trigger = now
        asyncio.create_task(self._handle_eat_event())

    async def _download_remote_file(self, source, destination, timeout=150):
        destination = pathlib.Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.part")
        try:
            await self._run("download", source, temporary, timeout=timeout)
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise RuntimeError("downloaded file is empty")
            temporary.replace(destination)
            return await asyncio.to_thread(destination.read_bytes)
        finally:
            temporary.unlink(missing_ok=True)

    async def _recording_for_event(self, record):
        timestamp = int(record.get("evt", 0) or 0)
        if not timestamp:
            raise ValueError("foraging event has no timestamp")
        local_time = datetime.fromtimestamp(timestamp).astimezone()
        offset = int((local_time.utcoffset().total_seconds()
                      if local_time.utcoffset() else 0))
        target = timestamp + offset
        day = local_time.strftime("%Y/%m/%d")
        cache = self.cat_profiles.root / "recording-cache"
        index_path = cache / (local_time.strftime("%Y%m%d") + "-day_idx.txt")
        index_source = f"/tmp/sdcard/video/{day}/day_idx.txt"
        try:
            raw = await self._download_remote_file(index_source, index_path)
        except (OSError, RuntimeError, TimeoutError, asyncio.TimeoutError):
            if not index_path.exists() or index_path.stat().st_size == 0:
                raise
            raw = index_path.read_bytes()
        entries = [(int(start), int(duration)) for start, duration in
                   re.findall(rb"(\d{10})_(\d{4})", raw)]
        if not entries:
            raise RuntimeError("recording index is empty")
        start, duration = min(entries, key=lambda item: abs(item[0] - target))
        if abs(start - target) > 15 * 60:
            raise RuntimeError("matching recording was not found")
        folder = f"/tmp/sdcard/video/{day}/{start}_{duration:04d}"
        cover_path = cache / f"{record.get('id')}-{start}.jpg"
        cover = await self._download_remote_file(folder + "/cover.jpg", cover_path)
        return cover, {"start": start, "duration": duration,
                       "source": folder + "/0000.mp4", "cover": cover_path.name}

    async def _handle_recorded_eat_event(self, record):
        event_id = str(record.get("id"))
        self._recording_state[event_id] = {"status": "pending"}
        async with self._recording_lock:
            last_error = None
            for attempt in range(5):
                try:
                    if attempt:
                        await asyncio.sleep(20)
                    cover, recording = await self._recording_for_event(record)
                    self._recording_state[event_id] = {"status": "recognized", **recording}
                    try:
                        identity = await asyncio.to_thread(self._recognize_external, cover)
                    except Exception as exc:
                        identity = ("未知猫咪", 0.0,
                                    f"识别接口失败: {type(exc).__name__}")
                    event_time = datetime.fromtimestamp(
                        int(record.get("evt", 0))).astimezone()
                    await asyncio.to_thread(
                        self.cat_profiles.record_event, cover, *identity,
                        event_id=event_id, event_time=event_time,
                        recording=recording)
                    if self._event_callback:
                        await self._event_callback()
                    return
                except (OSError, RuntimeError, TimeoutError, ValueError,
                        asyncio.TimeoutError) as exc:
                    last_error = type(exc).__name__
            self._recording_state[event_id] = {"status": "failed", "error": last_error}

    async def download_latest_playback(self):
        records = (self._foraging or {}).get("records", [])
        if not records:
            raise RuntimeError("没有可下载的觅食记录")
        record = records[0]
        event_id = str(record.get("id"))
        _, recording = await self._recording_for_event(record)
        destination = pathlib.Path(self.hass.config.path(
            "www", "meoof-playback", f"{event_id}.mp4"))
        await self._download_remote_file(recording["source"], destination, timeout=300)
        state = {"status": "ready", **recording,
                 "url": f"/local/meoof-playback/{event_id}.mp4",
                 "bytes": destination.stat().st_size}
        self._recording_state[event_id] = state
        return state

    async def add_cat_profile(self):
        frame = await self.camera_image()
        if not frame:
            raise RuntimeError("未能获取监控画面")
        await asyncio.to_thread(self.cat_profiles.add_profile_sample, self.cat_name, frame)

    async def delete_cat_profile(self):
        await asyncio.to_thread(self.cat_profiles.delete_profile, self.cat_name)

    async def classify_latest_pending(self):
        event = await asyncio.to_thread(
            self.cat_profiles.classify_latest_pending, self.cat_name)
        if self._event_callback:
            await self._event_callback()
        return event

    async def skip_latest_pending(self):
        event = await asyncio.to_thread(self.cat_profiles.skip_latest_pending)
        if self._event_callback:
            await self._event_callback()
        return event

    async def pending_review_image(self):
        return await asyncio.to_thread(self.cat_profiles.latest_pending_image)

    async def latest_eating_image(self):
        return await asyncio.to_thread(self.cat_profiles.latest_valid_image)

    async def profile_sample_image(self, index):
        image, _ = await asyncio.to_thread(
            self.cat_profiles.profile_sample, self.cat_name, index)
        return image

    async def profile_sample_info(self, index):
        _, filename = await asyncio.to_thread(
            self.cat_profiles.profile_sample, self.cat_name, index)
        return filename

    def _recognize_external(self, jpeg):
        options = self._recognition_options()

        if not options.get("recognition_enabled"):
            return "未知猫咪", 0.0, "外部识别未启用"
        content = [{"type": "text", "text": options.get("recognition_prompt") or
                    "根据参考照片识别当前进食的是哪只猫。只输出JSON：cat, confidence, detail。无法确定时cat写未知猫咪。"}]
        for name, image in self.cat_profiles.reference_images():
            content.extend([
                {"type": "text", "text": f"参考猫咪：{name}"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}},
            ])
        content.extend([
            {"type": "text", "text": "下面是本次进食截图："},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
        ])
        payload = json.dumps({"model": options.get("recognition_model", "gpt-4.1-mini"),
                              "messages": [{"role": "user", "content": content}],
                              "temperature": 0, "response_format": {"type": "json_object"}}).encode()
        url = options.get("recognition_url", "").rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        request = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + options.get("recognition_api_key", ""),
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
        text = result["choices"][0]["message"]["content"]
        parsed = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        name = parsed.get("cat", "未知猫咪")
        if name not in self.cat_profiles.profiles:
            name = "未知猫咪"
        return name, float(parsed.get("confidence", 0)), str(parsed.get("detail", ""))

    def _recognition_options(self):
        options = dict(self.entry.options)
        if not options.get("recognition_url") or not options.get("recognition_api_key"):
            try:
                fallback = json.loads(pathlib.Path(
                    self.hass.config.path("meoof-recognition.json")
                ).read_text(encoding="utf-8"))
                options.update({key: value for key, value in fallback.items() if value})
            except (OSError, ValueError):
                pass
        return options

    async def start_event_monitor(self, callback):
        self._event_callback = callback
        if not self._event_task or self._event_task.done():
            self._event_task = asyncio.create_task(self._event_monitor_loop())

    async def _event_monitor_loop(self):
        while True:
            try:
                if self._camera_active:
                    await asyncio.sleep(2)
                    continue
                await self._ensure_open_runtime()
                device = await asyncio.to_thread(self._device)
                self._event_process = await asyncio.create_subprocess_exec(
                    *self._command("events"), cwd=self.runtime, env=self._environment(device),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                while self._event_process.stdout:
                    line = await self._event_process.stdout.readline()
                    if not line:
                        break
                    match = FIELDS.match(line.decode(errors="replace").strip())
                    if match:
                        key, value = match.groups()
                        if key == "resolved_host":
                            self._open_host = value
                        elif key == "status_response_type":
                            self._event_status_fields = {key: value}
                            self._event_status_time = time.monotonic()
                    if line.startswith(b"event=eat "):
                        self._schedule_eat_event()
                await self._event_process.wait()
            except asyncio.CancelledError:
                return
            except (OSError, ValueError):
                pass
            await asyncio.sleep(2 if self._camera_active else 10)

    async def _pause_event_monitor_for_camera(self):
        process = self._event_process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()

    async def _handle_eat_event(self):
        try:
            await self.acquire_camera()
            frame, sequence = await self.wait_camera_frame(-1, 15)
            frame, _ = await self.wait_camera_frame(sequence, 4)
            if frame:
                try:
                    identity = await asyncio.to_thread(self._recognize_external, frame)
                except Exception as exc:
                    identity = ("未知猫咪", 0.0, f"识别接口失败: {type(exc).__name__}")
                await asyncio.to_thread(self.cat_profiles.record_event, frame, *identity)
                if self._event_callback:
                    await self._event_callback()
        except (OSError, RuntimeError, TimeoutError, ValueError, asyncio.TimeoutError):
            pass
        finally:
            await self.release_camera()

    async def stop_event_monitor(self):
        if self._event_task:
            self._event_task.cancel()
        if self._event_process and self._event_process.returncode is None:
            self._event_process.terminate()
            try:
                await asyncio.wait_for(self._event_process.wait(), 5)
            except asyncio.TimeoutError:
                self._event_process.kill()
        self._event_task = self._event_process = None

    async def camera_image(self):
        await self.start_camera()
        if self._camera_frame is None:
            await self.wait_camera_frame(-1, timeout=15)
        self._schedule_camera_stop()
        return self._camera_frame

    async def acquire_camera(self):
        self._camera_users += 1
        if self._camera_idle_task:
            self._camera_idle_task.cancel()
            self._camera_idle_task = None
        try:
            await self.start_camera()
        except Exception:
            self._camera_users = max(0, self._camera_users - 1)
            raise

    async def release_camera(self):
        self._camera_users = max(0, self._camera_users - 1)
        self._schedule_camera_stop()

    def _schedule_camera_stop(self):
        if self._camera_users or (self._camera_idle_task and not self._camera_idle_task.done()):
            return
        self._camera_idle_task = asyncio.create_task(self._stop_camera_when_idle())

    async def _stop_camera_when_idle(self):
        try:
            await asyncio.sleep(30)
            if self._camera_users == 0:
                await self.stop_camera()
        except asyncio.CancelledError:
            pass

    async def start_camera(self):
        async with self._camera_lock:
            if self._camera_process and self._camera_process.returncode is None:
                return
            await self._ensure_open_runtime()
            await self._stop_camera_unlocked()
            self._camera_active = True
            try:
                for lines in self._camera_stderr.values():
                    lines.clear()
                await self._pause_event_monitor_for_camera()
                work = pathlib.Path(self.hass.config.path(".meoof-camera"))
                await asyncio.to_thread(work.mkdir, mode=0o700, exist_ok=True)
                fifo = work / "video.h264"
                if await asyncio.to_thread(fifo.exists):
                    await asyncio.to_thread(fifo.unlink)
                await asyncio.to_thread(os.mkfifo, fifo, 0o600)
                self._ffmpeg_process = await asyncio.create_subprocess_exec(
                    *self._camera_ffmpeg_command(fifo),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                device = await asyncio.to_thread(self._device)
                self._camera_process = await asyncio.create_subprocess_exec(
                    *self._command("stream", fifo), cwd=self.runtime,
                    env=self._environment(device),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                self._camera_reader_task = asyncio.create_task(
                    self._read_camera_frames())
                self._camera_stderr_tasks = [
                    asyncio.create_task(self._read_camera_stderr(
                        self._camera_process, "runtime")),
                    asyncio.create_task(self._read_camera_stderr(
                        self._ffmpeg_process, "ffmpeg")),
                ]
            except Exception:
                await self._stop_camera_unlocked()
                raise

    @staticmethod
    def _camera_ffmpeg_command(fifo):
        # Egg Roll may end its first IDR one or two macroblocks early. FFmpeg
        # can conceal that damage, but nobuffer and an input fps filter discard
        # the only initial frame carrying SPS/PPS. Limit the output rate instead
        # and explicitly allow the recoverable frame to reach the JPEG encoder.
        return [
            "ffmpeg", "-loglevel", "error", "-err_detect", "ignore_err",
            "-flags", "+low_delay+output_corrupt", "-f", "h264", "-i",
            str(fifo), "-r", "5", "-f", "image2pipe", "-vcodec", "mjpeg",
            "-pix_fmt", "yuvj420p", "-q:v", "4", "pipe:1",
        ]

    async def _read_camera_stderr(self, process, source):
        try:
            while process and process.stderr:
                line = await process.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    self._camera_stderr[source].append(text[:500])
        except asyncio.CancelledError:
            pass

    async def _read_camera_frames(self):
        buffer = bytearray()
        try:
            while self._ffmpeg_process and self._ffmpeg_process.stdout:
                chunk = await self._ffmpeg_process.stdout.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start < 0 or end < 0:
                        if start > 0:
                            del buffer[:start]
                        break
                    frame = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    async with self._camera_condition:
                        self._camera_frame = frame
                        self._camera_sequence += 1
                        self._camera_condition.notify_all()
        except asyncio.CancelledError:
            pass

    async def wait_camera_frame(self, sequence, timeout=10):
        await self.start_camera()
        async with self._camera_condition:
            if self._camera_sequence == sequence or self._camera_frame is None:
                await asyncio.wait_for(self._camera_condition.wait(), timeout)
            return self._camera_frame, self._camera_sequence

    async def stop_camera(self):
        async with self._camera_lock:
            await self._stop_camera_unlocked()

    async def _stop_camera_unlocked(self):
        for process in (self._camera_process, self._ffmpeg_process):
            if process and process.returncode is None:
                process.terminate()
        for process in (self._camera_process, self._ffmpeg_process):
            if process and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        if self._camera_reader_task:
            self._camera_reader_task.cancel()
        for task in self._camera_stderr_tasks:
            if not task.done():
                task.cancel()
        if self._camera_stderr_tasks:
            await asyncio.gather(*self._camera_stderr_tasks,
                                 return_exceptions=True)
        self._camera_stderr_tasks = []
        self._camera_process = self._ffmpeg_process = self._camera_reader_task = None
        self._camera_frame = None
        self._camera_active = False
