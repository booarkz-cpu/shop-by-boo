import React, {useEffect, useState} from "react";

/** v28.38: connection keys of the subscription (copy, QR), a WireGuard / AmneziaWG config, traffic by day and server. */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
const gb = (b: number) => `${(Number(b || 0) / 1024 ** 3).toFixed(2)} ГБ`;

function copy(text: string, done: (t: string) => void) {
  navigator.clipboard?.writeText(text).then(() => done("Скопировано"), () => done("Не удалось скопировать"));
}

/** «Ключи подключения»: every server of the subscription as its own link, plus WireGuard when the shop hands it out. */
export function ConnectionKeys({request}: {request: RequestFn}) {
  const [data, setData] = useState<any>(null);
  const [qr, setQr] = useState<{title: string; png: string} | null>(null);
  const [wg, setWg] = useState<any>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { request("/api/me/subscription/keys").then(setData).catch(() => setData(null)); }, [request]);
  if (!data || (!data.keys.length && !data.wireguard)) return null;
  const showQr = async (i: number, title: string) => {
    try { setQr({title, png: (await request(`/api/me/subscription/keys/${i}/qr`)).png}); } catch (e: any) { setMsg(e.message); }
  };
  const getWg = async () => {
    try { setWg(await request("/api/me/wg-config")); } catch (e: any) { setMsg(e.message); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([wg.config], {type: "text/plain"}));
    const a = document.createElement("a"); a.href = url; a.download = wg.filename; a.click(); URL.revokeObjectURL(url);
  };
  return (
    <section className="form-card" aria-label="Ключи подключения">
      <h3>Ключи подключения</h3>
      <p className="muted">Каждый сервер отдельной ссылкой — для приложений, которые не умеют подписки.</p>
      {msg ? <p className="workspace-alert" role="status">{msg}</p> : null}
      <ul className="key-list">{data.keys.map((k: any, i: number) => <li key={i}>
        <span><b>{k.name}</b> <small className="muted">{k.protocol}</small></span>
        <span className="btn-row"><button className="btn-ghost" onClick={() => copy(k.link, setMsg)}>Копировать</button>
          <button className="btn-ghost" onClick={() => showQr(i, k.name)}>QR</button></span></li>)}</ul>
      {qr ? <figure className="connection-qr-wrap"><img className="connection-qr" src={qr.png} alt={`QR-код: ${qr.title}`} width={196} height={196}/><figcaption>{qr.title}</figcaption>
        <button className="btn-ghost" onClick={() => setQr(null)}>Скрыть</button></figure> : null}
      {data.wireguard ? <>
        <h4>WireGuard</h4>
        {!wg ? <button className="btn-primary" onClick={getWg}>Получить конфиг WireGuard</button> : <>
          <p className="muted">{wg.name}: конфиг закреплён за этим устройством.</p>
          <div className="btn-row"><button className="btn-primary" onClick={download}>Скачать .conf</button>
            <button className="btn-ghost" onClick={() => copy(wg.config, setMsg)}>Копировать</button>
            <button className="btn-ghost" onClick={async () => { try { const r = await request("/api/me/wg-config/qr"); setQr({title: r.name, png: r.png}); } catch (e: any) { setMsg(e.message); } }}>QR</button></div>
        </>}
      </> : null}
    </section>
  );
}

/** «Трафик по дням»: bars for 7 / 30 / 90 days and the share of each server. */
export function MyTraffic({request}: {request: RequestFn}) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  useEffect(() => { request(`/api/me/traffic?days=${days}`).then(setData).catch(() => setData(null)); }, [request, days]);
  if (!data || !data.days.length) return null;
  const max = Math.max(1, ...data.days.map((x: any) => x.bytes));
  return (
    <section className="form-card" aria-label="Трафик по дням">
      <h3>Трафик по дням</h3>
      <div className="btn-row">{[7, 30, 90].map((d) => <button key={d} className={d === days ? "btn-primary" : "btn-ghost"} onClick={() => setDays(d)}>{d} дн.</button>)}</div>
      <p>Всего {gb(data.total_bytes)} · в среднем {gb(data.per_day_bytes)} в день{data.peak ? ` · пик ${data.peak.day.slice(5)} — ${gb(data.peak.bytes)}` : ""}</p>
      <div className="traffic-bars" role="img" aria-label="Трафик по дням">{data.days.map((x: any) =>
        <span key={x.day} title={`${x.day}: ${gb(x.bytes)}`} style={{height: `${Math.max(3, (x.bytes * 100) / max)}%`}}/>)}</div>
      {data.nodes.length ? <ul className="key-list">{data.nodes.map((n: any) => <li key={n.name}><span>{n.name}</span><span>{gb(n.bytes)} · {n.share}%</span></li>)}</ul> : null}
    </section>
  );
}
