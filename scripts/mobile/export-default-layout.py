#!/usr/bin/env python3
"""Write the default layout of the Android and iOS apps (backend/app/mobile_layout.py) into both apps.

    cd backend && python ../scripts/mobile/export-default-layout.py

Run it after changing the default sections, buttons or texts; tests/test_mobile_layout.py fails
while the bundled copies differ from the backend.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.mobile_layout import bundled_defaults  # noqa: E402

text = json.dumps(bundled_defaults(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
for path in ("mobile/android-user/app/src/main/assets/default_layout.json", "mobile/ios-user/VpnShopUser/default_layout.json"):
    (ROOT / path).write_text(text)
    print("wrote", path)
