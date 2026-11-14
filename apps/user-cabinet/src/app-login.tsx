import React, {useState} from 'react';

type Request = (path:string, options?:RequestInit)=>Promise<any>;
type Link = {deep_link:string; open_url:string; expires_in:number};

/** One tap from the cabinet / Mini App into the Android or iOS app, already signed in. */
export function AppLogin({request, open=(url:string)=>{window.location.href=url}}:{request:Request; open?:(url:string)=>void}) {
  const [link,setLink]=useState<Link|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function issue() {
    setBusy(true);setError('');
    try {
      const next=await request('/api/me/app-login',{method:'POST'}) as Link;
      setLink(next);open(next.open_url);
    } catch(e:any) {setError(e?.message||'Не удалось создать ссылку.');}
    finally {setBusy(false);}
  }
  return <div className="form-card stack" data-app-login><h3>Вход в приложение</h3>
    <p className="muted">Откройте эту страницу на телефоне с приложением «Корги Люси» и нажмите кнопку: приложение откроется уже с вашим аккаунтом, без адреса и пароля. Ссылка одноразовая и действует несколько минут.</p>
    <button className="primary" disabled={busy} onClick={issue}>{busy?'Создаём ссылку…':'Войти в приложение'}</button>
    {link&&<p role="status" className="muted">Приложение не открылось? <a href={link.deep_link}>Открыть напрямую</a>. Ссылка действует {Math.round(link.expires_in/60)} мин. Не пересылайте её никому.</p>}
    {error&&<p role="alert" className="error">{error}</p>}
  </div>;
}
