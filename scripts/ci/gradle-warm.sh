#!/usr/bin/env bash
# Fetch the Gradle wrapper with retries. In --android-runtime mode also run the AGP task
# that consumes :app:debugRuntimeClasspath before declaring the runtime ready.
# A clean GRADLE_USER_HOME still has no module cache: only the wrapper distribution may
# be reused from GRADLE_WARM_WRAPPER_CACHE. A failed resolution is asked again with a
# longer pause; --refresh-dependencies is added only on those later attempts.
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

pause() {
  local seconds=$1
  if [[ ${GRADLE_WARM_NO_SLEEP:-} == 1 ]]; then
    echo "gradle: backoff ${seconds}s"
    return 0
  fi
  sleep "$seconds"
}

gradle_home() {
  if [[ -n ${GRADLE_USER_HOME:-} ]]; then
    printf '%s\n' "$GRADLE_USER_HOME"
  else
    printf '%s\n' "$HOME/.gradle"
  fi
}

seed_wrapper_cache() {
  local cache=${GRADLE_WARM_WRAPPER_CACHE:-}
  [[ -n $cache && -d $cache ]] || return 0
  local home dists
  home=$(gradle_home)
  dists="$home/wrapper/dists"
  mkdir -p "$dists" "$cache"
  if compgen -G "$cache/*" > /dev/null; then
    cp -a "$cache/." "$dists/"
  fi
}

save_wrapper_cache() {
  local cache=${GRADLE_WARM_WRAPPER_CACHE:-}
  [[ -n $cache ]] || return 0
  local home dists
  home=$(gradle_home)
  dists="$home/wrapper/dists"
  [[ -d $dists ]] || return 0
  mkdir -p "$cache"
  cp -a "$dists/." "$cache/"
}

forget_module_cache() {
  local home
  home=$(gradle_home)
  rm -rf "$home/caches" "$home/daemon" "$home/native" "$home/.tmp"
}

write_mirror_init() {
  local file=$1
  cat > "$file" << 'EOF'
// Appended after the app repositories, which stay google() then mavenCentral().
// The mirror is only a fallback for a transient miss of a Central artifact.
settingsEvaluated { settings ->
    def mirror = "https://maven-central.storage-download.googleapis.com/maven2/"
    settings.pluginManagement.repositories.maven { url = mirror }
    settings.dependencyResolutionManagement.repositories.maven { url = mirror }
}
EOF
}

resolve_runtime() {
  local init attempt code delay
  init=$(mktemp)
  write_mirror_init "$init"
  for attempt in 1 2 3 4 5 6; do
    local -a args
    args=(:app:processDebugNavigationResources --no-daemon --console=plain --init-script "$init")
    if (( attempt == 1 )); then
      args+=(--info)
    else
      forget_module_cache
      args+=(--refresh-dependencies)
    fi
    set +e
    bash gradlew "${args[@]}"
    code=$?
    set -e
    if (( code == 0 )); then
      echo "gradle: $dir debug navigation resources ready"
      rm -f "$init"
      return 0
    fi
    if (( attempt == 6 )); then
      echo "::error title=gradle::debug runtime for $dir did not resolve (try $attempt of 6)" >&2
      rm -f "$init"
      return "$code"
    fi
    echo "::warning title=gradle::debug runtime for $dir failed (try $attempt of 6)" >&2
    delay=$((5 << (attempt - 1)))
    pause "$delay"
  done
}

for dir in "$@"; do
  (
    cd -- "$dir"
    seed_wrapper_cache
    for attempt in 1 2 3 4 5 6; do
      if bash gradlew --version --no-daemon -q >/dev/null; then
        break
      fi
      if (( attempt == 6 )); then
        echo "::error title=gradle::the Gradle distribution for $dir did not download" >&2
        exit 1
      fi
      echo "::warning title=gradle::Gradle distribution download for $dir failed (try $attempt of 6)" >&2
      pause $((5 << (attempt - 1)))
    done
    echo "gradle: $dir distribution ready"
    save_wrapper_cache
    if [[ $android_runtime == true ]]; then
      resolve_runtime
    fi
  )
done
