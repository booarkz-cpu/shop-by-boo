#!/usr/bin/env bash
# v1.5.0 (stage 20, N9): ktlint on the main screen of «Корги Люси: клиент» and its tests
# (mobile/android-client/ktlint-files.txt; style in mobile/android-client/.editorconfig). The ktlint release is pinned
# by SHA-256; the older files join the list as they are rewritten.
set -euo pipefail
VERSION=1.7.1
SHA256=b596a05f09364e1997b644152683af12fef58944f3acfabdf78071f5a490eb98
cd "$(dirname "$0")/../../mobile/android-client"
bin="${RUNNER_TEMP:-/tmp}/ktlint-$VERSION"
if [ ! -x "$bin" ]; then
  curl -fsSL --retry 8 --retry-all-errors --retry-delay 20 -o "$bin" "https://github.com/pinterest/ktlint/releases/download/$VERSION/ktlint"
  echo "$SHA256  $bin" | sha256sum -c -
  chmod +x "$bin"
fi
mapfile -t patterns < <(grep -v '^\s*$' ktlint-files.txt)
"$bin" --relative "${patterns[@]}"
echo "ktlint: OK (${#patterns[@]} patterns)"
