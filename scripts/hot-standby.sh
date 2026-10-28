#!/usr/bin/env bash
# Hot standby of the shop database: PostgreSQL streaming replication between two servers with the shop installed.
#
#   primary STANDBY_IP      on the main server: replication role, TLS, the port open to STANDBY_IP only, a slot
#   standby PRIMARY_IP      on the second server: copy the database from the primary and follow it (shop stopped)
#   status                  either side: role, lag, connected replicas
#   promote                 on the standby: become the primary and start the whole shop here
#   demote                  on an old primary that came back after a promotion: stop the shop so it cannot write
#   drop-slot               on the primary: forget a standby that is gone for good (frees retained WAL)
#   files-key               on the standby: print the SSH key that pulls files (media, Support Pro uploads, app packages)
#   files-allow 'KEY' IP    on the primary: let that key read the shop volumes only (rrsync, read-only, from IP only)
#   files-sync PRIMARY_IP   on the standby: copy the volumes now (the agent does it every hour)
#
# Both databases follow the primary: the shop (service db, port 5432) and Support Pro (support_db, port 5433).
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
# Clusters: compose service, superuser = database name, published port.
CLUSTERS=("db vpnshop 5432" "support_db support 5433")
psql_on() { local service="$1" user="$2"; shift 2; docker compose exec -T "$service" psql -v ON_ERROR_STOP=1 -U "$user" -d "$user" -At "$@"; }
psql_db() { psql_on db vpnshop "$@"; }
has_service() { docker compose config --services 2>/dev/null | grep -qx "$1"; }
FILE_VOLUMES=(media_data support_uploads app_packages)
FILES_KEY=/root/.ssh/corgi_standby_files
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
  if has_service support_db; then
    printf '  support_db:\n    ports:\n      - "5433:5432"\n' >> docker-compose.override.yml
  fi
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
# Inside DOCKER-USER the port is already the container port (5432 for both databases).
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
  for cluster in "${CLUSTERS[@]}"; do
    read -r service user port <<<"$cluster"
    has_service "$service" || continue
    say "$service: роль $ROLE, слот $SLOT, TLS, доступ только для $standby"
    psql_on "$service" "$user" -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE') THEN CREATE ROLE $ROLE WITH REPLICATION LOGIN; END IF; END \$\$;"
    psql_on "$service" "$user" -c "ALTER ROLE $ROLE WITH REPLICATION LOGIN PASSWORD '$password';"
    psql_on "$service" "$user" -c "SELECT pg_create_physical_replication_slot('$SLOT') WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name = '$SLOT');" >/dev/null
    local tmp; tmp="$(mktemp -d)"
    openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj "/CN=corgi-$service" -keyout "$tmp/server.key" -out "$tmp/server.crt" 2>/dev/null
    docker compose cp "$tmp/server.crt" "$service:$PGDATA_IN/server.crt"
    docker compose cp "$tmp/server.key" "$service:$PGDATA_IN/server.key"
    rm -rf "$tmp"
    docker compose exec -T "$service" sh -c "chown postgres:postgres $PGDATA_IN/server.crt $PGDATA_IN/server.key && chmod 600 $PGDATA_IN/server.key"
    psql_on "$service" "$user" -c "ALTER SYSTEM SET ssl = on;" -c "ALTER SYSTEM SET wal_level = replica;" -c "ALTER SYSTEM SET max_wal_senders = 5;" \
            -c "ALTER SYSTEM SET max_slot_wal_keep_size = '20GB';"
    local rule="hostssl replication $ROLE $standby/32 scram-sha-256"
    docker compose exec -T "$service" sh -c "grep -qxF '$rule' $PGDATA_IN/pg_hba.conf || echo '$rule' >> $PGDATA_IN/pg_hba.conf"
  done
  say "Порты 5432 и 5433 наружу — только для $standby"
  firewall_unit "$standby"
  write_override
  docker compose up -d db
  has_service support_db && docker compose up -d support_db
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
  say "Останавливаю магазин на этом сервере (резерв только хранит копию баз)"
  docker compose stop backend backend_standby worker bot mail_receiver support_pro support_worker support_migrate caddy 2>/dev/null || true
  for cluster in "${CLUSTERS[@]}"; do
    read -r service user port <<<"$cluster"
    has_service "$service" || continue
    docker compose stop "$service"
    say "$service: копирую с $primary:$port (pg_basebackup, может занять время)"
    docker compose run --rm --no-deps -e PGPASSWORD="$password" --entrypoint sh "$service" -c "
      set -e
      rm -rf $PGDATA_IN.new && mkdir -p $PGDATA_IN.new
      pg_basebackup -d 'host=$primary port=$port user=$ROLE sslmode=require application_name=corgi_standby' \
        -D $PGDATA_IN.new -R -X stream -S $SLOT -P
      rm -rf $PGDATA_IN.old && { [ -d $PGDATA_IN ] && mv $PGDATA_IN $PGDATA_IN.old || true; }
      mv $PGDATA_IN.new $PGDATA_IN
      chown -R postgres:postgres $PGDATA_IN && chmod 700 $PGDATA_IN"
    docker compose up -d "$service"
  done
  docker compose up -d redis
  sleep 8
  cmd_status
  echo
  echo "Резерв следует за основным. Предыдущие данные этого сервера — в $PGDATA_IN.old внутри тома (удалите, когда убедитесь)."
  echo "Дальше: агент резерва (Резервные копии → Горячий резерв → «Команда установки агента»)."
}

cmd_status() {
  if has_service support_db; then
    echo "Support Pro: $(psql_on support_db support -c "SELECT CASE WHEN pg_is_in_recovery() THEN 'резерв, задержка ' || COALESCE(round(EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp()))::text, '?') || ' с' ELSE 'основной' END" 2>/dev/null || echo 'нет данных')"
  fi
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
  if has_service support_db && [[ "$(psql_on support_db support -c 'SELECT pg_is_in_recovery()')" == "t" ]]; then
    psql_on support_db support -c "SELECT pg_promote(true, 60);"
  fi
  rm -f docker-compose.override.yml
  say "Запускаю магазин здесь"
  docker compose up -d
  echo "Готово. Переключите DNS на этот сервер (агент делает это сам, если задан CF_API_TOKEN)."
  echo "Старый основной, когда вернётся: сначала bash scripts/hot-standby.sh demote, потом настройте его резервом."
}

cmd_demote() {
  say "Останавливаю магазин и базу: этот сервер больше не основной"
  docker compose stop backend backend_standby worker bot mail_receiver support_pro support_worker caddy db support_db 2>/dev/null || true
  systemctl disable --now corgi-standby-firewall.service 2>/dev/null || true
  rm -f docker-compose.override.yml
  echo "Чтобы сделать его резервом нового основного: на новом — hot-standby.sh primary <IP этого>, здесь — hot-standby.sh standby <IP нового>."
}

cmd_drop_slot() {
  for cluster in "${CLUSTERS[@]}"; do
    read -r service user port <<<"$cluster"
    has_service "$service" || continue
    psql_on "$service" "$user" -c "SELECT pg_drop_replication_slot('$SLOT') FROM pg_replication_slots WHERE slot_name = '$SLOT' AND NOT active;"
  done
  echo "Слоты удалены (если резерв был отключён)."
}

volume_dir() {
  # The docker volume of this compose project that ends with _NAME (project names differ between servers).
  local name; name="$(docker volume ls --format '{{.Name}}' | grep -E "_$1\$" | head -1)"
  [[ -n "$name" ]] && docker volume inspect -f '{{.Mountpoint}}' "$name"
}

cmd_files_key() {
  [[ -f "$FILES_KEY" ]] || ssh-keygen -q -t ed25519 -N '' -C corgi-standby-files -f "$FILES_KEY"
  echo "На основном сервере выполните:"
  echo "  bash scripts/hot-standby.sh files-allow '$(cat "$FILES_KEY.pub")' $(curl -fsS4 https://api.ipify.org 2>/dev/null || echo IP_ЭТОГО_СЕРВЕРА)"
}

cmd_files_allow() {
  local key="${1:?Публичный ключ из files-key}" from="${2:?IP резервного сервера}"
  valid_ip "$from"
  [[ "$key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || { echo "Это не ключ ssh-ed25519" >&2; exit 2; }
  local rrsync; rrsync="$(command -v rrsync || ls /usr/share/doc/rsync/scripts/rrsync /usr/share/rsync/scripts/rrsync 2>/dev/null | head -1)"
  [[ -n "$rrsync" ]] || { apt-get install -y rsync >/dev/null && rrsync="$(command -v rrsync || echo /usr/share/doc/rsync/scripts/rrsync)"; }
  chmod +x "$rrsync" 2>/dev/null || true
  local root=/var/lib/docker/volumes
  mkdir -p /root/.ssh && touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
  # Read-only, only the docker volumes directory, only from the standby's address, no shell, no forwarding.
  local line="command=\"$rrsync -ro $root\",from=\"$from\",restrict $key"
  grep -qF "$key" /root/.ssh/authorized_keys && sed -i "\|$key|d" /root/.ssh/authorized_keys
  echo "$line" >> /root/.ssh/authorized_keys
  echo "Готово: ключ резерва может только читать $root и только с $from."
}

cmd_files_sync() {
  local primary="${1:?IP основного сервера}"
  valid_ip "$primary"
  [[ -f "$FILES_KEY" ]] || { echo "Сначала: hot-standby.sh files-key" >&2; exit 2; }
  for volume in "${FILE_VOLUMES[@]}"; do
    local dest; dest="$(volume_dir "$volume")" || true
    [[ -n "$dest" ]] || continue
    # rrsync roots paths at /var/lib/docker/volumes; both servers use the same APP_DIR, so the volume names match.
    local project_volume; project_volume="$(basename "$(dirname "$dest")")"
    rsync -a --delete -e "ssh -i $FILES_KEY -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
      "root@$primary:$project_volume/_data/" "$dest/"
    echo "$volume: скопирован"
  done
}

case "${1:-}" in
  primary) shift; cmd_primary "$@" ;;
  standby) shift; cmd_standby "$@" ;;
  status) cmd_status ;;
  promote) cmd_promote ;;
  demote) cmd_demote ;;
  drop-slot) cmd_drop_slot ;;
  files-key) cmd_files_key ;;
  files-allow) shift; cmd_files_allow "$@" ;;
  files-sync) shift; cmd_files_sync "$@" ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
