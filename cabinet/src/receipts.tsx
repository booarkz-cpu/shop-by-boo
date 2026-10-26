import React, {useEffect, useState} from "react";

type Request = (path: string, options?: RequestInit) => Promise<any>;

/** Receipts of the customer's payments sent to the tax service (GET /api/me/receipts). */
export function MyReceipts({request}: {request: Request}) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { request("/api/me/receipts").then((r) => setRows(Array.isArray(r) ? r : [])).catch(() => setRows([])); }, [request]);
  if (!rows || rows.length === 0) return null;
  return <div className="workspace-receipts" data-receipts><h3>Чеки</h3>
    <ul>{rows.map((r, i) => <li key={i}>
      <span>{new Date(r.created_at).toLocaleDateString()} · {r.kind === "refund" ? "возврат" : "оплата"} · {r.amount} ₽ · {r.name}</span>{" "}
      {r.receipt_url ? <a href={r.receipt_url} target="_blank" rel="noreferrer">Открыть чек</a> : <span className="muted">чек отправлен на почту</span>}
    </li>)}</ul></div>;
}
