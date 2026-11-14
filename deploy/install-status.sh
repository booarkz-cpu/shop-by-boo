#!/usr/bin/env bash
# v28.144.0 (REQ-INFRA-0008): the installer's stages in a machine-readable file, so a script, the panel or support can
# tell where an installation is or where it stopped without reading the terminal:
#   {"state": "running" | "failed" | "done", "stage": "<current>", "stages": [{"name", "title", "state", "at"}, …],
#    "error": "<message>" | null, "updated_at": "…"}
# Sourced by deploy/install-vps.sh. INSTALL_STATUS chooses the file (default /var/log/vpn-shop-install.json).
INSTALL_STATUS="${INSTALL_STATUS:-/var/log/vpn-shop-install.json}"
INSTALL_STAGES=(preflight settings dependencies files secrets firewall images services health admin report)
declare -A INSTALL_TITLES=([preflight]="проверка сервера" [settings]="ответы на вопросы" [dependencies]="системные пакеты и Docker"
  [files]="файлы выпуска" [secrets]=".env и секреты" [firewall]="порты и firewall" [images]="сборка образов"
  [services]="запуск служб" [health]="API и миграции" [admin]="первый оператор" [report]="итог установки")
declare -A INSTALL_STATE=() INSTALL_AT=()
INSTALL_CURRENT=""
INSTALL_ERROR=""
INSTALL_OVERALL="running"

_status_json_escape() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/ }; s=${s//$'\t'/ }; printf '%s' "$s"; }

status_write() {
  local now first=1 out name
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  out="{\"state\":\"$INSTALL_OVERALL\",\"stage\":\"$INSTALL_CURRENT\",\"stages\":["
  for name in "${INSTALL_STAGES[@]}"; do
    (( first )) || out+=","; first=0
    out+="{\"name\":\"$name\",\"title\":\"${INSTALL_TITLES[$name]}\",\"state\":\"${INSTALL_STATE[$name]:-pending}\",\"at\":\"${INSTALL_AT[$name]:-}\"}"
  done
  if [[ -n "$INSTALL_ERROR" ]]; then out+="],\"error\":\"$(_status_json_escape "$INSTALL_ERROR")\""; else out+="],\"error\":null"; fi
  out+=",\"updated_at\":\"$now\"}"
  mkdir -p "$(dirname "$INSTALL_STATUS")" 2>/dev/null || true
  printf '%s\n' "$out" > "$INSTALL_STATUS.tmp" 2>/dev/null && mv -f "$INSTALL_STATUS.tmp" "$INSTALL_STATUS" 2>/dev/null || true
}

# status_stage <name>: the previous stage is done, <name> is running.
status_stage() {
  local now; now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  [[ -n "$INSTALL_CURRENT" && "${INSTALL_STATE[$INSTALL_CURRENT]:-}" == running ]] && INSTALL_STATE[$INSTALL_CURRENT]=done
  INSTALL_CURRENT=$1; INSTALL_STATE[$1]=running; INSTALL_AT[$1]=$now
  status_write
}

status_fail() { INSTALL_ERROR=${1:-"остановлена"}; INSTALL_OVERALL=failed
  [[ -n "$INSTALL_CURRENT" ]] && INSTALL_STATE[$INSTALL_CURRENT]=failed; status_write; }

status_done() { [[ -n "$INSTALL_CURRENT" ]] && INSTALL_STATE[$INSTALL_CURRENT]=done; INSTALL_OVERALL=done; INSTALL_ERROR=""; status_write; }

# On exit: an installation that did not reach status_done failed at the current stage.
status_on_exit() { local code=$?; [[ "$INSTALL_OVERALL" == running ]] && status_fail "${INSTALL_LAST_ERROR:-код выхода $code}"; return $code; }
