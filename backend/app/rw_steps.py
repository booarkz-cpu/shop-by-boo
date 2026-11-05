"""Steps of the Remnawave installation wizard — the closed list (v28.66, stage 10; docs/ru/new/DEPLOYMENT_AGENT.md).

Every step is a fixed script of this module with typed parameters. ``STEP_KINDS`` is the whole list: the runner
refuses any other kind. Each step is idempotent (running it again does not break what it did), and the steps
that change a server have a rollback that the runner calls in reverse order after a failure."""
from __future__ import annotations

import asyncio
import re
import ipaddress
import os
import json
import secrets as pysecrets
import socket
import string
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import rw_plan
from .rw_remote import Remote, RemoteError, tail

STEP_KINDS = ("preflight", "install_docker", "write_files", "compose_up", "wait_panel", "panel_bootstrap",
              "firewall_node_port", "register_node", "verify", "backup_panel", "restore_panel", "compose_down",
              "selfsteal_profile", "node_module", "fetch_panel_backup", "compose_ctl", "node_transports")
FILE_NAMES = ("docker-compose.yml", ".env", "Caddyfile", "index.html")
COMPONENTS = ("panel", "node", "subscription_page", "proxy", "selfsteal", "xray_checker")
_sleep = asyncio.sleep  # tests replace it
fetch_bytes = None  # tests: async (url) -> bytes
SUPPORTED_OS = {("debian", "12"), ("debian", "13"), ("ubuntu", "22.04"), ("ubuntu", "24.04"), ("ubuntu", "26.04")}


class StepError(RuntimeError):
    """A step failed; the message is shown to the administrator (no secrets, no raw remote output)."""


@dataclass
class Context:
    """What a running installation knows. ``servers`` — id → registry row as a dict with decrypted credentials."""
    plan: rw_plan.PlanIn
    servers: dict[int, dict]
    secrets: dict
    state: dict
    shop_panel_url: str | None = None
    shop_panel_token: str | None = None
    log: list[str] = field(default_factory=list)
    connect: object = None  # callable(server) -> Remote; replaced in tests

    def remote(self, server_id: int) -> Remote:
        server = self.servers[server_id]
        if self.connect:
            return self.connect(server)
        return Remote(server["host"], server["ssh_port"], server["ssh_user"], server["host_key_fingerprint"],
                      key=server.get("key"), password=server.get("password"))

    def secret_values(self) -> list[str]:
        return [v for v in self.secrets.values() if isinstance(v, str)] + [self.shop_panel_token or ""]


def access_cookie(ctx: "Context") -> tuple[str, str]:
    """The panel's access key; made once and kept with the installation's secrets (it survives updates)."""
    if not ctx.secrets.get("panel_cookie_name"):
        ctx.secrets["panel_cookie_name"] = "rw" + pysecrets.token_hex(6)
        ctx.secrets["panel_cookie_value"] = pysecrets.token_hex(16)
    return ctx.secrets["panel_cookie_name"], ctx.secrets["panel_cookie_value"]


def tinyauth_login(ctx: "Context") -> tuple[str, str]:
    """The TinyAuth login (v28.78.0): made once and kept with the installation's secrets, so the files of an update
    are the same and the administrator's session survives. Returns (username, bcrypt hash); the password itself
    is shown with the panel's credentials."""
    if not ctx.secrets.get("tinyauth_password_hash"):
        import bcrypt  # a dependency of paramiko, which the wizard's SSH needs anyway
        password = pysecrets.token_urlsafe(18)
        ctx.secrets["tinyauth_username"] = "corgi"
        ctx.secrets["tinyauth_password"] = password
        ctx.secrets["tinyauth_password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    return ctx.secrets["tinyauth_username"], ctx.secrets["tinyauth_password_hash"]


def new_secrets() -> dict:
    alphabet = string.ascii_letters + string.digits
    # The panel requires 24+ characters with upper and lower case letters and digits.
    password = "Rw" + "".join(pysecrets.choice(alphabet) for _ in range(30)) + "a1Z"
    return {"db_password": pysecrets.token_hex(24), "app_secret": pysecrets.token_hex(48), "metrics_password": pysecrets.token_hex(16),
            "subpage_jwt_secret": pysecrets.token_hex(32), "panel_admin_username": "corgi-admin", "panel_admin_password": password}


async def _run(ctx: Context, server_id: int, script: str, *args: str, stdin: bytes | None = None, timeout: int = 900):
    def work():
        with ctx.remote(server_id) as remote:
            return remote.run(script, *args, stdin=stdin, timeout=timeout)
    try:
        return await asyncio.to_thread(work)
    except RemoteError as exc:
        raise StepError(str(exc)) from exc


def _note(ctx: Context, text: str) -> None:
    ctx.log.append(tail(text, ctx.secret_values()))


# ---------- preflight ----------

PREFLIGHT = r"""set -u
. /etc/os-release 2>/dev/null || true
echo "os_id=${ID:-unknown}"; echo "os_version=${VERSION_ID:-}"; echo "os_name=${PRETTY_NAME:-unknown}"
echo "arch=$(uname -m)"; echo "cpu=$(nproc 2>/dev/null || echo 0)"
echo "ram_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)"
echo "disk_gb=$(df -Pk / | awk 'NR==2{print int($4/1048576)}')"
echo "root=$([ "$(id -u)" = 0 ] && echo yes || echo no)"
if command -v docker >/dev/null 2>&1; then
  echo "docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo client-only)"
  echo "compose=$(docker compose version --short 2>/dev/null || echo none)"
  for c in remnawave remnanode remnawave-subscription-page remnawave-caddy; do
    s="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" && echo "container=$c $s"
  done
else echo "docker=none"; echo "compose=none"; fi
ss -ltnpH 2>/dev/null | awk '{n=split($4,a,":"); p=$6; sub(/^users:\(\("/,"",p); sub(/".*/,"",p); print "listen=" a[n] " " p}'
for svc in nginx apache2 caddy haproxy angie; do systemctl is-active --quiet "$svc" 2>/dev/null && echo "service=$svc"; done
if command -v ufw >/dev/null 2>&1; then echo "ufw=$(ufw status 2>/dev/null | awk 'NR==1{print $2}')"; else echo "ufw=none"; fi
echo "public_ip=$(hostname -I 2>/dev/null | awk '{print $1}')"
for d in "$@"; do echo "dns=$d $(getent ahostsv4 "$d" 2>/dev/null | awk 'NR==1{print $1}')"; done
"""

OWNER_CONTAINER = {"caddy": "remnawave-caddy", "panel": "remnawave", "subscription_page": "remnawave-subscription-page",
                   "node": "remnanode", "selfsteal": "remnawave-selfsteal"}


def parse_facts(text: str) -> dict:
    facts: dict = {"listen": {}, "services": [], "containers": {}, "dns": {}}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "listen":
            port, _, proc = value.partition(" ")
            if port.isdigit():
                facts["listen"].setdefault(int(port), proc or "?")
        elif key == "service":
            facts["services"].append(value)
        elif key == "container":
            name, _, status = value.partition(" ")
            facts["containers"][name] = status
        elif key == "dns":
            domain, _, ip = value.partition(" ")
            facts["dns"][domain] = ip or None
        elif key in ("cpu", "ram_mb", "disk_gb"):
            facts[key] = int(value) if value.isdigit() else 0
        elif key:
            facts[key] = value
    return facts


def evaluate(facts: dict, roles: list[str], domains: list[str], node_port: int | None, host: str, tls: str) -> list[dict]:
    """Checks of the preflight: ``error`` stops the installation, ``warn`` is shown in the plan."""
    checks = []

    def add(key, status, detail):
        checks.append({"key": key, "status": status, "detail": detail})

    os_pair = (facts.get("os_id"), facts.get("os_version"))
    if os_pair in SUPPORTED_OS:
        add("os", "ok", f"{facts.get('os_name')}")
    elif facts.get("compose") not in (None, "none"):
        add("os", "warn", f"{facts.get('os_name')}: не проверялась, но Docker с compose уже есть")
    else:
        add("os", "error", f"{facts.get('os_name')}: поддерживаются Debian 12–13 и Ubuntu 22.04–26.04")
    arch = facts.get("arch")
    add("arch", "ok" if arch in ("x86_64", "aarch64") else "error", f"Архитектура {arch}")
    need_ram = 2048 if "panel" in roles else 512
    ram = facts.get("ram_mb", 0)
    add("ram", "ok" if ram >= need_ram else ("warn" if ram >= need_ram // 2 else "error"), f"Память {ram} МБ, нужно от {need_ram}")
    need_disk = 10 if "panel" in roles else 5
    disk = facts.get("disk_gb", 0)
    add("disk", "ok" if disk >= need_disk else "error", f"Свободно {disk} ГБ, нужно от {need_disk}")
    add("cpu", "ok" if facts.get("cpu", 0) >= 1 else "error", f"Процессоров: {facts.get('cpu', 0)}")
    add("root", "ok" if facts.get("root") == "yes" else "error",
        "Права root есть" if facts.get("root") == "yes" else "Нет прав root: нужен root или sudo без пароля")
    docker = facts.get("docker", "none")
    add("docker", "ok" if docker != "none" else "warn", f"Docker {docker}" if docker != "none" else "Docker нет — будет установлен")
    listen = facts.get("listen", {})
    wanted = []
    if {"panel", "subscription_page"} & set(roles):
        wanted += [(p, "caddy") for p in rw_plan.PANEL_PORTS]
    if "panel" in roles:
        wanted += [(p, "panel") for p in rw_plan.LOCAL_PORTS["panel"]]
    if "subscription_page" in roles:
        wanted += [(p, "subscription_page") for p in rw_plan.LOCAL_PORTS["subscription_page"]]
    if "node" in roles and node_port:
        wanted.append((node_port, "node"))
    if "selfsteal" in roles:
        wanted += [(80, "selfsteal"), (443, "node")]
    containers = facts.get("containers", {})
    for port, owner in wanted:
        proc = listen.get(port)
        if not proc:
            add(f"port_{port}", "ok", f"Порт {port} свободен")
        elif OWNER_CONTAINER[owner] in containers:
            add(f"port_{port}", "warn", f"Порт {port} занят прежней установкой Remnawave ({OWNER_CONTAINER[owner]}): она будет обновлена")
        else:
            # Another reverse proxy (for example the shop's own Caddy) is never replaced or doubled.
            add(f"port_{port}", "error", f"Порт {port} занят процессом {proc}: освободите его или выберите другой сервер")
    for svc in facts.get("services", []):
        add(f"service_{svc}", "error" if {"panel", "subscription_page"} & set(roles) else "warn",
            f"Работает {svc}: он конфликтует с Caddy за порты 80/443" if {"panel", "subscription_page"} & set(roles) else f"Работает {svc}")
    try:
        server_ip = str(ipaddress.ip_address(host))
    except ValueError:
        server_ip = facts.get("public_ip")
    for domain in domains:
        ip = facts.get("dns", {}).get(domain)
        if ip and server_ip and ip == server_ip:
            add(f"dns_{domain}", "ok", f"{domain} → {ip}")
        else:
            add(f"dns_{domain}", "error" if tls == "acme" else "warn",
                f"{domain} → {ip or 'не найден'}, а сервер {server_ip}: " + ("Let's Encrypt не выдаст сертификат" if tls == "acme" else "для внутреннего сертификата это допустимо"))
    if facts.get("ufw") not in (None, "none"):
        add("ufw", "ok", f"ufw: {facts.get('ufw')}")
    return checks


async def preflight(ctx: Context, server_id: int, roles: list[str], domains: list[str], node_port: int | None) -> dict:
    result = await _run(ctx, server_id, PREFLIGHT, *domains, timeout=120)
    if result.code != 0 and "password is required" in result.err:
        raise StepError("sudo требует пароль: дайте пользователю sudo без пароля или используйте root")
    facts = parse_facts(result.out)
    checks = evaluate(facts, roles, domains, node_port, ctx.servers[server_id]["host"], ctx.plan.tls)
    return {"facts": facts, "checks": checks, "ok": not any(c["status"] == "error" for c in checks)}


async def run_preflight(ctx: Context, st: dict) -> None:
    out = await preflight(ctx, st["server_id"], st["params"]["roles"], st["params"]["domains"], st["params"].get("node_port"))
    ctx.state.setdefault("preflight", {})[str(st["server_id"])] = out
    errors = [c["detail"] for c in out["checks"] if c["status"] == "error"]
    for c in out["checks"]:
        _note(ctx, f"{c['status']}: {c['detail']}")
    if st["params"].get("report_only"):
        containers = out["facts"].get("containers", {})
        _note(ctx, "Контейнеры: " + (", ".join(f"{k} {v}" for k, v in containers.items()) or "нет контейнеров Remnawave"))
        return
    if errors:
        raise StepError("Проверка не пройдена: " + "; ".join(errors))


# ---------- docker ----------

async def run_install_docker(ctx: Context, st: dict) -> None:
    from .provisioner import DOCKER_INSTALL
    result = await _run(ctx, st["server_id"], DOCKER_INSTALL, timeout=900)
    _note(ctx, result.out + result.err)
    if result.code != 0:
        raise StepError("Docker не установлен: " + ("ключ репозитория Docker не совпал с опубликованным" if result.code == 21 else
                                                   "ОС не Debian/Ubuntu" if result.code == 20 else "ошибка apt"))


# ---------- files ----------

WRITE = r"""set -eu
dir="$1"; name="$2"; sum="$3"
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy|/opt/remnawave-selfsteal|/opt/remnawave-xray-checker) ;; *) echo "bad dir" >&2; exit 2 ;; esac
case "$name" in docker-compose.yml|.env|Caddyfile|index.html) ;; *) echo "bad name" >&2; exit 2 ;; esac
install -d -m 0750 "$dir"
umask 077
if [ -f "$dir/$name" ]; then cp -p "$dir/$name" "$dir/$name.rw-prev"; else rm -f "$dir/$name.rw-prev"; fi
cat > "$dir/$name.rw-new"
echo "$sum  $dir/$name.rw-new" | sha256sum -c --status
# A page served by a container that does not run as root must be readable; secrets (.env) stay 0600.
[ "$name" = index.html ] && chmod 0644 "$dir/$name.rw-new"
mv "$dir/$name.rw-new" "$dir/$name"
"""

UNWRITE = r"""set -eu
dir="$1"; name="$2"
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy|/opt/remnawave-selfsteal|/opt/remnawave-xray-checker) ;; *) exit 2 ;; esac
case "$name" in docker-compose.yml|.env|Caddyfile|index.html) ;; *) exit 2 ;; esac
if [ -f "$dir/$name.rw-prev" ]; then mv "$dir/$name.rw-prev" "$dir/$name"; else rm -f "$dir/$name"; fi
"""


async def _panel_url_and_token(ctx: Context) -> tuple[str, str]:
    if ctx.plan.panel_server_id:
        token = ctx.secrets.get("panel_token")
        if not token:
            raise StepError("Нет токена API панели: шаг «администратор панели» не выполнен")
        return f"https://{ctx.plan.panel_domain}", token
    if not (ctx.shop_panel_url and ctx.shop_panel_token):
        raise StepError("Магазин не подключён к панели Remnawave")
    return ctx.shop_panel_url, ctx.shop_panel_token


async def files_for(ctx: Context, component: str, server_id: int) -> dict[str, str]:
    plan = ctx.plan
    if component == "panel":
        return {"docker-compose.yml": rw_plan.panel_compose(), ".env": rw_plan.panel_env(plan, ctx.secrets)}
    if component == "subscription_page":
        url, token = await _panel_url_and_token(ctx)
        local = server_id == plan.panel_server_id
        files = {"docker-compose.yml": rw_plan.subpage_compose(plan.subpage_template), ".env": rw_plan.subpage_env(url, token, ctx.secrets, local)}
        if plan.subpage_template == "orion":
            files["index.html"] = await orion_page()
        return files
    if component == "proxy":
        sites = {}
        if server_id == plan.panel_server_id:
            sites[plan.panel_domain] = 3000
        if server_id == plan.subpage_server_id:
            sites[plan.sub_domain] = 3010
        protect, guard, gate, files = {}, {}, {}, {}
        if plan.panel_access == "cookie" and plan.panel_domain in sites:
            protect[plan.panel_domain] = access_cookie(ctx)
        tinyauth = plan.panel_access == "tinyauth" and plan.panel_domain in sites
        if tinyauth:
            sites[plan.auth_domain] = rw_plan.TINYAUTH_PORT
            guard[plan.panel_domain] = rw_plan.TINYAUTH_PORT
            files[".env"] = rw_plan.tinyauth_env(plan.auth_domain, *tinyauth_login(ctx))
        if plan.panel_access == "gate" and plan.panel_domain in sites:
            from .panel_gate import shop_base
            gate[plan.panel_domain] = shop_base()
        return {"Caddyfile": rw_plan.caddyfile(sites, plan.tls, plan.acme_email, protect, guard, gate),
                "docker-compose.yml": rw_plan.caddy_compose(tinyauth), **files}
    if component == "node":
        key = ctx.state.get("node_secret_key") or await _keygen(ctx)
        return {"docker-compose.yml": rw_plan.node_compose(key, plan.node_port, selfsteal=bool(plan.selfsteal_domain), hysteria="hysteria2" in plan.transports,
                                                           xray_core=bool(plan.xray_core))}
    if component == "xray_checker":
        url = ctx.secrets.get("checker_subscription_url")
        if not url:
            raise StepError("Не задан адрес подписки для Xray Checker")
        if not ctx.secrets.get("checker_password"):
            ctx.secrets["checker_user"] = "checker"
            ctx.secrets["checker_password"] = pysecrets.token_hex(16)
        return {"docker-compose.yml": rw_plan.checker_compose(),
                ".env": rw_plan.checker_env(url, plan.xray_checker_interval, ctx.secrets["checker_user"], ctx.secrets["checker_password"])}
    if component == "selfsteal":
        return {"Caddyfile": rw_plan.selfsteal_caddyfile(plan.selfsteal_domain, plan.tls, plan.acme_email),
                "index.html": rw_plan.selfsteal_page(plan.selfsteal_template, plan.selfsteal_domain),
                "docker-compose.yml": rw_plan.selfsteal_compose()}
    raise StepError(f"Неизвестный компонент {component}")


async def orion_page() -> str:
    """The pinned Orion page; a file whose SHA-256 differs is never written."""
    import hashlib
    if fetch_bytes:
        data = await fetch_bytes(rw_plan.ORION["url"])
    else:
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(rw_plan.ORION["url"])
        if r.status_code != 200:
            raise StepError(f"Шаблон Orion не скачан: HTTP {r.status_code}")
        data = r.content
    if hashlib.sha256(data).hexdigest() != rw_plan.ORION["sha256"]:
        raise StepError("Шаблон Orion не совпал с закреплённой SHA-256: файл не записан")
    return data.decode()


async def run_write_files(ctx: Context, st: dict) -> None:
    import hashlib
    component = st["params"]["component"]
    directory = rw_plan.DIRS[component]
    written = []
    for name, content in (await files_for(ctx, component, st["server_id"])).items():
        data = content.encode()
        result = await _run(ctx, st["server_id"], WRITE, directory, name, hashlib.sha256(data).hexdigest(), stdin=data, timeout=60)
        if result.code != 0:
            raise StepError(f"Не удалось записать {directory}/{name}")
        written.append(name)
        _note(ctx, f"{directory}/{name}: записан, SHA-256 сверен")
    ctx.state.setdefault("written", {})[f"{st['server_id']}:{component}"] = written


async def undo_write_files(ctx: Context, st: dict) -> None:
    component = st["params"]["component"]
    for name in ctx.state.get("written", {}).get(f"{st['server_id']}:{component}", []):
        await _run(ctx, st["server_id"], UNWRITE, rw_plan.DIRS[component], name, timeout=60)


# ---------- compose ----------

COMPOSE = r"""set -eu
dir="$1"; action="$2"
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy|/opt/remnawave-selfsteal|/opt/remnawave-xray-checker) ;; *) exit 2 ;; esac
cd "$dir"
case "$action" in
  up) if [ "$dir" = /opt/remnawave-subpage ]; then docker network inspect remnawave-network >/dev/null 2>&1 || docker network create remnawave-network >/dev/null; fi
      docker compose pull -q && docker compose up -d --remove-orphans && docker compose ps --format '{{.Name}} {{.State}}' ;;
  down) docker compose down --remove-orphans ;;
  ps) docker compose ps --format '{{.Name}} {{.State}}' ;;
  start) docker compose start && docker compose ps --format '{{.Name}} {{.State}}' ;;
  stop) docker compose stop && docker compose ps -a --format '{{.Name}} {{.State}}' ;;
  restart) docker compose restart && docker compose ps --format '{{.Name}} {{.State}}' ;;
  logs) docker compose logs --no-color --timestamps --tail "${3:-200}" 2>&1 ;;
  *) exit 2 ;;
esac
"""


async def run_compose_up(ctx: Context, st: dict) -> None:
    result = await _run(ctx, st["server_id"], COMPOSE, rw_plan.DIRS[st["params"]["component"]], "up", timeout=1200)
    _note(ctx, result.out + result.err)
    if result.code != 0:
        raise StepError("Контейнеры не запустились: docker compose завершился с ошибкой (журнал шага)")


async def undo_compose_up(ctx: Context, st: dict) -> None:
    # Volumes stay: a rollback never deletes the panel's database.
    await _run(ctx, st["server_id"], COMPOSE, rw_plan.DIRS[st["params"]["component"]], "down", timeout=300)


async def run_compose_down(ctx: Context, st: dict) -> None:
    result = await _run(ctx, st["server_id"], COMPOSE, rw_plan.DIRS[st["params"]["component"]], "down", timeout=300)
    _note(ctx, result.out + result.err)
    if result.code != 0:
        raise StepError("Контейнеры не остановлены")


# "remnawave | JWT_AUTH_SECRET=…", "password: …": whatever follows a secret-looking name on a log line.
_ENV_SECRET = re.compile(r"(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY)[A-Z0-9_]*\s*[=:]\s*)\S+")


async def run_compose_ctl(ctx: Context, st: dict) -> None:
    """start / stop / restart / logs of one component's containers; files and volumes never change. Logs go to the
    step's journal with the installation's secrets and anything that looks like KEY=value of a secret replaced."""
    op = st["params"]["op"]
    if op not in rw_plan.SERVICE_ACTIONS:
        raise StepError("Неизвестная команда")
    args = (str(rw_plan.LOG_LINES),) if op == "logs" else ()
    result = await _run(ctx, st["server_id"], COMPOSE, rw_plan.DIRS[st["params"]["component"]], op, *args, timeout=300)
    text = result.out + result.err
    if op == "logs":
        text = _ENV_SECRET.sub(lambda m: m.group(1) + "***", text)
    _note(ctx, text)
    if result.code != 0:
        raise StepError({"start": "Контейнеры не запустились", "stop": "Контейнеры не остановлены",
                         "restart": "Контейнеры не перезапустились", "logs": "Журнал не прочитан"}[op] + " (журнал шага)")


# ---------- panel ----------

WAIT_PANEL = r"""for i in $(seq 1 90); do curl -fsS --max-time 3 http://127.0.0.1:3001/health >/dev/null 2>&1 && { echo ready; exit 0; }; sleep 2; done; exit 1"""

PANEL_CALL = r"""set -eu
method="$1"; path="$2"; browser="${3:-0}"
case "$method" in GET|POST|PATCH|DELETE) ;; *) exit 2 ;; esac
case "$path" in /api/*) ;; *) exit 2 ;; esac
tmp="$(mktemp)"; chmod 600 "$tmp"; trap 'rm -f "$tmp" "$tmp.body"' EXIT
IFS= read -r token || true
: > "$tmp"
[ -n "$token" ] && printf 'Authorization: Bearer %s\n' "$token" >> "$tmp"
[ "$browser" = 1 ] && printf 'X-Remnawave-Client-Type: browser\n' >> "$tmp"
cat > "$tmp.body"
if [ -s "$tmp.body" ]; then set -- --data-binary @"$tmp.body"; else set --; fi
curl -sS --max-time 60 -w '\n%{http_code}' -X "$method" -H 'X-Forwarded-For: 127.0.0.1' -H 'X-Forwarded-Proto: https' \
  -H 'Content-Type: application/json' -H @"$tmp" "$@" "http://127.0.0.1:3000$path"
"""


async def panel_api(ctx: Context, method: str, path: str, body: dict | None = None, token: str | None = None, browser: bool = False):
    """A call to the panel. A panel installed by this run is reached over SSH on 127.0.0.1:3000 (before DNS and TLS
    exist); otherwise the shop's own Remnawave client is used."""
    if not ctx.plan.panel_server_id:
        from .remnawave import RemnawaveClient
        try:
            return await RemnawaveClient()._request(method, path, **({"json": body} if body is not None else {}))
        except Exception as exc:  # RemnawaveError, not configured, circuit open, network
            raise StepError(f"Панель магазина ответила ошибкой на {method} {path}: {type(exc).__name__}") from exc
    token = ctx.secrets.get("panel_token", "") if token is None else token
    stdin = (token + "\n" + (json.dumps(body) if body is not None else "")).encode()
    result = await _run(ctx, ctx.plan.panel_server_id, PANEL_CALL, method, path, "1" if browser else "0", stdin=stdin, timeout=90)
    text, _, code = result.out.rpartition("\n")
    if result.code != 0 or not code.isdigit() or int(code) >= 400:
        raise StepError(f"Панель ответила ошибкой на {method} {path} ({code or result.code})")
    data = json.loads(text) if text.strip() else {}
    return data.get("response", data) if isinstance(data, dict) else data


async def run_wait_panel(ctx: Context, st: dict) -> None:
    result = await _run(ctx, st["server_id"], WAIT_PANEL, timeout=240)
    if result.code != 0:
        raise StepError("Панель не ответила на /health за 3 минуты")


async def run_panel_bootstrap(ctx: Context, st: dict) -> None:
    if ctx.secrets.get("panel_token"):
        try:
            await panel_api(ctx, "GET", "/api/system/metadata")
            _note(ctx, "Токен API уже создан и действует")
            return
        except StepError:
            ctx.secrets.pop("panel_token", None)
    creds = {"username": ctx.secrets["panel_admin_username"], "password": ctx.secrets["panel_admin_password"]}
    try:
        auth = await panel_api(ctx, "POST", "/api/auth/register", creds, token="")
    except StepError:
        auth = await panel_api(ctx, "POST", "/api/auth/login", creds, token="")  # registered by an earlier run
    jwt = auth.get("accessToken")
    if not jwt:
        raise StepError("Панель не выдала токен администратора")
    made = await panel_api(ctx, "POST", "/api/tokens", {"name": "corgi-shop", "expiresInDays": 3650}, token=jwt, browser=True)
    if not made.get("token"):
        raise StepError("Панель не создала токен API")
    ctx.secrets["panel_token"] = made["token"]
    _note(ctx, f"Администратор панели {ctx.secrets['panel_admin_username']} создан; токен API для магазина сохранён зашифрованным")


async def _keygen(ctx: Context) -> str:
    out = await panel_api(ctx, "GET", "/api/keygen")
    key = (out or {}).get("pubKey") or (out or {}).get("secretKey")
    if not key:
        raise StepError("Панель не выдала ключ ноды")
    ctx.state["node_secret_key"] = key
    return key


# ---------- node ----------

FIREWALL = r"""set -eu
ip="$1"; port="$2"; action="$3"
command -v ufw >/dev/null 2>&1 || { echo "ufw нет: правило не добавлено"; exit 0; }
ufw status 2>/dev/null | head -1 | grep -q active || { echo "ufw выключен: правило не добавлено"; exit 0; }
if [ "$action" = add ]; then ufw allow from "$ip" to any port "$port" proto tcp; else ufw delete allow from "$ip" to any port "$port" proto tcp || true; fi
if [ "${4:-}" = web ]; then
  if [ "$action" = add ]; then ufw allow 80/tcp; ufw allow 443/tcp; else ufw delete allow 80/tcp || true; ufw delete allow 443/tcp || true; fi
fi
"""


def panel_ip(ctx: Context) -> str:
    host = ctx.servers[ctx.plan.panel_server_id]["host"] if ctx.plan.panel_server_id else urlsplit(ctx.shop_panel_url or "").hostname
    if not host:
        raise StepError("Не известен адрес панели")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        try:
            return socket.gethostbyname(host)
        except OSError as exc:
            raise StepError(f"Адрес панели {host} не разрешается") from exc


async def run_firewall_node_port(ctx: Context, st: dict) -> None:
    if st["server_id"] == ctx.plan.panel_server_id:
        _note(ctx, "Нода на сервере панели: панель обращается к ней локально, правило не нужно")
        return
    ip = panel_ip(ctx)
    web = ("web",) if ctx.plan.selfsteal_domain else ()
    result = await _run(ctx, st["server_id"], FIREWALL, ip, str(ctx.plan.node_port), "add", *web, timeout=60)
    _note(ctx, result.out + result.err)
    if result.code != 0:
        raise StepError("Правило ufw не добавлено")
    ctx.state.setdefault("firewall", {})[str(st["server_id"])] = ip


async def undo_firewall_node_port(ctx: Context, st: dict) -> None:
    ip = ctx.state.get("firewall", {}).get(str(st["server_id"]))
    if ip:
        web = ("web",) if ctx.plan.selfsteal_domain else ()
        await _run(ctx, st["server_id"], FIREWALL, ip, str(ctx.plan.node_port), "delete", *web, timeout=60)


def node_address(ctx: Context, server_id: int) -> str:
    if ctx.plan.node_domain and len(ctx.plan.node_server_ids) == 1:
        return ctx.plan.node_domain
    if server_id == ctx.plan.panel_server_id:
        # The panel runs in a bridge network and reaches the node on the host through the bridge gateway.
        return ctx.state.get("bridge_gateway") or "172.17.0.1"
    return ctx.servers[server_id]["host"]


GATEWAY = r"""docker network inspect remnawave-network -f '{{(index .IPAM.Config 0).Gateway}}'"""


async def run_register_node(ctx: Context, st: dict) -> None:
    sid = st["server_id"]
    existing = ctx.state.get("nodes", {}).get(str(sid))
    if existing:
        _note(ctx, f"Нода уже зарегистрирована: {existing}")
        return
    if sid == ctx.plan.panel_server_id:
        out = await _run(ctx, sid, GATEWAY, timeout=30)
        if out.code == 0 and out.out.strip():
            ctx.state["bridge_gateway"] = out.out.strip()
    profiles = (await panel_api(ctx, "GET", "/api/config-profiles")).get("configProfiles") or []
    own = ctx.state.get("selfsteal_profile")
    profile = next((p for p in profiles if own and p.get("uuid") == own), None) or next((p for p in profiles if p.get("inbounds")), None)
    if not profile:
        raise StepError("В панели нет профиля конфигурации с inbound: создайте его в «Remnawave: панель»")
    name = f"{ctx.plan.node_name}-{sid}"[:30]
    node = await panel_api(ctx, "POST", "/api/nodes", {
        "name": name, "address": node_address(ctx, sid), "port": ctx.plan.node_port, "countryCode": ctx.plan.country_code,
        "configProfile": {"activeConfigProfileUuid": profile["uuid"], "activeInbounds": [i["uuid"] for i in profile["inbounds"]]}})
    ctx.state.setdefault("nodes", {})[str(sid)] = node.get("uuid")
    _note(ctx, f"Нода {name} создана в панели ({node.get('uuid')})")


async def undo_register_node(ctx: Context, st: dict) -> None:
    uuid = ctx.state.get("nodes", {}).pop(str(st["server_id"]), None)
    if uuid:
        await panel_api(ctx, "DELETE", f"/api/nodes/{uuid}")


# ---------- SelfSteal ----------

async def run_selfsteal_profile(ctx: Context, st: dict) -> None:
    """VLESS + REALITY with «dest» on the node's SelfSteal socket, keys from the panel, and the host customers get."""
    if ctx.state.get("selfsteal_profile"):
        _note(ctx, f"Профиль SelfSteal уже создан: {ctx.state['selfsteal_profile']}")
        return
    from .rw_extensions import RealityIn, reality_config
    domain = ctx.plan.selfsteal_domain
    pairs = (await panel_api(ctx, "GET", "/api/system/tools/x25519/generate")).get("keypairs") or []
    if not pairs:
        raise StepError("Панель не выдала ключи x25519")
    name = f"SelfSteal-{st['server_id']}-{pysecrets.token_hex(2)}"[:30]
    config = reality_config(RealityIn(name=name, server_names=[domain], dest="selfsteal"), pairs[0]["privateKey"])
    profile = await panel_api(ctx, "POST", "/api/config-profiles", {"name": name, "config": config})
    inbound = (profile.get("inbounds") or [{}])[0].get("uuid")
    ctx.state["selfsteal_profile"] = profile.get("uuid")
    if inbound:
        host = await panel_api(ctx, "POST", "/api/hosts", {"remark": name, "address": domain, "port": 443, "sni": domain,
                                                         "inbound": {"configProfileUuid": profile.get("uuid"), "configProfileInboundUuid": inbound}})
        ctx.state["selfsteal_host"] = host.get("uuid")
    _note(ctx, f"Профиль {name}: REALITY на 443, dest {rw_plan.SELFSTEAL_SOCKET}, serverNames [{domain}]; хост {domain}:443")


async def undo_selfsteal_profile(ctx: Context, st: dict) -> None:
    host = ctx.state.pop("selfsteal_host", None)
    if host:
        await panel_api(ctx, "DELETE", f"/api/hosts/{host}")
    profile = ctx.state.pop("selfsteal_profile", None)
    if profile:
        await panel_api(ctx, "DELETE", f"/api/config-profiles/{profile}")


SELFSTEAL_CHECK = r"""set -u
domain="$1"
[ -S /dev/shm/selfsteal.sock ] || { echo "nosocket"; exit 0; }
curl -sk --max-time 10 --haproxy-protocol --unix-socket /dev/shm/selfsteal.sock -o /dev/null -w '%{http_code}' "https://$domain/"
"""


# ---------- node modules (v28.70.0) ----------
# Fixed scripts with typed arguments; secrets reach them on stdin, never in argv. Each «apply» keeps what it
# replaces (*.rw-prev), and «undo» puts it back — the runner calls it after a failure of a later step.

IPV6 = r"""set -eu
f=/etc/sysctl.d/99-remnawave-ipv6.conf
[ -d /proc/sys/net/ipv6 ] || { echo "kernel"; exit 3; }
# The uplink: the interface of the default IPv4 route (a per-interface disable_ipv6=1 keeps it dead at all=0).
iface="$(ip -o -4 route show default 2>/dev/null | awk '{print $5; exit}')"
write() {
  { echo "# Managed by the shop's installation wizard (module IPv6)"
    for k in all default lo ${iface:+"$iface"}; do echo "net.ipv6.conf.$k.disable_ipv6 = $1"; done; } > "$f"
  sysctl -q -p "$f"
}
# Disabling IPv6 drops the interface's addresses and enabling does not bring static or DHCPv6 ones back:
# networking is re-read once, as the distribution configures it, and the global address is waited for.
refresh() {
  [ -n "$iface" ] || return 0
  ip -6 addr show dev "$iface" scope global 2>/dev/null | grep -q inet6 && return 0
  [ "${1:-}" = had ] || return 0
  if [ -d /etc/netplan ] && command -v netplan >/dev/null 2>&1; then netplan apply >/dev/null 2>&1 || true
  elif [ -f /etc/network/interfaces ] && command -v ifup >/dev/null 2>&1; then ifdown "$iface" >/dev/null 2>&1 || true; ifup "$iface" >/dev/null 2>&1 || true
  else systemctl restart systemd-networkd >/dev/null 2>&1 || true; fi
  for _ in $(seq 1 15); do ip -6 addr show dev "$iface" scope global 2>/dev/null | grep -v tentative | grep -q inet6 && return 0; sleep 1; done
  echo "noaddr"
}
had() { [ -f "$f.rw-had" ] && echo had; }
# After a switch the interface re-runs duplicate address detection: wait until no address is «tentative»,
# so the next step does not start on a network that is still settling.
settle() { for _ in $(seq 1 10); do ip -6 addr show 2>/dev/null | grep -q tentative || return 0; sleep 1; done; }
case "$1" in
  on|off)
    rm -f "$f.rw-prev" "$f.rw-none"
    if [ -f "$f" ]; then cp -p "$f" "$f.rw-prev"; else : > "$f.rw-none"; fi
    if [ "$1" = off ]; then
      # remembered: the server had a global IPv6 address, so switching back on must restore one
      if [ -n "$iface" ] && ip -6 addr show dev "$iface" scope global 2>/dev/null | grep -q inet6; then : > "$f.rw-had"; fi
      write 1
    else
      write 0
      refresh "$(had)"
      settle
    fi ;;
  undo)
    if [ -f "$f.rw-prev" ]; then mv "$f.rw-prev" "$f"; sysctl -q -p "$f";
    elif [ -f "$f.rw-none" ]; then rm -f "$f" "$f.rw-none"
      for k in all default lo ${iface:+"$iface"}; do sysctl -q -w "net.ipv6.conf.$k.disable_ipv6=0" || true; done; fi
    [ "$(sysctl -n net.ipv6.conf.all.disable_ipv6)" = 0 ] && refresh "$(had)" ;;
  *) exit 2 ;;
esac
[ "$(sysctl -n net.ipv6.conf.all.disable_ipv6)" = 0 ] && [ "$1" != off ] && rm -f "$f.rw-had"
echo "disable_ipv6=$(sysctl -n net.ipv6.conf.all.disable_ipv6) iface=${iface:-none} global=$( [ -n "$iface" ] && ip -6 addr show dev "$iface" scope global 2>/dev/null | grep -c inet6 || true)"
"""

APT_GET = r"""apt_get() { DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::=--force-confold -y -q "$@"; }"""

XRAY_CORE = APT_GET + r"""
set -eu
d=/opt/remnanode/xray-core
case "$1" in
  install)
    url="$2"; sum="$3"
    case "$url" in https://github.com/XTLS/Xray-core/releases/download/v*/Xray-linux-*.zip) ;; *) echo "bad url" >&2; exit 2 ;; esac
    echo "$sum" | grep -Eq '^[0-9a-f]{64}$' || exit 2
    command -v unzip >/dev/null 2>&1 || { apt_get update >/dev/null; apt_get install unzip >/dev/null; }
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    curl -fsSL --max-time 300 -o "$tmp/core.zip" "$url"
    echo "$sum  $tmp/core.zip" | sha256sum -c --status || { echo "sha256 mismatch"; exit 4; }
    # XTLS also publishes a .dgst file next to the archive: when it is served, it must agree too.
    if curl -fsSL --max-time 60 -o "$tmp/core.dgst" "$url.dgst" 2>/dev/null; then
      want="$(sed -n 's/^SHA2-256= *//p' "$tmp/core.dgst" | head -n1 | tr -d ' \r')"
      [ -z "$want" ] || [ "$want" = "$sum" ] || { echo "dgst mismatch"; exit 4; }
    fi
    unzip -q -o "$tmp/core.zip" xray -d "$tmp/x"
    head -c 4 "$tmp/x/xray" | grep -q ELF || { echo "not an ELF binary"; exit 4; }
    install -d -m 0755 "$d"
    if [ -f "$d/xray" ]; then cp -p "$d/xray" "$d/xray.rw-prev"; else rm -f "$d/xray.rw-prev"; fi
    install -m 0755 "$tmp/x/xray" "$d/xray"
    "$d/xray" version | head -n1 ;;
  remove)
    if [ -f "$d/xray" ]; then mv "$d/xray" "$d/xray.rw-prev"; fi
    echo "removed" ;;
  undo)
    if [ -f "$d/xray.rw-prev" ]; then mv "$d/xray.rw-prev" "$d/xray"; else rm -f "$d/xray"; fi ;;
  *) exit 2 ;;
esac
"""

XRAY_VERSION = r"""docker exec remnanode sh -c '[ -x /usr/local/bin/rw-core ] && /usr/local/bin/rw-core version || xray version' 2>/dev/null | head -n1"""

# WARP Native: a WireGuard interface «warp» to Cloudflare WARP, without routes (Table = off) — only the Xray
# outbound with sockopt.interface = warp uses it (rw_extensions.profile_warp). wgcf (ViRb3/wgcf, MIT) registers
# the WARP account; the binary comes from GitHub and is checked by the SHA-256 GitHub published for it.
WARP = APT_GET + r"""
set -eu
d=/opt/remnawave-warp
case "$1" in
  install)
    url="$2"; sum="$3"
    case "$url" in https://github.com/ViRb3/wgcf/releases/download/v*/wgcf_*_linux_*) ;; *) echo "bad url" >&2; exit 2 ;; esac
    echo "$sum" | grep -Eq '^[0-9a-f]{64}$' || exit 2
    command -v wg-quick >/dev/null 2>&1 || { apt_get update >/dev/null; apt_get install wireguard-tools >/dev/null; }
    install -d -m 0700 "$d" /etc/wireguard
    curl -fsSL --max-time 300 -o "$d/wgcf.new" "$url"
    echo "$sum  $d/wgcf.new" | sha256sum -c --status || { rm -f "$d/wgcf.new"; echo "sha256 mismatch"; exit 4; }
    chmod 0755 "$d/wgcf.new"; mv "$d/wgcf.new" "$d/wgcf"
    cd "$d"
    [ -f wgcf-account.toml ] || ./wgcf register --accept-tos >/dev/null
    ./wgcf generate >/dev/null
    v6=1; [ "$(sysctl -n net.ipv6.conf.all.disable_ipv6 2>/dev/null || echo 1)" = 0 ] || v6=0
    awk -v v6="$v6" '
      /^DNS *=/ {next}
      /^Address *=/ && v6 == 0 { n = split(substr($0, index($0, "=") + 1), a, ","); out = "";
        for (i = 1; i <= n; i++) { gsub(/ /, "", a[i]); if (a[i] !~ /:/) out = out (out ? ", " : "") a[i] }
        print "Address = " out; next }
      /^AllowedIPs *=/ && v6 == 0 { print "AllowedIPs = 0.0.0.0/0"; next }
      { print }
      /^\[Interface\]/ { print "Table = off" }' wgcf-profile.conf > /etc/wireguard/warp.conf.new
    chmod 0600 /etc/wireguard/warp.conf.new
    if [ -f /etc/wireguard/warp.conf ]; then cp -p /etc/wireguard/warp.conf /etc/wireguard/warp.conf.rw-prev; fi
    mv /etc/wireguard/warp.conf.new /etc/wireguard/warp.conf
    systemctl enable wg-quick@warp >/dev/null 2>&1
    systemctl restart wg-quick@warp
    sleep 2
    curl -fsS --max-time 15 --interface warp https://www.cloudflare.com/cdn-cgi/trace | grep '^warp=' ;;
  remove|undo)
    systemctl disable --now wg-quick@warp >/dev/null 2>&1 || true
    if [ "$1" = undo ] && [ -f /etc/wireguard/warp.conf.rw-prev ]; then
      mv /etc/wireguard/warp.conf.rw-prev /etc/wireguard/warp.conf; systemctl enable --now wg-quick@warp >/dev/null 2>&1 || true
    else rm -f /etc/wireguard/warp.conf; fi
    echo "warp off" ;;
  *) exit 2 ;;
esac
"""

# NetBird from its signed apt repository (pkgs.netbird.io, as the official documentation installs it); the setup
# key comes on stdin and reaches netbird through NB_SETUP_KEY, so it is never in a process list or a file.
NETBIRD = APT_GET + r"""
set -eu
case "$1" in
  install)
    mgmt="${2:-}"
    case "$mgmt" in ""|https://*) ;; *) exit 2 ;; esac
    key="$(cat)"
    [ -n "$key" ] || { echo "no key"; exit 2; }
    if ! command -v netbird >/dev/null 2>&1; then
      apt_get update >/dev/null; apt_get install ca-certificates curl gnupg >/dev/null
      curl -fsSL --max-time 60 https://pkgs.netbird.io/debian/public.key | gpg --dearmor --yes -o /usr/share/keyrings/netbird-archive-keyring.gpg
      echo 'deb [signed-by=/usr/share/keyrings/netbird-archive-keyring.gpg] https://pkgs.netbird.io/debian stable main' > /etc/apt/sources.list.d/netbird.list
      apt_get update >/dev/null; apt_get install netbird >/dev/null
      : > /etc/netbird.rw-installed
    fi
    netbird service install >/dev/null 2>&1 || true
    netbird service start >/dev/null 2>&1 || true
    if [ -n "$mgmt" ]; then NB_SETUP_KEY="$key" netbird up --management-url "$mgmt" >/dev/null
    else NB_SETUP_KEY="$key" netbird up >/dev/null; fi
    netbird status | grep -E '^(Management|NetBird IP):' ;;
  remove|undo)
    netbird down >/dev/null 2>&1 || true
    echo "netbird down" ;;
  *) exit 2 ;;
esac
"""

CHECKER_STATUS = r"""set -u
creds="$(cat)"
curl -fsS --max-time 15 -u "$creds" http://127.0.0.1:2112/api/v1/proxies 2>/dev/null || echo '{"success": false}'
"""


def _modules(ctx: Context, sid: int) -> dict:
    return ctx.state.setdefault("modules", {}).setdefault(str(sid), {})


async def run_node_module(ctx: Context, st: dict) -> None:
    p, sid = st["params"], st["server_id"]
    name, enabled = p["module"], p.get("enabled", True)
    mods = _modules(ctx, sid)
    if name == "ipv6":
        result = await _run(ctx, sid, IPV6, "on" if enabled else "off", timeout=60)
        _note(ctx, result.out + result.err)
        if result.code == 3:
            raise StepError("IPv6 выключен в ядре (ipv6.disable=1 в параметрах загрузки): sysctl его не включит")
        if result.code != 0:
            raise StepError("Настройка IPv6 не применилась")
        if enabled and "noaddr" in result.out:
            raise StepError("IPv6 включён, но интерфейс не получил прежний глобальный адрес IPv6: проверьте настройки сети сервера")
        mods["ipv6"] = "on" if enabled else "off"
    elif name == "xray_core":
        args = ("install", p["url"], p["sha256"]) if enabled else ("remove",)
        result = await _run(ctx, sid, XRAY_CORE, *args, timeout=600)
        _note(ctx, result.out + result.err)
        if result.code == 4:
            raise StepError("Файл ядра Xray не прошёл проверку (SHA-256 или формат): ничего не заменено")
        if result.code != 0:
            raise StepError("Ядро Xray не установлено")
        mods["xray_core"] = p.get("version") if enabled else None
    elif name == "warp":
        args = ("install", p["url"], p["sha256"]) if enabled else ("remove",)
        result = await _run(ctx, sid, WARP, *args, timeout=600)
        _note(ctx, result.out + result.err)
        if result.code == 4:
            raise StepError("Файл wgcf не прошёл проверку SHA-256")
        if result.code != 0 or (enabled and "warp=" not in result.out):
            raise StepError("Интерфейс warp не поднялся (журнал шага)")
        mods["warp"] = enabled
    elif name == "netbird":
        if enabled:
            key = ctx.secrets.pop("netbird_setup_key", None)
            if not key:
                raise StepError("Нет ключа установки NetBird: составьте план заново и введите ключ")
            result = await _run(ctx, sid, NETBIRD, "install", p.get("management_url") or "", stdin=key.encode(), timeout=900)
        else:
            result = await _run(ctx, sid, NETBIRD, "remove", timeout=120)
        _note(ctx, result.out + result.err)
        if result.code != 0 or (enabled and "Connected" not in result.out):
            raise StepError("NetBird не подключился к серверу управления (журнал шага)")
        mods["netbird"] = enabled
    elif name == "transports":
        wanted = p.get("transports") or []
        flags = ["on" if t in wanted else "off" for t in ("xhttp", "grpc", "hysteria2")]
        result = await _run(ctx, sid, TRANSPORTS_SH, ctx.plan.selfsteal_domain, *flags, timeout=300)
        _note(ctx, result.out + result.err)
        if result.code == 5:
            raise StepError("Нет сертификата SelfSteal для Hysteria2: Caddy ноды ещё не получил его (проверьте DNS домена и повторите)")
        if result.code != 0:
            raise StepError("Порты и сертификат транспортов не настроены (журнал шага)")
        mods["transports"] = list(wanted)
    elif name == "xray_checker":
        data = {}
        for _ in range(15):
            data = await checker_status(ctx, sid)
            if data.get("success"):
                break
            await _sleep(4)
        if not data.get("success"):
            raise StepError("Xray Checker не отвечает на 127.0.0.1:2112")
        _note(ctx, f"Xray Checker: проверяет {len(data.get('data') or [])} серверов подписки")
    else:
        raise StepError(f"Неизвестный модуль {name}")
    ctx.state.setdefault("applied_modules", []).append([sid, name, enabled])


# v28.81.0: «Транспорты ноды». Ports of the chosen transports in ufw (if it is on) and, for Hysteria2, the TLS certificate
# of the SelfSteal domain: copied from the node's Caddy (any issuer) to HYSTERIA_DIR every day by a systemd timer; Xray
# reloads it (ocspStapling). After remnawave-manager (MIT, (c) Корги Люси): write_hysteria_cert_helper, write_firewall.
TRANSPORTS_SH = r"""set -eu
domain="$1"; xhttp="$2"; grpc="$3"; hy="$4"; dir=/opt/remnanode/hysteria
case "$domain" in *[!a-z0-9.-]*|"") exit 2 ;; esac
port() {  # port/proto on|off
  command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -q active || return 0
  if [ "$2" = on ]; then ufw allow "$1" >/dev/null; else ufw delete allow "$1" >/dev/null 2>&1 || true; fi
}
port 4443/tcp "$xhttp"; port 8443/tcp "$grpc"; port 443/udp "$hy"
if [ "$hy" = on ]; then
  install -d -m 0755 "$dir"
  cat > /usr/local/sbin/corgi-hysteria-cert.sh <<EOF
#!/bin/sh
set -eu
d=\$(docker exec remnawave-selfsteal sh -c 'find /data/caddy/certificates -type d -name "$domain" | head -n1')
[ -n "\$d" ] || exit 3
docker exec remnawave-selfsteal cat "\$d/$domain.crt" > $dir/cert.pem.new
docker exec remnawave-selfsteal cat "\$d/$domain.key" > $dir/key.pem.new
[ -s $dir/cert.pem.new ] && [ -s $dir/key.pem.new ] || exit 4
chmod 0644 $dir/cert.pem.new; chmod 0600 $dir/key.pem.new
mv -f $dir/cert.pem.new $dir/cert.pem; mv -f $dir/key.pem.new $dir/key.pem
EOF
  chmod 0700 /usr/local/sbin/corgi-hysteria-cert.sh
  printf '[Unit]\nDescription=Copy the SelfSteal certificate for Hysteria2\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/corgi-hysteria-cert.sh\n' > /etc/systemd/system/corgi-hysteria-cert.service
  printf '[Unit]\nDescription=Daily copy of the SelfSteal certificate for Hysteria2\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=1h\nPersistent=true\n[Install]\nWantedBy=timers.target\n' > /etc/systemd/system/corgi-hysteria-cert.timer
  systemctl daemon-reload; systemctl enable --now corgi-hysteria-cert.timer >/dev/null 2>&1
  # Caddy may still be getting the certificate: wait for it up to two minutes.
  for i in $(seq 1 24); do /usr/local/sbin/corgi-hysteria-cert.sh 2>/dev/null && break; sleep 5; done
  [ -s "$dir/cert.pem" ] && [ -s "$dir/key.pem" ] || { echo "nocert"; exit 5; }
  echo "cert=$(openssl x509 -in $dir/cert.pem -noout -enddate 2>/dev/null | cut -d= -f2)"
else
  systemctl disable --now corgi-hysteria-cert.timer >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/corgi-hysteria-cert.service /etc/systemd/system/corgi-hysteria-cert.timer /usr/local/sbin/corgi-hysteria-cert.sh
  systemctl daemon-reload || true
fi
echo "transports xhttp=$xhttp grpc=$grpc hysteria2=$hy"
"""


def transport_inbounds(base: dict, domain: str, wanted: list[str]) -> list[dict]:
    """The inbounds of the chosen transports next to ``base`` (the VLESS + TCP + REALITY inbound of the profile): the
    same REALITY settings (keys, SelfSteal site, serverNames); Hysteria2 with the copied certificate."""
    reality = (base.get("streamSettings") or {}).get("realitySettings") or {}
    sniff = base.get("sniffing") or {"enabled": True, "destOverride": ["http", "tls", "quic"]}
    out = []
    for name in wanted:
        tag, port, _proto = rw_plan.TRANSPORTS[name]
        if name == "hysteria2":
            out.append({"tag": tag, "port": port, "listen": "0.0.0.0", "protocol": "hysteria", "settings": {"version": 2, "clients": []},
                        "sniffing": sniff,
                        "streamSettings": {"network": "hysteria", "hysteriaSettings": {"version": 2}, "security": "tls",
                                           "tlsSettings": {"serverName": domain, "alpn": ["h3"], "certificates": [
                                               {"certificateFile": f"{rw_plan.HYSTERIA_MOUNT}/cert.pem", "keyFile": f"{rw_plan.HYSTERIA_MOUNT}/key.pem",
                                                "ocspStapling": 3600}]}}})
            continue
        stream = {"network": name, "security": "reality", "realitySettings": dict(reality)}
        if name == "xhttp":
            stream["xhttpSettings"] = {"path": "/xhttp", "mode": "auto"}
        else:
            stream["grpcSettings"] = {"serviceName": "grpc", "multiMode": True}
        out.append({"tag": tag, "port": port, "listen": "0.0.0.0", "protocol": "vless", "settings": {"clients": [], "decryption": "none"},
                    "sniffing": sniff, "streamSettings": stream})
    return out


def transport_host(name: str, domain: str, profile: str, inbound: str, remark: str) -> dict:
    tag, port, _ = rw_plan.TRANSPORTS[name]
    body = {"remark": remark[:40], "address": domain, "port": port, "sni": domain,
            "inbound": {"configProfileUuid": profile, "configProfileInboundUuid": inbound}}
    if name == "xhttp":
        body["path"] = "/xhttp"
    if name == "grpc":
        body["path"] = "grpc"  # the panel puts a gRPC host's path into the serviceName of the link
    if name == "hysteria2":
        body["alpn"] = "h3"
    return body


async def run_node_transports(ctx: Context, st: dict) -> None:
    ctx.state["transports_before"] = list(ctx.state.get("transports") or [])
    await _apply_transports(ctx, list(ctx.plan.transports))


async def undo_node_transports(ctx: Context, st: dict) -> None:
    if "transports_before" in ctx.state:
        await _apply_transports(ctx, ctx.state.pop("transports_before"))


async def _apply_transports(ctx: Context, chosen: list[str]) -> None:
    """Make the SelfSteal profile carry exactly the chosen transports: inbounds, a host each, the same squads as the
    REALITY inbound; then restart the node. VLESS + TCP + REALITY stays untouched."""
    plan = ctx.plan
    uuid = ctx.state.get("selfsteal_profile")
    if not uuid:
        raise StepError("Нет профиля SelfSteal этой установки: транспорты добавляются к нему")
    profile = await panel_api(ctx, "GET", f"/api/config-profiles/{uuid}")
    config = profile.get("config") or {}
    tags = {t for t, _p, _n in rw_plan.TRANSPORTS.values()}
    inbounds = [i for i in config.get("inbounds") or [] if i.get("tag") not in tags]
    base = next((i for i in inbounds if ((i.get("streamSettings") or {}).get("security") == "reality")), None)
    if not base:
        raise StepError("В профиле SelfSteal нет inbound'а VLESS + REALITY")
    before = {i.get("tag") for i in config.get("inbounds") or []}
    ctx.state["profile_inbounds"] = sorted(set(ctx.state.get("profile_inbounds") or [])
                                           | {i.get("uuid") for i in profile.get("inbounds") or [] if i.get("uuid")})
    wanted = {rw_plan.TRANSPORTS[n][0]: n for n in chosen}
    # Hosts of the transports being removed go first, while their inbounds still exist: once an inbound leaves the
    # profile the panel unbinds its hosts and they could not be told apart any more (seen on Remnawave 3.4).
    old_by_tag = {i.get("tag"): i.get("uuid") for i in profile.get("inbounds") or []}
    gone = {old_by_tag[t] for t in tags if t not in wanted and old_by_tag.get(t)}
    created = ctx.state.setdefault("transport_hosts", {})
    hosts = await _hosts(ctx)
    for host in hosts:
        bound = (host.get("inbound") or {}).get("configProfileInboundUuid")
        if host.get("uuid") and (bound in gone or host.get("uuid") in {created.get(t) for t in tags if t not in wanted}):
            await panel_api(ctx, "DELETE", f"/api/hosts/{host['uuid']}")
    for tag in list(created):
        if tag not in wanted:
            created.pop(tag)
    config["inbounds"] = inbounds + transport_inbounds(base, plan.selfsteal_domain, chosen)
    await panel_api(ctx, "PATCH", "/api/config-profiles", {"uuid": uuid, "config": config})
    profile = await panel_api(ctx, "GET", f"/api/config-profiles/{uuid}")
    by_tag = {i.get("tag"): i.get("uuid") for i in profile.get("inbounds") or []}
    # Hosts: one per chosen transport inbound of this profile.
    bound = {(h.get("inbound") or {}).get("configProfileInboundUuid") for h in await _hosts(ctx)}
    for tag, name in wanted.items():
        inbound = by_tag.get(tag)
        if inbound and inbound not in bound:
            host = await panel_api(ctx, "POST", "/api/hosts", transport_host(name, plan.selfsteal_domain, uuid, inbound, f"{plan.selfsteal_domain} {name}"))
            if isinstance(host, dict) and host.get("uuid"):
                created[tag] = host["uuid"]
    # Squads: wherever the REALITY inbound is, the transports are too (and nowhere once removed).
    main = by_tag.get(base.get("tag"))
    squads = await panel_api(ctx, "GET", "/api/internal-squads")
    squads = squads if isinstance(squads, list) else squads.get("internalSquads", [])
    extra = [by_tag[t] for t in wanted if by_tag.get(t)]
    touched = 0
    for squad in squads:
        current = [i.get("uuid") for i in squad.get("inbounds") or []]
        if main not in current:
            continue
        valid = set(by_tag.values())
        # Drop inbounds of this profile that no longer exist (removed transports), add the chosen transports.
        keep = [i for i in current if i in valid or i not in _profile_inbound_history(ctx)]
        new = list(dict.fromkeys(keep + extra))
        if new != current:
            await panel_api(ctx, "PATCH", "/api/internal-squads", {"uuid": squad.get("uuid"), "inbounds": new})
            touched += 1
    ctx.state["profile_inbounds"] = sorted(set(ctx.state["profile_inbounds"]) | set(by_tag.values()))
    # The nodes of this installation serve every inbound of the profile; PATCH makes the panel push the new config.
    active = [i.get("uuid") for i in profile.get("inbounds") or [] if i.get("uuid")]
    for node in (ctx.state.get("nodes") or {}).values():
        await panel_api(ctx, "PATCH", "/api/nodes", {"uuid": node, "configProfile": {"activeConfigProfileUuid": uuid, "activeInbounds": active}})
        await panel_api(ctx, "POST", f"/api/nodes/{node}/actions/restart", {"forceRestart": False})
    ctx.state["transports"] = list(chosen)
    _note(ctx, f"Профиль {uuid}: inbound'ы {sorted(by_tag)} (было {sorted(before)}); сквадов обновлено: {touched}")


async def _hosts(ctx: Context) -> list[dict]:
    hosts = await panel_api(ctx, "GET", "/api/hosts")
    return hosts if isinstance(hosts, list) else hosts.get("hosts", [])


def _profile_inbound_history(ctx: Context) -> set:
    return set(ctx.state.get("profile_inbounds") or [])


async def checker_status(ctx: Context, sid: int) -> dict:
    creds = f"{ctx.secrets.get('checker_user', '')}:{ctx.secrets.get('checker_password', '')}"
    out = await _run(ctx, sid, CHECKER_STATUS, stdin=creds.encode(), timeout=30)
    try:
        data = json.loads(out.out or "{}")
    except ValueError:
        return {"success": False}
    return data if isinstance(data, dict) else {"success": False}


async def undo_node_module(ctx: Context, st: dict) -> None:
    p, sid = st["params"], st["server_id"]
    script = {"ipv6": IPV6, "xray_core": XRAY_CORE, "warp": WARP, "netbird": NETBIRD}.get(p["module"])
    if p["module"] in ("warp", "netbird") and not p.get("enabled", True):
        return  # switching off is not undone: the interface or the connection stays off, which is safe
    if script and [sid, p["module"], p.get("enabled", True)] in ctx.state.get("applied_modules", []):
        await _run(ctx, sid, script, "undo", timeout=300)


# ---------- verify ----------

HTTPS_CHECK = r"""set -u
domain="$1"; ua="$2"; cookie="${4:-}"
code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$domain:443:127.0.0.1" -A "$ua" ${cookie:+-H "Cookie: $cookie"} "https://$domain/$3")"
echo "$code"
"""


BROWSER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 corgi-verify"


async def run_verify(ctx: Context, st: dict) -> None:
    plan = ctx.plan
    problems = []
    if plan.panel_server_id:
        for _ in range(20):
            cookie = "=".join(access_cookie(ctx)) if plan.panel_access == "cookie" else ""
            # TinyAuth redirects browsers to its login page (other clients get 401): ask as a browser.
            agent = BROWSER_AGENT if plan.panel_access in ("tinyauth", "gate") else "corgi-verify"
            code = (await _run(ctx, plan.panel_server_id, HTTPS_CHECK, plan.panel_domain, agent, "api/auth/status", cookie,
                               timeout=30)).out.strip()
            if code == ("302" if plan.panel_access in ("tinyauth", "gate") else "200"):
                break
            await _sleep(6)
        _note(ctx, f"https://{plan.panel_domain}/api/auth/status через Caddy: {code}")
        if code != "200" and not (plan.panel_access in ("tinyauth", "gate") and code == "302"):
            problems.append(f"панель не отвечает через HTTPS ({code})")
        if plan.panel_access == "tinyauth":
            # The login portal answers, and the panel's pages send a browser without a session to it.
            portal = (await _run(ctx, plan.panel_server_id, HTTPS_CHECK, plan.auth_domain, "corgi-verify", "api/healthz", "",
                                 timeout=30)).out.strip()
            _note(ctx, f"https://{plan.auth_domain}/api/healthz (TinyAuth): {portal}")
            if portal != "200":
                problems.append(f"TinyAuth не отвечает через HTTPS ({portal or 'нет ответа'})")
            if code != "302":
                problems.append(f"страницы панели открываются без входа в TinyAuth ({code})")
        if plan.panel_access == "gate" and code != "302":
            # 302 comes from the shop itself (to its admin panel): the panel's server reaches the shop and asks it.
            problems.append(f"страницы панели не спрашивают магазин о входе ({code}: 502 — сервер панели не достучался до магазина)")
        if plan.tls == "acme":
            import httpx
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    answer = await client.get(f"https://{plan.panel_domain}/api/auth/status",
                                              headers={"Cookie": cookie} if cookie else None)
                _note(ctx, f"С сервера магазина, с проверкой сертификата: {answer.status_code}")
            except httpx.HTTPError as exc:
                problems.append(f"с сервера магазина https://{plan.panel_domain} недоступен: {type(exc).__name__}")
    for sid, uuid in ctx.state.get("nodes", {}).items():
        connected = False
        for _ in range(40):
            node = await panel_api(ctx, "GET", f"/api/nodes/{uuid}")
            if node.get("isConnected"):
                connected = True
                break
            await _sleep(4)
        _note(ctx, f"Нода {uuid}: {'на связи' if connected else 'не подключилась'}")
        if not connected:
            problems.append(f"нода на сервере {ctx.servers[int(sid)]['name']} не подключилась к панели")
    if plan.subpage_server_id:
        code = (await _run(ctx, plan.subpage_server_id, HTTPS_CHECK, plan.sub_domain, "v2rayNG/1.9.30", "", timeout=30)).out.strip()
        _note(ctx, f"https://{plan.sub_domain} через Caddy: {code}")
        if code in ("", "000", "502", "503"):
            problems.append(f"страница подписки не отвечает ({code or 'нет ответа'})")
    if plan.selfsteal_domain:
        sid = plan.node_server_ids[0]
        code = ""
        for _ in range(20):
            code = (await _run(ctx, sid, SELFSTEAL_CHECK, plan.selfsteal_domain, timeout=30)).out.strip()
            if code == "200":
                break
            await _sleep(6)
        _note(ctx, f"Сайт SelfSteal через {rw_plan.SELFSTEAL_SOCKET}: {code or 'нет ответа'}")
        if code != "200":
            problems.append(f"сайт SelfSteal не отвечает на сокете ({code or 'нет ответа'})")
    if plan.module and plan.module.name == "xray_core":
        want = (plan.xray_core or "").lstrip("v")
        for sid in plan.node_server_ids:
            got = (await _run(ctx, sid, XRAY_VERSION, timeout=30)).out.strip()
            _note(ctx, f"{ctx.servers[sid]['name']}: {got or 'версия ядра не прочитана'}")
            if want and want not in got:
                problems.append(f"на ноде {ctx.servers[sid]['name']} работает не то ядро ({got or 'нет ответа'})")
    if problems:
        raise StepError("Проверка не пройдена: " + "; ".join(problems))


# ---------- panel backup and restore ----------

BACKUP = r"""set -eu
cd /opt/remnawave
install -d -m 0700 /opt/remnawave/backups
f="/opt/remnawave/backups/panel-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec remnawave-db pg_dump -U postgres -Fc postgres > "$f.part"
mv "$f.part" "$f"; chmod 600 "$f"
ls -1t /opt/remnawave/backups/panel-*.dump | tail -n +6 | xargs -r rm -f
echo "$f $(stat -c %s "$f")"
"""

RESTORE = r"""set -eu
f="${1:-}"
case "$f" in "") f="$(ls -1t /opt/remnawave/backups/panel-*.dump 2>/dev/null | head -1)" ;;
  /opt/remnawave/backups/panel-[0-9]*Z.dump) [ -f "$f" ] || { echo "нет копии" >&2; exit 3; } ;;
  *) echo "bad file" >&2; exit 2 ;; esac
[ -n "$f" ] || { echo "нет копии" >&2; exit 3; }
cd /opt/remnawave
docker compose stop remnawave
docker exec -i remnawave-db pg_restore -U postgres -d postgres --clean --if-exists < "$f"
docker compose start remnawave
echo "$f"
"""


async def run_backup_panel(ctx: Context, st: dict) -> None:
    result = await _run(ctx, st["server_id"], BACKUP, timeout=900)
    if result.code != 0:
        raise StepError("Копия базы панели не создана")
    ctx.state["last_panel_backup"] = result.out.strip()
    _note(ctx, f"Копия базы панели: {result.out.strip()} (хранятся 5 последних на сервере)")


async def run_restore_panel(ctx: Context, st: dict) -> None:
    # v28.74.0: an update's rollback restores the copy made at its start (``file``), not just the newest one.
    file = (st.get("params") or {}).get("file")
    result = await _run(ctx, st["server_id"], RESTORE, *([file] if file else []), timeout=1800)
    if result.code == 3:
        raise StepError("На сервере нет копии базы панели")
    if result.code != 0:
        raise StepError("Восстановление базы панели не удалось")
    _note(ctx, f"База панели восстановлена из {result.out.strip()}")


# v28.74.0 (stage 15, carried over from stage 10): the panel's copy also leaves its server — encrypted, into the
# shop's backup volume — so losing the panel's server does not lose its database.
FETCH_BACKUP = r"""set -eu
f="$1"
case "$f" in /opt/remnawave/backups/panel-[0-9]*Z.dump) ;; *) echo "bad file" >&2; exit 2 ;; esac
[ -f "$f" ] || { echo "нет копии" >&2; exit 3; }
sha256sum "$f" | cut -d' ' -f1
base64 -w0 "$f"
"""
MAX_PANEL_COPY = 256 * 1024 * 1024  # larger copies stay on the server only (noted in the step's log)
PANEL_COPIES_KEEP = 10


def panel_copies_dir():
    from pathlib import Path
    return Path(os.environ.get("RW_PANEL_COPIES_DIR", "/data/backups/remnawave"))


def seal(data: bytes) -> bytes:
    """AES-256-GCM with the shop's key (APP_SECRET): nonce + ciphertext."""
    import secrets as _secrets

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from .security import _key
    nonce = _secrets.token_bytes(12)
    return nonce + AESGCM(_key()).encrypt(nonce, data, b"remnawave-panel-copy")


def unseal(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from .config import settings
    from .security import _key
    for secret in (settings.app_secret, settings.app_secret_previous):
        if not secret:
            continue
        try:
            return AESGCM(_key(secret)).decrypt(blob[:12], blob[12:], b"remnawave-panel-copy")
        except Exception:  # noqa: BLE001 — try the previous key
            continue
    raise ValueError("Копия не расшифровывается ключом магазина")


async def run_fetch_panel_backup(ctx: Context, st: dict) -> None:
    """Never stops the action: if the copy cannot be taken, it stays on the panel's server and the log says so."""
    try:
        await _fetch_panel_backup(ctx, st)
    except (StepError, ValueError, OSError) as exc:
        ctx.state["last_panel_copy"] = {"error": str(exc)[:300]}
        _note(ctx, f"Внимание: {exc}. Копия осталась только на сервере панели")


async def _fetch_panel_backup(ctx: Context, st: dict) -> None:
    import base64
    import hashlib
    from datetime import datetime, timezone

    path, _, size = str(ctx.state.get("last_panel_backup") or "").partition(" ")
    if not path:
        raise StepError("Копии базы панели в этом запуске нет")
    if size.isdigit() and int(size) > MAX_PANEL_COPY:
        _note(ctx, f"Копия {size} байт больше {MAX_PANEL_COPY // 1048576} МБ: осталась только на сервере панели ({path})")
        return
    result = await _run(ctx, st["server_id"], FETCH_BACKUP, path, timeout=1800)
    if result.code != 0:
        raise StepError("Копию базы панели не удалось забрать с сервера")
    digest, _, body = result.out.strip().partition("\n")
    data = base64.b64decode(body.strip() or b"", validate=True)
    if hashlib.sha256(data).hexdigest() != digest.strip():
        raise StepError("Копия базы панели пришла повреждённой (SHA-256 не совпал)")
    folder = panel_copies_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"panel-{st['server_id']}-{stamp}.dump.enc"
    tmp = target.with_suffix(".part")
    tmp.write_bytes(seal(data))
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    for old in sorted(folder.glob(f"panel-{st['server_id']}-*.dump.enc"))[:-PANEL_COPIES_KEEP]:
        old.unlink(missing_ok=True)
    ctx.state["last_panel_copy"] = {"file": target.name, "sha256": digest.strip(), "size": len(data), "at": stamp}
    _note(ctx, f"Копия базы панели ({len(data)} байт) зашифрована и сохранена в магазине: {target.name}")


RUN = {"preflight": run_preflight, "install_docker": run_install_docker, "write_files": run_write_files,
       "compose_up": run_compose_up, "wait_panel": run_wait_panel, "panel_bootstrap": run_panel_bootstrap,
       "firewall_node_port": run_firewall_node_port, "register_node": run_register_node, "verify": run_verify,
       "backup_panel": run_backup_panel, "restore_panel": run_restore_panel, "fetch_panel_backup": run_fetch_panel_backup, "compose_down": run_compose_down,
       "selfsteal_profile": run_selfsteal_profile, "node_module": run_node_module, "compose_ctl": run_compose_ctl,
       "node_transports": run_node_transports}
UNDO = {"write_files": undo_write_files, "compose_up": undo_compose_up, "firewall_node_port": undo_firewall_node_port,
        "register_node": undo_register_node, "selfsteal_profile": undo_selfsteal_profile, "node_module": undo_node_module,
        "node_transports": undo_node_transports}
assert set(RUN) == set(STEP_KINDS)
