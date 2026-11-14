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
  const {ticket,options}=await req('/api/admin/auth/passkeys/login/options',{method:'POST'});
  const credential=await navigator.credentials.get({publicKey:{...options, challenge:bytes(options.challenge),
    allowCredentials:(options.allowCredentials||[]).map((x:any)=>({...x,id:bytes(x.id)}))}}) as PublicKeyCredential|null;
  if (!credential) throw Error('Вход отменён.');
  return req('/api/admin/auth/passkeys/login/verify',{method:'POST',body:JSON.stringify({ticket,credential:serialize(credential)})});
}
export function PasskeySettings({d,reload,req}:{d:any;reload:()=>void;req:Request}) {
  const [name,setName]=useState('Мой ключ');
  const [password,setPassword]=useState('');
  const [otp,setOtp]=useState('');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  async function register(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setMessage('');
    try {
      supported();
      const {ticket,options}=await req('/api/admin/auth/passkeys/registration/options',{method:'POST',
        body:JSON.stringify({name,password,otp:otp||null})});
      setPassword('');setOtp('');
      const credential=await navigator.credentials.create({publicKey:{...options, challenge:bytes(options.challenge),
        user:{...options.user,id:bytes(options.user.id)},
        excludeCredentials:(options.excludeCredentials||[]).map((x:any)=>({...x,id:bytes(x.id)}))}}) as PublicKeyCredential|null;
      if (!credential) throw Error('Регистрация отменена.');
      await req('/api/admin/auth/passkeys/registration/verify',{method:'POST',body:JSON.stringify({ticket,credential:serialize(credential)})});
      setMessage('Ключ зарегистрирован. Теперь он доступен на странице входа.');reload();
    } catch(error:any) {setMessage(error.message||'Не удалось зарегистрировать ключ.');}
    finally {setPassword('');setOtp('');setBusy(false);}
  }
  const rows=Array.isArray(d)?d:[];
  return <div className="card"><h3>Ключи доступа / WebAuthn</h3>
    <p className="muted">Подтвердите пароль и действующий код 2FA, если он включён. Браузер запросит биометрию или PIN устройства. До десяти ключей на администратора.</p>
    <form onSubmit={register}><label>Название<input maxLength={100} value={name} onChange={e=>setName(e.target.value)} required/></label>
      <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label>
      <label>Код 2FA или резервный код<input autoComplete="one-time-code" maxLength={20} value={otp} onChange={e=>setOtp(e.target.value)}/></label>
      <button className="primary" disabled={busy}>{busy?'Подтверждение…':'Добавить ключ доступа'}</button></form>
    {message&&<p role="status">{message}</p>}
    <table><thead><tr><th>Название</th><th>Создан</th><th>Последний вход</th><th>Действие</th></tr></thead>
      <tbody>{rows.map((x:any)=><tr key={x.id}><td>{x.name}</td><td>{x.created_at}</td><td>{x.last_used_at||'—'}</td>
        <td><button disabled={busy} onClick={async()=>{setBusy(true);try {await req(`/api/admin/v41/passkeys/${x.id}`,{method:'DELETE'});reload();}
          catch(error:any){setMessage(error.message);}finally{setBusy(false);}}}>Удалить</button></td></tr>)}</tbody></table>
    {!rows.length&&<p>Ключи ещё не добавлены.</p>}</div>;
}
