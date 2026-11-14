import React, {useEffect, useState} from 'react';

export function Partners({request}:{request:(p:string,o?:RequestInit)=>Promise<any>}) {
  const [rows,setRows]=useState<any[]>([]),[withdrawals,setWithdrawals]=useState<any[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [name,setName]=useState(''),[slug,setSlug]=useState(''),[owner,setOwner]=useState(''),[percent,setPercent]=useState('20');
  const [key,setKey]=useState(''),[reference,setReference]=useState('');
  async function load(){try{const [r,w]=await Promise.all([request('/api/admin/marketplace/resellers'),request('/api/admin/marketplace/withdrawals')]);setRows(r);setWithdrawals(w)}catch(e:any){setError(e.message)}}
  useEffect(()=>{load()},[request]);
  async function act(path:string,body:any){setBusy(true);setError('');try{const result=await request(path,{method:'POST',body:JSON.stringify(body)});await load();return result}catch(e:any){setError(e.message)}finally{setBusy(false)}}
  return <section className="card"><h3>Партнёры и выплаты</h3>{error&&<p role="alert">{error}</p>}
    <label>Название<input value={name} maxLength={255} onChange={e=>setName(e.target.value)}/></label>
    <label>Slug<input value={slug} maxLength={64} pattern="[a-z0-9-]+" onChange={e=>setSlug(e.target.value)}/></label>
    <label>ID аккаунта владельца<input type="number" min={1} value={owner} onChange={e=>setOwner(e.target.value)}/></label>
    <label>Комиссия %<input type="number" min={0} max={100} step="0.01" value={percent} onChange={e=>setPercent(e.target.value)}/></label>
    <button type="button" disabled={busy||!name||!slug||!owner} onClick={async()=>{const r=await act('/api/admin/marketplace/resellers',{name,slug,owner_user_id:Number(owner),commission_percent:percent});if(r)setKey(r.api_key)}}>Создать партнёра</button>
    {key&&<label>API-ключ — сохраните сейчас<input readOnly value={key}/><button type="button" onClick={()=>setKey('')}>Скрыть</button></label>}
    <table><thead><tr><th>Партнёр</th><th>Владелец</th><th>Комиссия</th><th>Баланс</th><th>Состояние</th></tr></thead><tbody>{rows.map(x=><tr key={x.id}><td>{x.name} / {x.slug}</td><td>{x.owner_user_id||'API only'}</td><td>{x.commission_percent}%</td><td>{x.balance}</td><td>{x.enabled?'Активен':'Отключён'}</td></tr>)}</tbody></table>
    <label>Номер фактической выплаты<input maxLength={255} value={reference} onChange={e=>setReference(e.target.value)}/></label>
    <p>«Выплачено» фиксирует уже выполненный внешний перевод. Автоматического банковского перевода нет.</p>
    <table><thead><tr><th>№ / партнёр</th><th>Сумма</th><th>Реквизиты</th><th>Состояние</th><th>Действия</th></tr></thead><tbody>{withdrawals.map(x=><tr key={x.id}><td>{x.id} / {x.reseller_id}</td><td>{x.amount} {x.currency}</td><td>{x.destination}</td><td>{x.status}</td><td>{['requested','approved'].includes(x.status)&&<>
      {x.status==='requested'&&<button type="button" disabled={busy} onClick={()=>act(`/api/admin/marketplace/withdrawals/${x.id}/decision`,{status:'approved'})}>Одобрить</button>}
      <button type="button" disabled={busy} onClick={()=>act(`/api/admin/marketplace/withdrawals/${x.id}/decision`,{status:'rejected'})}>Отклонить</button>
      {x.status==='approved'&&<button type="button" disabled={busy||!reference.trim()} onClick={()=>act(`/api/admin/marketplace/withdrawals/${x.id}/decision`,{status:'paid',reference})}>Выплачено</button>}
    </>}</td></tr>)}</tbody></table>
  </section>;
}
