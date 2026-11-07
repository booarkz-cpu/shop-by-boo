"""«Установка» (v28.92.0, stage 20, N7): every operation on the owner's servers in one catalogue.

The catalogue only gathers what works elsewhere in the admin panel — a card either opens a section that does the job,
starts the installer, or plans a module of the installation that holds the chosen server (plan → approval → steps →
rollback, as in «Установка Remnawave»). Nothing here is a button without a function: operations that are not built yet
are not listed (docs/ru/new/BACKLOG.md, N7, keeps them).

For the chosen server the catalogue also says where it is on the way «Подготовьте сервер → Установите панель →
Подключите домен» and which installation a module would go to.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import RemnawaveInstallation, RemnawaveServer
from .security import require_permission, require_stepup

router = APIRouter(prefix="/api/admin/install")

GROUPS = {
    "panel": "Панель и подписки",
    "nodes": "VPN-ноды и маршруты",
    "protect": "Обслуживание и защита",
    "sales": "Продажи и кабинет клиента",
}

# id, group, title, what it does, over SSH, shown in «Простой», action
#   action: ("tab", <admin tab>) | ("install", None) | ("module", <module name>, <role it needs: node|any>)
#           | ("action", <installation action>) — snapshot; the «danger zone» is its own block of the section
OPS: tuple[tuple, ...] = (
    ("install_panel", "panel", "Установка Remnawave-панели", "Docker-стек панели, Caddy с сертификатом и токен API для магазина — мастер с планом и откатом.", True, True, ("install", None)),
    ("update_panel", "panel", "Обновить панель и ноды", "Проверенные версии образов: копия базы, обновление, проверка, откат; по расписанию или кнопкой.", True, True, ("tab", "releases")),
    ("panel_domain", "panel", "Открыть панель по домену", "Домен и сертификат панели, записи DNS, маршруты Caddy.", False, True, ("tab", "domains")),
    ("sub_page", "panel", "Страница подписки", "Своя страница: «добавить в приложение», QR, срок и трафик — рядом с панелью или отдельно.", False, True, ("tab", "subscriptionPortal")),
    ("panel_profiles", "panel", "Профили, хосты и сквады", "Профили конфигурации нод, хосты и внутренние сквады панели.", False, False, ("tab", "remnawave")),
    ("client_balancer", "panel", "Автовыбор сервера в приложении", "Балансировщик клиента (leastPing) в шаблоне подписки — без SSH.", False, False, ("tab", "rwExtensions")),
    ("add_node", "nodes", "Подключить ноду", "Нода к панели — один сервер или несколько сразу.", True, True, ("install", None)),
    ("all_protocols", "nodes", "Все протоколы на одной ноде", "TCP/xHTTP/gRPC + REALITY, Hysteria2, VLESS + TCP + TLS; отпечаток браузера, TLS 1.2/1.3.", True, True, ("module", "transports", "node")),
    ("selfsteal", "nodes", "Маскировка SelfSteal", "Свой сайт на домене ноды: сводка, проверка снаружи, свой архив, каталог шаблонов.", True, True, ("tab", "selfsteal")),
    ("node_port", "nodes", "Доступ панели к нодам", "Служебный порт нод — только для сервера панели, сразу на всех нодах; правило снимается, если панель потеряла ноду.", True, True, ("module", "node_port", "node")),
    ("routing_ru", "nodes", "Российские сервисы напрямую", "Маршрутизация на сервере: свои правила и российские сервисы мимо VPN.", False, False, ("tab", "rwExtensions")),
    ("ads_nodes", "nodes", "Блокировка рекламы на нодах", "Реклама и трекеры не открываются у всех клиентов профиля — правило geosite:category-ads-all на нодах, без SSH.", False, True, ("tab", "rwExtensions")),
    ("torrents", "nodes", "Торренты на нодах", "Блокировка BitTorrent плагином ноды и счётчики срабатываний.", False, False, ("tab", "torrents")),
    ("warp", "nodes", "WARP на ноде", "Интерфейс Cloudflare WARP для выхода к отдельным сервисам.", True, False, ("module", "warp", "node")),
    ("xray_core", "nodes", "Ядро Xray нужной версии", "Выпуск Xray-core с GitHub (SHA-256 сверяется) вместо ядра образа.", True, False, ("module", "xray_core", "node")),
    ("availability", "nodes", "Доступность нод", "Проверки из разных сетей, RIPE Atlas, качество подключений.", False, True, ("tab", "availability")),
    ("xray_checker", "nodes", "Проверка конфигов трафиком", "Xray Checker проверяет каждый сервер подписки настоящим соединением.", True, False, ("module", "xray_checker", "any")),
    ("mss_clamp", "nodes", "MSS clamp", "Меряет MTU пути до Cloudflare и Яндекса; если он меньше MTU интерфейса — включает MSS clamp. Нода не перезапускается.", True, False, ("module", "mss_clamp", "node")),
    ("hardening", "protect", "Базовая защита и ускорение", "fail2ban, обновления безопасности, BBR, SSH только с ваших адресов.", True, True, ("module", "hardening", "any")),
    ("node_guard", "protect", "Защита ноды (nftables)", "Лимит новых соединений с одного адреса на портах ноды, автобан на 10 минут; ваш адрес, панель и CGNAT — без ограничений.", True, True, ("module", "node_guard", "node")),
    ("swap", "protect", "Файл подкачки", "Swap нужного размера и vm.swappiness=10 после проверки свободного места.", True, False, ("module", "swap", "any")),
    ("watchdog", "protect", "Самовосстановление", "Таймер на сервере поднимает остановленные контейнеры и перезапускает зависшую панель.", True, True, ("module", "watchdog", "any")),
    ("ipv6", "protect", "IPv6 на сервере", "Включить или выключить IPv6 (прежняя настройка возвращается при ошибке).", True, False, ("module", "ipv6", "any")),
    ("netbird", "protect", "Частная сеть NetBird", "Серверы в одной сети NetBird по ключу установки.", True, False, ("module", "netbird", "any")),
    ("https_status", "protect", "Статус-страница VPN", "Публичная страница статуса сервиса на своём домене.", False, True, ("tab", "status")),
    ("alerts", "protect", "Оповещения", "Мониторинг и уведомления о сбоях.", False, True, ("tab", "monitoring")),
    ("backups", "protect", "Резервные копии", "Копии базы магазина и панели, проверка восстановления, копия в Telegram.", False, True, ("tab", "backups")),
    ("snapshot", "protect", "Снапшот сервера → скачать", "Копия базы панели и файлы всех компонентов (compose, .env, Caddyfile, сайт) — зашифрованы в магазине, скачиваются с подтверждением 2FA.", True, True, ("action", "snapshot")),
    ("terminal", "protect", "Терминал сервера", "Командная оболочка на сервере с подтверждением 2FA и записью сессии.", True, False, ("tab", "nodeTerminal")),
    ("remove", "protect", "Удалить установку", "Остановить и убрать контейнеры установки (тома и копии остаются) — в «Установка Remnawave».", True, False, ("tab", "rwInstaller")),
    ("bot", "sales", "Telegram-бот продаж", "Свой бот магазина: меню, оплата, подписки.", False, True, ("tab", "telegramBot")),
    ("cabinet", "sales", "Веб-кабинет клиента", "Кабинет и Mini App: вкладки, страницы, тексты.", False, True, ("tab", "cabinet")),
    ("plans", "sales", "Тарифы и цены", "Тарифы, региональные цены, пробный период.", False, True, ("tab", "plans")),
    ("payments", "sales", "Кассы и способы оплаты", "Подключение касс и проверка платежей.", False, True, ("tab", "providers")),
)


def catalogue() -> list[dict]:
    out = []
    for op_id, group, title, text, ssh, simple, action in OPS:
        out.append({"id": op_id, "group": group, "title": title, "text": text, "ssh": ssh, "simple": simple,
                    "action": {"kind": action[0], "tab": action[1] if action[0] == "tab" else None,
                               "name": action[1] if action[0] == "action" else None,
                               "module": action[1] if action[0] == "module" else None,
                               "needs": action[2] if action[0] == "module" else None}})
    return out


async def server_state(db: AsyncSession, server_id: int) -> dict:
    """Where the server is on the way and which installation holds it (the latest succeeded one, not removed)."""
    server = await db.get(RemnawaveServer, server_id)
    if not server:
        raise HTTPException(404, "Сервер не найден")
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "install",
                                                                 RemnawaveInstallation.status == "succeeded")
                             .order_by(RemnawaveInstallation.id.desc()))).scalars().all()
    removed = {r.source_installation_id for r in (await db.execute(select(RemnawaveInstallation).where(
        RemnawaveInstallation.action == "remove", RemnawaveInstallation.status == "succeeded"))).scalars().all()}
    holder = next((r for r in rows if server_id in (r.server_ids or []) and r.id not in removed), None)
    roles = sorted({role for sid, rs in ((holder.plan or {}).get("servers") or {}).items() if int(sid) == server_id for role in rs.get("roles", [])}) \
        if holder else []
    params = holder.params if holder else {}
    return {"server": {"id": server.id, "name": server.name, "host": server.host, "status": server.status},
            "installation_id": holder.id if holder else None, "roles": roles,
            "steps": {"prepared": server.status not in ("new", "unreachable"), "panel": "panel" in roles or "node" in roles,
                      "domain": bool(params.get("panel_domain") or params.get("selfsteal_domain") or params.get("node_domain"))}}


@router.get("/catalogue")
async def get_catalogue(server_id: int | None = None, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    state = await server_state(db, server_id) if server_id else None
    ops = catalogue()
    if state:
        for op in ops:
            needs = op["action"]["needs"]
            needs_install = op["action"]["kind"] in ("module", "action")
            op["ready"] = not needs_install or (state["installation_id"] is not None and (needs != "node" or "node" in state["roles"]))
    return {"groups": GROUPS, "operations": ops, "state": state, "total": len(ops)}


# ---------------------------------------------------------------- snapshots (encrypted in the shop)

SNAPSHOT_NAME = re.compile(r"^(config-\d+-\d{8}T\d{6}Z\.tar\.gz|panel-\d+-\d{8}T\d{6}Z\.dump)\.enc$")


@router.get("/snapshots")
async def snapshots(admin=Depends(require_permission("backups.read"))):
    from .rw_steps import panel_copies_dir
    folder = panel_copies_dir()
    files = sorted((f for f in folder.glob("*.enc") if SNAPSHOT_NAME.match(f.name)), key=lambda f: f.name.split("-", 2)[2], reverse=True) \
        if folder.is_dir() else []
    return {"snapshots": [{"name": f.name, "kind": "files" if f.name.startswith("config-") else "database",
                           "server_id": int(f.name.split("-")[1]), "size": f.stat().st_size,
                           "created_at": datetime.strptime(f.name.split("-")[2][:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()}
                          for f in files[:60]]}


@router.get("/snapshots/{name}")
async def download_snapshot(name: str, db: AsyncSession = Depends(get_db), admin=Depends(require_stepup("backups.write"))):
    """A snapshot decrypted: the files as tar.gz, the panel's database in pg_dump -Fc format."""
    from .main import audit
    from .rw_steps import panel_copies_dir, unseal
    if not SNAPSHOT_NAME.match(name):
        raise HTTPException(404, "Нет такого снапшота")
    path = panel_copies_dir() / name
    if not path.is_file():
        raise HTTPException(404, "Нет такого снапшота")
    try:
        data = unseal(path.read_bytes())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit(db, "install.snapshot.downloaded", admin.email, name, {"size": len(data)})
    await db.commit()
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name.removesuffix(".enc")}"'})
