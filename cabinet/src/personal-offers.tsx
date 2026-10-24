import React,{useEffect,useState} from 'react';
export function PersonalOffers({request,onSelect}:{request:(path:string)=>Promise<any>;onSelect:(code:string)=>void}){
 const[rows,setRows]=useState<any[]>([]),[offset,setOffset]=useState<number|null>(0),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{let live=true;request('/api/me/offers').then(x=>{if(live){setRows(Array.isArray(x?.items)?x.items:[]);setOffset(x?.next_offset??null)}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[request]);
 async function next(){setBusy(true);setError('');try{const x=await request(`/api/me/offers?offset=${offset}`);setRows(r=>[...r,...(Array.isArray(x?.items)?x.items:[])]);setOffset(x?.next_offset??null)}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 if(!rows.length&&offset===null&&!error)return null;
 return <section className="form-card"><h2>Ваши предложения</h2>{error&&<p role="alert" className="error">{error}</p>}{rows.map(o=><article key={o.code}><h3>{o.title}</h3><p>{o.description}</p><p>Скидка: {o.value}{o.kind==='percent'?'%':''}. Итоговая цена и ограничения проверяются при оформлении выбранного тарифа.</p><button onClick={()=>onSelect(o.code)}>Применить {o.code}</button></article>)}{offset!==null&&<button disabled={busy} onClick={next}>Проверить следующие предложения</button>}</section>;
}
