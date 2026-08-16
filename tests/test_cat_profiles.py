import importlib.util
import pathlib
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit


MODULE = pathlib.Path(__file__).parents[1] / "custom_components" / "meoof" / "cat_profiles.py"
SPEC = importlib.util.spec_from_file_location("meoof_cat_profiles", MODULE)
CAT_PROFILES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAT_PROFILES)


class _Config:
    def __init__(self, root):
        self.root = pathlib.Path(root)

    def path(self, *parts):
        return str(self.root.joinpath(*parts))


class _Hass:
    def __init__(self, root):
        self.config = _Config(root)


class SmartFeedSnapshotTokenTest(unittest.TestCase):
    def test_signed_url_is_bound_to_smart_feed_filename(self):
        with tempfile.TemporaryDirectory() as root:
            profiles = CAT_PROFILES.CatProfiles(_Hass(root))
            profiles.load()
            url = profiles.smart_feed_snapshot_url("check.jpg")
            parsed = urlsplit(url)
            token = parse_qs(parsed.query)["token"][0]

            self.assertEqual(parsed.path,
                             "/api/meoof/smart_feed_snapshot/check.jpg")
            self.assertTrue(profiles.valid_smart_feed_snapshot_token(
                "check.jpg", token))
            self.assertFalse(profiles.valid_smart_feed_snapshot_token(
                "other.jpg", token))
            self.assertFalse(profiles.valid_snapshot_token("check.jpg", token))


if __name__ == "__main__":
    unittest.main()
