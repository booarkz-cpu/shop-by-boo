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
import ipaddress
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Pinned 2026-11-03: panel 3.4.8, node 3.4.4, subscription page 8.0.1 (the versions verified by the live tests).
IMAGES = {
    "panel": "remnawave/backend:3@sha256:d87ba51deb99486983f599edaf14d1c2127631e66989d7692dd53644b7857f81",
    "node": "remnawave/node:latest@sha256:19ca38195f699f59c0e5978489a18173234aca4b1bd29bab495b16e9d6423f70",
    "subscription_page": "remnawave/subscription-page:latest@sha256:ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6",
    "postgres": "postgres:18.4@sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636",
    "valkey": "valkey/valkey:9-alpine@sha256:bf09d58e96d6b4524a15396b65b242bbe18beebbcc15a04d8ee75ddac62fae0b",
    "caddy": "caddy:2.11-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5",
    # v28.78.0: TinyAuth (tinyauthapp/tinyauth, GPL-3.0 — run as a separate container, its code is not part of the
    # shop) — the login portal in front of the panel's pages; checked in CI by tests/live/test_tinyauth_live.py.
    "tinyauth": "ghcr.io/tinyauthapp/tinyauth:v5.2.0@sha256:220aa235c76393a73fece831d7ba967b8698d3907fd8e3c4c952f699c7b142a5",
}
TINYAUTH_PORT = 3002
# v28.74.0: the upstream versions behind these digests, compared with the releases on GitHub by the auto-update
# (rw_autoupdate.py). A newer upstream release is installed only after a shop release pins and live-tests it.
VERSIONS = {"panel": "3.4.8", "node": "3.4.4", "subscription_page": "8.0.1"}
UPSTREAM = {"panel": "remnawave/backend", "node": "remnawave/node", "subscription_page": "remnawave/subscription-page"}
DIRS = {"panel": "/opt/remnawave", "node": "/opt/remnanode", "subscription_page": "/opt/remnawave-subpage", "proxy": "/opt/remnawave-caddy",
        "selfsteal": "/opt/remnawave-selfsteal", "xray_checker": "/opt/remnawave-xray-checker"}
# v28.70.0: Xray Checker (kutovoys/xray-checker, MIT) v1.3.1, pinned by the digest the live test pulled
# (tests/live/test_node_modules_live.py prints it on every run).
CHECKER_IMAGE = "kutovoys/xray-checker:v1.3.1@sha256:33c9a4987caa3a5f0af466ae3eeb233b53068931d0e2e7af357d4dfc5269bc4a"
MODULES = ("ipv6", "xray_core", "warp", "netbird", "xray_checker", "transports", "hardening", "watchdog", "selfsteal_site", "node_port",
           "mss_clamp", "node_guard", "swap", "sni_scan", "mtproto", "geo_files", "cdn", "psiphon")
MODULE_TITLES = {"ipv6": "IPv6", "xray_core": "Ядро Xray", "warp": "WARP Native", "netbird": "NetBird", "xray_checker": "Xray Checker",
                 "transports": "Протоколы и маскировка ноды", "hardening": "Защита сервера", "watchdog": "Самовосстановление",
                 "selfsteal_site": "Сайт SelfSteal", "node_port": "Порт ноды для панели", "mss_clamp": "MSS clamp",
                 "node_guard": "Защита ноды (nftables)", "swap": "Файл подкачки",
                 "sni_scan": "Подбор сайта для REALITY", "mtproto": "MTProto-прокси для Telegram", "psiphon": "Сервер Psiphon (psiphond)",
                 "geo_files": "Российские списки блокировок (geo)", "cdn": "Cloudflare CDN"}
# v28.95.0 (N7): the Russian lists sit next to the image's own geo files (those stay as they are) and are used as
# ext:ru-geosite.dat:<category> / ext:ru-geoip.dat:<category> in the routing rules of the panel.
GEO_DIR = "/usr/local/share/xray"
GEO_FILES = {"geoip": "ru-geoip.dat", "geosite": "ru-geosite.dat"}
# Release files by the server's architecture (uname -m; the preflight allows only these two).
XRAY_ASSETS = {"x86_64": "Xray-linux-64.zip", "aarch64": "Xray-linux-arm64-v8a.zip"}
WGCF_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
SELFSTEAL_SOCKET = "/dev/shm/selfsteal.sock"
# v28.81.0: extra transports of a SelfSteal node next to VLESS + TCP + REALITY on 443 (after remnawave-manager, MIT,
# (c) Корги Люси): tag, port, network — the same REALITY keys and the SelfSteal site; Hysteria2 uses the TLS certificate
# the node's Caddy issued for the SelfSteal domain (copied to HYSTERIA_DIR, Xray reloads it).
# v28.90.0 (N6): «tls» — VLESS + TCP + TLS with the same certificate and the TLS versions the owner chose; REALITY and
# Hysteria2 (QUIC) work only over TLS 1.3, so the choice applies to this inbound.
TRANSPORTS = {"xhttp": ("VLESS_XHTTP_REALITY", 4443, "tcp"), "grpc": ("VLESS_GRPC_REALITY", 8443, "tcp"), "hysteria2": ("HYSTERIA2", 443, "udp"),
              "tls": ("VLESS_TCP_TLS", 2053, "tcp"),
              # v28.98.0 (N7): VLESS + XHTTP + TLS behind Cloudflare — the client reaches the CDN domain on 2083 (a port
              # Cloudflare proxies), Cloudflare reaches the node on 2083 over TLS with the SelfSteal certificate.
              "cdn": ("VLESS_XHTTP_CDN", 2083, "tcp")}
TRANSPORT_TITLES = {"xhttp": "VLESS + xHTTP + REALITY (TCP 4443)", "grpc": "VLESS + gRPC + REALITY (TCP 8443)", "hysteria2": "Hysteria2 (UDP 443)",
                    "tls": "VLESS + TCP + TLS (TCP 2053)", "cdn": "VLESS + XHTTP через Cloudflare CDN (TCP 2083)"}
TransportName = Literal["xhttp", "grpc", "hysteria2", "tls", "cdn"]
CDN_PATH = "/cdn"
# v28.94.0 (N7): ports the node already uses (REALITY 443, extra transports, SelfSteal's HTTP) — MTProto takes another one.
MTPROTO_TAKEN = {80, 443, *(port for _, port, _ in TRANSPORTS.values())}
# v28.90.0 (N5): the uTLS fingerprint clients present (Remnawave host «fingerprint»); Firefox by default.
FINGERPRINTS = {"firefox": "Firefox", "chrome": "Chrome", "safari": "Safari", "ios": "iOS", "android": "Android", "edge": "Edge",
                "qq": "QQ", "random": "Случайный из популярных", "randomized": "Полностью случайный"}
Fingerprint = Literal["firefox", "chrome", "safari", "ios", "android", "edge", "qq", "random", "randomized"]
TlsVersion = Literal["1.2", "1.3"]


def _networks(value: list[str], label: str) -> list[str]:
    out = []
    for raw in value:
        try:
            net = ipaddress.ip_network(raw.strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"{label}: {raw}") from exc
        if net.num_addresses > 65536:
            raise ValueError(f"Слишком широкий диапазон: {raw}")
        out.append(str(net))
    return list(dict.fromkeys(out))
HYSTERIA_DIR = "/opt/remnanode/hysteria"
HYSTERIA_MOUNT = "/var/lib/corgi-hysteria"
# v28.91.0 (N8): the catalogue of selfsteal_sites (22 templates, a build of its own for every node) and «custom» —
# a site the administrator uploaded as an archive (selfsteal_upload: its id in «SelfSteal → Свои сайты»).
from .selfsteal_sites import CATALOGUE as _SITES  # noqa: E402

SELFSTEAL_TEMPLATES = {t.id: t.ru[0][0] for t in _SITES} | {"custom": "свой сайт"}
MODES = ("panel_node", "panel", "node", "panel_subpage", "subpage", "distributed", "add_node")
MODE_TITLES = {
    "panel_node": "Панель и нода на одном сервере", "panel": "Только панель", "node": "Только нода",
    "panel_subpage": "Панель и страница подписки", "subpage": "Только страница подписки",
    "distributed": "Распределённая установка", "add_node": "Добавить ноду к панели",
}
# \Z, not $: «$» also matches before a final newline, and a name ends up in a Caddyfile.
DOMAIN = re.compile(r"^(?=.{4,253}\Z)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+\Z")
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
    # v28.97.0 (N7): former panel domains still served after «Сменить домен панели»: subscriptions /api/sub/ keep working,
    # everything else is redirected to the new domain; emptied by the same action with «старый домен больше не нужен».
    panel_domain_aliases: list[str] = Field(default_factory=list, max_length=3)
    sub_domain: str | None = Field(default=None, max_length=253)
    node_domain: str | None = Field(default=None, max_length=253)
    tls: Literal["acme", "internal"] = "acme"
    acme_email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    node_port: int = Field(default=2222, ge=1024, le=65535)
    node_name: str = Field(default="node", min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    country_code: str = Field(default="XX", pattern=r"^[A-Z]{2}$")
    firewall: bool = True
    # v28.67.0: «закрыть доступ к панели» — the panel's pages answer only with the access cookie (rw_plan.caddyfile).
    panel_access: Literal["open", "cookie", "tinyauth", "gate"] = "open"
    # v28.78.0: «tinyauth» — the panel's pages ask for a login on this domain (TinyAuth). It must be a sibling of the
    # panel's domain (auth.example.com for panel.example.com): the session cookie is set for the common parent.
    auth_domain: str | None = Field(default=None, max_length=253)
    # v28.70.0: SelfSteal on the node — Caddy serves a template site for this domain on a unix socket and Xray
    # REALITY on port 443 uses it as its «dest» (the node looks like an ordinary site).
    selfsteal_domain: str | None = Field(default=None, max_length=253)
    selfsteal_template: str = Field(default="cloud", max_length=40)
    selfsteal_lang: Literal["ru", "en"] = "ru"
    selfsteal_upload: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    # v28.77.0: the page of the Remnawave subscription page — its own, or Orion (legiz-ru/Orion, MIT) pinned below.
    subpage_template: Literal["default", "orion"] = "default"
    # v28.70.0: node modules that change the files the wizard writes, so updates keep them:
    # an Xray core of the chosen release mounted into the node, and Xray Checker on one of the servers.
    xray_core: str | None = Field(default=None, pattern=r"^v\d{1,3}\.\d{1,3}\.\d{1,3}$")
    geo_files: str | None = Field(default=None, pattern=r"^\d{12}$")
    # v28.98.0 (N7): Cloudflare — the CDN domain of the nodes' XHTTP (transport «cdn») and the subscription domain behind the CDN.
    cdn_domain: str | None = Field(default=None, max_length=253)
    cdn_subscription: bool = False  # v28.95.0: the build of the Russian geo lists mounted into the nodes
    xray_checker_server_id: int | None = None
    xray_checker_interval: int = Field(default=300, ge=60, le=86400)
    # v28.81.0: extra transports of the SelfSteal node (TRANSPORTS); VLESS + TCP + REALITY on 443 always stays.
    transports: list[TransportName] = Field(default_factory=list, max_length=4)
    # v28.90.0 (N5, N6): the browser fingerprint of the hosts and the TLS versions of «VLESS + TCP + TLS».
    fingerprint: Fingerprint = "firefox"
    tls_min: TlsVersion = "1.3"
    tls_max: TlsVersion = "1.3"
    # v28.90.0 (N5): more addresses allowed to the node's port besides the panel's (for a panel move: add the new one first).
    node_port_ips: list[str] = Field(default_factory=list, max_length=10)
    # v28.92.0 (N7): «Опасная зона → Удалить компонент» — which one (rw_api.action fills it with the action).
    remove_component: Literal["panel", "subscription_page", "proxy", "node", "selfsteal", "xray_checker"] | None = None
    # v28.93.0 (N7 «Экстренное восстановление»): the snapshot of the files to put back (rw_api.action fills it).
    snapshot_file: str | None = Field(default=None, pattern=r"^config-\d{1,9}-\d{8}T\d{6}Z\.tar\.gz\.enc$")
    # The module action being planned (rw_api.action fills it; it is not kept after the run).
    module: "ModuleRun | None" = None

    @model_validator(mode="after")
    def check(self):
        for field in ("panel_domain", "sub_domain", "node_domain", "selfsteal_domain", "auth_domain", "cdn_domain"):
            value = getattr(self, field)
            if value is not None:
                value = value.strip().lower().rstrip(".")
                if not DOMAIN.match(value):
                    raise ValueError(f"{field}: некорректный домен")
                setattr(self, field, value)
        if "cdn" in self.transports and not (self.cdn_domain and self.selfsteal_domain):
            raise ValueError("XHTTP через CDN: нужен домен CDN и SelfSteal на ноде")
        if self.cdn_domain and self.cdn_domain in (self.panel_domain, self.sub_domain, self.selfsteal_domain, self.node_domain, self.auth_domain):
            raise ValueError("Домен CDN — отдельный, не домен панели, подписки или SelfSteal")
        aliases = []
        for value in self.panel_domain_aliases:
            value = value.strip().lower().rstrip(".")
            if not DOMAIN.match(value):
                raise ValueError("panel_domain_aliases: некорректный домен")
            if value != self.panel_domain and value not in aliases:
                aliases.append(value)
        self.panel_domain_aliases = aliases
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
        if self.selfsteal_domain:
            if len(self.node_server_ids) != 1:
                raise ValueError("SelfSteal — для одной ноды: у каждой ноды свой домен")
            if self.node_server_ids[0] in (self.panel_server_id, self.subpage_server_id):
                raise ValueError("SelfSteal занимает порт 443 ноды: ставьте ноду на сервер без панели и страницы подписки")
            if self.node_domain and self.node_domain != self.selfsteal_domain:
                raise ValueError("Домен ноды и домен SelfSteal должны совпадать")
            if self.tls == "acme" and not self.acme_email:
                raise ValueError("Для сертификата Let's Encrypt нужен email (ACME)")
        if self.selfsteal_template not in SELFSTEAL_TEMPLATES:
            raise ValueError("Сайт SelfSteal: шаблон из каталога или свой сайт")
        if (self.selfsteal_template == "custom") != bool(self.selfsteal_upload):
            raise ValueError("Свой сайт SelfSteal: выберите загруженный архив")
        self.transports = sorted(set(self.transports))
        if self.tls_min > self.tls_max:
            raise ValueError("TLS: минимальная версия выше максимальной")
        self.node_port_ips = _networks(self.node_port_ips, "Адрес для порта ноды")
        if self.transports and not self.selfsteal_domain:
            raise ValueError("Транспорты xHTTP, gRPC, Hysteria2 и TLS ставятся на ноду с SelfSteal (домен ноды и сертификат)")
        if self.xray_checker_server_id and self.xray_checker_server_id not in roles_of(self):
            raise ValueError("Xray Checker ставится на один из серверов этой установки")
        if self.panel_access in ("cookie", "tinyauth", "gate") and not self.panel_server_id:
            raise ValueError("Закрыть доступ можно к панели, которую ставит мастер")
        if self.panel_access == "tinyauth":
            if not self.auth_domain:
                raise ValueError("Для входа через TinyAuth нужен свой домен, например auth.example.com")
            if self.auth_domain in (self.panel_domain, self.sub_domain, self.node_domain, self.selfsteal_domain):
                raise ValueError("Домен TinyAuth должен отличаться от доменов панели, подписки и нод")
            parent = self.auth_domain.split(".", 1)[1]
            if parent.count(".") < 1 or not (self.panel_domain == parent or self.panel_domain.endswith("." + parent)):
                raise ValueError(f"Домен панели должен быть в той же зоне, что и TinyAuth: …{parent}")
        elif self.auth_domain:
            self.auth_domain = None
        if self.tls == "acme" and (self.panel_domain or self.sub_domain) and not self.acme_email:
            raise ValueError("Для сертификата Let's Encrypt нужен email (ACME)")
        return self


class Hardening(BaseModel):
    """v28.84.0: «Защита сервера» — what to turn on. ``admin_ips``: SSH only from these addresses (and the shop's own)."""
    model_config = ConfigDict(extra="forbid")
    fail2ban: bool = True
    upgrades: bool = True
    bbr: bool = True
    admin_ips: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("admin_ips")
    @classmethod
    def _ips(cls, value: list[str]) -> list[str]:
        return _networks(value, "Адрес администратора")


class ModuleRun(BaseModel):
    """One module action: what to do on which servers. ``release`` — the files GitHub published for the chosen
    version, by architecture, with their SHA-256 (looked up when the plan is made, so the approved plan fixes them)."""
    model_config = ConfigDict(extra="forbid")
    name: Literal["ipv6", "xray_core", "warp", "netbird", "xray_checker", "transports", "hardening", "watchdog", "selfsteal_site", "node_port",
                  "mss_clamp", "node_guard", "swap", "sni_scan", "mtproto", "geo_files", "cdn", "psiphon"]
    enabled: bool = True
    # v28.98.0 (N7): Cloudflare — the parts this run switches (on with enabled, back to direct without).
    cdn_nodes: bool = False
    cdn_subscription: bool = False
    # v28.99.0 (N7): psiphond — its port and tunnel protocol.
    psiphon_port: int = Field(default=10443, ge=1024, le=65535)
    psiphon_protocol: Literal["OSSH", "TLS-OSSH"] = "OSSH"
    # v28.94.0 (N7): MTProto — the port and the site FakeTLS pretends to be.
    mtproto_port: int = Field(default=9443, ge=1024, le=65535)
    mtproto_domain: str = Field(default="www.cloudflare.com", min_length=4, max_length=100, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
    # v28.92.0 (N7): «Защита ноды» — ports, new connections per second from one address, extra allowed addresses, mode;
    # «Файл подкачки» — size in MB.
    guard_ports: list[int] = Field(default_factory=lambda: [443, 4443, 8443, 2053], max_length=12)
    guard_rate: int = Field(default=150, ge=5, le=5000)
    guard_allow: list[str] = Field(default_factory=list, max_length=10)
    guard_mode: Literal["enforce", "observe"] = "enforce"
    swap_mb: int = Field(default=1024, ge=256, le=16384)
    server_ids: list[int] = Field(default_factory=list, max_length=20)
    version: str | None = Field(default=None, max_length=40)
    transports: list[TransportName] = Field(default_factory=list, max_length=5)
    hardening: "Hardening | None" = None
    release: dict[str, dict[str, str]] = Field(default_factory=dict)
    management_url: str | None = Field(default=None, max_length=200, pattern=r"^https://[A-Za-z0-9.-]+(:\d{1,5})?(/[A-Za-z0-9._~/-]*)?$")


PlanIn.model_rebuild()


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
        steal = bool(plan.selfsteal_domain and "node" in rs)
        steps.append(step("preflight", sid, f"{name}: проверка перед установкой", roles=rs + (["selfsteal"] if steal else []),
                          domains=[d for d in (plan.panel_domain if "panel" in rs else None,
                                               plan.auth_domain if "panel" in rs else None,
                                               plan.sub_domain if "subscription_page" in rs else None,
                                               plan.selfsteal_domain if steal else None) if d],
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
        changes[s].append(f"Каталог {DIRS['subscription_page']}; контейнер remnawave-subscription-page на 127.0.0.1:3010; "
                          f"страница: {SUBPAGE_TEMPLATES[plan.subpage_template]}")
    for sid in {x for x in (p, s) if x}:
        name = servers[sid]["name"]
        sites = [d for d in ((plan.panel_domain if sid == p else None), (plan.auth_domain if sid == p else None),
                             (plan.sub_domain if sid == s else None)) if d]
        steps += [step("write_files", sid, f"{name}: Caddy для {', '.join(sites)}", component="proxy"),
                  step("compose_up", sid, f"{name}: запуск Caddy (HTTPS)", component="proxy")]
        changes[sid].append(f"Caddy занимает порты 80 и 443; сертификаты: {'Let’s Encrypt (HTTP-01)' if plan.tls == 'acme' else 'внутренний центр Caddy'}")
        if sid == p and plan.panel_access == "cookie":
            changes[sid].append("Доступ к страницам панели закрыт: открывается только по секретной ссылке (API с токеном и подписки работают)")
        if sid == p and plan.panel_access == "tinyauth":
            changes[sid].append(f"Страницы панели — после входа на https://{plan.auth_domain} (TinyAuth, контейнер remnawave-tinyauth "
                                f"на 127.0.0.1:{TINYAUTH_PORT}); API с токеном и подписки работают без входа")
        if sid == p and plan.panel_access == "gate":
            changes[sid].append("Страницы панели — только администраторам магазина с правом управлять серверами (кнопка «Открыть панель» "
                                "в мастере; Caddy спрашивает магазин о каждом запросе); API с токеном и подписки работают без входа")
    for n in plan.node_server_ids:
        name = servers[n]["name"]
        if plan.selfsteal_domain:
            steps += [step("write_files", n, f"{name}: SelfSteal — Caddy и сайт «{SELFSTEAL_TEMPLATES[plan.selfsteal_template]}»", component="selfsteal"),
                      step("compose_up", n, f"{name}: запуск Caddy SelfSteal (сертификат {plan.selfsteal_domain})", component="selfsteal")]
            changes[n] += [f"Каталог {DIRS['selfsteal']}: Caddy на порту 80 и сокете {SELFSTEAL_SOCKET}, сайт-шаблон для {plan.selfsteal_domain}",
                           "Порт 443 занимает Xray (REALITY), чужие запросы видят сайт-шаблон"]
        steps += [step("write_files", n, f"{name}: файлы ноды", component="node"),
                  step("compose_up", n, f"{name}: запуск ноды", component="node")]
        changes[n].append(f"Каталог {DIRS['node']}; контейнер remnanode (сеть хоста), порт {plan.node_port}")
        if plan.firewall:
            steps.append(step("firewall_node_port", n, f"{name}: порт {plan.node_port} только для адреса панели"))
            changes[n].append(f"Порт {plan.node_port}/tcp — только с адреса панели (nftables; и правило ufw, если он включён). "
                              "Если после установки панель не видит ноду, правило снимается"
                              + ("; порты 80 и 443 открыты для всех" if plan.selfsteal_domain else ""))
        if plan.selfsteal_domain:
            steps.append(step("selfsteal_profile", n, f"{name}: профиль VLESS + REALITY с SelfSteal и хост {plan.selfsteal_domain}"))
            changes.setdefault(n, []).append("В панели: профиль конфигурации REALITY (ключи от панели) и хост для клиентов")
        steps.append(step("register_node", n, f"{name}: нода в панели"))
        if plan.transports:
            chosen = ", ".join(TRANSPORT_TITLES[t] for t in plan.transports)
            steps += [step("node_module", n, f"{name}: порты и сертификат Hysteria2 — {chosen}", module="transports", transports=plan.transports),
                      step("node_transports", None, f"Панель: транспорты {chosen} в профиле SelfSteal, хосты и сквады")]
            changes[n].append(f"Транспорты: {chosen}; если есть ufw — их порты открыты для всех")
    steps.append(step("verify", None, "Проверка: HTTPS панели, связь нод, страница подписки" + (", сайт SelfSteal" if plan.selfsteal_domain else "")))
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


# v28.77.0: Orion — a subscription page template by legiz-ru (MIT, Copyright (c) 2025 legiz-ru), the
# «Custom extensions by legiz» of eGamesAPI/remnawave-reverse-proxy. Pinned to a commit and its SHA-256: the wizard
# writes exactly this file, never «main». The page loads its scripts from jsDelivr and Skypack in the visitor's browser.
ORION = {"commit": "d232def6a6c11e37aeeb76ebfb1ee8eb5eb8b5bd",
         "sha256": "7bfec9a1fa8e62206504bd86690c69a6d4deae6767f09a10b21936f53ef0ecee",
         "url": "https://raw.githubusercontent.com/legiz-ru/Orion/d232def6a6c11e37aeeb76ebfb1ee8eb5eb8b5bd/index.html"}
SUBPAGE_TEMPLATES = {"default": "Стандартная страница Remnawave", "orion": "Orion (legiz-ru, MIT)"}


def subpage_compose(template: str = "default") -> str:
    volumes = '    volumes: ["./index.html:/opt/app/frontend/index.html:ro"]\n' if template == "orion" else ""
    return f"""services:
  remnawave-subscription-page:
    image: {IMAGES['subscription_page']}
    container_name: remnawave-subscription-page
    hostname: remnawave-subscription-page
    restart: always
    env_file: .env
    ports: ["127.0.0.1:3010:3010"]
{volumes}    networks: [remnawave-network]
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


# The shop's address in a panel's Caddyfile: https://host[:port] (http only for 127.0.0.1 — the live test).
SHOP_URL = re.compile(r"^(https://(?!-)[a-z0-9.-]{4,253}(?::\d{2,5})?|http://127\.0\.0\.1:\d{2,5})\Z")
COOKIE_PART = re.compile(r"^[A-Za-z0-9]{8,64}\Z")


def caddyfile(sites: dict[str, int], tls: str, email: str | None, protect: dict[str, tuple[str, str]] | None = None,
              guard: dict[str, int] | None = None, gate: dict[str, str] | None = None, moved: dict[str, str] | None = None) -> str:
    """``sites`` — domain → local port. Caddy terminates TLS and adds X-Forwarded-For/-Proto, which the panel and
    the subscription page require.

    ``protect`` — domain → (cookie name, value): the idea of ``manage_panel_access`` in eGamesAPI/remnawave-reverse-proxy
    (MIT, Copyright (c) 2025 eGames), written for this builder. Opening ``https://<domain>/?<name>=<value>`` once sets
    the cookie; without it the connection is closed, as if nothing listened. Requests with a bearer token to ``/api/``
    (the shop, the panel's own pages after login) and subscriptions ``/api/sub/`` stay open: they are authorized by the
    panel itself.

    ``guard`` — domain → local port of TinyAuth (v28.78.0): the same pages ask TinyAuth first (``forward_auth``,
    its Caddy endpoint answers 200 with a session and a redirect to the login page without one); the same
    requests as above stay open.

    ``gate`` — domain → the shop's public address (v28.78.0, panel_gate.py): the same pages ask the shop; the
    one-time link ``/__corgi_gate`` is handed to the shop, which sets the panel domain's cookie."""
    protect = protect or {}
    guard = guard or {}
    gate = gate or {}
    lines = []
    if email:
        lines += ["{", f"\temail {email}", "}", ""]
    for domain, port in sites.items():
        if not DOMAIN.match(domain):
            raise ValueError("Некорректный домен")
        body = [*(["\ttls internal"] if tls == "internal" else [])]
        if domain in protect:
            name, value = protect[domain]
            if not (COOKIE_PART.match(name) and COOKIE_PART.match(value)):
                raise ValueError("Некорректный ключ доступа")
            body += [f"\t@key query {name}={value}",
                     f'\theader @key +Set-Cookie "{name}={value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000"',
                     "\t@locked {", f"\t\tnot header Cookie *{name}={value}*", f"\t\tnot query {name}={value}",
                     "\t\tnot path /api/sub/*", "\t\tnot {", "\t\t\tpath /api/*", '\t\t\theader Authorization "Bearer *"', "\t\t}", "\t}",
                     "\tabort @locked"]
        if domain in guard:
            body += ["\t@guarded {", "\t\tnot path /api/sub/*", "\t\tnot {", "\t\t\tpath /api/*", '\t\t\theader Authorization "Bearer *"',
                     "\t\t}", "\t}", f"\tforward_auth @guarded 127.0.0.1:{int(guard[domain])} {{", "\t\turi /api/auth/caddy", "\t}"]
        if domain in gate:
            shop = gate[domain]
            if not SHOP_URL.match(shop):
                raise ValueError("Некорректный адрес магазина")
            body += ["\thandle /__corgi_gate {", "\t\trewrite * /api/panel-gate/redeem?{query}", f"\t\treverse_proxy {shop} {{",
                     "\t\t\theader_up Host {upstream_hostport}", "\t\t\theader_up X-Corgi-Gate-Host {host}", "\t\t}", "\t}",
                     "\thandle {", "\t\t@guarded {", "\t\t\tnot path /api/sub/*", "\t\t\tnot {", "\t\t\t\tpath /api/*",
                     '\t\t\t\theader Authorization "Bearer *"', "\t\t\t}", "\t\t}", f"\t\tforward_auth @guarded {shop} {{",
                     "\t\t\turi /api/panel-gate/verify", "\t\t\theader_up Host {upstream_hostport}", "\t\t\theader_up X-Corgi-Gate-Host {host}",
                     "\t\t}", f"\t\treverse_proxy 127.0.0.1:{int(port)}", "\t}"]
            lines += [f"{domain} {{", *body, "}", ""]
            continue
        body.append(f"\treverse_proxy 127.0.0.1:{int(port)}")
        lines += [f"{domain} {{", *body, "}", ""]
    for old, new in (moved or {}).items():
        # v28.97.0: a former panel domain — the clients' subscription links keep working, the rest goes to the new domain.
        if not (DOMAIN.match(old) and DOMAIN.match(new)) or old in sites:
            raise ValueError("Некорректный прежний домен")
        port = sites[new]
        # The shop's own API calls (a bearer token) also stay until «Подключить магазин» points it at the new domain.
        lines += [f"{old} {{", *(["\ttls internal"] if tls == "internal" else []),
                  "\t@kept {", "\t\tpath /api/sub/*", "\t}", "\t@shop {", "\t\tpath /api/*", '\t\theader Authorization "Bearer *"', "\t}",
                  "\thandle @kept {", f"\t\treverse_proxy 127.0.0.1:{int(port)} {{", f"\t\t\theader_up Host {new}", "\t\t}", "\t}",
                  "\thandle @shop {", f"\t\treverse_proxy 127.0.0.1:{int(port)} {{", f"\t\t\theader_up Host {new}", "\t\t}", "\t}",
                  "\thandle {", f"\t\tredir https://{new}{{uri}} 308", "\t}", "}", ""]
    return "\n".join(lines)


def caddy_compose(tinyauth: bool = False) -> str:
    extra = f"""  tinyauth:
    image: {IMAGES['tinyauth']}
    container_name: remnawave-tinyauth
    restart: always
    ports: ["127.0.0.1:{TINYAUTH_PORT}:3000"]
    env_file: .env
    volumes: ["tinyauth-data:/data"]
""" if tinyauth else ""
    return f"""services:
  caddy:
    image: {IMAGES['caddy']}
    container_name: remnawave-caddy
    restart: always
    network_mode: host
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy-data:/data", "caddy-config:/config"]
{extra}volumes:
  caddy-data: {{}}
  caddy-config: {{}}
{"  tinyauth-data: {}" + chr(10) if tinyauth else ""}"""


TINYAUTH_USER = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}\Z")


def tinyauth_env(auth_domain: str, username: str, password_hash: str) -> str:
    """TinyAuth v5 settings. The bcrypt hash is single-quoted: compose reads such values literally (no ``$`` expansion)."""
    if not DOMAIN.match(auth_domain) or not TINYAUTH_USER.match(username):
        raise ValueError("Некорректные настройки TinyAuth")
    if not re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", password_hash):
        raise ValueError("Некорректный хеш пароля TinyAuth")
    return (f"TINYAUTH_APPURL=https://{auth_domain}\n"
            f"TINYAUTH_AUTH_USERS='{username}:{password_hash}'\n"
            "TINYAUTH_AUTH_SECURECOOKIE=true\n"
            "TINYAUTH_AUTH_SESSIONEXPIRY=43200\n"
            "TINYAUTH_AUTH_LOGINMAXRETRIES=5\n"
            "TINYAUTH_LABELPROVIDER=none\n")


def node_compose(secret_key: str, node_port: int, selfsteal: bool = False, xray_core: bool = False, hysteria: bool = False,
                 geo: bool = False) -> str:
    """``hysteria`` — the node has a TLS-certificate transport (Hysteria2 or VLESS + TCP + TLS)."""
    from .provisioner import node_compose as official
    text = official(secret_key, node_port).replace("image: remnawave/node:latest", f"image: {IMAGES['node']}")
    volumes = []
    if selfsteal:
        # Xray reaches the SelfSteal site through the socket in /dev/shm (shared with the Caddy container).
        volumes.append("      - /dev/shm:/dev/shm:rw\n")
    if xray_core:
        # The core of the chosen release (checked by SHA-256 when downloaded) instead of the bundled one;
        # the node's rw-core starts /usr/local/bin/xray unless a panel profile points it at another core.
        volumes.append("      - ./xray-core/xray:/usr/local/bin/xray:ro\n")
    if geo:
        # v28.95.0 (N7): the Russian lists next to the image's geoip.dat / geosite.dat — new names, nothing replaced.
        volumes += [f"      - ./geo/{name}:{GEO_DIR}/{name}:ro\n" for name in GEO_FILES.values()]
    if hysteria:
        # Hysteria2 and VLESS + TCP + TLS read the SelfSteal domain's certificate (copied there by the node's timer, see rw_steps.TRANSPORTS_SH).
        volumes.append(f"      - {HYSTERIA_DIR}:{HYSTERIA_MOUNT}:ro\n")
    if volumes:
        text = text.replace("    cap_add:\n", "    volumes:\n" + "".join(volumes) + "    cap_add:\n", 1)
    return text


def checker_compose() -> str:
    return f"""services:
  xray-checker:
    image: {CHECKER_IMAGE}
    container_name: remnawave-xray-checker
    restart: unless-stopped
    network_mode: host
    env_file: .env
    logging:
      driver: json-file
      options: {{max-size: "10m", max-file: "3"}}
"""


def checker_env(subscription_url: str, interval: int, user: str, password: str) -> str:
    """Metrics and the API only on 127.0.0.1:2112 behind Basic Auth; the shop reads them over SSH."""
    for value in (subscription_url, user, password):
        if any(c in value for c in "\n\r\"'$`\\ "):
            raise ValueError("Недопустимые символы в настройках Xray Checker")
    return "\n".join([f"SUBSCRIPTION_URL={subscription_url}", "SUBSCRIPTION_UPDATE=true", "SUBSCRIPTION_UPDATE_INTERVAL=300",
                      f"PROXY_CHECK_INTERVAL={int(interval)}", "PROXY_CHECK_METHOD=ip", "PROXY_TIMEOUT=30",
                      "METRICS_HOST=127.0.0.1", "METRICS_PORT=2112", "METRICS_PROTECTED=true",
                      f"METRICS_USERNAME={user}", f"METRICS_PASSWORD={password}", ""])


def selfsteal_caddyfile(domain: str, tls: str, email: str | None) -> str:
    """Caddy of the node: the HTTP-01 challenge and a redirect on port 80; the template site over TLS on the unix
    socket that Xray REALITY passes foreign connections to, with the PROXY protocol (xver 1) so the site sees the
    real client address. After eGamesAPI/remnawave-reverse-proxy (MIT, (c) 2025 eGames), src/caddy/install_node.sh."""
    if not DOMAIN.match(domain):
        raise ValueError("Некорректный домен")
    opts = ["\tadmin off", "\tservers {", "\t\tlistener_wrappers {", "\t\t\tproxy_protocol", "\t\t\ttls", "\t\t}", "\t}",
            "\tauto_https disable_redirects"]
    if tls == "internal":
        opts.append("\tlocal_certs")
    elif email:
        opts.append(f"\temail {email}")
    return "\n".join(["{", *opts, "}", "",
                      f"http://{domain} {{", "\tbind 0.0.0.0", f"\tredir https://{domain}{{uri}} permanent", "}", "",
                      # v28.91.0 (N8): a whole site (rw_steps.SITE keeps «current» pointing at the deployed build), its own
                      # 404 page, HSTS and no «Server: Caddy» — what «SelfSteal → Проверка снаружи» looks for.
                      f"https://{domain} {{", f"\tbind unix/{SELFSTEAL_SOCKET}", "\troot * /sites/current",
                      "\theader {", "\t\t-Server", '\t\tStrict-Transport-Security "max-age=31536000; includeSubDomains"',
                      "\t\tX-Content-Type-Options nosniff", "\t\tReferrer-Policy strict-origin-when-cross-origin", "\t}",
                      "\tencode gzip", "\ttry_files {path} {path}/index.html {path}.html", "\tfile_server",
                      "\thandle_errors {", "\t\trewrite * /404.html", "\t\tfile_server", "\t}", "}", "",
                      ":80 {", "\tbind 0.0.0.0", "\trespond 204", "}", ""])


def selfsteal_compose() -> str:
    return f"""services:
  caddy:
    image: {IMAGES['caddy']}
    container_name: remnawave-selfsteal
    restart: always
    network_mode: host
    command: sh -c 'rm -f {SELFSTEAL_SOCKET} && caddy run --config /etc/caddy/Caddyfile --adapter caddyfile'
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile:ro", "./sites:/sites:ro", "/dev/shm:/dev/shm:rw", "caddy-data:/data", "caddy-config:/config"]
    healthcheck:
      test: ["CMD", "test", "-S", "{SELFSTEAL_SOCKET}"]
      interval: 5s
      timeout: 3s
      retries: 20
volumes:
  caddy-data: {{}}
  caddy-config: {{}}
"""


ACTIONS = ("install", "update", "diagnose", "restore", "reinstall", "remove", "module", "start", "stop", "restart", "logs",
           "snapshot", "remove_component", "restore_files", "change_domain")
ACTION_TITLES = {"change_domain": "Смена домена панели", "restore_files": "Экстренное восстановление файлов", "snapshot": "Снапшот сервера", "remove_component": "Удаление компонента", "install": "Установка", "update": "Обновление", "diagnose": "Диагностика", "restore": "Восстановление базы панели",
                 "reinstall": "Переустановка", "remove": "Удаление", "module": "Модуль",
                 "start": "Запуск", "stop": "Остановка", "restart": "Перезапуск", "logs": "Журналы контейнеров"}
# v28.77.0: service control over the containers an installation runs (manage_panel in eGamesAPI/remnawave-reverse-proxy,
# MIT, (c) 2025 eGames — the idea, written here as wizard steps). Files and volumes never change.
SERVICE_ACTIONS = ("start", "stop", "restart", "logs")
LOG_LINES = 200


def module_steps(plan: PlanIn, servers: dict[int, dict], roles: dict[int, list[str]]) -> tuple[list[dict], str]:
    """Steps of one module action. Each server-side change is a ``node_module`` step (a closed script of rw_steps)
    with its own rollback; a new Xray core is then written into the node's compose file and the node restarted."""
    mod = plan.module
    if not mod:
        raise ValueError("Не выбран модуль")
    nodes = [sid for sid, rs in roles.items() if "node" in rs]
    targets = mod.server_ids or (nodes if mod.name != "xray_checker" else [])
    if any(sid not in roles for sid in targets):
        raise ValueError("Модуль ставится на серверы этой установки")
    steps: list[dict] = []
    name = mod.name
    state = "включить" if mod.enabled else "выключить"
    if name == "ipv6":
        if not targets:
            raise ValueError("Выберите серверы")
        for sid in targets:
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: IPv6 — {state}", module="ipv6", enabled=mod.enabled))
        title = f"IPv6: {state}"
    elif name == "xray_core":
        if not nodes:
            raise ValueError("В этой установке нет нод")
        for sid in nodes:
            n = servers[sid]["name"]
            if mod.enabled:
                arch = servers[sid].get("arch")
                asset = mod.release.get(arch or "")
                if not asset:
                    raise ValueError(f"{n}: нет файла ядра для архитектуры {arch or 'неизвестно'} (проверьте сервер)")
                steps.append(step("node_module", sid, f"{n}: ядро Xray {mod.version} (SHA-256 {asset['sha256'][:12]}…)",
                                  module="xray_core", enabled=True, version=mod.version, url=asset["url"], sha256=asset["sha256"]))
            else:
                steps.append(step("node_module", sid, f"{n}: вернуть ядро Xray из образа ноды", module="xray_core", enabled=False))
            steps += [step("write_files", sid, f"{n}: файлы ({DIRS['node']})", component="node"),
                      step("compose_up", sid, f"{n}: перезапуск ноды", component="node")]
        steps.append(step("verify", None, "Проверка: ноды на связи, версия ядра"))
        title = f"Ядро Xray: {mod.version}" if mod.enabled else "Ядро Xray из образа ноды"
    elif name == "warp":
        if not targets:
            raise ValueError("Выберите серверы")
        for sid in targets:
            n = servers[sid]["name"]
            if mod.enabled:
                arch = servers[sid].get("arch")
                asset = mod.release.get(arch or "")
                if not asset:
                    raise ValueError(f"{n}: нет файла wgcf для архитектуры {arch or 'неизвестно'}")
                steps.append(step("node_module", sid, f"{n}: WARP — интерфейс warp (wgcf {mod.version}, SHA-256 {asset['sha256'][:12]}…)",
                                  module="warp", enabled=True, url=asset["url"], sha256=asset["sha256"]))
            else:
                steps.append(step("node_module", sid, f"{n}: WARP — выключить интерфейс warp", module="warp", enabled=False))
        title = f"WARP Native: {state}"
    elif name == "netbird":
        if not targets:
            raise ValueError("Выберите серверы")
        for sid in targets:
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: NetBird — {'подключить' if mod.enabled else 'отключить'}",
                              module="netbird", enabled=mod.enabled, management_url=mod.management_url))
        title = f"NetBird: {state}"
    elif name in ("hardening", "watchdog"):
        targets = mod.server_ids or list(roles)
        if any(sid not in roles for sid in targets):
            raise ValueError("Модуль ставится на серверы этой установки")
        for sid in targets:
            n = servers[sid]["name"]
            if name == "hardening":
                h = mod.hardening or Hardening()
                what = ", ".join([w for w, on in (("fail2ban для SSH", h.fail2ban), ("автообновления безопасности", h.upgrades), ("BBR", h.bbr)) if on]
                                 + ([f"SSH только с {', '.join(h.admin_ips)} и адреса магазина"] if h.admin_ips else [])) or "всё выключить"
                steps.append(step("node_module", sid, f"{n}: защита сервера — {what}", module="hardening", hardening=h.model_dump()))
            else:
                steps.append(step("node_module", sid, f"{n}: самовосстановление — {state}", module="watchdog", enabled=mod.enabled))
        title = MODULE_TITLES[name] + (f": {state}" if name == "watchdog" else "")
    elif name == "transports":
        if not plan.selfsteal_domain or len(plan.node_server_ids) != 1:
            raise ValueError("Транспорты меняются у установки с SelfSteal на одной ноде")
        sid = plan.node_server_ids[0]
        n = servers[sid]["name"]
        chosen = ", ".join(TRANSPORT_TITLES[t] for t in plan.transports) or "только TCP + REALITY"
        chosen += f"; отпечаток {FINGERPRINTS[plan.fingerprint]}" + (f"; TLS {plan.tls_min}–{plan.tls_max}" if "tls" in plan.transports else "")
        steps += [step("node_module", sid, f"{n}: порты и сертификат TLS — {chosen}", module="transports", transports=plan.transports),
                  step("write_files", sid, f"{n}: файлы ({DIRS['node']})", component="node"),
                  step("compose_up", sid, f"{n}: перезапуск ноды", component="node"),
                  step("node_transports", None, f"Панель: inbound'ы профиля SelfSteal, хосты и сквады — {chosen}"),
                  step("verify", None, "Проверка: нода на связи")]
        title = f"Протоколы и маскировка: {chosen}"
    elif name == "node_port":
        # v28.90.0 (N5): the node's port only from the panel (and the extra addresses) on every node at once — nftables
        # always, ufw too when it is on; «verify» takes the rule back from a node the panel stops seeing.
        targets = mod.server_ids or nodes
        if not targets or any(sid not in nodes for sid in targets):
            raise ValueError("Выберите ноды этой установки")
        extra = f" и {', '.join(plan.node_port_ips)}" if plan.node_port_ips else ""
        for sid in targets:
            what = f"только с адреса панели{extra}" if mod.enabled else "открыть (снять правило)"
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: порт {plan.node_port}/tcp — {what}", module="node_port",
                              enabled=mod.enabled, ips=plan.node_port_ips))
        steps.append(step("verify", None, "Проверка: панель видит ноды (иначе правило снимается)"))
        title = f"Порт ноды для панели: {'закрыть для всех, кроме панели' if mod.enabled else 'открыть'}"
    elif name == "sni_scan":
        # v28.92.0 (N7 «Автоподбор SNI»): read-only — which well-known sites answer the node with TLS 1.3 + HTTP/2.
        targets = mod.server_ids or nodes
        if not targets or any(sid not in nodes for sid in targets):
            raise ValueError("Выберите ноды этой установки")
        for sid in targets:
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: проверить сайты-кандидаты (TLS 1.3, HTTP/2, скорость); ничего не меняется",
                              module="sni_scan", enabled=True))
        title = "Подбор сайта для REALITY"
    elif name == "cdn":
        # v28.98.0 (N7): Cloudflare in front of the nodes' XHTTP and/or the subscription domain. Switching on: the node's
        # transport first, then the DNS records go behind the CDN; switching off: the records first, then the transport.
        sub_target = plan.sub_domain if plan.subpage_server_id else plan.panel_domain
        sub_server = plan.subpage_server_id or plan.panel_server_id
        node_steps: list[dict] = []
        if mod.cdn_nodes:
            if not plan.selfsteal_domain or len(plan.node_server_ids) != 1 or not plan.cdn_domain:
                raise ValueError("XHTTP через CDN — у установки с SelfSteal на одной ноде и с доменом CDN")
            sid = plan.node_server_ids[0]
            n = servers[sid]["name"]
            ip = servers[sid]["host"]
            chosen = ", ".join(TRANSPORT_TITLES[t] for t in plan.transports) or "только TCP + REALITY"
            node_steps = [step("node_module", sid, f"{n}: порты и сертификат TLS — {chosen}", module="transports", transports=plan.transports),
                          step("write_files", sid, f"{n}: файлы ({DIRS['node']})", component="node"),
                          step("compose_up", sid, f"{n}: перезапуск ноды", component="node"),
                          step("node_transports", None, f"Панель: inbound'ы и хосты — {chosen}")]
            dns = step("cdn_dns", None, (f"Cloudflare: {plan.cdn_domain} → {ip} через CDN, SSL «Full» для этого домена" if mod.enabled
                                         else f"Cloudflare: убрать {plan.cdn_domain} и правило SSL"),
                       part="nodes", on=bool(mod.enabled), domain=plan.cdn_domain, addresses=[ip])
            steps += node_steps + [dns] if mod.enabled else [dns] + node_steps
        if mod.cdn_subscription:
            if not sub_target or not sub_server:
                raise ValueError("Нет домена подписки в этой установке")
            on = bool(mod.enabled)
            steps.append(step("cdn_dns", None, f"Cloudflare: {sub_target} — {'через CDN (оранжевое облако)' if on else 'напрямую (серое облако)'}",
                              part="subscription", on=on, domain=sub_target, addresses=[servers[sub_server]["host"]]))
        if not steps:
            raise ValueError("Выберите, что вынести за CDN")
        steps.append(step("verify", None, "Проверка: ноды и панель на связи"))
        title = "Cloudflare CDN: " + ("включить" if mod.enabled else "выключить")
    elif name == "geo_files":
        # v28.95.0 (N7): the Russian geo lists on every node of the installation (like the Xray core: the files, then the node restarts).
        if not nodes:
            raise ValueError("В этой установке нет нод")
        for sid in nodes:
            n = servers[sid]["name"]
            if mod.enabled:
                if set(mod.release) != set(GEO_FILES):
                    raise ValueError("Нет файлов списков с SHA-256 (составьте план заново)")
                steps.append(step("node_module", sid, f"{n}: российские списки {mod.version} (geoip {mod.release['geoip']['sha256'][:12]}…, "
                                  f"geosite {mod.release['geosite']['sha256'][:12]}…)", module="geo_files", enabled=True, version=mod.version,
                                  files={k: mod.release[k] for k in GEO_FILES}))
            else:
                steps.append(step("node_module", sid, f"{n}: убрать российские списки", module="geo_files", enabled=False))
            steps += [step("write_files", sid, f"{n}: файлы ({DIRS['node']})", component="node"),
                      step("compose_up", sid, f"{n}: перезапуск ноды", component="node")]
        steps.append(step("verify", None, "Проверка: ноды на связи"))
        title = f"Российские списки: {mod.version}" if mod.enabled else "Российские списки: убрать"
    elif name == "psiphon":
        # v28.99.0 (N7): the owner's own Psiphon server on the chosen nodes (rw_netmods.PSIPHON).
        targets = mod.server_ids or nodes
        if not targets or any(sid not in nodes for sid in targets):
            raise ValueError("Выберите ноды этой установки")
        if mod.enabled and (mod.psiphon_port in MTPROTO_TAKEN or mod.psiphon_port == plan.node_port):
            raise ValueError(f"Порт {mod.psiphon_port} занят нодой: выберите другой")
        for sid in targets:
            what = (f"psiphond ({mod.psiphon_protocol}, TCP {mod.psiphon_port}) — сборка из исходников Psiphon при первом включении"
                    if mod.enabled else "убрать psiphond")
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: {what}", module="psiphon", enabled=mod.enabled,
                              psiphon_port=mod.psiphon_port, psiphon_protocol=mod.psiphon_protocol))
        title = f"{MODULE_TITLES[name]}: {state}"
    elif name == "mtproto":
        # v28.94.0 (N7): a Telegram MTProto proxy with FakeTLS on the chosen nodes (rw_netmods.MTPROTO, image pinned by digest).
        targets = mod.server_ids or nodes
        if not targets or any(sid not in nodes for sid in targets):
            raise ValueError("Выберите ноды этой установки")
        if mod.enabled and (mod.mtproto_port in MTPROTO_TAKEN or mod.mtproto_port == plan.node_port):
            raise ValueError(f"Порт {mod.mtproto_port} занят нодой: выберите другой (не 80, 443, 2053, 4443, 8443 и не порт ноды для панели)")
        for sid in targets:
            what = (f"MTProto-прокси на TCP {mod.mtproto_port}, маскировка под {mod.mtproto_domain}" if mod.enabled
                    else "убрать MTProto-прокси")
            steps.append(step("node_module", sid, f"{servers[sid]['name']}: {what}", module="mtproto", enabled=mod.enabled,
                              mtproto_port=mod.mtproto_port, mtproto_domain=mod.mtproto_domain))
        title = f"{MODULE_TITLES[name]}: {state}"
    elif name in ("mss_clamp", "node_guard", "swap"):
        # v28.92.0 (N7, rw_netmods): MSS clamp and the guard on the nodes by default, swap on any server of the installation.
        targets = mod.server_ids or (list(roles) if name == "swap" else nodes)
        if not targets or any(sid not in roles for sid in targets):
            raise ValueError("Выберите серверы этой установки")
        if name == "node_guard" and (not mod.guard_ports or any(not 1 <= p <= 65535 for p in mod.guard_ports)):
            raise ValueError("Порты защиты: от 1 до 65535")
        allow = _networks(mod.guard_allow, "Адрес без ограничений")
        for sid in targets:
            n = servers[sid]["name"]
            if name == "mss_clamp":
                what = "измерить MTU пути и включить MSS clamp, если нужен" if mod.enabled else "выключить MSS clamp"
            elif name == "node_guard":
                what = (f"{'лимит' if mod.guard_mode == 'enforce' else 'только счёт'} {mod.guard_rate} новых соединений/с с адреса на портах "
                        f"{', '.join(map(str, mod.guard_ports))}" if mod.enabled else "выключить защиту")
            else:
                what = f"файл подкачки {mod.swap_mb} МБ" if mod.enabled else "убрать файл подкачки"
            steps.append(step("node_module", sid, f"{n}: {what}", module=name, enabled=mod.enabled, ports=sorted(set(mod.guard_ports)),
                              rate=mod.guard_rate, allow=allow, mode=mod.guard_mode, swap_mb=mod.swap_mb))
        title = f"{MODULE_TITLES[name]}: {state}"
    elif name == "selfsteal_site":
        # v28.88.0 (BACKLOG A3): another site-template behind SelfSteal without a reinstall — the node's Caddy files
        # are rewritten (the previous ones come back on an error) and Caddy restarted; the node and REALITY stay as is.
        if not plan.selfsteal_domain or not plan.node_server_ids:
            raise ValueError("Сайт-шаблон меняется у установки с SelfSteal")
        site = SELFSTEAL_TEMPLATES[plan.selfsteal_template]
        for sid in plan.node_server_ids:
            n = servers[sid]["name"]
            steps += [step("write_files", sid, f"{n}: SelfSteal — сайт «{site}»", component="selfsteal"),
                      step("compose_up", sid, f"{n}: перезапуск Caddy SelfSteal", component="selfsteal")]
        steps.append(step("verify", None, "Проверка: ноды на связи"))
        title = f"Сайт SelfSteal: «{site}»"
    else:  # xray_checker
        sid = plan.xray_checker_server_id
        if mod.enabled and not sid:
            raise ValueError("Выберите сервер для Xray Checker")
        if mod.enabled:
            n = servers[sid]["name"]
            steps += [step("write_files", sid, f"{n}: файлы ({DIRS['xray_checker']})", component="xray_checker"),
                      step("compose_up", sid, f"{n}: запуск Xray Checker", component="xray_checker"),
                      step("node_module", sid, f"{n}: Xray Checker отвечает (127.0.0.1:2112)", module="xray_checker", enabled=True)]
        else:
            old = mod.server_ids[0] if mod.server_ids else None
            if not old:
                raise ValueError("Xray Checker не установлен")
            steps.append(step("compose_down", old, f"{servers[old]['name']}: остановка Xray Checker", component="xray_checker"))
        title = f"Xray Checker: {state}"
    return steps, title


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
    if action == "module":
        steps, title = module_steps(plan, servers, roles)
        return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {title}", "images": IMAGES,
                "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": rs, "changes": []}
                            for sid, rs in roles.items()},
                "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}

    def components(sid: int) -> list[str]:
        rs = roles[sid]
        out = [c for c in ("panel", "subscription_page") if c in rs]
        if {"panel", "subscription_page"} & set(rs):
            out.append("proxy")
        if "node" in rs:
            if plan.selfsteal_domain:
                out.append("selfsteal")
            out.append("node")
        if sid == plan.xray_checker_server_id:
            out.append("xray_checker")
        return out

    if action == "change_domain":
        # v28.97.0 (N7): the panel moves to a new domain. The new domain must point at the panel's server (checked first);
        # the panel's .env (PANEL_DOMAIN, FRONT_END_DOMAIN and, without a separate subscription page, SUB_PUBLIC_DOMAIN)
        # and Caddy are written again; former domains in panel_domain_aliases keep serving /api/sub/ (the clients'
        # subscription links) and redirect the rest. After success the shop rewrites the stored subscription links.
        if not p:
            raise ValueError("В этой установке нет панели")
        name = servers[p]["name"]
        new, old = plan.panel_domain, plan.panel_domain_aliases
        steps.append(step("preflight", p, f"{name}: {new} указывает на этот сервер", roles=roles[p], domains=[new], node_port=None))
        steps += [step("backup_panel", p, f"{name}: копия базы панели"),
                  step("write_files", p, f"{name}: файлы панели ({DIRS['panel']}) — домен {new}", component="panel"),
                  step("write_files", p, f"{name}: Caddy ({DIRS['proxy']}) — {new}" + (f", прежние {', '.join(old)} — подписки и переадресация" if old else ""),
                       component="proxy")]
        if plan.subpage_server_id == p and plan.sub_domain:
            steps.append(step("write_files", p, f"{name}: файлы страницы подписки ({DIRS['subscription_page']})", component="subscription_page"))
        steps += [step("compose_up", p, f"{name}: перезапуск панели", component="panel"),
                  step("wait_panel", p, f"{name}: панель отвечает (/health)"),
                  step("compose_up", p, f"{name}: перезапуск Caddy", component="proxy"),
                  step("verify", None, f"Проверка: https://{new}")]
        changes = [f"Домен панели — {new}"] + ([f"Прежние домены {', '.join(old)}: подписки работают, остальное — переадресация на {new}"] if old
                                              else ["Прежних доменов больше нет"])
        return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {new}", "images": IMAGES,
                "servers": {str(p): {"name": name, "host": servers[p]["host"], "roles": roles[p], "changes": changes}},
                "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}
    if action == "snapshot":
        # v28.92.0 (N7): «Снапшот сервера» — the panel's database (as before an update) and the files of every
        # component (compose, .env, Caddyfile, site; no volumes), encrypted in the shop; downloaded in «Установка».
        if p:
            steps += [step("backup_panel", p, f"{servers[p]['name']}: копия базы панели"),
                      step("fetch_panel_backup", p, f"{servers[p]['name']}: копия базы панели — зашифрованной в хранилище магазина")]
        for sid in roles:
            steps.append(step("fetch_configs", sid, f"{servers[sid]['name']}: файлы компонентов ({', '.join(components(sid))}) — в хранилище магазина"))
        return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {MODE_TITLES[plan.mode]}", "images": IMAGES,
                "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": rs, "changes": []}
                            for sid, rs in roles.items()},
                "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}
    if action == "restore_files":
        # v28.93.0 (N7): the files of a snapshot back on its server — the current files are packed first and come back
        # on any error; then every component of the server restarts with the restored files.
        name = plan.snapshot_file or ""
        sid = int(name.split("-")[1]) if name else None
        if sid not in roles:
            raise ValueError("Снапшот не от сервера этой установки")
        steps.append(step("put_configs", sid, f"{servers[sid]['name']}: файлы из снапшота {name.removesuffix('.enc')} (текущие — в копию на сервере)",
                          snapshot=name))
        steps += [step("compose_up", sid, f"{servers[sid]['name']}: перезапуск ({DIRS[c]})", component=c) for c in components(sid)]
        if "panel" in components(sid):
            steps.append(step("wait_panel", sid, f"{servers[sid]['name']}: панель отвечает (/health)"))
        return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {servers[sid]['name']}", "images": IMAGES,
                "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": roles[sid],
                                       "changes": [f"Файлы компонентов — из снапшота {name.removesuffix('.enc')}"]}},
                "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}
    if action == "remove_component":
        comp = plan.remove_component
        holders = [sid for sid in roles if comp in components(sid)]
        if not comp or not holders:
            raise ValueError("Этого компонента нет на серверах установки")
        if comp == "panel":
            steps += [step("backup_panel", p, f"{servers[p]['name']}: копия базы панели"),
                      step("fetch_panel_backup", p, f"{servers[p]['name']}: копия базы панели — зашифрованной в хранилище магазина")]
        for sid in holders:
            steps.append(step("compose_down", sid, f"{servers[sid]['name']}: остановить и убрать контейнеры ({DIRS[comp]}); тома и файлы остаются",
                              component=comp))
        return {"mode": plan.mode, "action": action, "title": f"{ACTION_TITLES[action]}: {DIRS[comp]}", "images": IMAGES,
                "servers": {str(sid): {"name": servers[sid]["name"], "host": servers[sid]["host"], "roles": roles[sid],
                                       "changes": [f"Контейнеры {DIRS[comp]} остановлены и удалены; вернуть — «Переустановить» установку"]}
                            for sid in holders},
                "steps": [{**st, "position": i + 1} for i, st in enumerate(steps)]}
    if action in SERVICE_ACTIONS:
        verb = {"start": "запуск", "stop": "остановка", "restart": "перезапуск", "logs": f"последние {LOG_LINES} строк журнала"}[action]
        order = list(roles)
        if action == "stop":  # nodes first, the panel last: clients lose a node before the panel goes
            order = sorted(order, key=lambda sid: 0 if "node" in roles[sid] else 1)
        for sid in order:
            name = servers[sid]["name"]
            for comp in components(sid):
                steps.append(step("compose_ctl", sid, f"{name}: {verb} ({DIRS[comp]})", component=comp, op=action))
                if comp == "panel" and action in ("start", "restart"):
                    steps.append(step("wait_panel", sid, f"{name}: панель отвечает (/health)"))
        if action in ("start", "restart") and any("node" in rs for rs in roles.values()):
            steps.append(step("verify", None, "Проверка: HTTPS панели, связь нод, страница подписки"))
    elif action == "diagnose":
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
            steps.append(step("fetch_panel_backup", p, f"{servers[p]['name']}: копия базы панели — зашифрованной в хранилище магазина"))
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
