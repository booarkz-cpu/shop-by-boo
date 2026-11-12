#!/usr/bin/env python3
"""Generated parts of docs/architecture: the containers (from docker-compose.yml) and the API catalogue by area
(from docs/API_ENDPOINTS.md, itself generated from OpenAPI).

    python3 scripts/generate-architecture-docs.py          # write
    python3 scripts/generate-architecture-docs.py --check  # fail when the files are stale
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/architecture"
ROLE = {
    "volume_init": "Готовит права на томах перед запуском остальных служб",
    "redis": "Блокировки, идемпотентность, предохранитель запросов к панели, кэш",
    "db": "База магазина",
    "backend": "API магазина: клиенты, платежи, подписки, панель администратора",
    "backend_standby": "Запасной экземпляр API (включается профилем)",
    "worker": "Фоновые задачи: выдача и продление доступа, расписания, проверки",
    "mail_receiver": "Приём почты служебных адресов (включается профилем)",
    "bot": "Telegram-бот",
    "admin": "Веб-панель администратора (статические файлы)",
    "miniapp": "Mini App Telegram (статические файлы)",
    "cabinet": "Личный кабинет (статические файлы)",
    "support_db": "База Support Pro",
    "support_redis": "Очереди и блокировки Support Pro",
    "support_migrate": "Миграции базы Support Pro, выполняется и завершается",
    "support_pro": "API Support Pro: обращения, переписка, база знаний",
    "support_worker": "Фоновые задачи Support Pro",
    "caddy": "Единственная точка входа: HTTPS, маршрутизация по доменам, заголовки безопасности",
}
AREAS = [
    ("/api/admin/rw", "Remnawave: установка, ноды, расширения (панель администратора)"),
    ("/api/admin", "Панель администратора"),
    ("/api/webhooks", "Webhook платёжных провайдеров и внешних систем"),
    ("/api/payments", "Платежи"),
    ("/api/auth", "Вход и учётные записи"),
    ("/api/me", "Данные вошедшего клиента"),
    ("/api/mobile", "Мобильные приложения"),
    ("/api/support", "Поддержка"),
    ("/api/agent", "Агенты нод"),
    ("/api", "Остальной API магазина"),
    ("/health", "Проверки готовности"),
    ("/sub", "Выдача подписки"),
    ("/", "Прочее: служебные файлы, ссылки, загрузки"),
]


def image(service: dict) -> str:
    build = service.get("build")
    if isinstance(build, dict):
        return f"сборка `{build.get('context', '.').lstrip('./') or '.'}/{build.get('dockerfile', 'Dockerfile')}`".replace("`./", "`")
    if isinstance(build, str):
        return f"сборка `{build.lstrip('./')}`"
    name = str(service.get("image") or "")
    match = re.search(r":-([^}@]+)", name)
    return f"образ `{match.group(1) if match else name.split('@')[0]}`" if name else "как у основной службы"


def host_port(mapping) -> str:
    """The port on the host: `80`, `443/udp`, or the default of a configurable one."""
    text = str(mapping)
    default = re.match(r"^\$\{[A-Z_]+:-(\d+)\}", text)
    host = default.group(1) + " (по умолчанию)" if default else text.split(":")[0]
    return host + ("/udp" if text.endswith("/udp") else "")


def containers() -> str:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    missing = sorted(set(services) - set(ROLE))
    if missing:
        raise SystemExit(f"describe these services in ROLE of scripts/generate-architecture-docs.py: {missing}")
    lines = ["# Контейнеры", "",
             "Сгенерировано из `docker-compose.yml`: `python3 scripts/generate-architecture-docs.py`. Руками не править.", "",
             "Всё работает на одном сервере в Docker Compose. Наружу открыты только порты Caddy и, при включённом профиле `mail`, порт приёма почты.", "",
             "| Служба | Назначение | Откуда | Порты наружу | Проверка готовности | Зависит от | Профиль |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, service in services.items():
        ports = ", ".join(f"`{host_port(p)}`" for p in service.get("ports") or []) or "—"
        deps = ", ".join(f"`{d}`" for d in (service.get("depends_on") or {})) or "—"
        profile = ", ".join(f"`{p}`" for p in service.get("profiles") or []) or "всегда"
        lines.append(f"| `{name}` | {ROLE[name]} | {image(service)} | {ports} | {'есть' if service.get('healthcheck') else 'нет'} | {deps} | {profile} |")
    lines += ["", "## Сети", "",
              "| Сеть | Кто в ней |", "| --- | --- |"]
    by_net = collections.defaultdict(list)
    for name, service in services.items():
        for net in (service.get("networks") or ["default"]):
            by_net[net].append(name)
    for net in sorted(by_net):
        lines.append(f"| `{net}` | {', '.join(f'`{n}`' for n in by_net[net])} |")
    lines += ["", "## Тома", "", "| Том | Кто подключает |", "| --- | --- |"]
    volumes = collections.defaultdict(list)
    for name, service in services.items():
        for volume in service.get("volumes") or []:
            source = volume.split(":")[0] if isinstance(volume, str) else str(volume.get("source"))
            if source in (compose.get("volumes") or {}):
                volumes[source].append(name)
    for volume in sorted(volumes):
        lines.append(f"| `{volume}` | {', '.join(f'`{n}`' for n in volumes[volume])} |")
    lines += ["", "## Схема", "", "```mermaid", "flowchart LR", "  internet((Интернет)) --> caddy"]
    for name, service in services.items():
        for dep in service.get("depends_on") or {}:
            if dep != "volume_init":
                lines.append(f"  {name} --> {dep}")
    lines += ["```", ""]
    return "\n".join(lines)


def api_catalog() -> str:
    text = (ROOT / "docs/API_ENDPOINTS.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)` \| `([^`]+)` \| [^|]* \| ([^|]+) \|$", text, re.M)
    if len(rows) < 100:
        raise SystemExit("docs/API_ENDPOINTS.md has an unexpected format")
    count, methods, access = collections.Counter(), collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for method, path, who in rows:
        area = next(title for prefix, title in AREAS if path == prefix or path.startswith(prefix.rstrip("/") + "/") or prefix == "/")
        count[area] += 1
        methods[area][method] += 1
        access[area]["право роли" if who.strip().startswith("право") else who.strip()] += 1
    lines = ["# Каталог API по областям", "",
             "Сгенерировано из [API_ENDPOINTS.md](../API_ENDPOINTS.md): `python3 scripts/generate-architecture-docs.py`. Руками не править.", "",
             f"Всего маршрутов: **{len(rows)}**. Полный перечень с правами — в [API_ENDPOINTS.md](../API_ENDPOINTS.md); "
             "общие правила (вход, CSRF, ошибки) — в [API.md](../ru/new/API.md).", "",
             "| Область | Начало пути | Маршрутов | Методы | Кто вызывает |", "| --- | --- | ---: | --- | --- |"]
    for prefix, title in AREAS:
        if count[title]:
            m = ", ".join(f"{k} {v}" for k, v in sorted(methods[title].items()))
            a = "; ".join(f"{k}: {v}" for k, v in access[title].most_common(3))
            lines.append(f"| {title} | `{prefix}` | {count[title]} | {m} | {a} |")
    lines += ["", "API один на все клиенты: бот, Mini App, кабинет, веб-панель и мобильные приложения ходят в один `backend`.",
              "Support Pro — отдельная служба со своим API и своей базой за тем же Caddy.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, text in (("CONTAINER_DIAGRAM.md", containers()), ("API_CATALOG.md", api_catalog())):
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(path.relative_to(ROOT))
    if stale:
        print(f"stale: {stale}; run python3 scripts/generate-architecture-docs.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
