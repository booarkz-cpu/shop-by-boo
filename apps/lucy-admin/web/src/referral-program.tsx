import React,{useEffect,useState} from "react";
export function ReferralProgram({request,toast}:{request:(path:string,options?:RequestInit)=>Promise<any>;toast:(message:string)=>void}) {
 const [rates,setRates]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 useEffect(()=>{request("/api/admin/referrals/program").then(d=>setRates(d.percentages.join(", "))).catch(e=>setError(e.message))},[request]);
 async function save(e:React.FormEvent){e.preventDefault();if(busy)return;setBusy(true);setError("");try{const percentages=rates.split(",").map(x=>x.trim());const d=await request("/api/admin/referrals/program",{method:"PUT",body:JSON.stringify({percentages})});setRates(d.percentages.join(", "));toast("Условия сохранены для новых заказов")}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <div className="card"><h3>Многоуровневые рефералы</h3>{error&&<div role="alert" className="error">{error}</div>}<form onSubmit={save}><label>Проценты уровней через запятую<input required value={rates} onChange={e=>setRates(e.target.value)} placeholder="10, 5, 2"/></label><p>От одного до пяти уровней, суммарно до 100%. Условия фиксируются при создании заказа. Возврат отменяет все его начисления.</p><button disabled={busy||!rates}>Сохранить условия</button></form></div>
}
