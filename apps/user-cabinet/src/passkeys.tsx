import React, {useState} from 'react';

type Request = (path:string, options?:RequestInit)=>Promise<any>;
const bytes = (value:string):Uint8Array<ArrayBuffer> => {
  const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/'));
  return Uint8Array.from(raw, c=>c.charCodeAt(0));
};
const encoded = (value:ArrayBuffer):string => btoa(String.fromCharCode(...new Uint8Array(value)))
  .replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
function supported() {
  if (!window.isSecureContext || !navigator.credentials || !window.PublicKeyCredential)
    throw Error('Ключи доступа требуют HTTPS и браузер с поддержкой WebAuthn.');
}
function serialize(credential:PublicKeyCredential) {
  const response=credential.response;
  const common={id:credential.id, rawId:encoded(credential.rawId), type:credential.type,
    clientExtensionResults:credential.getClientExtensionResults()};
  if ('attestationObject' in response) {
    const attestation=response as AuthenticatorAttestationResponse;
    return {...common, response:{clientDataJSON:encoded(attestation.clientDataJSON),
      attestationObject:encoded(attestation.attestationObject), transports:attestation.getTransports?.()||[]}};
  }
  const assertion=response as AuthenticatorAssertionResponse;
  return {...common, response:{clientDataJSON:encoded(assertion.clientDataJSON),
    authenticatorData:encoded(assertion.authenticatorData), signature:encoded(assertion.signature),
    userHandle:assertion.userHandle ? encoded(assertion.userHandle) : null}};
}
export async function loginWithPasskey(req:Request) {
  supported();
  const {ticket,options}=await req('/api/auth/passkeys/login/options',{method:'POST'});
  const credential=await navigator.credentials.get({publicKey:{...options, challenge:bytes(options.challenge),
    allowCredentials:(options.allowCredentials||[]).map((x:any)=>({...x,id:bytes(x.id)}))}}) as PublicKeyCredential|null;
  if (!credential) throw Error('Вход отменён.');
  return req('/api/auth/passkeys/login/verify',{method:'POST',body:JSON.stringify({ticket,credential:serialize(credential)})});
}
export function CustomerPasskeys({req}:{req:Request}) {
  const [d,setData]=useState<any[]>([]);
  const reload=()=>req("/api/auth/passkeys").then(setData).catch(e=>setMessage(e.message));
  React.useEffect(()=>{reload()},[req]);
  const [name,setName]=useState('Мой ключ');
  const [password,setPassword]=useState('');
  const [otp,setOtp]=useState('');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  async function register(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setMessage('');
    try {
      supported();
      const {ticket,options}=await req('/api/auth/passkeys/registration/options',{method:'POST',
        body:JSON.stringify({name,password:password||null})});
      setPassword('');setOtp('');
      const credential=await navigator.credentials.create({publicKey:{...options, challenge:bytes(options.challenge),
        user:{...options.user,id:bytes(options.user.id)},
        excludeCredentials:(options.excludeCredentials||[]).map((x:any)=>({...x,id:bytes(x.id)}))}}) as PublicKeyCredential|null;
      if (!credential) throw Error('Регистрация отменена.');
      await req('/api/auth/passkeys/registration/verify',{method:'POST',body:JSON.stringify({ticket,credential:serialize(credential)})});
      setMessage('Ключ зарегистрирован. Теперь он доступен на странице входа.');reload();
    } catch(error:any) {setMessage(error.message||'Не удалось зарегистрировать ключ.');}
    finally {setPassword('');setOtp('');setBusy(false);}
  }
  const rows=Array.isArray(d)?d:[];
  return <div className="form-card stack"><h3>Ключи доступа</h3>
    <p className="muted">Для аккаунта с паролем подтвердите текущий пароль. Для входа через Telegram/OAuth сначала войдите заново. Браузер запросит биометрию или PIN устройства. До десяти ключей на аккаунт.</p>
    <form onSubmit={register}><label>Название<input maxLength={100} value={name} onChange={e=>setName(e.target.value)} required/></label>
      <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label>
      <button className="primary" disabled={busy}>{busy?'Подтверждение…':'Добавить ключ доступа'}</button></form>
    {message&&<p role="status">{message}</p>}
    <table><thead><tr><th>Название</th><th>Создан</th><th>Последний вход</th><th>Действие</th></tr></thead>
      <tbody>{rows.map((x:any)=><tr key={x.id}><td>{x.name}</td><td>{x.created_at}</td><td>{x.last_used_at||'—'}</td>
        <td><button disabled={busy} onClick={async()=>{setBusy(true);try {await req(`/api/auth/passkeys/${x.id}/delete`,{method:'POST',body:JSON.stringify({password:password||null})});reload();}
          catch(error:any){setMessage(error.message);}finally{setBusy(false);}}}>Удалить</button></td></tr>)}</tbody></table>
    {!rows.length&&<p>Ключи ещё не добавлены.</p>}</div>;
}
