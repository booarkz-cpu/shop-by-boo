"""Ports of the shop's servers: opened by the installer, and by hand from the admin panel (owner's task of 2026-11-13).

«Добавь в задачи, что бы порты все необходимые были открыты автоматом при установке и можно было открыть порты через
панель управления администратора».

What a server needs follows from what the shop installed on it (``required``): Caddy of the panel and the subscription
page (TCP 80, 443), a node (TCP 443 for REALITY), its SelfSteal site (TCP 80 for the certificate), the chosen transports,
MTProto and Psiphon, MASQUE. The node's port for the panel is not opened for everyone: it has its own rule that lets in
only the panel's address (``rw_steps.FIREWALL``), and it is shown here as such.

The node script (``NODE``) opens a port in every firewall it finds on the server — ufw, firewalld, iptables with a
closing INPUT chain, an nftables input chain with policy drop — and remembers what it opened, so «close» removes only
that and a reboot restores it (iptables and nftables keep nothing on their own). It never enables a firewall and never
closes the SSH port. A firewall of the hosting provider (a cloud security group) is outside the server: the page says
so and checks the TCP ports from the shop's side.

``scripts/ci/ports-check.sh`` runs the script for real against iptables and nftables in network namespaces.
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/ports", tags=["remnawave-ports"])
SPEC = re.compile(r"^(tcp|udp)/([0-9]{1,5})\Z")
PROTOS = ("tcp", "udp")

__all__ = ["router", "NODE", "required", "spec", "parse_scan", "status", "required_for"]


class PortIn(BaseModel):
    port: int = Field(ge=1, le=65535)
    proto: str = Field(pattern="^(tcp|udp)$")


def spec(ports: list[dict]) -> str:
    """``[{"port": 443, "proto": "tcp"}, …]`` → ``tcp/443,udp/443`` (sorted, without repeats) for the node script."""
    out = sorted({f"{p['proto']}/{int(p['port'])}" for p in ports if p.get("proto") in PROTOS and 1 <= int(p["port"]) <= 65535},
                 key=lambda x: (int(x.split("/")[1]), x))
    return ",".join(out)


def required(roles: list[str], *, transports=(), mtproto: int | None = None, psiphon: tuple[int, str] | None = None,
             masque: int | None = None, node_port: int | None = None) -> list[dict]:
    """What a server with these roles must have open. ``why`` is shown to the administrator."""
    from .rw_plan import TRANSPORTS
    out: dict[tuple[str, int], dict] = {}

    def add(proto: str, port: int, why: str, scope: str = "all") -> None:
        key = (proto, int(port))
        if key in out:
            if why not in out[key]["why"]:
                out[key]["why"] += f"; {why}"
            return
        out[key] = {"proto": proto, "port": int(port), "why": why, "scope": scope}

    if "panel" in roles or "subscription_page" in roles:
        add("tcp", 80, "Caddy: сертификат Let’s Encrypt и переход на HTTPS")
        add("tcp", 443, "Caddy: панель и страница подписки по HTTPS")
    if "node" in roles:
        add("tcp", 443, "нода: VLESS + REALITY")
    if "selfsteal" in roles:
        add("tcp", 80, "сайт SelfSteal: сертификат и обычные посетители")
    for name in transports:
        if name in TRANSPORTS:
            _tag, port, proto = TRANSPORTS[name]
            add(proto, port, f"транспорт {name}")
    if mtproto:
        add("tcp", mtproto, "MTProto-прокси Telegram")
    if psiphon:
        add("tcp", psiphon[0], f"Psiphon ({psiphon[1]})")
    if masque:
        add("tcp", masque, "MASQUE за сайтом SelfSteal")
    if node_port:
        add("tcp", node_port, "нода ↔ панель", scope="panel")
    return sorted(out.values(), key=lambda p: (p["port"], p["proto"]))


def parse_scan(out: str) -> dict:
    """The node script's «scan»: firewalls found, what they let in, what listens, the SSH port, what the shop opened."""
    res = {"firewalls": [], "allowed": set(), "listening": {}, "ssh": [], "opened": set()}
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "firewall":
            res["firewalls"].append(parts[1])
        elif len(parts) == 3 and parts[0] == "allowed" and parts[1] in (*PROTOS, "any") and parts[2].isdigit():
            for proto in (PROTOS if parts[1] == "any" else (parts[1],)):
                res["allowed"].add((proto, int(parts[2])))
        elif len(parts) >= 3 and parts[0] == "listen" and parts[1] in PROTOS and parts[2].isdigit():
            res["listening"].setdefault((parts[1], int(parts[2])), parts[3] if len(parts) > 3 else "")
        elif len(parts) == 2 and parts[0] == "ssh" and parts[1].isdigit():
            res["ssh"].append(int(parts[1]))
        elif len(parts) == 2 and parts[0] == "opened" and SPEC.match(parts[1]):
            proto, port = parts[1].split("/")
            res["opened"].add((proto, int(port)))
    if not res["firewalls"]:
        res["firewalls"] = ["none"]
    return res


def status(scan: dict, needed: list[dict], reachable: dict | None = None) -> list[dict]:
    """One row per port: the required ones first, then everything else that listens on the server."""
    none = scan["firewalls"] == ["none"]
    rows, seen = [], set()

    def row(proto: str, port: int, why: str, scope: str) -> dict:
        key = (proto, port)
        seen.add(key)
        if scope == "panel":
            firewall = "panel_only"
        elif none or key in scan["allowed"]:
            firewall = "open"
        else:
            firewall = "closed"
        return {"proto": proto, "port": port, "why": why, "scope": scope, "firewall": firewall,
                "listening": key in scan["listening"], "process": scan["listening"].get(key, ""),
                "opened_by_shop": key in scan["opened"], "ssh": port in scan["ssh"] and proto == "tcp",
                "reachable": (reachable or {}).get(key)}

    for p in needed:
        rows.append({**row(p["proto"], p["port"], p["why"], p["scope"]), "required": True})
    for (proto, port), process in sorted(scan["listening"].items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if (proto, port) not in seen:
            rows.append({**row(proto, port, "", "all"), "required": False})
    for proto, port in sorted(scan["opened"] - seen, key=lambda k: (k[1], k[0])):
        rows.append({**row(proto, port, "открыт вручную", "all"), "required": False})
    return rows


async def required_for(db: AsyncSession, server_id: int) -> list[dict]:
    """What the shop's finished installations put on this server, latest state of every module."""
    from .models import RemnawaveInstallation
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.status == "done")
                             .order_by(RemnawaveInstallation.id))).scalars().all()
    roles: set[str] = set()
    transports: set[str] = set()
    mtproto = psiphon = node_port = None
    for row in rows:
        for st in (row.plan or {}).get("steps", []):
            if st.get("server_id") != server_id:
                continue
            p = st.get("params") or {}
            if st.get("kind") == "preflight" and p.get("roles"):
                roles |= set(p["roles"])
                node_port = p.get("node_port") or node_port
            elif st.get("kind") == "node_module" and p.get("module") == "transports":
                transports = set(p.get("transports") or [])
            elif st.get("kind") == "node_module" and p.get("module") == "mtproto":
                mtproto = p.get("mtproto_port") if p.get("enabled", True) else None
            elif st.get("kind") == "node_module" and p.get("module") == "psiphon":
                psiphon = (p.get("psiphon_port"), p.get("psiphon_protocol") or "") if p.get("enabled", True) else None
    from .masque_panel import _state
    masque = ((await _state(db))["nodes"].get(str(server_id)) or {})
    return required(sorted(roles), transports=sorted(transports), mtproto=mtproto, psiphon=psiphon,
                    masque=masque.get("port") if masque.get("state") == "on" else None, node_port=node_port)


async def reach(host: str, ports: list[int], timeout: float = 3.0) -> dict:
    """Whether the shop's server can open a TCP connection to each port — through every firewall on the way,
    the hosting provider's included. UDP cannot be checked this way."""
    async def one(port: int):
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        return True
    results = await asyncio.gather(*(one(p) for p in ports))
    return {("tcp", p): ok for p, ok in zip(ports, results)}


# ---------------------------------------------------------------- the node script
# The core is written to /usr/local/sbin/corgi-ports.sh on every call, so the boot unit can reapply the rules that
# iptables and nftables do not keep. Actions: scan | open <spec> | close <spec> | reapply.
# Exit codes: 2 bad arguments, 3 the SSH port, 4 a firewall refused the rule.
CORE = r"""#!/bin/bash
set -eu
list=/etc/corgi/ports.list; tag=corgi-ports
ufw_on() { command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -q "Status: active"; }
fwd_on() { command -v firewall-cmd >/dev/null 2>&1 && [ "$(firewall-cmd --state 2>/dev/null)" = running ]; }
ipt_closing() {  # $1: iptables or ip6tables — INPUT drops what it does not accept
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -S INPUT 2>/dev/null | grep -Eq '^-P INPUT (DROP|REJECT)|^-A INPUT .*-j (DROP|REJECT)$'
}
nft_chains() {  # input chains with policy drop that iptables does not manage: "family table chain"
  command -v nft >/dev/null 2>&1 || return 0
  nft -a list ruleset 2>/dev/null | awk '
    /^table /{fam=$2; tbl=$3}
    /^\tchain /{ch=$2}
    /type filter hook input/ && /policy drop/{ if (tbl !~ /^corgi_/ && !(fam ~ /^ip6?$/ && tbl=="filter")) print fam, tbl, ch }'
}
ssh_ports() { ss -Hltnp 2>/dev/null | awk '/"sshd"/{n=split($4,a,":"); print a[n]}' | sort -u; }
check() {  # proto/port
  case "$1" in tcp/*|udp/*) ;; *) exit 2 ;; esac
  p=${1#*/}; case "$p" in ""|*[!0-9]*) exit 2 ;; esac
  [ "$p" -ge 1 ] && [ "$p" -le 65535 ] || exit 2
}
persist_ipt() {
  if command -v netfilter-persistent >/dev/null 2>&1; then netfilter-persistent save >/dev/null 2>&1 || true; fi
}
open_one() {  # proto port
  proto=$1; p=$2
  if ufw_on; then ufw allow "$p/$proto" comment "$tag" >/dev/null || return 4; fi
  if fwd_on; then firewall-cmd -q --permanent --add-port="$p/$proto" || return 4; reload_fwd=1; fi
  if ! ufw_on && ! fwd_on; then
    for t in iptables ip6tables; do
      if ipt_closing "$t"; then
        "$t" -C INPUT -p "$proto" --dport "$p" -m comment --comment "$tag" -j ACCEPT 2>/dev/null \
          || "$t" -I INPUT -p "$proto" --dport "$p" -m comment --comment "$tag" -j ACCEPT || return 4
        save_ipt=1
      fi
    done
  fi
  nft_chains | while read -r fam tbl ch; do
    nft list chain "$fam" "$tbl" "$ch" 2>/dev/null | grep -q "comment \"$tag $proto/$p\"" \
      || nft insert rule "$fam" "$tbl" "$ch" meta l4proto "$proto" th dport "$p" accept comment "\"$tag $proto/$p\"" || exit 4
  done || return 4
}
close_one() {  # proto port
  proto=$1; p=$2
  if ufw_on; then ufw delete allow "$p/$proto" >/dev/null 2>&1 || true; fi
  if fwd_on; then firewall-cmd -q --permanent --remove-port="$p/$proto" >/dev/null 2>&1 || true; reload_fwd=1; fi
  for t in iptables ip6tables; do
    command -v "$t" >/dev/null 2>&1 || continue
    while "$t" -D INPUT -p "$proto" --dport "$p" -m comment --comment "$tag" -j ACCEPT 2>/dev/null; do save_ipt=1; done
  done
  nft_chains | while read -r fam tbl ch; do
    nft -a list chain "$fam" "$tbl" "$ch" 2>/dev/null | grep "comment \"$tag $proto/$p\"" | grep -o 'handle [0-9]*' | cut -d' ' -f2 \
      | while read -r h; do nft delete rule "$fam" "$tbl" "$ch" handle "$h" || true; done
  done
}
action="${1:-}"; arg="${2:-}"; reload_fwd=0; save_ipt=0
install -d -m 0755 /etc/corgi; touch "$list"
case "$action" in
scan)
  found=0
  if ufw_on; then echo "firewall ufw"; found=1
    ufw status 2>/dev/null | awk '$2=="ALLOW" && $3=="Anywhere" {print $1}' | sed 's/ (v6)//' | while read -r r; do
      case "$r" in */tcp|*/udp) echo "allowed ${r#*/} ${r%/*}" ;; *[!0-9]*) ;; *) echo "allowed any $r" ;; esac
    done
  fi
  if fwd_on; then echo "firewall firewalld"; found=1
    for r in $(firewall-cmd --list-ports 2>/dev/null); do echo "allowed ${r#*/} ${r%/*}"; done
    for s in $(firewall-cmd --list-services 2>/dev/null); do
      case "$s" in ssh) echo "allowed tcp 22" ;; http) echo "allowed tcp 80" ;; https) echo "allowed tcp 443" ;; esac
    done
  fi
  if ! ufw_on && ! fwd_on; then
    for t in iptables ip6tables; do
      if ipt_closing "$t"; then
        [ "$t" = iptables ] && { echo "firewall iptables"; found=1; }
        "$t" -S INPUT 2>/dev/null | grep -- '-j ACCEPT' | grep -v -- ' -s ' \
          | sed -n 's/.*-p \(tcp\|udp\).*--dport \([0-9]*\).*/allowed \1 \2/p'
      fi
    done
  fi
  if [ -n "$(nft_chains)" ]; then echo "firewall nftables"; found=1
    nft list ruleset 2>/dev/null | grep -Eo '(tcp|udp|th) dport [0-9]+ accept' | awk '{p=$1=="th"?"any":$1; print "allowed", p, $3}'
  fi
  [ "$found" = 1 ] || echo "firewall none"
  ss -Hltnp 2>/dev/null | awk '{n=split($4,a,":"); q=$6; sub(/^users:\(\("/,"",q); sub(/".*/,"",q); print "listen tcp", a[n], q}'
  ss -Hlunp 2>/dev/null | awk '{n=split($4,a,":"); q=$6; sub(/^users:\(\("/,"",q); sub(/".*/,"",q); print "listen udp", a[n], q}'
  for s in $(ssh_ports); do echo "ssh $s"; done
  sort -u "$list" | sed 's/^/opened /'
  echo "ports=scan" ;;
open|close)
  [ -n "$arg" ] || exit 2
  for item in $(echo "$arg" | tr , ' '); do check "$item"; done
  if [ "$action" = close ]; then
    for item in $(echo "$arg" | tr , ' '); do
      [ "${item%/*}" = tcp ] && for s in $(ssh_ports) 22; do [ "${item#*/}" = "$s" ] && { echo "ssh port $s"; exit 3; }; done
    done
  fi
  for item in $(echo "$arg" | tr , ' '); do
    if [ "$action" = open ]; then
      open_one "${item%/*}" "${item#*/}" || { echo "refused $item"; exit 4; }
      grep -qx "$item" "$list" || echo "$item" >> "$list"
      echo "opened $item"
    else
      close_one "${item%/*}" "${item#*/}"
      grep -vx "$item" "$list" > "$list.new" || true; mv -f "$list.new" "$list"
      echo "closed $item"
    fi
  done
  [ "$reload_fwd" = 1 ] && firewall-cmd -q --reload
  [ "$save_ipt" = 1 ] && persist_ipt
  echo "ports=$action" ;;
reapply)
  # At boot (corgi-ports.service): put back what iptables and nftables forgot. ufw and firewalld keep their rules.
  while read -r item; do [ -n "$item" ] && { open_one "${item%/*}" "${item#*/}" || true; }; done < "$list"
  [ "$save_ipt" = 1 ] && persist_ipt
  echo "ports=reapply" ;;
*) exit 2 ;;
esac
"""

NODE = r"""set -eu
install -d -m 0755 /usr/local/sbin
cat > /usr/local/sbin/corgi-ports.sh <<'CORGI_PORTS_CORE'
""" + CORE + r"""CORGI_PORTS_CORE
chmod 0700 /usr/local/sbin/corgi-ports.sh
if [ -d /run/systemd/system ] && [ ! -f /etc/systemd/system/corgi-ports.service ]; then
  printf '[Unit]\nDescription=Ports opened by the shop\nAfter=network-pre.target nftables.service netfilter-persistent.service ufw.service firewalld.service\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/corgi-ports.sh reapply\n[Install]\nWantedBy=multi-user.target\n' \
    > /etc/systemd/system/corgi-ports.service
  systemctl daemon-reload; systemctl enable corgi-ports.service >/dev/null 2>&1 || true
fi
exec bash /usr/local/sbin/corgi-ports.sh "$@"
"""

REASONS = {3: "Это порт SSH: закрыть его — потерять доступ к серверу", 4: "Брандмауэр сервера не принял правило",
           2: "Неверный порт"}


# ---------------------------------------------------------------- admin

async def _server(db: AsyncSession, server_id: int):
    from .models import RemnawaveServer
    row = await db.get(RemnawaveServer, server_id)
    if not row:
        raise HTTPException(404, "Сервер не найден")
    return row


async def _ssh(db: AsyncSession, server_id: int, *args: str):
    from . import rw_jobs, rw_ssh, rw_steps
    row = await _server(db, server_id)
    try:
        return row, await rw_steps._run(rw_ssh._ctx(rw_jobs.server_dict(row)), server_id, NODE, *args, timeout=180)
    except rw_steps.StepError as exc:
        raise HTTPException(502, f"SSH: {exc}") from exc


async def view(db: AsyncSession, server_id: int, check_outside: bool = False) -> dict:
    row, result = await _ssh(db, server_id, "scan")
    if result.code != 0:
        raise HTTPException(502, "Сервер не ответил на проверку портов")
    scan = parse_scan(result.out)
    needed = await required_for(db, server_id)
    reachable = None
    if check_outside:
        tcp = sorted({p["port"] for p in needed if p["proto"] == "tcp" and p["scope"] == "all"}
                     | {port for proto, port in scan["listening"] if proto == "tcp"})[:40]
        reachable = await reach(row.host, tcp)
    rows = status(scan, needed, reachable)
    return {"server_id": server_id, "name": row.name, "host": row.host, "firewalls": scan["firewalls"], "ports": rows,
            "missing": [f"{r['proto']}/{r['port']}" for r in rows if r["required"] and r["firewall"] == "closed"],
            "checked_outside": check_outside,
            "notes": ["Если брандмауэра на сервере нет, порты закрывает только брандмауэр хостинга (группа безопасности в его панели): "
                      "магазин его не видит. «Проверить снаружи» показывает, доходит ли соединение до TCP-порта.",
                      "UDP-порты (Hysteria2) снаружи так не проверить.",
                      "Порт SSH магазин не закрывает никогда."]}


@router.get("/{server_id}")
async def ports(server_id: int, outside: bool = False, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await view(db, server_id, outside)


async def _change(db: AsyncSession, admin, server_id: int, action: str, items: list[PortIn]) -> dict:
    from .main import audit
    text = spec([i.model_dump() for i in items])
    if not text:
        raise HTTPException(422, "Нет портов")
    _row, result = await _ssh(db, server_id, action, text)
    if result.code != 0:
        raise HTTPException(409 if result.code == 3 else 502, REASONS.get(result.code, f"Скрипт завершился с кодом {result.code}"))
    await audit(db, f"rw.ports.{action}", admin.email, str(server_id), {"ports": text})
    await db.commit()
    return await view(db, server_id)


@router.post("/{server_id}/open")
async def open_ports(server_id: int, items: list[PortIn], db: AsyncSession = Depends(get_db),
                     admin=Depends(require_permission("provision_nodes"))):
    return await _change(db, admin, server_id, "open", items)


@router.post("/{server_id}/open-required")
async def open_required(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Opens what the shop's own installations need here (the node's port for the panel keeps its own rule)."""
    needed = [PortIn(port=p["port"], proto=p["proto"]) for p in await required_for(db, server_id) if p["scope"] == "all"]
    if not needed:
        raise HTTPException(409, "Магазин ничего не устанавливал на этот сервер")
    return await _change(db, admin, server_id, "open", needed)


@router.post("/{server_id}/close")
async def close_ports(server_id: int, items: list[PortIn], db: AsyncSession = Depends(get_db),
                      admin=Depends(require_permission("provision_nodes"))):
    return await _change(db, admin, server_id, "close", items)
