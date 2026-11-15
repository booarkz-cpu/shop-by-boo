"""Layout stage 5: the shop's API lives in services/backend/. This file is not the application.

It stays at the old path for installed servers. The updater of an older release (scripts/github_release_fetch.py,
scripts/update.sh as they are on the server) reads the installed version from this file and takes a downloaded release
for a shop release only if this file is in it. Without it such a server could not update past this release.

The version below is kept equal to services/backend/app/main.py (tests/test_layout_stage5.py, scripts/check-current-docs.py).
"""
APP_VERSION = "21.5.1"
