import React, {useMemo, useState} from "react";
import {Activity, ArrowUpRight, ChevronDown, CircleDollarSign, CreditCard, DatabaseBackup, FileText, Gauge, RefreshCw, Server, ShieldAlert, TriangleAlert, Users, Zap} from "lucide-react";
import {Button} from "./components/ui/button";
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger} from "./components/ui/dropdown-menu";
import {SearchInput} from "./components/ui/search-input";
import {Segmented} from "./components/ui/segmented";
import {StatusBadge, StatusDot, type Tone} from "./components/ui/status";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type NodeFilter = "all" | "online" | "offline" | "disabled";
type Node = {name: string; country: string; status: string; users_online: number | null};

const money = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 2});
const count = new Intl.NumberFormat("ru-RU");

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function nodeTone(status: string): Tone {
  if (status === "online") return "ok";
  if (status === "offline") return "danger";
  if (status === "disabled") return "idle";
  return "warn";
}

function nodeLabel(status: string) {
  if (status === "online") return "Онлайн";
  if (status === "offline") return "Офлайн";
  if (status === "disabled") return "Отключён";
  return "Неизвестно";
}

function flag(country: string) {
  const code = country.trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1a5 + c.charCodeAt(0)));
}

export function Dashboard({d, navigate, reload, request, toast, brandName}: {d: any; navigate?: (tab: string) => void; reload: () => void; request: Request; toast: (message: string) => void; brandName: string}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<NodeFilter>("all");
  const [busy, setBusy] = useState(false);
  const a = d?.analytics || {};
  const health = d?.health || {};
  const nodesAvailable = Array.isArray(d?.nodes?.nodes);
  const nodes: Node[] = nodesAvailable ? d.nodes.nodes : [];
  const users = num(a?.users?.total || d?.remnawave_users?.response?.total);
  const newUsers = num(a?.users?.new_24h);
  const active = num(a?.subscriptions?.active);
  const revenue = {day: num(a?.revenue?.["24h"]), week: num(a?.revenue?.["7d"]), month: num(a?.revenue?.["30d"])};
  const failed = num(a?.payments?.fulfillment_failed);
  const pending = num(a?.payments?.pending);
  const online = nodes.filter((n) => n.status === "online").length;
  const offline = nodes.filter((n) => n.status === "offline").length;
  const disabled = nodes.filter((n) => n.status === "disabled").length;
  const onlineUsers = nodes.reduce((sum, n) => sum + (typeof n.users_online === "number" ? n.users_online : 0), 0);
  const checks: {name: string; ok: boolean; hint: string}[] = [
    {name: "API", ok: Boolean(health.version), hint: health.version ? `v${health.version}` : "—"},
    {name: "База данных", ok: Boolean(health.database), hint: "PostgreSQL"},
    {name: "Redis", ok: Boolean(health.redis), hint: "Очереди и лимиты"},
    {name: "Remnawave", ok: nodesAvailable && !d?.nodes?.error, hint: nodesAvailable ? `${online}/${nodes.length} узлов` : "Нет ответа"},
  ];
  const attention = checks.filter((x) => !x.ok).length + (failed > 0 ? 1 : 0) + (offline > 0 ? 1 : 0);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return nodes.filter((n) => (filter === "all" || n.status === filter) && (!q || n.name.toLowerCase().includes(q) || n.country.toLowerCase().includes(q)));
  }, [nodes, query, filter]);

  async function reconcile() {
    setBusy(true);
    try {
      const result = await request("/api/admin/payments/reconcile", {method: "POST"});
      toast(typeof result?.checked === "number" ? `Сверено: ${result.checked}, подтверждено: ${result.confirmed ?? 0}` : "Сверка запущена");
      reload();
    } catch (error: any) {
      toast(error?.message || "Сверка не выполнена");
    } finally {
      setBusy(false);
    }
  }

  const metrics: {key: string; label: string; value: string; hint: string; icon: React.ReactNode; tone: Tone; to: string}[] = [
    {key: "users", label: "Пользователи", value: count.format(users), hint: newUsers ? `+${count.format(newUsers)} за 24 часа` : "Всего аккаунтов", icon: <Users aria-hidden="true" />, tone: "info", to: "crm"},
    {key: "subs", label: "Активные подписки", value: count.format(active), hint: users ? `${Math.round((active / Math.max(users, 1)) * 100)}% от аккаунтов` : "Действующие сроки", icon: <Zap aria-hidden="true" />, tone: "ok", to: "subscriptionOperations"},
    {key: "revenue", label: "Выручка · 30 дней", value: `${money.format(revenue.month)} ₽`, hint: `${money.format(revenue.day)} ₽ за 24 часа`, icon: <CircleDollarSign aria-hidden="true" />, tone: "info", to: "analytics"},
    {key: "failed", label: "Ошибки выдачи", value: count.format(failed), hint: failed ? "Требуют внимания" : "Очередь чистая", icon: <TriangleAlert aria-hidden="true" />, tone: failed ? "danger" : "ok", to: "payments"},
  ];

  return (
    <div className="dash">
      <section className="dash-banner" aria-label="Состояние магазина">
        <div className="dash-banner-main">
          <div className="dash-banner-icon">
            <Gauge aria-hidden="true" />
          </div>
          <div>
            <div className="eyebrow">{brandName} · CONTROL CENTER</div>
            <h2>{attention ? "Есть пункты, требующие внимания" : "Все системы работают штатно"}</h2>
            <p>Продажи, подписки, узлы Remnawave и фоновые задачи — сводка в реальном времени.</p>
          </div>
        </div>
        <div className="dash-banner-meta">
          <StatusBadge tone={attention ? "warn" : "ok"}>{attention ? `Внимание: ${attention}` : "Онлайн"}</StatusBadge>
          <span className="dash-version">API {health.version || "—"}</span>
          {d?.role && <span className="dash-version">Роль: {d.role}</span>}
        </div>
      </section>

      <div className="dash-metrics">
        {metrics.map((m) => (
          <button type="button" className="dash-metric" data-tone={m.tone} key={m.key} onClick={() => navigate?.(m.to)}>
            <span className="dash-metric-icon">{m.icon}</span>
            <span className="dash-metric-label">{m.label}</span>
            <strong>{m.value}</strong>
            <small>{m.hint}</small>
            <ArrowUpRight className="dash-metric-go" aria-hidden="true" />
          </button>
        ))}
      </div>

      <section className="dash-strip" aria-label="Ключевые показатели">
        <div><span>Выручка · 24 ч</span><b>{money.format(revenue.day)} ₽</b></div>
        <div><span>Выручка · 7 дн</span><b>{money.format(revenue.week)} ₽</b></div>
        <div><span>Ожидают оплаты</span><b data-tone={pending ? "warn" : undefined}>{count.format(pending)}</b></div>
        <div><span>Платежей всего</span><b>{count.format(num(d?.payments))}</b></div>
        <div><span>Тарифов</span><b>{count.format(num(d?.plans))}</b></div>
        <div><span>Онлайн на узлах</span><b>{count.format(onlineUsers)}</b></div>
      </section>

      <div className="dash-controls">
        <div className="dash-controls-title">
          <h3>Серверы</h3>
          <span className="muted">{nodesAvailable ? `${online} из ${nodes.length} онлайн` : "Remnawave недоступен"}</span>
        </div>
        <div className="dash-controls-actions">
          <Button variant="default" onClick={reload}>
            <RefreshCw aria-hidden="true" />
            Обновить
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" isLoading={busy}>
                Действия
                <ChevronDown aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel className="px-2 py-1 text-xs text-muted-foreground">Операции</DropdownMenuLabel>
              <DropdownMenuItem onSelect={reconcile}>
                <CreditCard aria-hidden="true" />
                Сверить платежи
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate?.("nodes")}>
                <Server aria-hidden="true" />
                Управление серверами
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate?.("jobs")}>
                <Activity aria-hidden="true" />
                Очередь задач
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => navigate?.("backups")}>
                <DatabaseBackup aria-hidden="true" />
                Резервные копии
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate?.("audit")}>
                <FileText aria-hidden="true" />
                Журнал действий
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="dash-filters">
        <SearchInput value={query} onValueChange={setQuery} label="Поиск сервера" placeholder="Поиск по названию или стране" />
        <Segmented<NodeFilter>
          label="Фильтр по статусу"
          value={filter}
          onChange={setFilter}
          options={[
            {value: "all", label: "Все", count: nodes.length},
            {value: "online", label: "Онлайн", count: online},
            {value: "offline", label: "Офлайн", count: offline},
            {value: "disabled", label: "Отключены", count: disabled},
          ]}
        />
      </div>

      <div className="dash-columns">
        <section className="card dash-nodes" aria-label="Список серверов">
          {visible.map((n, index) => (
            <article className="dash-node" key={`${n.name}-${index}`}>
              <StatusDot tone={nodeTone(n.status)} pulse={n.status === "online"} />
              <div className="dash-node-name">
                <strong>
                  {flag(n.country) && <span aria-hidden="true">{flag(n.country)} </span>}
                  {n.name}
                </strong>
                <small>{n.country || "—"}</small>
              </div>
              <span className="dash-node-users">{typeof n.users_online === "number" ? `${count.format(n.users_online)} онлайн` : "—"}</span>
              <StatusBadge tone={nodeTone(n.status)}>{nodeLabel(n.status)}</StatusBadge>
            </article>
          ))}
          {!visible.length && (
            <div className="dash-empty">
              <Server aria-hidden="true" />
              <p>{nodesAvailable ? "Нет серверов под выбранный фильтр" : "Remnawave не ответил. Проверьте URL и токен в настройках."}</p>
            </div>
          )}
        </section>

        <aside className="dash-side">
          <section className="card">
            <h3>Состояние платформы</h3>
            <div className="dash-checks">
              {checks.map((x) => (
                <div className="dash-check" key={x.name}>
                  <StatusDot tone={x.ok ? "ok" : "danger"} />
                  <span>{x.name}</span>
                  <small>{x.ok ? x.hint : "Проблема"}</small>
                </div>
              ))}
            </div>
          </section>
          <section className="card">
            <h3>Быстрые действия</h3>
            <div className="quick-actions">
              <button type="button" onClick={() => navigate?.("payments")}><CreditCard aria-hidden="true" /><b>Платежи</b><small>Проверить транзакции</small></button>
              <button type="button" onClick={() => navigate?.("crm")}><Users aria-hidden="true" /><b>Клиенты</b><small>Поиск и карточка</small></button>
              <button type="button" onClick={() => navigate?.("support")}><Activity aria-hidden="true" /><b>Обращения</b><small>Ответы клиентам</small></button>
              <button type="button" onClick={() => navigate?.("security")}><ShieldAlert aria-hidden="true" /><b>Безопасность</b><small>2FA и сессии</small></button>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
