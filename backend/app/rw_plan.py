"""Installation plans of the Remnawave wizard (v28.66, stage 10; docs/ru/new/REMNAWAVE_INSTALLATION_MODES.md).

A mode is a set of roles on servers (``panel``, ``node``, ``subscription_page``). ``build_plan`` turns the
administrator's choice into an ordered list of steps of the closed list (rw_steps.STEP_KINDS) with their
parameters, plus what will change on each server. Nothing here talks to a server.

The files the steps write are built here from typed values, following the official ``docker-compose-prod.yml``
and ``.env.sample`` of remnawave/backend, remnawave/node and remnawave/subscription-page. Images are pinned by
digest: the digests below were read in CI (.github/workflows/resolve-image-digests.yml) and the install test
(tests/live/test_install_live.py) runs exactly these images."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Pinned 2026-11-03: panel 3.4.8, node 3.4.4, subscription page 8.0.1 (the versions verified by the live tests).
IMAGES = {
    "panel": "remnawave/backend:3@sha256:d87ba51deb99486983f599edaf14d1c2127631e66989d7692dd53644b7857f81",
    "node": "remnawave/node:latest@sha256:19ca38195f699f59c0e5978489a18173234aca4b1bd29bab495b16e9d6423f70",
    "subscription_page": "remnawave/subscription-page:latest@sha256:ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6",
    "postgres": "postgres:18.4@sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636",
    "valkey": "valkey/valkey:9-alpine@sha256:bf09d58e96d6b4524a15396b65b242bbe18beebbcc15a04d8ee75ddac62fae0b",
    "caddy": "caddy:2.11-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5",
}
DIRS = {"panel": "/opt/remnawave", "node": "/opt/remnanode", "subscription_page": "/opt/remnawave-subpage", "proxy": "/opt/remnawave-caddy"}
MODES = ("panel_node", "panel", "node", "panel_subpage", "subpage", "distributed", "add_node")
MODE_TITLES = {
    "panel_node": "Панель и нода на одном сервере", "panel": "Только панель", "node": "Только нода",
    "panel_subpage": "Панель и страница подписки", "subpage": "Только страница подписки",
    "distributed": "Распределённая установка", "add_node": "Добавить ноду к панели",
}
DOMAIN = re.compile(r"^(?=.{4,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$")
PANEL_PORTS = (80, 443)
LOCAL_PORTS = {"panel": (3000, 3001, 6767), "subscription_page": (3010,)}


class PlanIn(BaseModel):
    """What the wizard sends. Servers are ids of the registry; everything else is a typed value."""
    model_config = ConfigDict(extra="forbid")
    mode: Literal["panel_node", "panel", "node", "panel_subpage", "subpage", "distributed", "add_node"]
    panel_server_id: int | None = None
    node_server_ids: list[int] = Field(default_factory=list, max_length=20)
    subpage_server_id: int | None = None
    panel_domain: str | None = Field(default=None, max_length=253)
    sub_domain: str | None = Field(default=None, max_length=253)
    node_domain: str | None = Field(default=None, max_length=253)
    tls: Literal["acme", "internal"] = "acme"
    acme_email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    node_port: int = Field(default=2222, ge=1024, le=65535)
    node_name: str = Field(default="node", min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    country_code: str = Field(default="XX", pattern=r"^[A-Z]{2}$")
    firewall: bool = True

    @model_validator(mode="after")
    def check(self):
        for field in ("panel_domain", "sub_domain", "node_domain"):
            value = getattr(self, field)
            if value is not None:
                value = value.strip().lower().rstrip(".")
                if not DOMAIN.match(value):
                    raise ValueError(f"{field}: некорректный домен")
                setattr(self, field, value)
        nodes = list(dict.fromkeys(self.node_server_ids))
        self.node_server_ids = nodes
        m = self.mode
        need_panel = m in ("panel_node", "panel", "panel_subpage", "distributed")
        if need_panel and not (self.panel_server_id and self.panel_domain):
            raise ValueError("Нужны сервер панели и домен панели")
        if not need_panel and self.panel_server_id:
            raise ValueError("В этом режиме панель не ставится: используется панель, подключённая к магазину")
        if m == "panel_node" and nodes not in ([], [self.panel_server_id]):
            raise ValueError("Панель и нода ставятся на один сервер")
        if m == "panel_node":
            self.node_server_ids = [self.panel_server_id]
        if m in ("panel", "panel_subpage", "subpage") and nodes:
            raise ValueError("В этом режиме ноды не ставятся")
        if m in ("node", "add_node", "distributed") and not nodes:
            raise ValueError("Выберите сервер для ноды")
        if m == "node" and len(nodes) != 1:
            raise ValueError("Режим «Только нода» — один сервер; для нескольких выберите «Добавить ноду»")
        if m == "distributed" and self.panel_server_id in nodes:
            raise ValueError("В распределённой установке нода ставится на другой сервер, чем панель")
        if m == "panel_subpage":
            self.subpage_server_id = self.panel_server_id
        if m in ("panel_subpage", "subpage") and not (self.subpage_server_id and self.sub_domain):
            raise ValueError("Нужны сервер и домен страницы подписки")
        if m not in ("panel_subpage", "subpage", "distributed") and self.subpage_server_id:
            raise ValueError("В этом режиме страница подписки не ставится")
        if self.subpage_server_id and not self.sub_domain:
            raise ValueError("Нужен домен страницы подписки")
        if self.tls == "acme" and (self.panel_domain or self.sub_domain) and not self.acme_email:
            raise ValueError("Для сертификата Let's Encrypt нужен email (ACME)")
        return self


def roles_of(plan: PlanIn) -> dict[int, list[str]]:
    roles: dict[int, list[str]] = {}
    if plan.panel_server_id:
        roles.setdefault(plan.panel_server_id, []).append("panel")
    if plan.subpage_server_id:
        roles.setdefault(plan.subpage_server_id, []).append("subscription_page")
    for sid in plan.node_server_ids:
        roles.setdefault(sid, []).append("node")
    return roles


def step(kind: str, server_id: int | None, title: str, **params) -> dict:
    return {"kind": kind, "server_id": server_id, "title": title, "params": params}


def build_plan(plan: PlanIn, servers: dict[int, dict], shop_panel: str | None) -> dict:
    """Steps and consequences. ``servers`` — id → {name, host, roles}; ``shop_panel`` — URL of the panel the shop uses."""
    roles = roles_of(plan)
    missing = [sid for sid in roles if sid not in servers]
    if missing:
        raise ValueError(f"Серверы не найдены в реестре: {missing}")
    uses_shop_panel = plan.panel_server_id is None
    if uses_shop_panel and not shop_panel:
        raise ValueError("Панель не ставится, а магазин не подключён к панели: укажите REMNAWAVE_URL и REMNAWAVE_TOKEN")
    steps: list[dict] = []
    changes: dict[int, list[str]] = {}
    for sid, rs in roles.items():
        name = servers[sid]["name"]
        steps.append(step("preflight", sid, f"{name}: проверка перед установкой", roles=rs,
                          domains=[d for d in (plan.panel_domain if "panel" in rs else None,
                                               plan.sub_domain if "subscription_page" in rs else None) if d],
                          node_port=plan.node_port if "node" in rs else None))
        steps.append(step("install_docker", sid, f"{name}: Docker и compose из подписанного репозитория"))
        changes[sid] = ["Docker Engine и плагин compose, если их нет (официальный репозиторий Docker)"]
    p = plan.panel_server_id
    if p:
        name = servers[p]["name"]
        steps += [
            step("write_files", p, f"{name}: файлы панели ({DIRS['panel']})", component="panel"),
            step("compose_up", p, f"{name}: запуск панели, базы и Valkey", component="panel"),
            step("wait_panel", p, f"{name}: панель отвечает (/health)"),
            step("panel_bootstrap", p, f"{name}: администратор панели и токен API для магазина"),
        ]
        changes[p] += [f"Каталог {DIRS['panel']}: docker-compose.yml и .env панели",
                       "Контейнеры remnawave, remnawave-db, remnawave-redis; порты 3000, 3001 и 6767 только на 127.0.0.1"]
    s = plan.subpage_server_id
    if s:
        name = servers[s]["name"]
        steps += [step("write_files", s, f"{name}: файлы страницы подписки", component="subscription_page"),
                  step("compose_up", s, f"{name}: запуск страницы подписки", component="subscription_page")]
        changes[s].append(f"Каталог {DIRS['subscription_page']}; контейнер remnawave-subscription-page на 127.0.0.1:3010")
    for sid in {x for x in (p, s) if x}:
        name = servers[sid]["name"]
        sites = [d for d in ((plan.panel_domain if sid == p else None), (plan.sub_domain if sid == s else None)) if d]
        steps += [step("write_files", sid, f"{name}: Caddy для {', '.join(sites)}", component="proxy"),
                  step("compose_up", sid, f"{name}: запуск Caddy (HTTPS)", component="proxy")]
        changes[sid].append(f"Caddy занимает порты 80 и 443; сертификаты: {'Let’s Encrypt (HTTP-01)' if plan.tls == 'acme' else 'внутренний центр Caddy'}")
    for n in plan.node_server_ids:
        name = servers[n]["name"]
        steps += [step("write_files", n, f"{name}: файлы ноды", component="node"),
                  step("compose_up", n, f"{name}: запуск ноды", component="node")]
        changes[n].append(f"Каталог {DIRS['node']}; контейнер remnanode (сеть хоста), порт {plan.node_port}")
        if plan.firewall:
            steps.append(step("firewall_node_port", n, f"{name}: порт {plan.node_port} только для адреса панели"))
            changes[n].append(f"Если есть ufw: правило «разрешить {plan.node_port}/tcp только с адреса панели»")
        steps.append(step("register_node", n, f"{name}: нода в панели"))
    steps.append(step("verify", None, "Проверка: HTTPS панели, связь нод, страница подписки"))
    return {
        "mode": plan.mode, "title": MODE_TITLES[plan.mode], "images": IMAGES,
        "panel": "новая" if p else f"подключённая к магазину ({shop_panel})",
        "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": rs, "changes": changes[sid]}
                    for sid, rs in roles.items()},
        "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)],
    }


def plan_hash(plan: dict, params: dict) -> str:
    return hashlib.sha256(json.dumps({"plan": plan, "params": params}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------- files ----------

def _q(value: str) -> str:
    """A YAML/.env-safe double-quoted value (JSON string syntax), refusing control characters."""
    if any(ord(c) < 32 for c in str(value)):
        raise ValueError("Недопустимый символ в значении")
    return json.dumps(str(value))


def panel_compose() -> str:
    return f"""services:
  remnawave:
    image: {IMAGES['panel']}
    container_name: remnawave
    hostname: remnawave
    restart: always
    env_file: .env
    ulimits: {{nofile: {{soft: 1048576, hard: 1048576}}}}
    logging: {{driver: json-file, options: {{max-size: 100m, max-file: "5"}}}}
    networks: [remnawave-network]
    volumes: ["valkey-socket:/var/run/valkey"]
    ports: ["127.0.0.1:3000:3000", "127.0.0.1:3001:3001"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3001/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    depends_on:
      remnawave-db: {{condition: service_healthy}}
      remnawave-redis: {{condition: service_healthy}}
  remnawave-db:
    image: {IMAGES['postgres']}
    container_name: remnawave-db
    hostname: remnawave-db
    restart: always
    shm_size: 512mb
    env_file: .env
    environment: [TZ=UTC]
    networks: [remnawave-network]
    ports: ["127.0.0.1:6767:5432"]
    volumes: ["remnawave-db-data:/var/lib/postgresql"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${{POSTGRES_USER}} -d $${{POSTGRES_DB}}"]
      interval: 3s
      timeout: 10s
      retries: 3
  remnawave-redis:
    image: {IMAGES['valkey']}
    container_name: remnawave-redis
    hostname: remnawave-redis
    restart: always
    networks: [remnawave-network]
    volumes: ["valkey-socket:/var/run/valkey"]
    command: valkey-server --save "" --appendonly no --maxmemory-policy noeviction --loglevel warning --unixsocket /var/run/valkey/valkey.sock --unixsocketperm 777 --port 0
    healthcheck:
      test: ["CMD", "valkey-cli", "-s", "/var/run/valkey/valkey.sock", "ping"]
      interval: 3s
      timeout: 3s
      retries: 3
networks:
  remnawave-network: {{name: remnawave-network, driver: bridge}}
volumes:
  remnawave-db-data: {{name: remnawave-db-data}}
  valkey-socket: {{name: valkey-socket}}
"""


def panel_env(plan: PlanIn, secrets: dict) -> str:
    sub_public = plan.sub_domain if plan.subpage_server_id else f"{plan.panel_domain}/api/sub"
    values = {
        "APP_PORT": "3000", "METRICS_PORT": "3001", "API_INSTANCES": "1",
        "DATABASE_URL": f"postgresql://postgres:{secrets['db_password']}@remnawave-db:5432/postgres",
        "REDIS_SOCKET": "/var/run/valkey/valkey.sock", "APP_SECRET": secrets["app_secret"],
        "IS_TELEGRAM_NOTIFICATIONS_ENABLED": "false",
        "PANEL_DOMAIN": plan.panel_domain, "FRONT_END_DOMAIN": plan.panel_domain, "SUB_PUBLIC_DOMAIN": sub_public,
        "METRICS_USER": "metrics", "METRICS_PASS": secrets["metrics_password"],
        "WEBHOOK_ENABLED": "false", "SHORT_UUID_METHOD": "nanoid", "SHORT_UUID_LENGTH": "16",
        "SERVICE_SNI_VERIFICATION": "true",
        "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": secrets["db_password"], "POSTGRES_DB": "postgres",
    }
    return "".join(f"{k}={_q(v)}\n" for k, v in values.items())


def subpage_compose() -> str:
    return f"""services:
  remnawave-subscription-page:
    image: {IMAGES['subscription_page']}
    container_name: remnawave-subscription-page
    hostname: remnawave-subscription-page
    restart: always
    env_file: .env
    ports: ["127.0.0.1:3010:3010"]
    networks: [remnawave-network]
networks:
  remnawave-network: {{external: true}}
"""


def subpage_env(panel_url: str, token: str, secrets: dict, network_local: bool) -> str:
    # On the panel's server the page talks to the panel inside remnawave-network over http:// and adds the
    # proxy headers itself; elsewhere it uses the panel's HTTPS address.
    values = {"APP_PORT": "3010", "REMNAWAVE_PANEL_URL": "http://remnawave:3000" if network_local else panel_url,
              "REMNAWAVE_API_TOKEN": token, "INTERNAL_JWT_SECRET": secrets["subpage_jwt_secret"], "TRUST_PROXY": "1",
              "MARZBAN_LEGACY_LINK_ENABLED": "false", "MARZBAN_LEGACY_DROP_REVOKED_SUBSCRIPTIONS": "false"}
    return "".join(f"{k}={_q(v)}\n" for k, v in values.items())


def subpage_network_compose_needed(local: bool) -> str:
    """A server with the page but without the panel has no remnawave-network: the step creates it."""
    return "" if local else "docker network inspect remnawave-network >/dev/null 2>&1 || docker network create remnawave-network"


def caddyfile(sites: dict[str, int], tls: str, email: str | None) -> str:
    """``sites`` — domain → local port. Caddy terminates TLS and adds X-Forwarded-For/-Proto, which the panel and
    the subscription page require."""
    lines = []
    if email:
        lines += ["{", f"\temail {email}", "}", ""]
    for domain, port in sites.items():
        if not DOMAIN.match(domain):
            raise ValueError("Некорректный домен")
        lines += [f"{domain} {{", *(["\ttls internal"] if tls == "internal" else []), f"\treverse_proxy 127.0.0.1:{int(port)}", "}", ""]
    return "\n".join(lines)


def caddy_compose() -> str:
    return f"""services:
  caddy:
    image: {IMAGES['caddy']}
    container_name: remnawave-caddy
    restart: always
    network_mode: host
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy-data:/data", "caddy-config:/config"]
volumes:
  caddy-data: {{}}
  caddy-config: {{}}
"""


def node_compose(secret_key: str, node_port: int) -> str:
    from .provisioner import node_compose as official
    return official(secret_key, node_port).replace("image: remnawave/node:latest", f"image: {IMAGES['node']}")


ACTIONS = ("install", "update", "diagnose", "restore", "reinstall", "remove")
ACTION_TITLES = {"install": "Установка", "update": "Обновление", "diagnose": "Диагностика", "restore": "Восстановление базы панели",
                 "reinstall": "Переустановка", "remove": "Удаление"}


def build_action(action: str, plan: PlanIn, servers: dict[int, dict]) -> dict:
    """Steps of a maintenance action over what an earlier installation put on its servers.

    * update — copy of the panel's database, then the same pinned files and ``compose up`` (pulls the pinned images);
    * diagnose — the read-only preflight of every server, nothing changes;
    * restore — the panel's database from the newest copy on its server;
    * reinstall — containers stopped and started again from freshly written files (volumes stay);
    * remove — copy of the panel's database, then the containers are stopped and removed; volumes and the
      copies stay on the server, so a later reinstall brings the data back."""
    if action not in ACTIONS or action == "install":
        raise ValueError("Неизвестное действие")
    roles = roles_of(plan)
    missing = [sid for sid in roles if sid not in servers]
    if missing:
        raise ValueError(f"Серверы не найдены в реестре: {missing}")
    steps: list[dict] = []
    p = plan.panel_server_id

    def components(sid: int) -> list[str]:
        rs = roles[sid]
        out = [c for c in ("panel", "subscription_page") if c in rs]
        if {"panel", "subscription_page"} & set(rs):
            out.append("proxy")
        if "node" in rs:
            out.append("node")
        return out

    if action == "diagnose":
        for sid, rs in roles.items():
            steps.append(step("preflight", sid, f"{servers[sid]['name']}: состояние сервера", roles=rs, domains=[], node_port=None,
                              report_only=True))
    elif action == "restore":
        if not p:
            raise ValueError("Эта установка не ставила панель: восстанавливать нечего")
        steps += [step("restore_panel", p, f"{servers[p]['name']}: база панели из последней копии"),
                  step("wait_panel", p, f"{servers[p]['name']}: панель отвечает (/health)")]
    else:
        if p and action in ("update", "remove", "reinstall"):
            steps.append(step("backup_panel", p, f"{servers[p]['name']}: копия базы панели"))
        for sid in roles:
            name = servers[sid]["name"]
            for comp in components(sid):
                if action in ("reinstall", "remove"):
                    steps.append(step("compose_down", sid, f"{name}: остановка ({DIRS[comp]})", component=comp))
                if action in ("update", "reinstall"):
                    steps += [step("write_files", sid, f"{name}: файлы ({DIRS[comp]})", component=comp),
                              step("compose_up", sid, f"{name}: запуск ({DIRS[comp]})", component=comp)]
                    if comp == "panel":
                        steps.append(step("wait_panel", sid, f"{name}: панель отвечает (/health)"))
        if action in ("update", "reinstall"):
            steps.append(step("verify", None, "Проверка: HTTPS панели, связь нод, страница подписки"))
    return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {MODE_TITLES[plan.mode]}", "images": IMAGES,
            "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": rs, "changes": []}
                        for sid, rs in roles.items()},
            "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}
