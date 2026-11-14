import React, {useEffect, useRef, useState} from 'react';
type RequestFn = (path:string, options?:RequestInit)=>Promise<any>;
const labels:Record<string,string> = {open:'Участие открыто',scheduled:'Скоро',ended:'Участие завершено',full:'Лимит участников',closed:'Акция закрыта',drawn:'Розыгрыш завершён',entered:'Вы участвуете',won:'Вы выиграли',lost:'Без награды',ineligible:'Участие недоступно'};

export function Giveaways({request,reload}:{request:RequestFn;reload:()=>Promise<void>}) {
 const [rows,setRows]=useState<any[]>([]),[next,setNext]=useState<number|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const serial=useRef(0);
 async function load(after=0) {const n=++serial.current;setLoading(true);setError('');try {const d=await request('/api/me/giveaways?after='+after);if(n===serial.current){setRows(prev=>after?[...prev,...d.items]:d.items);setNext(d.next_after)}} catch(e:any){if(n===serial.current)setError(e.message)} finally {if(n===serial.current)setLoading(false)}}
 useEffect(()=>{load();return()=>{serial.current++}},[request]);
 return <section className="stack"><h2 className="section-title">Конкурсы и призы</h2><p>Участие бесплатно, один раз на аккаунт. Награда зачисляется на внутренний баланс магазина. Для участия подтвердите email.</p>
 {error&&<p role="alert" className="workspace-alert">{error}</p>}{!loading&&!rows.length&&<p>Опубликованных акций пока нет.</p>}
 {rows.map(row=><GiveawayCard key={row.id} row={row} request={request} onDone={async updated=>{setRows(prev=>prev.map(r=>r.id===updated.id?updated:r));await reload().catch(()=>{})}}/>)}
 {loading&&<p role="status">Загрузка…</p>}<button className="btn-ghost" disabled={loading} onClick={()=>load()}>Обновить результаты</button>{next!=null&&<button className="btn-ghost" disabled={loading} onClick={()=>load(next)}>Показать ещё</button>}</section>
}

export function GiveawayCard({row,request,onDone}:{key?:number;row:any;request:RequestFn;onDone:(row:any)=>Promise<void>}) {
 const [busy,setBusy]=useState(false),[error,setError]=useState('');const locked=useRef(false);
 async function enter(){if(locked.current)return;locked.current=true;setBusy(true);setError('');try{const updated=await request(`/api/me/giveaways/${row.id}/enter`,{method:'POST'});await onDone(updated)}catch(e:any){setError(e.message)}finally{locked.current=false;setBusy(false)}}
 const weights=row.prizes.reduce((total:number,p:any)=>total+p.weight,0);
 return <article className="form-card stack"><h3>{row.title}</h3><p style={{whiteSpace:'pre-wrap'}}>{row.description}</p><p>{labels[row.phase]||row.phase} · {row.entry_count}/{row.max_entries} участников</p><p>До {new Date(row.ends_at).toLocaleString()}{row.require_subscription?' · нужна действующая подписка':''}</p>
 {row.kind==='contest'?<p>Победителей: не более {row.winners_count}. Награда каждому: {row.prizes[0].amount} {row.currency}. После окончания оператор проведёт один розыгрыш среди доступных аккаунтов.</p>:<><h4>Колесо призов</h4>{row.prizes.map((p:any,i:number)=><p key={i}>{p.amount} {row.currency} · вероятность {(100*p.weight/weights).toFixed(2)}%</p>)}<p>Награду определяет сервер. Повтор запроса возвращает тот же результат.</p></>}
 {row.my_entry&&<p role="status">{labels[row.my_entry.outcome]||row.my_entry.outcome}{Number(row.my_entry.reward_amount)>0?` · начислено ${row.my_entry.reward_amount} ${row.currency}`:''}</p>}
 {error&&<p role="alert" className="workspace-alert">{error}</p>}{!row.my_entry&&row.phase==='open'&&<button className="btn-primary" disabled={busy} onClick={enter}>{busy?'Отправка…':row.kind==='wheel'?'Получить результат колеса':'Участвовать бесплатно'}</button>}</article>
}
