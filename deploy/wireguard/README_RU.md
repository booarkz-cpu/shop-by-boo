> Актуальный дистрибутив: `v28.22.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

> Текущий магазин v21.5.1: [общая документация](../../DOCUMENTATION.md). Следуйте текущему регламенту установки и границам готовности.

# Corgi Edge WireGuard

Скрипт `provision-node.sh` подготавливает Linux-ноду WireGuard для Corgi Edge.

Перед production запуском:
1. установить `wireguard-tools`;
2. выполнить скрипт на выделенной ноде;
3. зарегистрировать ноду через `/api/admin/v16/nodes/register`;
4. настроить peer provisioning через секретный control-plane канал;
5. проверить health-check и failover;
6. включить `wg-quick@wg-corgi`.

Скрипт не включает сбор пользовательского трафика и не записывает payload VPN.
