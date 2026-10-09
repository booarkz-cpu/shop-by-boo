> Актуальная инструкция для дистрибутива v27. Runtime/API `21.5.1`. Head магазина `0062_support_delivery_identity`, Support Pro `0006`/3.6.

# Обновление существующего магазина

Обновляйте исходники и обе схемы согласованно. Полная production-приёмка и все функции матрицы ещё не завершены; сначала повторите процедуру на изолированном стенде с проверенным backup. История прежних изменений — в [CHANGELOG](../../CHANGELOG.md).

## Подготовка

Запишите текущий tag/commit, compose-проект и volumes. Проверьте свободное место, сохраните собственные изменения в отдельной ветке и убедитесь, что нет выполняющегося restore или неопределённых платёжных операций. Сохраните `.env` и `support-pro/.env` отдельно с ограниченным доступом; не добавляйте их в Git. Не заменяйте namespace/origin моста или идентичности старых клиентов.

Для новой установки используется [production-регламент](PRODUCTION_CURRENT.md). Эту процедуру применяют к действующей установке с существующими данными.

## Согласованный snapshot

Объявите окно обслуживания. В общем Compose остановите writers **до** backup, чтобы после snapshot не появились новые платежи, ответы или файлы:

```bash
cd /opt/vpn-shop
git status --short
git rev-parse HEAD
docker compose stop backend worker bot support_pro support_worker
sudo bash scripts/backup.sh
```

CLI создаёт зашифрованный bundle обеих баз, файлов и environment. Writers, уже остановленные до его запуска, не возобновляются автоматически. Сохраните пароль отдельно, перенесите архив/SHA256 вне сервера и проверьте restore drill. [Полный регламент](BACKUP_CURRENT.md). В самостоятельном Support Pro остановите его собственные app/worker/bot и сделайте snapshot его БД/uploads в том же окне; встроенный bundle не охватывает внешний сервер автоматически.

## Установка точного стабильного тега

После сохранения собственных изменений и проверенного snapshot:

```bash
git fetch origin
git switch --detach v27
docker compose build backend worker bot admin cabinet miniapp support_migrate support_pro support_worker
docker compose up -d db redis support_db support_redis
docker compose run --rm backend alembic upgrade head
docker compose run --rm support_migrate
```

Не используйте `git reset --hard`, удаление volumes или обнуление migration history. Если checkout конфликтует с собственными файлами, остановитесь и перенесите их в проверенную ветку; работающий production не должен быть местом для разрешения такого конфликта.

Для standalone Support Pro примените его `python -m app.migrate` в существующем compose-проекте, сохранив его credentials/volumes. Ожидаются head магазина 0062 и Support Pro 0006. До запуска нового worker обязателен обновлённый API магазина.

## Запуск и проверка

```bash
docker compose up -d backend
docker compose ps
docker compose exec -T backend python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=3)'
docker compose exec -T backend alembic current
```

Дождитесь успешной readiness-проверки; при отказе смотрите logs и не запускайте writers. Затем:

```bash
docker compose up -d worker bot admin cabinet miniapp support_pro support_worker
bash scripts/doctor.sh
docker compose logs --tail=80 support_worker
```

Проверьте вход и права, баланс/финансовый журнал, старые подписки, частные файлы поддержки, редакторы страниц/офферы и дерево меню. Support Pro 0006 запускает полный обход старой связанной истории. До окончания первого обхода не применяйте merge/split к старым обращениям. После обхода проверьте один выбранный перенос, постоянные ID/файл, внутреннюю заметку, закрытый источник и его приостановленную очередь. [Регламент mapping](SUPPORT_REMOTE_HISTORY_CURRENT.md).

## Особенность автоматического updater

Существующий `scripts/update.sh` автоматически сохраняет и восстанавливает только основную БД; он не является согласованным rollback двух схем. При переходе на Support Pro 0006 используйте ручную процедуру выше и полный bundle. Не считайте сообщение updater об откате доказательством восстановления Support Pro. При неудаче после его миграции сначала остановите writers и восстановите обе базы/файлы из одной согласованной копии. Внешние платежи, принятые после snapshot, требуют отдельной сверки.

## Границы миграций и откат

| Миграция | Что проверить |
| --- | --- |
| 0058 | Импорт профилей/начальных остатков, журнал повторов; исторические VPN/платежи не импортируются |
| 0059/0060 | Неизменяемые публикации, ограничения аудитории и резервы промокодов |
| 0061 | Старые плоские кнопки остаются в корне; дерево/стили/emoji защищены от потери при downgrade |
| 0062 + Support Pro 0006 | Исходные delivery keys, версии структуры, постоянные remote IDs и приостановленная очередь объединённого источника |

Миграции применяются всей цепочкой через `upgrade head`, не выборочным запуском файлов. Downgrade использованной истории/структуры блокируется. При ошибке исправление вперёд предпочтительно; полный возврат требует остановки writers и восстановления **обеих БД, файлов и соответствующих исходников**. Не обнуляйте защитные поля SQL-командами. [Восстановление](BACKUP_CURRENT.md) · [Production](PRODUCTION_CURRENT.md) · [Матрица](WORKSPACE_COVERAGE.md).
