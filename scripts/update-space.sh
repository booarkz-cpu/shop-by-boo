#!/usr/bin/env bash
# v28.143.0 (REQ-INFRA-0011): is there room for an update? Sourced by scripts/update.sh before anything is written.
# An update keeps a snapshot of the install and a dump of the database (.rollback), pulls new images and builds;
# a disk that fills up half way through leaves a broken install. The answer is checked first.
#   space_need_kb <install kb> <database kb>  → the kilobytes an update needs
#   space_check <need kb> <free kb>           → 0, or 1 with a message naming both numbers
SPACE_RESERVE_KB=${SPACE_RESERVE_KB:-2097152}   # 2 GiB for images, build layers and logs

space_need_kb() {
  local install=${1:-0} database=${2:-0}
  # the snapshot (compressed, at most the install) + the plain SQL dump (up to twice the database's size on disk)
  echo $(( install + database * 2 + SPACE_RESERVE_KB ))
}

space_check() {
  local need=$1 free=$2
  if (( free < need )); then
    printf 'Мало места на диске: для обновления нужно %d МБ, свободно %d МБ. Обновление отменено, ничего не изменено. Освободите место (старые снимки в .rollback, docker image prune) и повторите.\n' \
      $(( need / 1024 )) $(( free / 1024 )) >&2
    return 1
  fi
}
