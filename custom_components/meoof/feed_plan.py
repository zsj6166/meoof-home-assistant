"""Pure helpers for the Meoof feed-plan wire format.

The format was derived from interoperability testing with the official app.
Keeping parsing independent from Home Assistant makes malformed-payload tests
possible without loading the integration or contacting a device.
"""

import re

PLAN_DAYS = 8
PLAN_ITEMS = 30
PLAN_ITEM_SIZE = 9
PLAN_DAY_SIZE = PLAN_ITEMS * PLAN_ITEM_SIZE + 2
PLAN_WIRE_SIZE = PLAN_DAYS * PLAN_DAY_SIZE + 2


def parse_feed_plan_response(raw: str) -> dict:
    """Parse the textual probe response into a stable public structure."""
    match = re.search(r"data=([0-9a-fA-F]+)", raw or "")
    if not match:
        raise ValueError("feed plan response has no payload")
    payload = bytes.fromhex(match.group(1))
    if len(payload) < 90 or payload[1] != 0:
        raise ValueError("feed plan response is incomplete or unsuccessful")
    if (len(payload) - 2) % PLAN_DAYS:
        raise ValueError("feed plan response has an invalid day table")
    day_size = (len(payload) - 2) // PLAN_DAYS
    if day_size < 11 or (day_size - 2) % PLAN_ITEM_SIZE:
        raise ValueError("feed plan response has an invalid item table")
    item_count = (day_size - 2) // PLAN_ITEM_SIZE
    if not 1 <= item_count <= PLAN_ITEMS:
        raise ValueError("feed plan response has an unsupported item count")
    days = []
    for day_number in range(PLAN_DAYS):
        offset = 2 + day_number * day_size
        items = []
        for item_number in range(item_count):
            item_offset = offset + 2 + item_number * PLAN_ITEM_SIZE
            items.append({
                "index": payload[item_offset],
                "left": payload[item_offset + 1],
                "right": payload[item_offset + 2],
                "hour": payload[item_offset + 3],
                "minute": payload[item_offset + 4],
                "sound": payload[item_offset + 5] == 1,
                "enabled": payload[item_offset + 6] == 1,
            })
        days.append({"week": payload[offset],
                     "enabled": payload[offset + 1] == 1,
                     "items": items})
    return {"ok": True, "is_edit": payload[0] == 1,
            "items_per_day": item_count, "days": days}
