import React, {useEffect, useState} from "react";
type RequestFn=(path:string,options?:RequestInit)=>Promise<any>;
export type AccountLink={kind:"request"|"password-reset"|"verify-email";token:string;guest?:boolean};
export function accountLink():AccountLink|null {
 const [kind,query]=location.hash.slice(1).split("?");
 if(kind!=="password-reset"&&kind!=="verify-email")return null;
 const params=new URLSearchParams(query||"");
 return {kind,token:params.get("token")||"",guest:params.get("guest")==="1"};
}
export function AccountRecovery({link,request,onClose}:{link:AccountLink;request:RequestFn;onClose:(reset?:boolean)=>void}) {
 const [email,setEmail]=useState(""),[password,setPassword]=useState(""),[repeat,setRepeat]=useState(""),[busy,setBusy]=useState(false),[message,setMessage]=useState(""),[error,setError]=useState("");
 const reset=link.kind==="password-reset",verify=link.kind==="verify-email";
 async function submit(e:React.FormEvent){
  e.preventDefault();setError("");setMessage("");
  if(reset&&password!==repeat){setError("Пароли не совпадают");return;}
  if((reset||verify)&&!link.token){setError("В ссылке нет кода. Запросите новое письмо.");return;}
  setBusy(true);
  try{
   // A guest purchase (guest_checkout.py) sets the first password through the same page.
   const result=await request(verify?"/api/auth/email/verification/confirm":reset?(link.guest?"/api/auth/guest/setup":"/api/auth/password/reset/confirm"):"/api/auth/password/reset/request",
    {method:"POST",body:JSON.stringify(verify?{token:link.token}:reset?{token:link.token,password}:{email})});
   setPassword("");setRepeat("");setMessage(result.message||"Готово");
  }catch(e:any){setError(e.message||"Не удалось выполнить действие");}finally{setBusy(false);}
 }
 return <section className="form-card stack" aria-label="Восстановление доступа"><h2>{verify?"Подтвердить email":reset?"Новый пароль":"Восстановить пароль"}</h2>
  <p>{verify?"Подтвердите почту для своего аккаунта.":reset?"После изменения пароля все прежние сессии будут отозваны.":"Укажите почту, использованную при регистрации с паролем."}</p>
  {error&&<p role="alert" className="workspace-alert">{error}</p>}{message&&<p role="status" className="workspace-alert">{message}</p>}
  {!message&&<form className="stack" onSubmit={submit}>
   {!reset&&!verify&&<label className="field">Email<input type="email" autoComplete="email" required maxLength={320} value={email} onChange={e=>setEmail(e.target.value)}/></label>}
   {reset&&<><label className="field">Новый пароль<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label><label className="field">Повторите пароль<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={repeat} onChange={e=>setRepeat(e.target.value)}/></label></>}
   <button className="btn-primary" disabled={busy}>{verify?"Подтвердить почту":reset?"Изменить пароль":"Отправить письмо"}</button>
  </form>}
  <button type="button" className="btn-ghost" disabled={busy} onClick={()=>onClose(reset&&!!message)}>Вернуться в кабинет</button>
 </section>;
}
export function AccountSecurity({request,onPasswordChanged}:{request:RequestFn;onPasswordChanged:()=>void}) {
 const [status,setStatus]=useState<any>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState(""),[current,setCurrent]=useState(""),[password,setPassword]=useState(""),[repeat,setRepeat]=useState("");
 useEffect(()=>{let live=true;request("/api/me/email").then(s=>{if(live)setStatus(s)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[request]);
 async function verify(){setBusy(true);setError("");try{const r=await request("/api/me/email/verification/request",{method:"POST",body:"{}"});setNotice(r.message);}catch(e:any){setError(e.message);}finally{setBusy(false)}}
 async function change(e:React.FormEvent){e.preventDefault();setError("");if(password!==repeat){setError("Пароли не совпадают");return;}setBusy(true);
  try{await request("/api/me/password/change",{method:"POST",body:JSON.stringify({current_password:current,password})});setCurrent("");setPassword("");setRepeat("");onPasswordChanged();}catch(e:any){setError(e.message);}finally{setBusy(false)}}
 return <section className="stack"><h3>Почта и пароль</h3>{error&&<p className="workspace-alert" role="alert">{error}</p>}{notice&&<p className="workspace-alert" role="status">{notice}</p>}
  {status&&<><p>{status.email||"Почта не указана"} · {status.verified?"Подтверждена":"Не подтверждена"}</p>{status.email&&!status.verified&&<button className="btn-ghost" disabled={busy||!status.mail_enabled} onClick={verify}>Подтвердить email</button>}
  {status.password_enabled&&<form className="workspace-form" onSubmit={change}><label className="field">Текущий пароль<input type="password" autoComplete="current-password" required minLength={8} maxLength={128} value={current} onChange={e=>setCurrent(e.target.value)}/></label><label className="field">Новый пароль<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label><label className="field">Повторите пароль<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={repeat} onChange={e=>setRepeat(e.target.value)}/></label><p>После смены пароля войдите заново на всех устройствах.</p><button className="btn-primary" disabled={busy}>Изменить пароль</button></form>}</>}
 </section>;
}
