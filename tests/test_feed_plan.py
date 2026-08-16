import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / "custom_components" / "meoof" / "feed_plan.py"
SPEC = importlib.util.spec_from_file_location("meoof_feed_plan", MODULE)
feed_plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feed_plan)


def response_payload(success=0):
    payload = bytearray(feed_plan.PLAN_WIRE_SIZE)
    payload[0] = 0
    payload[1] = success
    for day in range(feed_plan.PLAN_DAYS):
        offset = 2 + day * feed_plan.PLAN_DAY_SIZE
        payload[offset] = day + 1
        payload[offset + 1] = 1
        for item in range(feed_plan.PLAN_ITEMS):
            item_offset = offset + 2 + item * feed_plan.PLAN_ITEM_SIZE
            payload[item_offset] = item + 1
    today = 2 + 7 * feed_plan.PLAN_DAY_SIZE
    first = today + 2
    payload[first + 1] = 2
    payload[first + 3] = 7
    payload[first + 4] = 30
    payload[first + 5] = 1
    payload[first + 6] = 1
    return payload


class FeedPlanTest(unittest.TestCase):
    def test_parse_today_item(self):
        raw = "20743 bytes=594 data=" + response_payload().hex()
        parsed = feed_plan.parse_feed_plan_response(raw)
        today = next(day for day in parsed["days"] if day["week"] == 8)
        self.assertTrue(today["enabled"])
        self.assertEqual(today["items"][0], {
            "index": 1, "left": 2, "right": 0, "hour": 7, "minute": 30,
            "sound": True, "enabled": True,
        })

    def test_rejects_failed_or_short_response(self):
        for raw in ("", "data=00", "data=" + response_payload(1).hex()):
            with self.assertRaises(ValueError):
                feed_plan.parse_feed_plan_response(raw)


if __name__ == "__main__":
    unittest.main()
