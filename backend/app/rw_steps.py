"""Steps of the Remnawave installation wizard — the closed list (v28.66, stage 10; docs/ru/new/DEPLOYMENT_AGENT.md).

Every step is a fixed script of this module with typed parameters. ``STEP_KINDS`` is the whole list: the runner
refuses any other kind. Each step is idempotent (running it again does not break what it did), and the steps
that change a server have a rollback that the runner calls in reverse order after a failure."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets as pysecrets
import socket
import string
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import rw_plan
from .rw_remote import Remote, RemoteError, tail

STEP_KINDS = ("preflight", "install_docker", "write_files", "compose_up", "wait_panel", "panel_bootstrap",
              "firewall_node_port", "register_node", "verify", "backup_panel", "restore_panel", "compose_down")
FILE_NAMES = ("docker-compose.yml", ".env", "Caddyfile")
COMPONENTS = ("panel", "node", "subscription_page", "proxy")
_sleep = asyncio.sleep  # tests replace it
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
                   "node": "remnanode"}


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
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy) ;; *) echo "bad dir" >&2; exit 2 ;; esac
case "$name" in docker-compose.yml|.env|Caddyfile) ;; *) echo "bad name" >&2; exit 2 ;; esac
install -d -m 0750 "$dir"
umask 077
if [ -f "$dir/$name" ]; then cp -p "$dir/$name" "$dir/$name.rw-prev"; else rm -f "$dir/$name.rw-prev"; fi
cat > "$dir/$name.rw-new"
echo "$sum  $dir/$name.rw-new" | sha256sum -c --status
mv "$dir/$name.rw-new" "$dir/$name"
"""

UNWRITE = r"""set -eu
dir="$1"; name="$2"
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy) ;; *) exit 2 ;; esac
case "$name" in docker-compose.yml|.env|Caddyfile) ;; *) exit 2 ;; esac
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
        return {"docker-compose.yml": rw_plan.subpage_compose(), ".env": rw_plan.subpage_env(url, token, ctx.secrets, local)}
    if component == "proxy":
        sites = {}
        if server_id == plan.panel_server_id:
            sites[plan.panel_domain] = 3000
        if server_id == plan.subpage_server_id:
            sites[plan.sub_domain] = 3010
        protect = {}
        if plan.panel_access == "cookie" and plan.panel_domain in sites:
            protect[plan.panel_domain] = access_cookie(ctx)
        return {"Caddyfile": rw_plan.caddyfile(sites, plan.tls, plan.acme_email, protect), "docker-compose.yml": rw_plan.caddy_compose()}
    if component == "node":
        key = ctx.state.get("node_secret_key") or await _keygen(ctx)
        return {"docker-compose.yml": rw_plan.node_compose(key, plan.node_port)}
    raise StepError(f"Неизвестный компонент {component}")


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
case "$dir" in /opt/remnawave|/opt/remnanode|/opt/remnawave-subpage|/opt/remnawave-caddy) ;; *) exit 2 ;; esac
cd "$dir"
case "$action" in
  up) if [ "$dir" = /opt/remnawave-subpage ]; then docker network inspect remnawave-network >/dev/null 2>&1 || docker network create remnawave-network >/dev/null; fi
      docker compose pull -q && docker compose up -d --remove-orphans && docker compose ps --format '{{.Name}} {{.State}}' ;;
  down) docker compose down --remove-orphans ;;
  ps) docker compose ps --format '{{.Name}} {{.State}}' ;;
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
    result = await _run(ctx, st["server_id"], FIREWALL, ip, str(ctx.plan.node_port), "add", timeout=60)
    _note(ctx, result.out + result.err)
    if result.code != 0:
        raise StepError("Правило ufw не добавлено")
    ctx.state.setdefault("firewall", {})[str(st["server_id"])] = ip


async def undo_firewall_node_port(ctx: Context, st: dict) -> None:
    ip = ctx.state.get("firewall", {}).get(str(st["server_id"]))
    if ip:
        await _run(ctx, st["server_id"], FIREWALL, ip, str(ctx.plan.node_port), "delete", timeout=60)


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
    profile = next((p for p in profiles if p.get("inbounds")), None)
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


# ---------- verify ----------

HTTPS_CHECK = r"""set -u
domain="$1"; ua="$2"; cookie="${4:-}"
code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$domain:443:127.0.0.1" -A "$ua" ${cookie:+-H "Cookie: $cookie"} "https://$domain/$3")"
echo "$code"
"""


async def run_verify(ctx: Context, st: dict) -> None:
    plan = ctx.plan
    problems = []
    if plan.panel_server_id:
        for _ in range(20):
            cookie = "=".join(access_cookie(ctx)) if plan.panel_access == "cookie" else ""
            code = (await _run(ctx, plan.panel_server_id, HTTPS_CHECK, plan.panel_domain, "corgi-verify", "api/auth/status", cookie,
                               timeout=30)).out.strip()
            if code == "200":
                break
            await _sleep(6)
        _note(ctx, f"https://{plan.panel_domain}/api/auth/status через Caddy: {code}")
        if code != "200":
            problems.append(f"панель не отвечает через HTTPS ({code})")
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
f="$(ls -1t /opt/remnawave/backups/panel-*.dump 2>/dev/null | head -1)"
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
    result = await _run(ctx, st["server_id"], RESTORE, timeout=1800)
    if result.code == 3:
        raise StepError("На сервере нет копии базы панели")
    if result.code != 0:
        raise StepError("Восстановление базы панели не удалось")
    _note(ctx, f"База панели восстановлена из {result.out.strip()}")


RUN = {"preflight": run_preflight, "install_docker": run_install_docker, "write_files": run_write_files,
       "compose_up": run_compose_up, "wait_panel": run_wait_panel, "panel_bootstrap": run_panel_bootstrap,
       "firewall_node_port": run_firewall_node_port, "register_node": run_register_node, "verify": run_verify,
       "backup_panel": run_backup_panel, "restore_panel": run_restore_panel, "compose_down": run_compose_down}
UNDO = {"write_files": undo_write_files, "compose_up": undo_compose_up, "firewall_node_port": undo_firewall_node_port,
        "register_node": undo_register_node}
assert set(RUN) == set(STEP_KINDS)
