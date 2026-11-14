import React, {useEffect, useState} from "react";

/** v28.52 «Оценка поддержки и NPS»: звёзды под отвеченными обращениями и вопрос «порекомендуете ли нас». */
type RequestFn = (path: string, options?: RequestInit) => Promise<any>;

export function FeedbackPrompt({request}: {request: RequestFn}) {
  const [f, setF] = useState<any>(null);
  const [comment, setComment] = useState("");
  const [done, setDone] = useState("");
  const load = () => request("/api/me/feedback").then(setF).catch(() => setF(null));
  useEffect(() => { load(); }, [request]);
  async function send(path: string, body: any) {
    try { await request(path, {method: "POST", body: JSON.stringify({...body, comment: comment.trim()})}); setDone("Спасибо за оценку!"); setComment(""); load(); }
    catch (e: any) { setDone(e.message || "Не получилось сохранить оценку"); }
  }
  if (!f || (!f.tickets?.length && !f.nps)) return done ? <p className="section-sub">{done}</p> : null;
  return (
    <div className="workspace-form feedback-prompt">
      {f.tickets?.slice(0, 2).map((t: any) => <div key={t.id}>
        <h3>Оцените ответ по обращению #{t.id}</h3>
        <p className="section-sub">{t.subject}</p>
        <div className="btn-row rating-row">{[1, 2, 3, 4, 5].map(s => <button key={s} className="btn-ghost" aria-label={`Оценка ${s} из 5`} onClick={() => send("/api/me/feedback/csat", {ticket_id: t.id, score: s})}>{"★".repeat(s)}</button>)}</div>
      </div>)}
      {f.nps && <div>
        <h3>Порекомендуете нас другу?</h3>
        <p className="section-sub">0 — точно нет, 10 — обязательно.</p>
        <div className="btn-row rating-row">{Array.from({length: 11}, (_, s) => <button key={s} className="btn-ghost" aria-label={`Оценка ${s} из 10`} onClick={() => send("/api/me/feedback/nps", {score: s})}>{s}</button>)}</div>
      </div>}
      <label className="field">Комментарий (необязательно)<textarea maxLength={1000} value={comment} onChange={e => setComment(e.target.value)}/></label>
      {done && <p className="section-sub">{done}</p>}
    </div>
  );
}
