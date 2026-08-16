import asyncio
import collections
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).parents[1] / "custom_components" / "meoof"
PACKAGE = "meoof_runtime_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
sys.modules[f"{PACKAGE}.cloud_auth"] = types.ModuleType(f"{PACKAGE}.cloud_auth")
for name in ("cat_profiles", "feed_plan"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.runtime_client", ROOT / "runtime_client.py")
runtime_client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime_client
spec.loader.exec_module(runtime_client)


def fake_client(wait_side_effect):
    client = runtime_client.MeoofRuntimeClient.__new__(
        runtime_client.MeoofRuntimeClient)
    client._camera_sequence = 0
    client._camera_users = 0
    client._camera_process = None
    client._camera_stderr = {
        "runtime": collections.deque(maxlen=20),
        "ffmpeg": collections.deque(maxlen=20),
    }
    client.acquire_camera = AsyncMock()
    client.release_camera = AsyncMock()
    client.stop_camera = AsyncMock()
    client.wait_camera_frame = AsyncMock(side_effect=wait_side_effect)
    return client


class SmartFeedCameraRetryTest(unittest.IsolatedAsyncioTestCase):
    def test_ffmpeg_keeps_recoverable_initial_keyframe(self):
        command = runtime_client.MeoofRuntimeClient._camera_ffmpeg_command(
            "/tmp/video.h264")
        self.assertIn("ignore_err", command)
        self.assertIn("+low_delay+output_corrupt", command)
        self.assertIn("yuvj420p", command)
        self.assertNotIn("nobuffer", command)
        self.assertNotIn("fps=5", command)

    async def test_low_confidence_live_frame_uses_recorded_cover(self):
        client = runtime_client.MeoofRuntimeClient.__new__(
            runtime_client.MeoofRuntimeClient)
        client._capture_smart_feed_frame = AsyncMock(return_value=(b"grey", 1))
        client._latest_recorded_smart_feed_frame = AsyncMock(
            return_value=(b"cover", 12.5))
        client._analyze_smart_feed_frame = AsyncMock(side_effect=[
            ("empty", 0.05, "unusable"), ("many", 0.99, "bowl is full")])
        client.stop_camera = AsyncMock()
        record = {}

        frame, level, confidence, _ = await client._smart_feed_observation(record)

        self.assertEqual((frame, level, confidence), (b"cover", "many", 0.99))
        self.assertEqual(record["frame_source"], "latest_foraging_recording")
        self.assertEqual(record["live_camera_confidence"], 0.05)

    async def test_latest_recorded_cover_selects_newest_event(self):
        client = runtime_client.MeoofRuntimeClient.__new__(
            runtime_client.MeoofRuntimeClient)
        client._foraging = {"records": [
            {"id": "older", "evt": int(time.time()) - 120},
            {"id": "newer", "evt": int(time.time()) - 60},
        ]}
        client._recording_for_event = AsyncMock(return_value=(b"cover", {}))

        frame, age = await client._latest_recorded_smart_feed_frame()

        self.assertEqual(frame, b"cover")
        self.assertLess(age, 2)
        self.assertEqual(client._recording_for_event.await_args.args[0]["id"], "newer")

    async def test_rebuilds_pipeline_once_after_timeout(self):
        client = fake_client([asyncio.TimeoutError(), (b"jpeg", 2)])

        frame, attempts = await client._capture_smart_feed_frame(timeout=1)

        self.assertEqual(frame, b"jpeg")
        self.assertEqual(attempts, 2)
        self.assertEqual(client.acquire_camera.await_count, 2)
        self.assertEqual(client.release_camera.await_count, 2)
        client.stop_camera.assert_awaited_once()

    async def test_reports_camera_stage_after_second_timeout(self):
        client = fake_client([asyncio.TimeoutError(), asyncio.TimeoutError()])
        client._camera_stderr["runtime"].append("stream session ended")

        with self.assertRaises(runtime_client.SmartFeedCheckError) as raised:
            await client._capture_smart_feed_frame(timeout=1)

        self.assertEqual(raised.exception.stage, "camera_frame_timeout")
        self.assertEqual(raised.exception.error_name, "TimeoutError")
        self.assertIn("stream session ended", raised.exception.detail)
        self.assertEqual(client.release_camera.await_count, 2)


if __name__ == "__main__":
    unittest.main()
