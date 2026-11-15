import React,{useRef,useState} from 'react';
type RequestFn=(path:string,options?:RequestInit)=>Promise<any>;
export function AttachmentUpload({ticketId,prefix='me',request,value,onChange,onBusyChange,disabled=false}:{key?:string|number;ticketId:number;prefix?:string;request:RequestFn;value:any[];onChange:(items:any[])=>void;onBusyChange?:(busy:boolean)=>void;disabled?:boolean}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const keys=useRef<Record<string,string>>({}),locked=useRef(false);
 async function upload(files:FileList|null){
  if(!files||locked.current)return;locked.current=true;setBusy(true);onBusyChange?.(true);setError('');const next=[...value];
  try{for(const file of Array.from(files)){
   if(file.size>2*1024*1024)throw Error('Файл должен быть не более 2 МБ');
   if(next.length>=3)throw Error('К сообщению можно прикрепить до трёх файлов');
   const bytes=await file.arrayBuffer();const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
   if(next.some(x=>x.sha256===digest&&x.name===file.name))continue;
   const fingerprint=file.name+digest;keys.current[fingerprint]??=crypto.randomUUID();
   const content=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Не удалось прочитать файл'));reader.readAsDataURL(file)});
   const item=await request(`/api/${prefix}/support/tickets/${ticketId}/attachments`,{method:'POST',headers:{'Idempotency-Key':keys.current[fingerprint]},body:JSON.stringify({name:file.name,content_base64:content})});next.push(item);onChange([...next]);
  }}catch(e:any){setError(e.message)}finally{locked.current=false;setBusy(false);onBusyChange?.(false)}
 }
 async function recover(){
  if(locked.current)return;locked.current=true;setBusy(true);onBusyChange?.(true);setError('');
  try{const items=await request(`/api/${prefix}/support/tickets/${ticketId}/attachments/drafts`);
   onChange(items);if(items.length>3)setError('Удалите лишние файлы: к сообщению можно прикрепить до трёх вложений');
  }catch(e:any){setError(e.message)}finally{locked.current=false;setBusy(false);onBusyChange?.(false)}
 }
 async function remove(id:number){if(busy)return;setBusy(true);onBusyChange?.(true);setError('');try{await request(`/api/${prefix}/support/attachments/${id}`,{method:'DELETE'});onChange(value.filter(v=>v.id!==id))}catch(e:any){setError(e.message)}finally{setBusy(false);onBusyChange?.(false)}}
 return <div className="support-attachments"><button type="button" disabled={disabled||busy} onClick={recover}>Восстановить загруженные файлы</button><label>Вложения · PNG, JPEG, PDF, TXT · до 2 МБ<input type="file" accept=".png,.jpg,.jpeg,.pdf,.txt" multiple disabled={disabled||busy||value.length>=3} onChange={e=>{upload(e.target.files);e.target.value=''}}/></label>{busy&&<p role="status">Загрузка вложений…</p>}{error&&<p role="alert">{error}</p>}{value.map(x=><div key={x.id}>{x.name} · {Math.ceil(x.size/1024)} КБ <button type="button" disabled={disabled||busy} onClick={()=>remove(x.id)}>Убрать из сообщения</button></div>)}</div>;
}
export function AttachmentFiles({files=[],prefix='me',request}:{files?:any[];prefix?:string;request:RequestFn}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function download(id:number){if(busy)return;setBusy(true);setError('');try{
  const item=await request(`/api/${prefix}/support/attachments/${id}`);const raw=atob(item.content_base64);
  const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
  const link=document.createElement('a');link.href=url;link.download=item.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <div>{files.map(x=><button type="button" className="btn-ghost" key={x.id} disabled={busy} onClick={()=>download(x.id)}>{x.name} · {Math.ceil(x.size/1024)} КБ</button>)}{error&&<p role="alert">{error}</p>}</div>;
}
