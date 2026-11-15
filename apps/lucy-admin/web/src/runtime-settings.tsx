import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clock3,
  KeyRound,
  Search,
  ServerCog,
  RotateCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/select-field";

type SettingValue = boolean | number | string | null;
type SettingKind =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "secret"
  | "select";

interface RuntimeSettingDefinition {
  key: string;
  group: string;
  title: string;
  description: string;
  kind: SettingKind;
  secret: boolean;
  minimum: number | null;
  maximum: number | null;
  choices: string[];
  optional: boolean;
  unit: string;
  value: SettingValue;
  configured: boolean;
  overridden: boolean;
  source: "database" | "environment";
}

interface RuntimeSettingChange {
  id: string;
  base_version: number;
  target_version: number | null;
  status: string;
  keys: string[];
  fingerprint: string;
  actor: string;
  reason: string;
  source_change_id: string | null;
  created_at: string;
  applied_at: string | null;
  can_apply: boolean;
  can_discard: boolean;
  can_rollback: boolean;
}

interface RestartRequiredSetting {
  key: string;
  env: string;
  reason: string;
}

interface ManagedElsewhereSetting {
  key: string;
  env: string;
  location: string;
  reason: string;
}

export interface RuntimeSettingsData {
  version: number;
  registry_version: number;
  convergence_seconds: number;
  hot_reload_count: number;
  restart_required_count: number;
  managed_elsewhere_count: number;
  can_write: boolean;
  settings: RuntimeSettingDefinition[];
  restart_required: RestartRequiredSetting[];
  managed_elsewhere: ManagedElsewhereSetting[];
  warnings: string[];
  errors: string[];
  staged: RuntimeSettingChange[];
  history: RuntimeSettingChange[];
}

interface StagePreview {
  key: string;
  title: string;
  clear: boolean;
  value: SettingValue;
  secret_changed: boolean;
}

interface StageResponse {
  change: RuntimeSettingChange;
  preview: StagePreview[];
  warnings: string[];
}

interface MutationResponse {
  version?: number;
  discarded?: boolean;
  id?: string;
  change?: RuntimeSettingChange;
  convergence_seconds?: number;
}

type Requester = (
  path: string,
  options?: RequestInit,
) => Promise<StageResponse | MutationResponse>;

interface RuntimeSettingsProps {
  data: RuntimeSettingsData;
  request: Requester;
  reload: () => Promise<void> | void;
  toast: (message: string) => void;
}

const GROUP_LABELS: Record<string, string> = {
  general: "Общие параметры",
  billing: "Платежи и риск",
  renewal: "Автопродление",
  remnawave: "Remnawave",
  monitoring: "Мониторинг и алерты",
  mail: "Почтовый канал",
  security: "Сетевая безопасность",
  telegram: "Telegram",
  urls: "Публичные URL",
  pricing: "Базовые цены",
  yookassa: "YooKassa",
  platega: "Platega",
  rollypay: "RollyPay",
  crypto: "Криптоплатежи",
  stripe: "Stripe",
  paypal: "PayPal",
  mobile_stores: "Мобильные магазины",
  mobile: "Native-клиенты",
  storage: "S3 и резервные копии",
  updates: "Обновления",
  oauth: "Yandex ID и VK ID",
  support: "Поддержка",
};

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    staged: "Ожидает применения",
    applied: "Применено",
    rolled_back: "Отменено откатом",
    discarded: "Удалено",
    superseded: "Устарело",
  };
  return labels[status] ?? status;
}

function dateTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU");
}

export function RuntimeSettings({
  data,
  request,
  reload,
  toast,
}: RuntimeSettingsProps) {
  const [draft, setDraft] = useState<Record<string, boolean | number | string>>(
    {},
  );
  const [touched, setTouched] = useState<string[]>([]);
  const [clearKeys, setClearKeys] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [staged, setStaged] = useState<StageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const initial: Record<string, boolean | number | string> = {};
    for (const setting of data.settings ?? []) {
      initial[setting.key] = setting.secret
        ? ""
        : setting.value === null
          ? ""
          : setting.value;
    }
    setDraft(initial);
    setTouched([]);
    setClearKeys([]);
    setStaged(null);
  }, [data.version, data.settings]);

  const groups = useMemo(() => {
    const result = new Map<string, RuntimeSettingDefinition[]>();
    const normalizedQuery = query.trim().toLocaleLowerCase("ru-RU");
    for (const setting of data.settings ?? []) {
      if (
        normalizedQuery &&
        !`${setting.title} ${setting.description} ${setting.key} ${setting.group}`
          .toLocaleLowerCase("ru-RU")
          .includes(normalizedQuery)
      ) {
        continue;
      }
      const rows = result.get(setting.group) ?? [];
      rows.push(setting);
      result.set(setting.group, rows);
    }
    return Array.from(result.entries());
  }, [data.settings, query]);

  function update(setting: RuntimeSettingDefinition, value: boolean | number | string) {
    setDraft((current) => ({ ...current, [setting.key]: value }));
    setTouched((current) =>
      current.includes(setting.key) ? current : [...current, setting.key],
    );
    setClearKeys((current) => current.filter((key) => key !== setting.key));
    setStaged(null);
  }

  function toggleClear(setting: RuntimeSettingDefinition) {
    if (!setting.overridden) return;
    setClearKeys((current) =>
      current.includes(setting.key)
        ? current.filter((key) => key !== setting.key)
        : [...current, setting.key],
    );
    setTouched((current) => current.filter((key) => key !== setting.key));
    setStaged(null);
  }

  async function stage() {
    if (!reason.trim()) {
      toast("Укажите причину изменения");
      return;
    }
    const changes: Record<string, boolean | number | string> = {};
    for (const key of touched) {
      const setting = data.settings.find((item) => item.key === key);
      if (!setting || clearKeys.includes(key)) continue;
      const value = draft[key];
      if (setting.secret && value === "") continue;
      changes[key] = value;
    }
    if (!Object.keys(changes).length && !clearKeys.length) {
      toast("Измените или сбросьте хотя бы один параметр");
      return;
    }
    setBusy(true);
    try {
      const result = await request("/api/admin/runtime-settings/stage", {
        method: "POST",
        body: JSON.stringify({
          base_version: data.version,
          changes,
          clear: clearKeys,
          reason: reason.trim(),
        }),
      });
      if (!("preview" in result) || !result.change) {
        throw new Error("Сервер не вернул staged-набор");
      }
      setStaged(result);
      toast("Изменения проверены и подготовлены");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Не удалось проверить настройки");
    } finally {
      setBusy(false);
    }
  }

  async function apply(change: RuntimeSettingChange) {
    if (!window.confirm("Применить проверенный набор без перезапуска сервисов?")) return;
    setBusy(true);
    try {
      await request(`/api/admin/runtime-settings/changes/${change.id}/apply`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: data.version,
          fingerprint: change.fingerprint,
        }),
      });
      toast(`Версия ${data.version + 1} применена`);
      setReason("");
      await reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Не удалось применить настройки");
    } finally {
      setBusy(false);
    }
  }

  async function discard(change: RuntimeSettingChange) {
    setBusy(true);
    try {
      await request(`/api/admin/runtime-settings/changes/${change.id}`, {
        method: "DELETE",
      });
      toast("Staged-набор удалён");
      await reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Не удалось удалить набор");
    } finally {
      setBusy(false);
    }
  }

  async function rollback(change: RuntimeSettingChange) {
    const rollbackReason = window.prompt(
      "Причина отката (будет записана в журнал)",
      `Откат версии ${change.target_version ?? ""}`,
    );
    if (!rollbackReason?.trim()) return;
    if (!window.confirm("Откатить последнюю версию настроек?")) return;
    setBusy(true);
    try {
      await request(`/api/admin/runtime-settings/changes/${change.id}/rollback`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: data.version,
          reason: rollbackReason.trim(),
        }),
      });
      toast("Настройки восстановлены из предыдущего снимка");
      await reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Не удалось откатить настройки");
    } finally {
      setBusy(false);
    }
  }

  const activeStage = staged?.change ?? data.staged?.find((item) => item.can_apply);
  return (
    <div className="runtime-settings-page">
      <section className="hero runtime-settings-hero">
        <div>
          <div className="eyebrow">Версия настроек: {data.version}</div>
          <h2>Настройки без перезапуска</h2>
          <p>
            Типизированные значения применяются атомарно. Секреты зашифрованы,
            каждое действие фиксируется, последнюю версию можно безопасно откатить.
          </p>
        </div>
        <div className="runtime-version-badge">
          <Zap aria-hidden="true" />
          <strong>≤ {data.convergence_seconds || 5} сек.</strong>
          <span>сходимость процессов</span>
        </div>
      </section>

      <section className="runtime-registry-toolbar" aria-label="Поиск по настройкам">
        <div className="runtime-search">
          <Search aria-hidden="true" />
          <label className="sr-only" htmlFor="runtime-settings-search">
            Найти параметр
          </label>
          <input
            id="runtime-settings-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Название, ключ или назначение"
            data-hint="Фильтр ищет по названию, техническому ключу, группе и тексту подсказки."
          />
        </div>
        <div className="runtime-registry-counts" aria-label="Покрытие реестра">
          <span><b>{data.hot_reload_count}</b> live</span>
          <span><b>{data.restart_required_count}</b> deployment</span>
          <span><b>{data.managed_elsewhere_count}</b> workflow</span>
          <span><b>{data.can_write ? "RW" : "RO"}</b> доступ</span>
        </div>
      </section>

      {(data.errors ?? []).map((message) => (
        <div className="error" role="alert" key={message}>
          <TriangleAlert aria-hidden="true" /> {message}
        </div>
      ))}
      {(data.warnings ?? []).map((message) => (
        <div className="runtime-warning" role="status" key={message}>
          <TriangleAlert aria-hidden="true" /> {message}
        </div>
      ))}

      <div className="runtime-settings-layout">
        <div className="runtime-setting-groups">
          {groups.map(([group, settings]) => (
            <section className="card runtime-setting-group" key={group}>
              <div className="card-title">
                <div>
                  <span className="runtime-group-index">
                    {String(groups.findIndex(([name]) => name === group) + 1).padStart(2, "0")}
                  </span>
                  <h3>{GROUP_LABELS[group] ?? group}</h3>
                </div>
                <SlidersHorizontal aria-hidden="true" />
              </div>
              <div className="runtime-fields">
                {settings.map((setting) => {
                  const clearing = clearKeys.includes(setting.key);
                  const currentValue = draft[setting.key];
                  return (
                    <div
                      className={`runtime-field${clearing ? " is-clearing" : ""}`}
                      key={setting.key}
                    >
                      <div className="runtime-field-copy">
                        <label htmlFor={`runtime-${setting.key}`}>
                          {setting.title}
                        </label>
                        <p>{setting.description}</p>
                        <div className="runtime-field-meta">
                          <span className={setting.overridden ? "is-overridden" : ""}>
                            {setting.source === "database" ? "Переопределено" : "Из .env"}
                          </span>
                          {setting.unit && <span>{setting.unit}</span>}
                          {setting.secret && (
                            <span>
                              <KeyRound aria-hidden="true" />
                              {setting.configured ? "секрет задан" : "не задан"}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="runtime-field-control">
                        {setting.kind === "boolean" ? (
                          <label className="runtime-switch">
                            <input
                              id={`runtime-${setting.key}`}
                              type="checkbox"
                              checked={Boolean(draft[setting.key])}
                              disabled={clearing || !data.can_write}
                              data-hint={setting.description}
                              onChange={(event) => update(setting, event.target.checked)}
                            />
                            <span aria-hidden="true" />
                            <b>{Boolean(draft[setting.key]) ? "Включено" : "Выключено"}</b>
                          </label>
                        ) : setting.kind === "select" ? (
                          <SelectField
                            id={`runtime-${setting.key}`}
                            value={String(draft[setting.key] ?? "")}
                            disabled={clearing || !data.can_write}
                            data-hint={setting.description}
                            onChange={(event) => update(setting, event.target.value)}
                          >
                            {setting.choices.map((choice) => (
                              <option value={choice} key={choice}>
                                {choice}
                              </option>
                            ))}
                          </SelectField>
                        ) : (
                          <input
                            id={`runtime-${setting.key}`}
                            type={
                              setting.kind === "secret"
                                ? "password"
                                : setting.kind === "integer" || setting.kind === "number"
                                  ? "number"
                                  : "text"
                            }
                            min={setting.minimum ?? undefined}
                            max={setting.maximum ?? undefined}
                            step={setting.kind === "number" ? "0.01" : undefined}
                            value={
                              typeof currentValue === "boolean"
                                ? ""
                                : currentValue ?? ""
                            }
                            disabled={clearing || !data.can_write}
                            placeholder={
                              setting.secret && setting.configured
                                ? "Введите только для замены"
                                : setting.optional
                                  ? "Не задано"
                                  : undefined
                            }
                            autoComplete={setting.secret ? "new-password" : undefined}
                            data-hint={setting.description}
                            onChange={(event) =>
                              update(
                                setting,
                                setting.kind === "integer" || setting.kind === "number"
                                  ? event.target.value === ""
                                    ? ""
                                    : Number(event.target.value)
                                  : event.target.value,
                              )
                            }
                          />
                        )}
                        {setting.overridden && data.can_write && (
                          <Button
                            variant={clearing ? "secondary" : "ghost"}
                            size="sm"
                            onClick={() => toggleClear(setting)}
                            disabled={busy}
                            data-hint="Сбросить переопределение и снова использовать значение из .env."
                          >
                            <RotateCcw aria-hidden="true" />
                            {clearing ? "Отменить сброс" : "Вернуть .env"}
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
          {!groups.length && (
            <div className="card empty-state">По этому запросу параметры не найдены.</div>
          )}
        </div>

        <aside className="runtime-review card">
          <div className="card-title">
            <div>
              <span className="runtime-group-index">APPLY</span>
              <h3>Проверка изменений</h3>
            </div>
            <ShieldCheck aria-hidden="true" />
          </div>
          <label htmlFor="runtime-change-reason">Причина изменения</label>
          <textarea
            id="runtime-change-reason"
            rows={3}
            maxLength={500}
            value={reason}
            disabled={!data.can_write}
            onChange={(event) => {
              setReason(event.target.value);
              setStaged(null);
            }}
            data-hint="Кратко опишите цель изменения. Причина сохраняется в истории, секреты сюда не вводите."
            placeholder="Например: снизить порог алертов после расширения кластера"
          />
          {!data.can_write && (
            <div className="runtime-warning" role="status">
              <ShieldCheck aria-hidden="true" /> Режим просмотра: изменение доступно только администратору.
            </div>
          )}
          <div className="runtime-review-counts">
            <span>{touched.length} изменено</span>
            <span>{clearKeys.length} сбрасывается</span>
          </div>
          <Button
            className="primary"
            onClick={stage}
            isLoading={busy}
            disabled={!data.can_write}
          >
            <Save aria-hidden="true" /> Проверить и подготовить
          </Button>

          {staged && (
            <div className="runtime-preview">
              <div className="runtime-preview-title">
                <CheckCircle2 aria-hidden="true" /> Проверка пройдена
              </div>
              {staged.preview.map((item) => (
                <div key={item.key}>
                  <span>{item.title}</span>
                  <b>
                    {item.clear
                      ? "значение из .env"
                      : item.secret_changed
                        ? "новый секрет"
                        : String(item.value)}
                  </b>
                </div>
              ))}
              {staged.warnings.map((warning) => (
                <small key={warning}>{warning}</small>
              ))}
            </div>
          )}

          {activeStage && data.can_write && (
            <div className="runtime-stage-actions">
              <code>{activeStage.fingerprint.slice(0, 12)}…</code>
              <Button
                className="primary"
                onClick={() => apply(activeStage)}
                isLoading={busy}
                disabled={!activeStage.can_apply}
              >
                <Zap aria-hidden="true" /> Применить версию {data.version + 1}
              </Button>
              <Button
                variant="outline"
                onClick={() => discard(activeStage)}
                disabled={busy || !activeStage.can_discard}
              >
                <Trash2 aria-hidden="true" /> Удалить staged-набор
              </Button>
            </div>
          )}
        </aside>
      </div>

      <section className="card runtime-history">
        <div className="card-title">
          <div>
            <span className="runtime-group-index">HISTORY</span>
            <h3>История версий</h3>
          </div>
          <Clock3 aria-hidden="true" />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Версия</th>
                <th>Состояние</th>
                <th>Параметры</th>
                <th>Причина</th>
                <th>Автор</th>
                <th>Время</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              {(data.history ?? []).map((change) => (
                <tr key={change.id}>
                  <td>{change.target_version ?? `base ${change.base_version}`}</td>
                  <td><span className={`runtime-status is-${change.status}`}>{statusLabel(change.status)}</span></td>
                  <td>{change.keys.join(", ")}</td>
                  <td>{change.reason}</td>
                  <td>{change.actor}</td>
                  <td>{dateTime(change.applied_at ?? change.created_at)}</td>
                  <td>
                    {change.can_rollback && data.can_write ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => rollback(change)}
                        disabled={busy}
                      >
                        <RotateCcw aria-hidden="true" /> Откатить
                      </Button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
              {!data.history?.length && (
                <tr><td colSpan={7} className="empty-state">Версии ещё не применялись</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <details className="card runtime-environment-bound">
        <summary>
          <span>
            <ServerCog aria-hidden="true" />
            Параметры deployment и специализированных процедур
          </span>
          <b>{data.restart_required_count + data.managed_elsewhere_count}</b>
        </summary>
        <div className="runtime-bound-copy">
          Эти значения намеренно нельзя менять через live-config: они создают
          подключения, middleware, контейнеры или требуют отдельной транзакционной
          процедуры. Значения секретов здесь не отображаются.
        </div>
        <div className="runtime-bound-grid">
          {(data.managed_elsewhere ?? []).map((setting) => (
            <article key={setting.key}>
              <div><code>{setting.env}</code><span>WORKFLOW</span></div>
              <strong>{setting.location}</strong>
              <p>{setting.reason}</p>
            </article>
          ))}
          {(data.restart_required ?? []).map((setting) => (
            <article key={setting.key}>
              <div><code>{setting.env}</code><span>DEPLOYMENT</span></div>
              <strong>{setting.key}</strong>
              <p>{setting.reason}</p>
            </article>
          ))}
        </div>
      </details>
    </div>
  );
}
