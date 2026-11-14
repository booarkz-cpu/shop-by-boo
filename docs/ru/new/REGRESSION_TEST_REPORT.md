# Регрессия — этап 18

Ошибки, найденные на этапе 18, и тесты, которые не дают им вернуться. Все тесты входят в обычный CI.

| Ошибка | Выпуск | Тест |
| --- | --- | --- |
| Выпуск v28.77.0 вышел без Android-приложений: новый apksigner печатает отпечаток только с `--verbose` | v28.77.1 | `tests/test_download_links.py`, сверка отпечатка в `scripts/build-android-apk.sh` |
| Ссылки на приложения в кабинете вели на сборки 2.10.0 старого репозитория | v28.77.0 | `tests/test_download_links.py`, `tests/test_v310.py` |
| «Документы»: баннер, загруженный сразу после «Сохранить», терялся; нестабильный e2e | v28.77.0 | `apps/lucy-admin/web/e2e/documents-banner.spec.ts` |
| Счётчики «Чеки в налоговую» и похожие склеивали подпись с числом | v28.77.0 | скриншоты разделов, `tests/test_screenshots.py` |
| Разделы без пункта меню не открывались: защита вкладок отправляла на «Все разделы» | v28.78.0 | `apps/lucy-admin/web/e2e/all-sections.spec.ts` («sections without a menu item open by link») |
| Последний активный администратор мог понизить, отключить или удалить себя | v28.78.0 | `tests/test_admin_coverage_security.py::test_administrators_and_the_last_active_admin` |
| Скидка акции и промокода проверялась только при создании | v28.78.0 | `tests/test_admin_coverage_marketing.py` |
| Подарочная карта создавалась в чужой валюте; код иногда 23 символа вместо 24 | v28.78.0 | `tests/test_admin_coverage_payments.py::test_gift_card_in_the_shop_currency_only` |
| Изменения ключей API, вебхуков, почты, DKIM, агентов, модулей, чёрного списка, порога торрентов и сброс подключений не попадали в журнал | v28.78.0 | `tests/test_admin_coverage_platform.py` |
| Имя домена с переводом строки в конце проходило проверку мастера | v28.78.0 | `tests/test_rw_tinyauth.py::test_names_with_a_trailing_newline_never_reach_a_caddyfile` |
| Новые версии Xray не пускают клиентов VLESS к внутренним адресам сервера (учтено в тесте VPN) | v28.77.0 | `scripts/mobile/vpn-e2e.sh`, `scripts/mobile/client-vpn-e2e.sh` |

Нестабильный тест `support-pro` `test_totp_replay_rejected` исправлен в v28.86.0: он брал «текущий» код TOTP, и на границе 30-секундного окна это был новый, действительный код. Теперь повторно отправляется именно тот код, которым выполнен вход.
