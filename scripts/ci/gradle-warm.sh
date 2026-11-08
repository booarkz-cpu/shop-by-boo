#!/usr/bin/env bash
# v28.110.0 (stage 20): GitHub release downloads answer 504 for hours at a time, and the Gradle wrapper downloads its
# distribution once without retrying. Fetch it ahead of the build: `gradlew --version` up to 6 times, 30 s apart.
# Usage: gradle-warm.sh <dir with gradlew>...
set -uo pipefail
for dir in "$@"; do
  for i in 1 2 3 4 5 6; do
    (cd "$dir" && bash gradlew --version --no-daemon -q >/dev/null) && { echo "gradle: $dir ready"; continue 2; }
    echo "::warning title=gradle::download of the Gradle distribution for $dir failed (try $i of 6)"
    sleep 30
  done
  echo "::error title=gradle::the Gradle distribution for $dir did not download"; exit 1
done
