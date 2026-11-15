import React, {useState} from "react";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

/** The name of the saved file: «corgi-lusi-my-data-2026-11-15.json». */
export const exportName = (now = new Date()) => `corgi-lusi-my-data-${now.toISOString().slice(0, 10)}.json`;

/**
 * v28.159.0 (REQ-SHOP-0017): «Мои данные» — the customer downloads everything the shop keeps about them
 * (GET /api/me/privacy/export) and can delete the account (DELETE /api/me/privacy/account). Deletion asks for
 * the word «УДАЛИТЬ»; the server refuses while a subscription is active or a purchase is not finished, and says why.
 */
export function MyData({request, onDeleted, save = saveFile}: {request: RequestFn; onDeleted: () => void; save?: (name: string, text: string) => void}) {
  const [busy, setBusy] = useState<"" | "export" | "delete">("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [word, setWord] = useState("");

  async function download() {
    setBusy("export"); setError(""); setStatus("");
    try {
      const data = await request("/api/me/privacy/export");
      save(exportName(), JSON.stringify(data, null, 2));
      setStatus("Файл с вашими данными сохранён");
    } catch (e: any) {
      setError(e.message || "Не удалось выгрузить данные");
    } finally { setBusy(""); }
  }

  async function remove() {
    if (word.trim() !== "УДАЛИТЬ") { setError("Чтобы удалить учётную запись, впишите слово УДАЛИТЬ"); return; }
    setBusy("delete"); setError(""); setStatus("");
    try {
      await request("/api/me/privacy/account", {method: "DELETE"});
      onDeleted();
    } catch (e: any) {
      setError(e.message || "Не удалось удалить учётную запись");
    } finally { setBusy(""); }
  }

  return <div className="form-card stack" data-my-data>
    <h3>Мои данные</h3>
    <p className="section-sub">Файл JSON со всем, что магазин хранит о вас: профиль и способы входа, подписки, платежи, обращения в поддержку, участие в розыгрышах и опросах.</p>
    <button type="button" className="btn-ghost" disabled={!!busy} onClick={download}>{busy === "export" ? "Готовим файл…" : "Скачать мои данные"}</button>
    {!confirming && <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => { setConfirming(true); setError(""); }}>Удалить учётную запись</button>}
    {confirming && <div className="stack" data-delete-account>
      <p className="section-sub">Способы входа, почта и имя будут стёрты, подписка в VPN отключена, войти снова будет нельзя. Платежи остаются в учёте магазина без ваших данных. Пока подписка действует или покупка не завершена, удаление не выполнится.</p>
      <label className="field">Впишите УДАЛИТЬ<input value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off"/></label>
      <div className="btn-row">
        <button type="button" className="btn-primary" disabled={!!busy} onClick={remove}>{busy === "delete" ? "Удаляем…" : "Удалить навсегда"}</button>
        <button type="button" className="btn-ghost" disabled={!!busy} onClick={() => { setConfirming(false); setWord(""); setError(""); }}>Отмена</button>
      </div>
    </div>}
    {status && <p className="section-sub" role="status">{status}</p>}
    {error && <p className="section-sub" role="alert">{error}</p>}
  </div>;
}

function saveFile(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url; link.download = name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
