import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;
const NAMES: Record<string, string> = {yookassa: "ЮKassa", rollypay: "RollyPay", platega: "Platega", cryptobot: "CryptoBot", freekassa: "Freekassa", cloudpayments: "CloudPayments", lava: "Lava", pal24: "Pal24", mulenpay: "Mulen Pay"};

/** «Платёжные агенты → Способы оплаты»: клиент выбирает СБП, карту или крипту, у каждого способа своя очередь касс. */
export function PaymentMethods({request, toast}: {request: Request; toast: (text: string) => void}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const load = () => request("/api/admin/payments/methods").then(setData).catch(e => setError(e.message));
  useEffect(() => { load(); }, [request]);
  async function save(next: any) {
    setError("");
    try { setData({...data, ...(await request("/api/admin/payments/methods", {method: "PUT", body: JSON.stringify({enabled: next.enabled, routes: next.routes})}))}); toast("Способы оплаты сохранены"); }
    catch (e: any) { setError(e.message); }
  }
  function move(method: string, index: number, delta: number) {
    const order = [...data.routes[method]];
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    save({...data, routes: {...data.routes, [method]: order}});
  }
  if (!data) return <div className="card"><h3>Способы оплаты</h3>{error ? <p className="error">{error}</p> : <p>Загрузка…</p>}</div>;
  return (
    <div className="card">
      <h3>Способы оплаты</h3>
      <p className="muted">Включите, чтобы клиент в кабинете, Mini App и приложениях выбирал «СБП», «Банковская карта» или «Криптовалюта».
        У каждого способа своя очередь касс: если первая касса отказала или остывает, заказ уходит в следующую того же способа.
        ЮKassa сразу открывается на выбранном способе, остальные кассы показывают свою страницу. Без этого режима работает общая «Очередь касс».</p>
      {error ? <p className="error">{error}</p> : null}
      <label className="check"><input type="checkbox" checked={data.enabled} onChange={e => save({...data, enabled: e.target.checked})}/> Клиент выбирает способ оплаты</label>
      {Object.entries(data.methods as Record<string, string>).map(([method, title]) => (
        <div key={method}>
          <h4>{title}</h4>
          {(data.routes[method] || []).length === 0 ? <p className="muted">Нет касс, принимающих этот способ.</p> : (
            <table className="table"><tbody>{data.routes[method].map((p: string, i: number) => (
              <tr key={p}><td>{i + 1}. {NAMES[p] || p}</td><td>{data.configured[p] ? "ключи заданы" : "нет ключей — пропускается"}</td>
                <td><button disabled={i === 0} onClick={() => move(method, i, -1)}>↑</button> <button disabled={i === data.routes[method].length - 1} onClick={() => move(method, i, 1)}>↓</button></td></tr>
            ))}</tbody></table>
          )}
        </div>
      ))}
    </div>
  );
}
