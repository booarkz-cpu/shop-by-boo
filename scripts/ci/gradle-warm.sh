#!/usr/bin/env bash
# Fetch the wrapper distribution with retries. In --android-runtime mode also run the
# AGP task that consumes :app:debugRuntimeClasspath before declaring the runtime ready.
set -euo pipefail

android_runtime=false
if [[ ${1:-} == --android-runtime ]]; then
  android_runtime=true
  shift
fi
if (( $# == 0 )); then
  echo "Usage: gradle-warm.sh [--android-runtime] <dir with gradlew>..." >&2
  exit 2
fi

for dir in "$@"; do
  (
    cd -- "$dir"
    for attempt in {1..6}; do
      if bash gradlew --version --no-daemon -q >/dev/null; then
        break
      fi
      if (( attempt == 6 )); then
        echo "::error title=gradle::the Gradle distribution for $dir did not download"
        exit 1
      fi
      echo "::warning title=gradle::Gradle distribution download for $dir failed (try $attempt of 6)"
      sleep 30
    done
    echo "gradle: $dir distribution ready"
    if [[ $android_runtime == true ]]; then
      bash gradlew :app:processDebugNavigationResources --no-daemon --console=plain --info
      echo "gradle: $dir debug navigation resources ready"
    fi
  )
done
