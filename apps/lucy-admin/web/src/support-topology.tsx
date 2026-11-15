import {SelectField} from "./components/select-field";
import React, {useState} from 'react';

export function SupportTopology({ticket, thread, request, onComplete}:{ticket:any;thread:any;
  request:(p:string,o?:RequestInit)=>Promise<any>;onComplete:()=>void}) {
  const [kind,setKind]=useState('merge'),[target,setTarget]=useState(''),[subject,setSubject]=useState('');
  const [ids,setIds]=useState<number[]>([]),[preview,setPreview]=useState<any>(null);
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const [key,setKey]=useState('');
  const payload={kind,source_id:ticket.id,target_id:kind==='merge'?Number(target)||null:null,
    subject:kind==='split'?subject:'',message_ids:kind==='split'?ids:[]};
  function changed(){setPreview(null);setKey('');setMessage('')}
  async function inspect(){setBusy(true);setMessage('');try{
    const result=await request('/api/admin/support/topology/preview',{method:'POST',body:JSON.stringify(payload)});
    setPreview(result);setKey(crypto.randomUUID());
  }catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
  async function apply(){setBusy(true);setMessage('');try{
    const result=await request('/api/admin/support/topology/apply',{method:'POST',
      body:JSON.stringify({...payload,fingerprint:preview.fingerprint}),headers:{'Idempotency-Key':key}});
    setMessage(`Готово. Итоговое обращение #${result.target_id}`);setPreview(null);onComplete();
  }catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
  return <details><summary>Объединить или разделить обращение</summary>
    <p>Можно перемещать историю только внутри одного клиентского аккаунта. Вложения сохраняют ID. Перед применением проверьте preview.</p>
    <label>Операция<SelectField value={kind} disabled={busy} onChange={e=>{setKind(e.target.value);changed()}}>
      <option value="merge">Объединить в другое обращение</option><option value="split">Выделить сообщения в новое</option></SelectField></label>
    {kind==='merge'?<label>Номер итогового обращения<input type="number" min={1} value={target} disabled={busy} onChange={e=>{setTarget(e.target.value);changed()}}/></label>:<>
      <label>Тема нового обращения<input maxLength={255} value={subject} disabled={busy} onChange={e=>{setSubject(e.target.value);changed()}}/></label>
      <p>Выберите сообщения из загруженной истории; при необходимости загрузите следующую страницу.</p>
      {(thread?.messages||[]).filter((m:any)=>m.id>0).map((m:any)=><label key={m.id}>
        <input type="checkbox" checked={ids.includes(m.id)} disabled={busy} onChange={e=>{setIds(e.target.checked?[...ids,m.id]:ids.filter(x=>x!==m.id));changed()}}/>
        #{m.id} · {m.role==='admin'?'Поддержка':'Клиент'} · {m.body.slice(0,120)}</label>)}
    </>}
    <button type="button" disabled={busy} onClick={inspect}>Показать preview</button>
    {preview&&<div role="status"><p>Клиент #{preview.user_id}. Будут перемещены сообщения: {preview.moving_messages.join(', ')||'нет'}; вложения: {preview.moving_attachments.length}.</p>
      {preview.initial_message_copied&&<p>Первое сообщение исходного обращения также будет сохранено. Исходное обращение станет архивным.</p>}
      <button type="button" disabled={busy} onClick={apply}>Применить проверенную операцию</button></div>}
    {message&&<p role="status">{message}</p>}
  </details>;
}
