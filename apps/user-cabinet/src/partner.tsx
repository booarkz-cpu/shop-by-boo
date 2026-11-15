import React, {useEffect, useRef, useState} from 'react';

export function PartnerPortal({request}:{request:(p:string,o?:RequestInit)=>Promise<any>}) {
  const [data,setData]=useState<any>(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const [amount,setAmount]=useState(''),[destination,setDestination]=useState('');
  const retry=useRef<{body:string;key:string}|null>(null);
  async function load(){try{setData(await request('/api/me/partner'));setMessage('')}catch(e:any){setMessage(e.status===404?'Партнёрский кабинет не подключён. Обратитесь к оператору магазина.':e.message)}}
  useEffect(()=>{load()},[request]);
  async function withdraw(e:React.FormEvent){e.preventDefault();setBusy(true);try{
    const body=JSON.stringify({amount,destination});if(retry.current?.body!==body)retry.current={body,key:crypto.randomUUID()};
    await request('/api/me/partner/withdrawals',{method:'POST',body,headers:{'Idempotency-Key':retry.current!.key}});
    retry.current=null;setAmount('');setDestination('');await load();setMessage('Заявка сохранена; сумма зарезервирована. Выплату проведёт оператор.');
  }catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
  return <section className="stack"><h2>Партнёрский кабинет</h2>{message&&<p role="status">{message}</p>}
    {data&&<><h3>{data.name}</h3><p>Комиссия {data.commission_percent}% · Доступно {data.balance} {data.currency} · {data.enabled?'Активен':'Отключён'}</p>
      <label className="field">Партнёрская ссылка<input readOnly value={data.link}/></label>
      <p>Начисления появляются после выдачи подписки. Условия фиксируются при заказе; возврат отменяет комиссию. Покупки партнёра самому себе не учитываются.</p>
      <form className="workspace-form" onSubmit={withdraw}><label className="field">Сумма<input required type="number" min={1} max={10000000} step="0.01" value={amount} onChange={e=>setAmount(e.target.value)}/></label>
        <label className="field">Реквизиты<input required minLength={3} maxLength={255} value={destination} onChange={e=>setDestination(e.target.value)}/></label>
        <button className="btn-primary" disabled={busy||!data.enabled}>Запросить выплату</button></form>
      <h3>Последние начисления</h3><div className="table-wrap"><table><thead><tr><th>Дата</th><th>Сумма</th><th>Ставка</th><th>Состояние</th></tr></thead><tbody>{data.commissions.map((x:any)=><tr key={x.id}><td>{new Date(x.created_at).toLocaleString()}</td><td>{x.amount} {x.currency}</td><td>{x.percent}%</td><td>{x.status==='credited'?'Начислено':'Отменено возвратом'}</td></tr>)}</tbody></table></div>
      <h3>Заявки на выплату</h3><div className="table-wrap"><table><thead><tr><th>№</th><th>Сумма</th><th>Состояние</th><th>Номер выплаты</th></tr></thead><tbody>{data.withdrawals.map((x:any)=><tr key={x.id}><td>{x.id}</td><td>{x.amount} {x.currency}</td><td>{({requested:'Запрошена',approved:'Одобрена',paid:'Выплачена',rejected:'Отклонена'} as Record<string,string>)[x.status]||x.status}</td><td>{x.reference||'—'}</td></tr>)}</tbody></table></div>
    </>}
  </section>;
}
