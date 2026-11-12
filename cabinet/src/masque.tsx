import React, {useEffect, useState} from "react";

/** v28.130.0: the customer's own MASQUE subscription — a link per subscription, copy, QR and a short how-to. */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Item = {subscription_id: number; name: string; url: string};

/** «MASQUE» on the «Подключение» page. Renders nothing when the shop does not hand MASQUE to this customer. */
export function MasqueLinks({request}: {request: RequestFn}) {
  const [items, setItems] = useState<Item[]>([]);
  const [qr, setQr] = useState<{title: string; png: string} | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    request("/api/me/masque").then((d) => setItems(d?.available ? d.items : [])).catch(() => setItems([]));
  }, [request]);
  if (!items.length) return null;
  const copy = (url: string) => navigator.clipboard?.writeText(url).then(() => setMsg("Ссылка скопирована"), () => setMsg("Не удалось скопировать"));
  const showQr = async (item: Item) => {
    try {
      setQr({title: item.name, png: (await request(`/api/me/masque/${item.subscription_id}/qr`)).png});
    } catch (e: any) {
      setMsg(e.message || "QR-код недоступен");
    }
  };
  const reissue = async (item: Item) => {
    if (!window.confirm(`Выдать новую ссылку MASQUE для «${item.name}»? Старая перестанет работать на всех устройствах.`)) return;
    try {
      const next = await request(`/api/me/masque/${item.subscription_id}/reissue`, {method: "POST"});
      setItems((list) => list.map((i) => (i.subscription_id === item.subscription_id ? {...i, url: next.url} : i)));
      setQr(null);
      setMsg("Новая ссылка готова. Добавьте её в клиент заново.");
    } catch (e: any) {
      setMsg(e.message || "Не удалось выдать новую ссылку");
    }
  };
  return (
    <section className="form-card" aria-label="MASQUE">
      <h3>MASQUE</h3>
      <p className="muted">Отдельная подписка для протокола MASQUE: туннель поверх обычного HTTPS. Пригодится, когда остальные способы не подключаются.</p>
      {msg ? <p className="workspace-alert" role="status">{msg}</p> : null}
      <ul className="key-list">
        {items.map((item) => (
          <li key={item.subscription_id}>
            <span><b>{item.name}</b> <small className="muted">MASQUE · HTTP/2</small></span>
            <span className="btn-row">
              <button type="button" className="btn-ghost" onClick={() => copy(item.url)} aria-label={`Копировать ссылку MASQUE: ${item.name}`}>Копировать</button>
              <button type="button" className="btn-ghost" onClick={() => showQr(item)} aria-label={`QR-код MASQUE: ${item.name}`}>QR</button>
              <button type="button" className="btn-ghost" onClick={() => reissue(item)} aria-label={`Новая ссылка MASQUE: ${item.name}`}>Новая ссылка</button>
            </span>
          </li>
        ))}
      </ul>
      {qr ? (
        <figure className="connection-qr-wrap">
          <img className="connection-qr" src={qr.png} alt={`QR-код MASQUE: ${qr.title}`} width={196} height={196} />
          <figcaption>{qr.title}</figcaption>
          <button type="button" className="btn-ghost" onClick={() => setQr(null)}>Скрыть</button>
        </figure>
      ) : null}
      <ol className="muted">
        <li>Нужен клиент с ядром Xray 26.9.30 или новее и подписками в формате JSON.</li>
        <li>Добавьте ссылку как подписку: в ней по одной конфигурации на каждый сервер.</li>
        <li>Ссылка личная. Если она попала к посторонним, нажмите «Новая ссылка»: старая перестанет работать.</li>
      </ol>
    </section>
  );
}
