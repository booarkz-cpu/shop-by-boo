## Русский

Тестовый стенд публикует TCP 18080–18083 на всех интерфейсах. `scripts/test-up.sh` вызывает `scripts/open-ports.sh` и открывает эти порты в файрволе хоста: ufw, firewalld или iptables.

Установщик VDS (`infrastructure/deployment/install-vps.sh`) открывает SSH, TCP 80, TCP 443 и UDP 443. PostgreSQL, Redis и порт приложения наружу не публикуются.

Если у хостера есть отдельный файрвол панели, в нём нужно разрешить те же порты: гостевая система его не меняет.

Версия приложения остаётся 20.0.0.

## English

The test stand publishes TCP 18080–18083 on every interface. `scripts/test-up.sh` calls `scripts/open-ports.sh` and opens those ports in the host firewall: ufw, firewalld, or iptables.

The VDS installer (`infrastructure/deployment/install-vps.sh`) opens SSH, TCP 80, TCP 443 and UDP 443. PostgreSQL, Redis and the application port stay unpublished.

A hoster panel firewall, when present, must allow the same ports. The guest system cannot change it.

The application version remains 20.0.0.

## Українська

Тестовий стенд публікує TCP 18080–18083 на всіх інтерфейсах. `scripts/test-up.sh` викликає `scripts/open-ports.sh` і відкриває ці порти у файрволі хоста: ufw, firewalld або iptables.

Встановлювач VDS (`infrastructure/deployment/install-vps.sh`) відкриває SSH, TCP 80, TCP 443 і UDP 443. PostgreSQL, Redis і порт застосунку назовні не публікуються.

Якщо в хостера є окремий файрвол панелі, у ньому треба дозволити ті самі порти: гостьова система його не змінює.

Версія застосунку лишається 20.0.0.
