import React,{useEffect,useRef,useState} from 'react';
type RequestFn=(path:string,options?:RequestInit)=>Promise<any>;
const labels:Record<string,string>={open:'Доступен',scheduled:'Скоро начнётся',closed:'Завершён'};
export function Surveys({request,reload}:{request:RequestFn;reload:()=>Promise<void>}){
 const [rows,setRows]=useState<any[]>([]),[next,setNext]=useState<number|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const serial=useRef(0);
 async function load(after=0){const n=++serial.current;setLoading(true);setError('');try{const d=await request('/api/me/surveys?after='+after);if(n===serial.current){setRows(prev=>after?[...prev,...d.items]:d.items);setNext(d.next_after)}}catch(e:any){if(n===serial.current)setError(e.message)}finally{if(n===serial.current)setLoading(false)}}
 useEffect(()=>{load();return()=>{serial.current++}},[request]);
 return <section className="stack"><h2 className="section-title">Опросы</h2><p>Ответы отправляются один раз. Условия участия и награда указаны в карточке.</p>{error&&<p role="alert" className="workspace-alert">{error}</p>}
 {!loading&&!rows.length&&<p>Опубликованных опросов пока нет.</p>}
 {rows.map(row=><SurveyCard key={row.id} row={row} request={request} onDone={async updated=>{setRows(prev=>prev.map(r=>r.id===updated.id?updated:r));await reload().catch(()=>{})}}/>)}
 {loading&&<p role="status">Загрузка…</p>}{next!=null&&<button className="btn-ghost" disabled={loading} onClick={()=>load(next)}>Показать ещё</button>}
 </section>
}
export function SurveyCard({row,request,onDone}:{key?:string|number;row:any;request:RequestFn;onDone:(updated:any)=>Promise<void>}){
 const [answers,setAnswers]=useState<any[]>(()=>row.my_answers||row.questions.map(()=>({choices:[],text:''}))),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const locked=useRef(false);const canAnswer=!row.submitted&&row.phase==='open';
 function choice(i:number,option:number,multiple:boolean){setAnswers(prev=>prev.map((a,j)=>j!==i?a:{text:'',choices:multiple?(a.choices.includes(option)?a.choices.filter((x:number)=>x!==option):[...a.choices,option]):[option]}))}
 async function submit(e:React.FormEvent){e.preventDefault();if(locked.current)return;setError('');
  if(answers.some((a,i)=>row.questions[i].kind==='text'?!a.text.trim():!a.choices.length)){setError('Ответьте на каждый вопрос');return;}
  locked.current=true;setBusy(true);try{const updated=await request(`/api/me/surveys/${row.id}/submit`,{method:'POST',body:JSON.stringify({answers})});await onDone(updated)}catch(e:any){setError(e.message)}finally{locked.current=false;setBusy(false)}}
 return <article className="form-card stack"><h3>{row.title}</h3><p style={{whiteSpace:'pre-wrap'}}>{row.description}</p><p>{labels[row.phase]||row.phase} · до {new Date(row.ends_at).toLocaleString()} · ответов {row.response_count}/{row.max_responses}</p>
 {Number(row.reward_amount)>0&&<p>Награда: {row.reward_amount} {row.currency} на баланс магазина.</p>}
 {(row.require_verified_email||row.require_subscription)&&<p className="section-sub">Условия: {[row.require_verified_email?'подтверждённый email':'',row.require_subscription?'действующая подписка':''].filter(Boolean).join(', ')}.</p>}
 {row.submitted&&<p role="status">Ответ принят.{Number(row.my_reward)>0&&` Начислено ${row.my_reward} ${row.currency}.`}</p>}{error&&<p role="alert" className="workspace-alert">{error}</p>}
 <form className="stack" onSubmit={submit}>{row.questions.map((q:any,i:number)=><fieldset className="stack" key={i} disabled={!canAnswer||busy}><legend>{i+1}. {q.text}</legend>
 {q.kind==='text'?<label className="field">Ваш ответ<input aria-label={`Ответ на вопрос ${i+1}`} value={answers[i]?.text||''} required maxLength={1000} onChange={e=>setAnswers(prev=>prev.map((a,j)=>j===i?{choices:[],text:e.target.value}:a))}/></label>:q.options.map((option:string,j:number)=><label key={j}><input type={q.kind==='multiple'?'checkbox':'radio'} name={`survey-${row.id}-question-${i}`} checked={answers[i]?.choices.includes(j)||false} onChange={()=>choice(i,j,q.kind==='multiple')}/> {option}</label>)}
 </fieldset>)}{canAnswer&&<button className="btn-primary" disabled={busy}>Отправить ответы</button>}</form>
 {row.statistics&&<section aria-label="Результаты опроса"><h4>Результаты</h4>{row.questions.map((q:any,i:number)=><div key={i}><strong>{q.text}</strong>{q.kind==='text'?<p>Текстовых ответов: {row.statistics[String(i)]?.answered||0}. Тексты доступны только оператору.</p>:q.options.map((option:string,j:number)=>{const count=row.statistics[String(i)]?.[String(j)]||0;return <p key={j}>{option}: {count} ({row.response_count?Math.round(100*count/row.response_count):0}%)</p>})}</div>)}</section>}
 </article>
}
