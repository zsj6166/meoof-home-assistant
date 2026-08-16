import json
import pathlib
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta


class CatProfiles:
    """Local cat profiles, reference images and eating-event archive."""

    def __init__(self, hass):
        self.root = pathlib.Path(hass.config.path(".meoof-cats"))
        self.path = self.root / "data.json"
        self.data = {"profiles": {}, "events": []}
        self._profile_avatars_cache = {}

    def load(self):
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.data.setdefault("profiles", {})
        self.data.setdefault("events", [])
        self.data.setdefault("external_profiles", {})
        self.data.setdefault("litter_events", [])
        if not self.data.get("snapshot_secret"):
            self.data["snapshot_secret"] = secrets.token_hex(32)
            self.save()
        self._refresh_profile_avatar_cache()

    def save(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.data["events"] = self.data["events"][-2000:]
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    def add_profile_sample(self, name, jpeg):
        name = name.strip()
        if not name:
            raise ValueError("猫咪名称不能为空")
        folder = self.root / "profiles" / name
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        samples = sorted(folder.glob("*.jpg"))
        number = int(samples[-1].stem) + 1 if samples else 1
        (folder / f"{number:03d}.jpg").write_bytes(jpeg)
        for old in sorted(folder.glob("*.jpg"))[:-10]:
            old.unlink(missing_ok=True)
        self.data["profiles"][name] = {"samples": len(list(folder.glob("*.jpg")))}
        self._refresh_profile_avatar_cache()
        self.save()

    def import_external_profile(self, name, jpeg, source):
        """Import an external avatar once, and again only when it changes."""
        digest = hashlib.sha256(jpeg).hexdigest()
        external = self.data.setdefault("external_profiles", {})
        if external.get(name, {}).get("digest") == digest:
            return False
        self.add_profile_sample(name, jpeg)
        external[name] = {"source": source, "digest": digest}
        self.save()
        return True

    def delete_profile(self, name):
        name = name.strip()
        folder = self.root / "profiles" / name
        for path in folder.glob("*.jpg") if folder.exists() else []:
            path.unlink(missing_ok=True)
        if folder.exists():
            folder.rmdir()
        self.data["profiles"].pop(name, None)
        self._refresh_profile_avatar_cache()
        self.save()

    def reference_images(self):
        result = []
        for name in self.data["profiles"]:
            folder = self.root / "profiles" / name
            for path in sorted(folder.glob("*.jpg"))[-3:]:
                result.append((name, path.read_bytes()))
        return result

    def profile_sample(self, name, index):
        """Return one profile sample, newest first."""
        folder = self.root / "profiles" / name.strip()
        samples = sorted(folder.glob("*.jpg"), reverse=True) if folder.exists() else []
        if index < 0 or index >= len(samples):
            return None, None
        return samples[index].read_bytes(), samples[index].name

    def record_event(self, jpeg, name="未知猫咪", confidence=0.0, detail="",
                     *, event_id=None, event_time=None, recording=None):
        if event_id is not None:
            existing = next((item for item in self.data["events"]
                             if str(item.get("event_id")) == str(event_id)), None)
            if existing:
                return existing
        now = event_time or datetime.now().astimezone()
        snapshots = self.root / "snapshots"
        snapshots.mkdir(parents=True, mode=0o700, exist_ok=True)
        filename = now.strftime("%Y%m%d-%H%M%S-%f.jpg")
        (snapshots / filename).write_bytes(jpeg)
        event = {"time": now.isoformat(), "cat": name,
                 "confidence": round(float(confidence), 3), "snapshot": filename,
                 "location": "喂食器进食区", "detail": detail}
        if event_id is not None:
            event["event_id"] = str(event_id)
        if recording:
            event["recording"] = recording
        self.data["events"].append(event)
        keep = {item.get("snapshot") for item in self.data["events"][-2000:]}
        for path in snapshots.glob("*.jpg"):
            if path.name not in keep:
                path.unlink(missing_ok=True)
        self.save()
        return event

    def summary(self, period):
        now = datetime.now().astimezone()
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        events = sorted(
            (e for e in self.data["events"]
             if datetime.fromisoformat(e["time"]) >= start
             and not e.get("excluded")),
            key=lambda item: datetime.fromisoformat(item["time"]),
        )
        cats = {}
        durations = {}
        counted_clips = set()
        for event in events:
            cat = event["cat"]
            cats[cat] = cats.get(cat, 0) + 1
            recording = event.get("recording") or {}
            duration = int(recording.get("duration", 0) or 0)
            clip_id = recording.get("source") or recording.get("start")
            clip_key = (cat, str(clip_id))
            if duration and clip_id is not None and clip_key not in counted_clips:
                counted_clips.add(clip_key)
                durations[cat] = durations.get(cat, 0) + duration
        return {"count": len(events), "by_cat": cats,
                "duration_by_cat": durations, "events": events[-50:]}

    def snapshot_url(self, filename):
        token = hmac.new(self.data["snapshot_secret"].encode(), filename.encode(),
                         hashlib.sha256).hexdigest()
        return f"/api/meoof/eating_snapshot/{filename}?token={token}"

    def valid_snapshot_token(self, filename, token):
        expected = hmac.new(self.data["snapshot_secret"].encode(), filename.encode(),
                            hashlib.sha256).hexdigest()
        return bool(token) and hmac.compare_digest(expected, token)

    def smart_feed_snapshot_url(self, filename):
        key = f"smart-feed/{filename}"
        token = hmac.new(self.data["snapshot_secret"].encode(), key.encode(),
                         hashlib.sha256).hexdigest()
        return f"/api/meoof/smart_feed_snapshot/{filename}?token={token}"

    def valid_smart_feed_snapshot_token(self, filename, token):
        key = f"smart-feed/{filename}"
        expected = hmac.new(self.data["snapshot_secret"].encode(), key.encode(),
                            hashlib.sha256).hexdigest()
        return bool(token) and hmac.compare_digest(expected, token)

    def manage_data(self):
        events = []
        for event in sorted(self.data.get("events", []),
                            key=lambda item: item.get("time", ""), reverse=True):
            if event.get("excluded"):
                continue
            item = {key: event.get(key) for key in
                    ("time", "cat", "snapshot", "event_id", "reviewed", "detail")}
            recording = event.get("recording") or {}
            item["clip_duration"] = int(recording.get("duration", 0) or 0)
            if item.get("snapshot"):
                item["image_url"] = self.snapshot_url(item["snapshot"])
            events.append(item)
        profiles = {}
        for name in self.data.get("profiles", {}):
            folder = self.root / "profiles" / name
            profiles[name] = [
                {"filename": path.name, "image_url": self.profile_url(name, path.name)}
                for path in sorted(folder.glob("*.jpg"), reverse=True)
            ]
        return {"events": events, "profiles": profiles}

    def profile_avatars(self):
        """Return a signed newest profile image URL for each cat."""
        return dict(self._profile_avatars_cache)

    def _refresh_profile_avatar_cache(self):
        """Refresh on worker-thread mutations so entity properties stay I/O free."""
        result = {}
        for name in self.data.get("profiles", {}):
            folder = self.root / "profiles" / name
            samples = sorted(folder.glob("*.jpg"), reverse=True)
            if samples:
                result[name] = self.profile_url(name, samples[0].name)
        self._profile_avatars_cache = result

    def profile_url(self, name, filename):
        key = f"profile/{name}/{filename}"
        token = hmac.new(self.data["snapshot_secret"].encode(), key.encode(),
                         hashlib.sha256).hexdigest()
        from urllib.parse import quote
        return (f"/api/meoof/profile_image/{quote(name, safe='')}/"
                f"{quote(filename, safe='')}?token={token}")

    def valid_profile_token(self, name, filename, token):
        key = f"profile/{name}/{filename}"
        expected = hmac.new(self.data["snapshot_secret"].encode(), key.encode(),
                            hashlib.sha256).hexdigest()
        return bool(token) and hmac.compare_digest(expected, token)

    def reclassify_event(self, snapshot, name, learn=False):
        event = next((item for item in self.data.get("events", [])
                      if item.get("snapshot") == snapshot), None)
        if not event or not name.strip():
            raise ValueError("record or cat not found")
        event["cat"] = name.strip()
        event["reviewed"] = True
        event["detail"] = "人工复核并修正分类"
        if learn:
            image = (self.root / "snapshots" / snapshot).read_bytes()
            self.add_profile_sample(name, image)
        self.save()

    def delete_event(self, snapshot):
        before = len(self.data.get("events", []))
        self.data["events"] = [item for item in self.data.get("events", [])
                               if item.get("snapshot") != snapshot]
        if len(self.data["events"]) == before:
            raise ValueError("record not found")
        if not any(item.get("snapshot") == snapshot for item in self.data["events"]):
            (self.root / "snapshots" / snapshot).unlink(missing_ok=True)
        self.save()

    def delete_profile_sample(self, name, filename):
        if pathlib.Path(filename).name != filename:
            raise ValueError("invalid filename")
        path = self.root / "profiles" / name / filename
        if not path.is_file():
            raise ValueError("sample not found")
        path.unlink()
        folder = path.parent
        count = len(list(folder.glob("*.jpg")))
        if count:
            self.data["profiles"][name] = {"samples": count}
        else:
            folder.rmdir()
            self.data["profiles"].pop(name, None)
        self._refresh_profile_avatar_cache()
        self.save()

    def profile_image(self, name, filename):
        if pathlib.Path(filename).name != filename:
            return None
        try:
            return (self.root / "profiles" / name / filename).read_bytes()
        except OSError:
            return None

    def pending_events(self):
        """Events that still need a human classification."""
        return [event for event in self.data.get("events", [])
                if event.get("cat") == "未知猫咪" and not event.get("reviewed")]

    def latest_pending_image(self):
        pending = self.pending_events()
        if not pending:
            return None
        try:
            return (self.root / "snapshots" / pending[-1]["snapshot"]).read_bytes()
        except (KeyError, OSError):
            return None

    def classify_latest_pending(self, name):
        """Classify newest unknown event and learn its snapshot as a sample."""
        name = name.strip()
        if not name:
            raise ValueError("猫咪名称不能为空")
        pending = self.pending_events()
        if not pending:
            raise ValueError("没有待分类的进食记录")
        event = pending[-1]
        image = (self.root / "snapshots" / event["snapshot"]).read_bytes()
        event["cat"] = name
        event["confidence"] = 1.0
        event["reviewed"] = True
        event["detail"] = "人工复核；已加入识别参考图库"
        self.add_profile_sample(name, image)
        self.save()
        return event

    def skip_latest_pending(self):
        """Mark the newest review item as a non-cat/invalid capture."""
        pending = self.pending_events()
        if not pending:
            raise ValueError("没有待分类的进食记录")
        event = pending[-1]
        event["reviewed"] = True
        event["excluded"] = True
        event["cat"] = "非猫画面"
        event["detail"] = "人工复核：不是猫；已从进食统计中排除"
        self.save()
        return event

    def latest_valid_event(self):
        return next((event for event in reversed(self.data.get("events", []))
                     if not event.get("excluded")), None)

    def latest_valid_image(self):
        """Return the snapshot for the newest non-excluded eating event."""
        event = self.latest_valid_event()
        if not event:
            return None
        try:
            return (self.root / "snapshots" / event["snapshot"]).read_bytes()
        except (KeyError, OSError):
            return None

    def merge_litter_events(self, records):
        """Persist Petkit litter events across polling cycles and restarts."""
        events = self.data.setdefault("litter_events", [])
        known = {str(event.get("event_id")): event for event in events}
        changed = False
        for record in records:
            event_id = str(record.get("event_id"))
            if event_id in known:
                if known[event_id] != record:
                    known[event_id].update(record)
                    changed = True
                continue
            events.append(record)
            known[event_id] = record
            changed = True
        if changed:
            events.sort(key=lambda event: event.get("timestamp", 0))
            self.data["litter_events"] = events[-2000:]
            self.save()
        return changed

    def litter_summary(self, period="day"):
        now = datetime.now().astimezone()
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        events = [event for event in self.data.get("litter_events", [])
                  if datetime.fromisoformat(event["time"]) >= start]
        by_cat = {}
        for event in events:
            by_cat[event["cat"]] = by_cat.get(event["cat"], 0) + 1
        return {"count": len(events), "by_cat": by_cat, "events": events[-100:]}

    def latest_litter_by_cat(self):
        """Return durable latest litter event per cat, independent of day reset."""
        result = {}
        for event in self.data.get("litter_events", []):
            cat = event.get("cat")
            if cat and cat != "未知猫咪":
                result[cat] = event
        return result

    @property
    def profiles(self):
        return {name: value.get("samples", 0) for name, value in self.data["profiles"].items()}

    @property
    def recorded_event_ids(self):
        """Cloud event ids already committed to the local archive."""
        return {str(item["event_id"]) for item in self.data.get("events", [])
                if item.get("event_id") is not None}
