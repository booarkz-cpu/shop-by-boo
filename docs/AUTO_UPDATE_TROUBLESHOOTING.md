# Автообновление: устранение неполадок

Дистрибутив `v28.56.0`, runtime/API `21.5.1`. Механизм: [AUTO_UPDATE.md](AUTO_UPDATE.md).
Безопасность: [AUTO_UPDATE_SECURITY.md](AUTO_UPDATE_SECURITY.md).

Все команды ниже — от root на сервере, если не указано иное. `APP_DIR` по умолчанию `/opt/vpn-shop`.

## Быстрая диагностика

```bash
sudo bash /opt/vpn-shop/scripts/auto-update.sh status
sudo systemctl status vpn-shop-update.timer --no-pager
sudo systemctl status vpn-shop-update-agent.timer --no-pager
sudo journalctl -u vpn-shop-update -n 100 --no-pager
sudo journalctl -u vpn-shop-update-agent -n 100 --no-pager
cat /opt/vpn-shop/.control/auto-update.status.json
cat /etc/vpn-shop/auto-update.json
```

Если `status` показывает установленную версию `?`, значит `github_release_fetch.current_distribution()`
не смогла прочитать `release-manifest.template.json` — дерево повреждено или запущено не из `APP_DIR`.

## Симптом → причина → действие

### «Агент автообновления не установлен» / панель показывает `setup_hint`

API вернул `503` или `available: false`.

Причина: каталог `.control` отсутствует или недоступен на запись процессу backend.

```bash
sudo mkdir -p /opt/vpn-shop/.control
sudo chown 10001:10001 /opt/vpn-shop/.control   # UID backend-а (backend/Dockerfile)
sudo -u '#10001' test -w /opt/vpn-shop/.control && echo writable
```

В контейнере путь другой — `/data/control`. Проверьте, что том смонтирован и доступен на запись.

### `agent_alive: false`

Причина: `agent_seen_at` в `status.json` старше 5 минут (`AGENT_FRESH = timedelta(minutes=5)`) —
таймер агента не работает.

```bash
sudo systemctl status vpn-shop-update-agent.timer --no-pager
sudo systemctl enable --now vpn-shop-update-agent.timer
sudo systemctl start vpn-shop-update-agent.service
```

### Ночью обновление не запускается

Проверьте по порядку:

1. `enabled` в `/etc/vpn-shop/auto-update.json` равен `true`;
2. `sudo systemctl is-enabled vpn-shop-update.timer` → `enabled`;
3. `next_run` в статусе не пустой; если пустой — systemd не отдаёт `NextElapseUSecRealtime`;
4. `Persistent=true` означает, что пропущенный запуск выполнится после загрузки — не паникуйте,
   если обновление прошло днём после перезагрузки;
5. `RandomizedDelaySec=900` — срабатывание может быть на 15 минут позже указанного времени.

```bash
sudo systemctl list-timers 'vpn-shop-update*' --no-pager
```

### `last_result: current` — «версия актуальна»

Это не ошибка. `version_tuple(latest) > version_tuple(current)` ложно: на GitHub нет более новой
стабильной версии.

Если вы уверены, что релиз есть, проверьте, что он **не** `draft` и **не** `prerelease`, а тег
строго вида `vX.Y.Z`:

```bash
curl -s https://api.github.com/repos/booarkz-cpu/shop-by-boo/releases/latest \
  | jq '{tag_name, draft, prerelease, assets: [.assets[].name]}'
```

### `last_result: failed`, `failed_release` заполнен

`failed_release` — версия, которая не установилась. Ночью она **повторно не ставится**
(файл `/etc/vpn-shop/auto-update.failed`). Кнопка «Обновить сейчас» пробует снова.

```bash
sudo cat /etc/vpn-shop/auto-update.failed
sudo cat /opt/vpn-shop/.control/auto-update.status.json | jq '.status.log_tail'
sudo journalctl -u vpn-shop-update -n 200 --no-pager | tail -50
```

Действия: устранить причину (см. ниже), затем либо повторить из панели, либо
`sudo bash scripts/auto-update.sh run`, либо сбросить блокировку:

```bash
sudo rm -f /etc/vpn-shop/auto-update.failed
```

### `recovery_mode: true`

Сервер в режиме восстановления после неудачного обновления: автообновление остановлено до ручной
проверки. Флаг — `/opt/vpn-shop/.rollback/RECOVERY_MODE` (ставится `scripts/rollback.sh`).

```bash
ls -la /opt/vpn-shop/.rollback/
sudo bash /opt/vpn-shop/scripts/doctor.sh
docker compose ps
curl -s localhost:8000/health | jq .
```

Убедившись, что магазин работает, снимите флаг:

```bash
sudo rm -f /opt/vpn-shop/.rollback/RECOVERY_MODE
```

### «GitHub не ответил» (`502`)

API не смог получить `releases/latest`. Причины: нет исходящей сети, лимит GitHub API, DNS.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/booarkz-cpu/shop-by-boo/releases/latest
```

`403` без токена — исчерпан анонимный лимит (60 запросов/час на IP). Обновление это не ломает:
агент обращается к API отдельно. Подождите час или используйте аутентифицированный запрос.

### «Несовпадение контрольной суммы» / ошибка манифеста

`github_release_fetch.py` прекращает установку. Это защита, а не поломка.

Проверьте вручную:

```bash
TAG=v28.56.0
cd /tmp && rm -rf verify && mkdir verify && cd verify
BASE="https://github.com/booarkz-cpu/shop-by-boo/releases/download/$TAG"
ZIP="remnawave_vpn_shop_v${TAG#v}_full_release.zip"
curl -sSLO "$BASE/$ZIP" && curl -sSLO "$BASE/$ZIP.sha256"
sha256sum -c "$ZIP.sha256"
```

Если хеш не сходится — **не устанавливайте** релиз. Дождитесь исправленного релиза или обратитесь
к владельцу репозитория.

### Недостаточно места на диске

Обновление распаковывает архив и делает снимок (`.rollback`), хранится `KEEP_SNAPSHOTS = 5`.

```bash
df -h /opt /var/lib/docker
du -sh /opt/vpn-shop/.rollback
```

Удалите старые снимки, оставив последний успешный:

```bash
ls -lt /opt/vpn-shop/.rollback/*.tar.gz | tail -n +3
```

### Ошибка сборки образов или перезапуска

Откат выполняется автоматически (`trap rollback ERR`). Если откат тоже не удался:

```bash
docker compose ps
docker compose logs --tail=200 backend
sudo bash scripts/rollback.sh                       # последний снимок + latest.sql
sudo bash scripts/rollback.sh /path/to/snapshot.tar.gz /path/to/dump.sql
```

`rollback.sh` требует **и** архив, **и** дамп БД. Без дампа он откажется работать и не тронет
установку — это осознанное поведение.

### Проверки здоровья не проходят после обновления

```bash
curl -s localhost:8000/health/live  | jq .
curl -s localhost:8000/health/ready | jq .
docker compose logs --tail=200 backend
docker compose logs --tail=100 db
```

`/health/ready` возвращает `redis` и `database`. Если `database: false` — вероятна неудачная
миграция. Смотрите журнал Alembic в логах backend и сверяйте head:

```bash
cd /opt/vpn-shop/backend && alembic heads
```

### «Обновление уже идёт» (`409`)

Защита от параллельного запуска. Если обновление действительно зависло:

```bash
sudo systemctl status vpn-shop-update.service --no-pager
sudo journalctl -u vpn-shop-update -n 50 --no-pager
```

Дождитесь завершения — `TimeoutStartSec=2h`. Не удаляйте `.control/*.json` во время работы:
агент потеряет состояние.

### Кнопка «Обновить сейчас» не реагирует

Запрос уже отправлен (`pending_run: true`) — агент выполнит его в течение минуты. Если агент не
работает, смотрите раздел `agent_alive: false`.

## Что нельзя делать

- **Не** редактируйте `auto-update.status.json` руками: агент перезапишет его, а расхождение
  сбивает диагностику.
- **Не** удаляйте `/etc/vpn-shop/auto-update.failed` без устранения причины: следующий ночной
  запуск повторит неудачную установку.
- **Не** запускайте `update.sh` параллельно с ночным таймером — используйте `flock`-защищённые
  скрипты (`backup.sh`) и дождитесь завершения текущего прогона.
- **Не** отключайте проверку SHA-256 «на время»: это единственный барьер против подмены артефакта.

## Сбор диагностики для передачи разработчику

```bash
{
  echo "== version =="; cat /opt/vpn-shop/release-manifest.template.json | jq '{version, distribution_tag, migration_head}'
  echo "== config =="; cat /etc/vpn-shop/auto-update.json
  echo "== timers =="; systemctl list-timers 'vpn-shop-update*' --no-pager
  echo "== status =="; cat /opt/vpn-shop/.control/auto-update.status.json
  echo "== journal =="; journalctl -u vpn-shop-update -n 200 --no-pager
  echo "== services =="; cd /opt/vpn-shop && docker compose ps
} > /tmp/autoupdate-diag.txt 2>&1
```

Перед отправкой откройте файл и убедитесь, что в нём нет значений из `.env`: снимки и журналы их
не печатают, но сторонние сообщения об ошибках могут содержать части URL с токеном.
