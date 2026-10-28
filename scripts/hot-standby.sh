#!/usr/bin/env bash
# Hot standby of the shop database: PostgreSQL streaming replication between two servers with the shop installed.
#
#   primary STANDBY_IP      on the main server: replication role, TLS, the port open to STANDBY_IP only, a slot
#   standby PRIMARY_IP      on the second server: copy the database from the primary and follow it (shop stopped)
#   status                  either side: role, lag, connected replicas
#   promote                 on the standby: become the primary and start the whole shop here
#   demote                  on an old primary that came back after a promotion: stop the shop so it cannot write
#   drop-slot               on the primary: forget a standby that is gone for good (frees retained WAL)
#
# The replication password is generated on the primary and kept in /root/corgi-standby.secret (never in git).
# Docker-published ports bypass ufw, so the port is limited with a DOCKER-USER iptables rule (a systemd unit keeps it).
# Read docs/modules/hot_standby.md before using promote: two primaries at once (split brain) lose data.
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
SLOT="corgi_standby"
ROLE="replicator"
SECRET_FILE="/root/corgi-standby.secret"
PGDATA_IN="/var/lib/postgresql/18/docker"
cd "$APP_DIR"
[[ -f .env ]] || { echo "Нет $APP_DIR/.env" >&2; exit 2; }

say() { printf '\n== %s\n' "$*"; }
psql_db() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U vpnshop -d vpnshop -At "$@"; }
valid_ip() { [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "Нужен IPv4-адрес, получено: $1" >&2; exit 2; }; }

write_override() {
  # docker compose merges docker-compose.override.yml automatically; it is local to this server (.gitignore).
  cat > docker-compose.override.yml <<'YAML'
# Written by scripts/hot-standby.sh: the database port for streaming replication (limited by the DOCKER-USER rule).
services:
  db:
    ports:
      - "5432:5432"
YAML
}

firewall_unit() {
  local allowed="$1"
  cat > /etc/systemd/system/corgi-standby-firewall.service <<UNIT
[Unit]
Description=Corgi Lusi: database port only for the hot standby
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'iptables -C DOCKER-USER -p tcp --dport 5432 ! -s ${allowed} -j DROP 2>/dev/null || iptables -I DOCKER-USER -p tcp --dport 5432 ! -s ${allowed} -j DROP'
ExecStop=/bin/sh -c 'iptables -D DOCKER-USER -p tcp --dport 5432 ! -s ${allowed} -j DROP || true'

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now corgi-standby-firewall.service
}

cmd_primary() {
  local standby="${1:?Укажите IP резервного сервера: hot-standby.sh primary 203.0.113.10}"
  valid_ip "$standby"
  command -v openssl >/dev/null || { echo "Нужен openssl" >&2; exit 2; }
  say "Пароль роли репликации"
  if [[ -s "$SECRET_FILE" ]]; then password="$(cat "$SECRET_FILE")"; else password="$(openssl rand -hex 24)"; printf '%s' "$password" > "$SECRET_FILE"; fi
  say "Роль $ROLE и слот $SLOT"
  psql_db -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE') THEN CREATE ROLE $ROLE WITH REPLICATION LOGIN; END IF; END \$\$;"
  psql_db -c "ALTER ROLE $ROLE WITH REPLICATION LOGIN PASSWORD '$password';"
  psql_db -c "SELECT pg_create_physical_replication_slot('$SLOT') WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name = '$SLOT');" >/dev/null
  say "TLS для репликации (самоподписанный сертификат)"
  local tmp; tmp="$(mktemp -d)"
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj "/CN=corgi-db" -keyout "$tmp/server.key" -out "$tmp/server.crt" 2>/dev/null
  docker compose cp "$tmp/server.crt" "db:$PGDATA_IN/server.crt"
  docker compose cp "$tmp/server.key" "db:$PGDATA_IN/server.key"
  rm -rf "$tmp"
  docker compose exec -T db sh -c "chown postgres:postgres $PGDATA_IN/server.crt $PGDATA_IN/server.key && chmod 600 $PGDATA_IN/server.key"
  psql_db -c "ALTER SYSTEM SET ssl = on;" -c "ALTER SYSTEM SET wal_level = replica;" -c "ALTER SYSTEM SET max_wal_senders = 5;" \
          -c "ALTER SYSTEM SET max_slot_wal_keep_size = '20GB';"
  say "Доступ только для $standby (pg_hba.conf)"
  local rule="hostssl replication $ROLE $standby/32 scram-sha-256"
  docker compose exec -T db sh -c "grep -qxF '$rule' $PGDATA_IN/pg_hba.conf || echo '$rule' >> $PGDATA_IN/pg_hba.conf"
  say "Порт 5432 наружу — только для $standby"
  firewall_unit "$standby"
  write_override
  docker compose up -d db
  sleep 5
  psql_db -c "SELECT pg_reload_conf();" >/dev/null
  say "Готово. На резервном сервере (магазин установлен тем же install.sh, .env скопирован с этого сервера):"
  echo "  REPLICATION_PASSWORD='$password' bash scripts/hot-standby.sh standby $(curl -fsS4 https://api.ipify.org 2>/dev/null || echo IP_ЭТОГО_СЕРВЕРА)"
  echo "Пароль сохранён в $SECRET_FILE (только root). Не отправляйте его в чат и не коммитьте."
}

cmd_standby() {
  local primary="${1:?Укажите IP основного сервера: hot-standby.sh standby 198.51.100.5}"
  valid_ip "$primary"
  local password="${REPLICATION_PASSWORD:-}"
  if [[ -z "$password" ]]; then read -rsp "Пароль репликации (из $SECRET_FILE основного сервера): " password; printf '\n' >&2; fi
  say "Останавливаю магазин на этом сервере (резерв только хранит копию базы)"
  docker compose stop backend backend_standby worker bot mail_receiver support_pro support_worker caddy 2>/dev/null || true
  docker compose stop db
  say "Копирую базу с $primary (pg_basebackup, может занять время)"
  docker compose run --rm --no-deps -e PGPASSWORD="$password" --entrypoint sh db -c "
    set -e
    rm -rf $PGDATA_IN.new && mkdir -p $PGDATA_IN.new
    pg_basebackup -d 'host=$primary port=5432 user=$ROLE sslmode=require application_name=corgi_standby' \
      -D $PGDATA_IN.new -R -X stream -S $SLOT -P
    rm -rf $PGDATA_IN.old && { [ -d $PGDATA_IN ] && mv $PGDATA_IN $PGDATA_IN.old || true; }
    mv $PGDATA_IN.new $PGDATA_IN
    chown -R postgres:postgres $PGDATA_IN && chmod 700 $PGDATA_IN"
  docker compose up -d db redis
  sleep 8
  cmd_status
  echo
  echo "Резерв следует за основным. Предыдущие данные этого сервера — в $PGDATA_IN.old внутри тома (удалите, когда убедитесь)."
  echo "Дальше: агент резерва (Резервные копии → Горячий резерв → «Команда установки агента»)."
}

cmd_status() {
  if [[ "$(psql_db -c 'SELECT pg_is_in_recovery()')" == "t" ]]; then
    echo "Роль: РЕЗЕРВ (следует за основным)"
    psql_db -c "SELECT 'Задержка, с: ' || COALESCE(round(EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp()))::text, 'нет данных')"
    psql_db -c "SELECT 'Поток: ' || COALESCE((SELECT status || ' от ' || sender_host FROM pg_stat_wal_receiver), 'не подключён')"
  else
    echo "Роль: ОСНОВНОЙ"
    psql_db -c "SELECT 'Реплика ' || client_addr || ': ' || state || ', отставание ' || COALESCE(round(EXTRACT(EPOCH FROM replay_lag))::text, '0') || ' с' FROM pg_stat_replication" | sed '/^$/d'
    psql_db -c "SELECT 'Слот ' || slot_name || (CASE WHEN active THEN ': активен' ELSE ': НЕ активен' END) || ', держит ' || pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots"
  fi
}

cmd_promote() {
  [[ "$(psql_db -c 'SELECT pg_is_in_recovery()')" == "t" ]] || { echo "Этот сервер уже основной." >&2; exit 2; }
  if [[ "${FORCE:-}" != "1" ]]; then
    read -rp "Основной сервер точно недоступен и не вернётся сам? Это необратимо. Введите ДА: " answer
    [[ "$answer" == "ДА" ]] || { echo "Отменено."; exit 1; }
  fi
  say "Повышаю резерв до основного"
  psql_db -c "SELECT pg_promote(true, 60);"
  rm -f docker-compose.override.yml
  say "Запускаю магазин здесь"
  docker compose up -d
  echo "Готово. Переключите DNS на этот сервер (агент делает это сам, если задан CF_API_TOKEN)."
  echo "Старый основной, когда вернётся: сначала bash scripts/hot-standby.sh demote, потом настройте его резервом."
}

cmd_demote() {
  say "Останавливаю магазин и базу: этот сервер больше не основной"
  docker compose stop backend backend_standby worker bot mail_receiver support_pro support_worker caddy db 2>/dev/null || true
  systemctl disable --now corgi-standby-firewall.service 2>/dev/null || true
  rm -f docker-compose.override.yml
  echo "Чтобы сделать его резервом нового основного: на новом — hot-standby.sh primary <IP этого>, здесь — hot-standby.sh standby <IP нового>."
}

cmd_drop_slot() {
  psql_db -c "SELECT pg_drop_replication_slot('$SLOT') FROM pg_replication_slots WHERE slot_name = '$SLOT' AND NOT active;"
  echo "Слот удалён (если резерв был отключён)."
}

case "${1:-}" in
  primary) shift; cmd_primary "$@" ;;
  standby) shift; cmd_standby "$@" ;;
  status) cmd_status ;;
  promote) cmd_promote ;;
  demote) cmd_demote ;;
  drop-slot) cmd_drop_slot ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
