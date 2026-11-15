"""Admin update status must match the release assets accepted by the updater."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("github_update", ROOT / "services/backend/app/github_update.py")
with patch.dict(sys.modules, {"fastapi": types.SimpleNamespace(HTTPException=Exception)}):
    update = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(update)


class ReleaseStatusTests(unittest.TestCase):
    def payload(self, tag="v20.0.21", names=None):
        zip_name = "remnawave_vpn_shop_v20_0_21_full_release.zip"
        if names is None:
            names = [zip_name, zip_name + ".sha256"]
        return {"tag_name": tag, "assets": [
            {"name": name, "browser_download_url": update.DOWNLOAD_PREFIX + tag + "/" + name}
            for name in names
        ]}

    def test_complete_release_is_available(self):
        result = update.release_status("20.0.20", self.payload())
        self.assertTrue(result["update_available"])
        self.assertEqual(len(result["assets"]), 2)

    def test_missing_checksum_is_unavailable(self):
        result = update.release_status("20.0.20", self.payload(names=["remnawave_vpn_shop_v20_0_21_full_release.zip"]))
        self.assertFalse(result["update_available"])

    def test_mismatched_tag_is_unavailable(self):
        result = update.release_status("20.0.20", self.payload(tag="v20.0.21-preview"))
        self.assertFalse(result["update_available"])
        self.assertEqual(result["assets"], [])

    def test_wrong_asset_url_is_unavailable(self):
        payload = self.payload()
        payload["assets"][1]["browser_download_url"] = update.DOWNLOAD_PREFIX + "v20.0.20/" + payload["assets"][1]["name"]
        result = update.release_status("20.0.20", payload)
        self.assertFalse(result["update_available"])


if __name__ == "__main__":
    unittest.main()
