import {AttachmentUpload,AttachmentFiles} from "./support-attachments";
import React, {useEffect, useRef, useState} from "react";

export function SupportConversation({ticketId,request,onStatusChange}:{key?:string|number;ticketId:number;request:(path:string,options?:RequestInit)=>Promise<any>;onStatusChange?:(status:string)=>void}) {
 const [thread,setThread]=useState<any>(null),[body,setBody]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false),[notice,setNotice]=useState("");
 const [attachments,setAttachments]=useState<any[]>([]),[uploadBusy,setUploadBusy]=useState(false);
 const serial=useRef(0),locked=useRef(false),retry=useRef<{body:string;fingerprint:string;key:string}|null>(null);
 const path=`/api/me/support/tickets/${ticketId}/messages`;
 async function load(more=false) {
  const n=++serial.current;setError("");setBusy(true);
  try {const result=await request(path+(more?`?after=${thread.next_cursor}`:""));if(n===serial.current){setThread(more?{...result,messages:[...thread.messages,...result.messages]}:result);onStatusChange?.(result.status)}}
  catch(e:any){if(n===serial.current)setError(e.message)}finally{if(n===serial.current)setBusy(false)}
 }
 useEffect(()=>{load();return()=>{serial.current++}},[ticketId]);
 async function send(e:React.FormEvent) {
  e.preventDefault();if(locked.current||uploadBusy||!body.trim())return;locked.current=true;setBusy(true);setError("");setNotice("");
  const submitted=body.trim(),ids=attachments.map(x=>x.id),fingerprint=JSON.stringify({body:submitted,ids});if(retry.current?.fingerprint!==fingerprint)retry.current={body:submitted,fingerprint,key:crypto.randomUUID()};
  try {await request(path,{method:"POST",body:JSON.stringify({message:submitted,attachment_ids:ids}),headers:{"Idempotency-Key":retry.current!.key}});retry.current=null;setAttachments([]);setBody("");setNotice("Сообщение отправлено");await load()}
  catch(e:any){setError(e.message)}finally{locked.current=false;setBusy(false)}
 }
 return <section className="support-conversation" aria-label={`Переписка по обращению ${ticketId}`}>
  {error&&<div className="workspace-alert error" role="alert">{error}<button className="btn-ghost" disabled={busy} onClick={()=>load()}>Повторить загрузку</button></div>}
  {notice&&<p role="status">{notice}</p>}
  {!thread&&!error&&<p role="status">Загрузка переписки…</p>}
  {thread&&<><p>{thread.status==="open"?"Ожидает ответа поддержки":"Ответ получен"}</p><div className="support-messages">{thread.messages.map((m:any)=><div className={`support-message ${m.role}`} key={m.id}><strong>{m.role==="admin"?"Поддержка":"Вы"}</strong><small>{new Date(m.created_at).toLocaleString()}</small><p>{m.body}</p><AttachmentFiles files={m.attachments} request={request}/></div>)}</div>{thread.next_cursor!==null&&<button className="btn-ghost" disabled={busy} onClick={()=>load(true)}>Загрузить следующие сообщения</button>}</>}
  {thread?.merged_into_id?<p role="status">Обращение объединено с #{thread.merged_into_id}. Вернитесь к списку и откройте итоговое обращение.</p>:<form className="workspace-form" onSubmit={send}><label className="field">Ответ в обращение #{ticketId}<textarea required maxLength={5000} value={body} onChange={e=>setBody(e.target.value)} disabled={busy}/></label><AttachmentUpload ticketId={ticketId} request={request} value={attachments} onChange={setAttachments} onBusyChange={setUploadBusy} disabled={busy}/><p className="section-sub">Ваш ответ снова откроет обращение. Переписка сохранится.</p><button className="btn-primary" disabled={busy||uploadBusy||!thread||!body.trim()}>{busy?"Отправка…":"Отправить сообщение"}</button></form>}
 </section>;
}
