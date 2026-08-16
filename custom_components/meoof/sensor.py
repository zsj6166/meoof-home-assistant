from datetime import datetime

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .entity import MeoofEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        MeoofStatusSensor(coordinator, entry, "battery", "电池电量", "%", "mdi:battery"),
        MeoofStatusSensor(coordinator, entry, "eat_detection", "进食检测灵敏度", None, "mdi:cat"),
        MeoofStatusSensor(coordinator, entry, "word_one", "状态字一", None, "mdi:code-braces"),
        MeoofStatusSensor(coordinator, entry, "word_two", "状态字二", None, "mdi:code-braces"),
        MeoofRawStatus(coordinator, entry),
        MeoofFeedHistory(coordinator, entry),
        MeoofLatestFeedRecord(coordinator, entry),
        MeoofForagingHistory(coordinator, entry),
        MeoofLatestForagingRecord(coordinator, entry),
        MeoofCatProfiles(coordinator, entry),
        MeoofLatestEating(coordinator, entry),
        MeoofPendingReview(coordinator, entry),
        MeoofLitterHistory(coordinator, entry),
        MeoofFeedPlan(coordinator, entry),
        MeoofSmartFeedHistory(coordinator, entry),
        MeoofEatingSummary(coordinator, entry, "day", "今日进食记录"),
        MeoofEatingSummary(coordinator, entry, "week", "本周进食记录"),
        MeoofEatingSummary(coordinator, entry, "month", "本月进食记录"),
    ])


class MeoofFeedPlan(MeoofEntity, SensorEntity):
    _attr_name = "今日出粮计划"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-today-feed-plan"

    @property
    def _items(self):
        plan = (self.coordinator.data or {}).get("feed_plan", {})
        today = next((day for day in plan.get("days", []) if day.get("week") == 8), {})
        return [item for item in today.get("items", [])
                if item.get("left", 0) + item.get("right", 0) > 0]

    @property
    def native_value(self):
        return sum(1 for item in self._items if item.get("enabled"))

    @property
    def extra_state_attributes(self):
        return {"items": self._items, "meoof_card_role": "today_feed_plan"}


class MeoofSmartFeedHistory(MeoofEntity, SensorEntity):
    _attr_name = "智能抑制出粮记录"
    _attr_icon = "mdi:bowl-mix-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-smart-feed-history"

    @property
    def native_value(self):
        smart = (self.coordinator.data or {}).get("smart_feed", {})
        latest = smart.get("latest") or {}
        return latest.get("status", "已启用" if smart.get("enabled") else "未启用")

    @property
    def extra_state_attributes(self):
        smart = (self.coordinator.data or {}).get("smart_feed", {})
        return {"enabled": smart.get("enabled", False),
                "latest": smart.get("latest"),
                "records": smart.get("records", []),
                "meoof_card_role": "smart_feed"}


class MeoofStatusSensor(MeoofEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, unit, icon):
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_unique_id = entry.entry_id + "-" + key

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("status", {}).get(self._key)


class MeoofRawStatus(MeoofEntity, SensorEntity):
    _attr_name = "原始状态"
    _attr_icon = "mdi:bowl-mix"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-raw-status"

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("probe", {}).get("status_response_type", "")
        return value.rsplit("data=", 1)[-1] if "data=" in value else value


class MeoofFeedHistory(MeoofEntity, SensorEntity):
    _attr_name = "喂食记录"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-feed-history"

    @property
    def native_value(self):
        history = (self.coordinator.data or {}).get("history", {})
        if history.get("reauth_required"):
            return "需要重新认证"
        return history.get("count", 0) if history.get("ok") else "不可用"

    @property
    def extra_state_attributes(self):
        history = (self.coordinator.data or {}).get("history", {})
        return {"records": [_format_feed_record(item)
                            for item in history.get("records", [])],
                "reauth_required": history.get("reauth_required", False),
                "meoof_card_role": "feed_history"}


def _format_feed_record(record):
    feed_type = int(record.get("ft", -1) or 0)
    timestamp = int(record.get("evt", 0) or 0)
    return {
        "id": record.get("id"),
        "time": datetime.fromtimestamp(timestamp).astimezone().isoformat()
        if timestamp else None,
        "type": "出粮",
        "feed_mode": {0: "计划", 2: "手动"}.get(feed_type, "其他"),
        "feed_type_code": feed_type,
        "left_planned_portions": record.get("lp", 0),
        "left_actual_portions": record.get("lf", 0),
        "right_planned_portions": record.get("rp", 0),
        "right_actual_portions": record.get("rf", 0),
        "actual_portions": int(record.get("lf", 0) or 0) + int(record.get("rf", 0) or 0),
    }


class MeoofLatestFeedRecord(MeoofEntity, SensorEntity):
    _attr_name = "最近一条喂食记录"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-latest-feed-record"

    @property
    def _record(self):
        records = (self.coordinator.data or {}).get("history", {}).get("records", [])
        return _format_feed_record(records[0]) if records else None

    @property
    def native_value(self):
        record = self._record
        return record["type"] if record else "暂无记录"

    @property
    def extra_state_attributes(self):
        return self._record or {}


def _format_foraging_record(record, recordings=None):
    timestamp = int(record.get("evt", 0) or 0)
    result = {
        "id": record.get("id"),
        "time": datetime.fromtimestamp(timestamp).astimezone().isoformat()
        if timestamp else None,
        "event_type": record.get("et"),
        "duration_data": record.get("cd"),
        "playback_timestamp": timestamp,
    }
    recording = (recordings or {}).get(str(record.get("id")))
    if recording:
        result["recording"] = recording
    return result


class MeoofForagingHistory(MeoofEntity, SensorEntity):
    _attr_name = "觅食记录"
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-foraging-history"

    @property
    def native_value(self):
        history = (self.coordinator.data or {}).get("foraging", {})
        return history.get("count", 0) if history.get("ok") else "不可用"

    @property
    def extra_state_attributes(self):
        history = (self.coordinator.data or {}).get("foraging", {})
        recordings = (self.coordinator.data or {}).get("recordings", {})
        return {"records": [_format_foraging_record(item, recordings)
                            for item in history.get("records", [])]}


class MeoofLatestForagingRecord(MeoofEntity, SensorEntity):
    _attr_name = "最近一条觅食记录"
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-latest-foraging-record"

    @property
    def _record(self):
        records = (self.coordinator.data or {}).get("foraging", {}).get("records", [])
        recordings = (self.coordinator.data or {}).get("recordings", {})
        return _format_foraging_record(records[0], recordings) if records else None

    @property
    def native_value(self):
        record = self._record
        return record["time"] if record else "暂无记录"

    @property
    def extra_state_attributes(self):
        return self._record or {}


class MeoofCatProfiles(MeoofEntity, SensorEntity):
    _attr_name = "猫咪档案"
    _attr_icon = "mdi:cat-multiple"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-cat-profiles"

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("cats", {}).get("profiles", {}))

    @property
    def extra_state_attributes(self):
        return {"profiles": (self.coordinator.data or {}).get("cats", {}).get("profiles", {}),
                "avatars": self.coordinator.client.cat_profiles.profile_avatars(),
                "meoof_card_role": "cat_profiles"}


class MeoofLatestEating(MeoofEntity, SensorEntity):
    _attr_name = "最近进食猫咪"
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-latest-eating"

    @property
    def native_value(self):
        latest = (self.coordinator.data or {}).get("cats", {}).get("latest")
        if latest:
            try:
                event_time = datetime.fromisoformat(latest["time"]).strftime("%H:%M:%S")
            except (KeyError, ValueError):
                event_time = "--:--:--"
            return f"{latest.get('cat', '未知猫咪')} · {event_time}"
        return latest.get("cat") if latest else "暂无记录"

    @property
    def extra_state_attributes(self):
        return ((self.coordinator.data or {}).get("cats", {}).get("latest") or {}) | {
            "meoof_card_role": "latest_eating"}


class MeoofEatingSummary(MeoofEntity, SensorEntity):
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator, entry, period, name):
        super().__init__(coordinator, entry)
        self._period = period
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}-eating-{period}"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cats", {}).get(self._period, {}).get("count", 0)

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("cats", {}).get(self._period, {}) | {
            "meoof_card_role": f"eating_{self._period}"}


class MeoofPendingReview(MeoofEntity, SensorEntity):
    _attr_name = "待分类进食记录"
    _attr_icon = "mdi:image-search"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-pending-review"

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("cats", {}).get("pending_review", []))

    @property
    def extra_state_attributes(self):
        records = (self.coordinator.data or {}).get("cats", {}).get("pending_review", [])
        return {"records": records[-50:]}


class MeoofLitterHistory(MeoofEntity, SensorEntity):
    _attr_name = "猫砂盆使用记录"
    _attr_icon = "mdi:cat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = entry.entry_id + "-litter-history"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cats", {}).get(
            "litter_day", {}).get("count", 0)

    @property
    def extra_state_attributes(self):
        cats = (self.coordinator.data or {}).get("cats", {})
        result = dict(cats.get("litter_day", {}))
        week = cats.get("litter_week", {})
        month = cats.get("litter_month", {})
        result["week_count"] = week.get("count", 0)
        result["week_by_cat"] = week.get("by_cat", {})
        result["week_events"] = week.get("events", [])
        result["month_count"] = month.get("count", 0)
        result["month_by_cat"] = month.get("by_cat", {})
        result["month_events"] = month.get("events", [])
        result["latest_by_cat"] = cats.get("litter_latest_by_cat", {})
        result["meoof_card_role"] = "litter_history"
        return result
