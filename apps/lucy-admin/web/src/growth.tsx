import React from "react";

const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");

/** «Аналитика → Удержание клиентов»: cohorts by the month of the first payment, LTV and why customers cancel. */
export function Retention({d}: {d: any}) {
  if (!d?.cohorts) return <div className="card"><p className="muted">Загрузка…</p></div>;
  const cur = d.currency || "RUB";
  const maxReason = Math.max(1, ...(d.cancel_reasons || []).map((r: any) => r.count));
  return <div className="retention">
    <div className="kpis">
      <div className="card kpi"><span>Платящих клиентов</span><b>{d.customers}</b></div>
      <div className="card kpi"><span>Средний доход с клиента (LTV)</span><b>{d.ltv} {cur}</b></div>
      <div className="card kpi"><span>Купили повторно</span><b>{d.repeat_rate}%</b></div>
      <div className="card kpi"><span>Сейчас с активной подпиской</span><b>{d.active_customers}</b></div>
    </div>
    <div className="card">
      <h3>Когорты по месяцу первой оплаты</h3>
      <p className="muted">Клиент попадает в месяц первой оплаты подписки. «Повторно» — заплатил ещё хотя бы раз, «активны» — подписка действует сейчас, LTV — вся выручка когорты на одного клиента.</p>
      {d.cohorts.length === 0 ? <p className="muted">Оплат подписок пока нет.</p> :
        <table><thead><tr><th>Месяц</th><th>Клиентов</th><th>Повторно</th><th>Активны</th><th>Выручка</th><th>LTV</th></tr></thead>
          <tbody>{d.cohorts.map((c: any) => <tr key={c.month} data-cohort={c.month}>
            <td>{c.month}</td><td>{c.customers}</td>
            <td><span className="bar" style={{width: `${c.repeat_rate}%`}}/>{c.repeat_rate}%</td>
            <td><span className="bar" style={{width: `${c.active_rate}%`}}/>{c.active_rate}%</td>
            <td>{c.revenue} {cur}</td><td>{c.ltv} {cur}</td></tr>)}</tbody></table>}
    </div>
    <div className="grid2">
      <div className="card">
        <h3>Почему отменяют (90 дней)</h3>
        <p className="muted">Ответ на вопрос при отмене автопродления в кабинете и Mini App.</p>
        {(d.cancel_reasons || []).length === 0 && <p className="muted">Ответов пока нет.</p>}
        {(d.cancel_reasons || []).map((r: any) => <div className="reason-row" key={r.reason}>
          <span>{r.label}</span><span className="bar" style={{width: `${Math.round(r.count * 100 / maxReason)}%`}}/><b>{r.count}</b></div>)}
      </div>
      <div className="card">
        <h3>Последние комментарии</h3>
        {(d.recent_comments || []).length === 0 && <p className="muted">Комментариев пока нет.</p>}
        {(d.recent_comments || []).map((c: any, i: number) => <p key={i}><b>{c.reason}</b> · <span className="muted">{when(c.created_at)}</span><br/>{c.comment}</p>)}
      </div>
    </div>
  </div>;
}

/** «Тарифы и оплата → Семейные подписки»: owners, members and whether each member reached Remnawave. */
export function FamilyGroups({d}: {d: any}) {
  const rows: any[] = Array.isArray(d) ? d : [];
  return <div className="card">
    <h3>Семейные подписки</h3>
    <p className="muted">Владелец тарифа с местами в семье приглашает близких ссылкой из кабинета или Mini App. Каждый участник получает свою учётную запись Remnawave с тем же сроком, трафиком и устройствами; срок следует за подпиской владельца (проверка каждые 5 минут). Места задаются в «Тарифах».</p>
    {rows.length === 0 ? <p className="muted">Семей пока нет.</p> :
      <table><thead><tr><th>Семья</th><th>Владелец</th><th>Подписка</th><th>Участники</th><th>Создана</th></tr></thead>
        <tbody>{rows.map((g) => <tr key={g.id} data-family={g.id}>
          <td>#{g.id}</td><td>{g.owner_user_id}</td><td>{g.subscription_id}</td>
          <td>{g.members.length === 0 ? "—" : g.members.map((m: any) => <div key={m.id}>{`клиент ${m.user_id} · ${m.status === "active" ? "в семье" : "удалён"} · ${m.error ? `ошибка: ${m.error}` : m.synced_at ? `синхронизирован ${when(m.synced_at)}` : "ожидает синхронизации"}`}</div>)}</td>
          <td>{when(g.created_at)}</td></tr>)}</tbody></table>}
  </div>;
}
