> Актуальный дистрибутив: `v28.161.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# Резервная копия v21.5.1

CLI `scripts/backup.sh` создаёт согласованную копию магазина и встроенного Support Pro. Она включает обе PostgreSQL базы в custom-format, media, мобильные пакеты, uploads Support Pro и все environment-файлы. Redis и удалённая Remnawave не входят в этот архив: состояние внешней VPN-панели сверяется отдельно.

## Создание

```bash
cd /opt/vpn-shop
sudo bash scripts/backup.sh
```

Введите пароль шифрования из 12–1024 символов. Сохраните его отдельно от архива: восстановить пароль невозможно. Для другого каталога: `sudo env BACKUP_DEST=/secure/backup bash scripts/backup.sh`.

Скрипт блокирует второй CLI-запуск, на короткое время останавливает только работающие writers магазина/Support Pro, делает дампы и файловые снимки, затем возобновляет эти же сервисы. Если snapshot не удался, сервисы также возобновляются, а неполный результат удаляется. Следите за сообщением об ошибке перезапуска и `docker compose ps`.

В `/var/backups/vpn-shop` появляются `shop-TIMESTAMP-RANDOM.vpb` и `.vpb.sha256`, с правами файла 0600. Архив шифруется потоковым AES-256-GCM; пароль обрабатывается scrypt с отдельной солью. Каждый блок, порядок и обязательное завершение потока проверяются. После создания скрипт выполняет проверочную дешифрацию без извлечения.

## Сохранение вне сервера

Скопируйте **зашифрованный** `.vpb` и SHA256 в отдельное хранилище. Из Windows/OpenSSH или другой командной строки:

```bash
scp root@SERVER_IP:/var/backups/vpn-shop/shop-TIMESTAMP-RANDOM.vpb .
scp root@SERVER_IP:/var/backups/vpn-shop/shop-TIMESTAMP-RANDOM.vpb.sha256 .
```

Замените имя точным результатом скрипта. В Termius можно использовать SFTP. Не скачивайте распакованные environment-файлы в публичные каталоги.

Вместе с копией запишите версию установленного дистрибутива. В Git-клоне сохраните вывод `git -C /opt/vpn-shop rev-parse HEAD` и `git -C /opt/vpn-shop tag --points-at HEAD`. Если тегов нет, сохраните полный SHA коммита. Для установки из скачанного архива сохраните имя файла, тег выпуска и SHA-256 дистрибутива. Поле `source_version` в копии формата 1 содержит версию runtime/API. Один и тот же runtime может входить в несколько выпусков.

## Проверка и подготовка к восстановлению

Проводите restore drill на отдельном сервере с тем же исходным релизом и изолированными volumes. Формат `.vpb` **не является** `.enc` из админ-панели и не загружается в её restore-форму.

На изолированном сервере с настроенным Compose и образом backend из исходного выпуска замените `shop-TIMESTAMP-RANDOM.vpb` именем вашей копии. В `/var/tmp` должно хватать места для расшифрованного архива.

```bash
(
  set -eu
  umask 077
  cd /var/backups/vpn-shop
  bundle=shop-TIMESTAMP-RANDOM.vpb
  actual=$(sha256sum -- "$bundle")
  if ! printf '%s\n' "$actual" | cmp -s - "$bundle.sha256"; then
    printf 'Имя архива или его SHA-256 расходится с файлом %s.sha256\n' "$bundle" >&2
    exit 1
  fi
  archive="$PWD/$bundle"
  cd /opt/vpn-shop
  read -rsp 'Пароль копии: ' BACKUP_BUNDLE_PASSWORD
  printf '\n'
  export BACKUP_BUNDLE_PASSWORD
  work=$(mktemp -d /var/tmp/shop-recovery.XXXXXXXX)
  if docker compose run --rm --no-deps -T -e BACKUP_BUNDLE_PASSWORD --entrypoint python backend /project/scripts/backup_bundle.py decrypt < "$archive" > "$work/recovery.tar" &&
      tar -tf "$work/recovery.tar"; then
    printf 'Архив для восстановления: %s/recovery.tar\n' "$work"
  else
    rm -f "$work/recovery.tar"
    rmdir "$work"
    exit 1
  fi
)
```

Команда сверяет с файлом, созданным `scripts/backup.sh`, и SHA-256, и имя выбранного архива. Если рядом лежит контрольная сумма другой копии, проверка останавливается до запроса пароля. Вывод ранних блоков возможен даже при повреждении конца архива, поэтому список файлов проверяется после успешного окончания расшифровки. При ошибке временный файл удаляется.

Подставьте путь к `recovery.tar`, который вывела предыдущая команда. Эта проверка читает данные непосредственно из архива, сверяет его состав и SHA-256 каждого файла с `backup-manifest.json` и выводит версию runtime/API, записанную при создании копии.

```bash
archive=/var/tmp/shop-recovery.XXXXXXXX/recovery.tar
python3 - "$archive" <<'PY'
import hashlib
import json
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:") as bundle:
    members = {}
    for member in bundle:
        name = member.name[2:] if member.name.startswith("./") else member.name
        if member.isdir() and name in ("", "."):
            continue
        if not member.isfile() or not name or name in (".", "..") or "/" in name or name in members:
            sys.exit(f"Неожиданная запись архива: {member.name}")
        members[name] = member
    if "backup-manifest.json" not in members:
        sys.exit("Отсутствует backup-manifest.json")
    with bundle.extractfile(members.pop("backup-manifest.json")) as stream:
        manifest = json.load(stream)
    required = {"shop.dump", "media.tar.gz", "app-packages.tar.gz", "environment.tar.gz"}
    support = {"support.dump", "support-uploads.tar.gz"}
    if support.intersection(members):
        required.update(support)
    expected = manifest.get("files")
    if manifest.get("format") != 1 or not isinstance(expected, dict) or set(expected) != set(members) or not required.issubset(members):
        sys.exit("Состав архива расходится с манифестом формата 1")
    for name, member in members.items():
        digest = hashlib.sha256()
        with bundle.extractfile(member) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected[name]:
            sys.exit(f"Не совпал SHA-256: {name}")
    print("Проверено файлов:", len(members), "Версия runtime/API:", manifest["source_version"])
PY
```

После успешной проверки продолжайте восстановление в каталоге с правами 0700. В `environment.tar.gz` находятся секреты. Сохраните текущие секреты отдельно и согласуйте ключи шифрования приложения и пароли БД с восстановленным окружением. Если в исходном магазине работал Support Pro, проверьте наличие обоих файлов `support.dump` и `support-uploads.tar.gz`.

Для нового изолированного контура остановите writers. Восстановите `shop.dump` штатным `pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error -U vpnshop -d vpnshop`; `support.dump` — аналогично в `support_db` с пользователем/базой `support`. Сначала проверьте `pg_restore --list`. Затем восстановите файловые архивы в соответствующие пустые volumes, окружение и исходную версию, примените миграции выбранного последующего релиза и проверьте health/worker/историю/файлы. При ошибке восстановления не возобновляйте продажи.

Этот CLI не выполняет автоматический restore в действующую базу. Старый `update.sh`/`rollback.sh` делает снимок только основной базы; он не является согласованным откатом встроенного Support Pro. Перед обновлением двух компонентов нужна именно полная копия и проверенный регламент восстановления.

## Учения по восстановлению в CI

Каждый PR и каждый коммит в `main` проходит учения `scripts/ci/restore-drill.sh` (задание «Containers» в `ci.yml`):

1. в работающий магазин добавляются клиент, тариф, подписка, оплаченный платёж, администратор и файл в media;
2. сервисы-писатели останавливаются, записывается число строк каждой таблицы обеих баз (магазин и Support Pro);
3. `scripts/backup.sh` делает зашифрованную копию (пароль создаётся на один прогон и нигде не печатается);
4. теряется всё: контейнеры, все тома и оба `.env`;
5. восстановление только из копии — расшифровка, сверка `backup-manifest.json`, окружение, `pg_restore` обеих баз, media, пакеты приложений, вложения Support Pro;
6. число строк каждой таблицы, подписка, платёж, администратор и файл совпадают с тем, что было до потери;
7. магазин запускается, администратор входит своим паролем.

Если хоть одна проверка не совпала, задание падает, и PR не вливается. Redis и внешняя панель Remnawave в копию не входят — это ограничение формата, а не учений.

## Регулярность

CLI не добавляет cron, retention или S3 автоматически. Для регулярного расписания используйте конфигурацию админ-панели с её форматом копий, либо собственный планировщик с безопасной передачей `BACKUP_BUNDLE_PASSWORD`, мониторингом кода выхода и внешним хранением. Административный backup основного магазина не заменяет согласованную копию двух баз.
