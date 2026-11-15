import React,{useEffect,useState} from 'react';
type Requester=(path:string)=>Promise<any>;
function Emoji({node,request,assetBase}:{node:any;request:Requester;assetBase:string}){
 const[url,setUrl]=useState('');useEffect(()=>{let live=true;setUrl('');if(node.icon_custom_emoji_id)request(`/api/public/menu-emoji/${node.icon_custom_emoji_id}`).then(x=>{if(live&&typeof x.url==='string'&&/^\/media\/menu-emoji-[a-f0-9]+\.png$/.test(x.url))setUrl(assetBase+x.url)}).catch(()=>{});return()=>{live=false}},[node.icon_custom_emoji_id,request,assetBase]);
 return url?<img src={url} alt="" width="24" height="24" style={{verticalAlign:'middle'}} onError={()=>setUrl('')}/>:<span aria-hidden="true">{node.icon||''}</span>;
}
export function ButtonTree({buttons,run,request,assetBase=''}:{buttons:any[];run:(node:any)=>void;request:Requester;assetBase?:string}){
 const[path,setPath]=useState<string[]>([]);useEffect(()=>setPath([]),[buttons]);let nodes=buttons||[];const trail:any[]=[];
 for(const id of path){const node=nodes.find(n=>n.id===id&&n.type==='folder');if(!node)break;trail.push(node);nodes=node.children||[]}
 const colors:Record<string,string>={primary:'#2563eb',success:'#15803d',danger:'#b91c1c'};
 return <section aria-label="Меню приложения">{trail.length>0&&<div className="btn-row"><button type="button" onClick={()=>setPath(p=>p.slice(0,-1))}>← Назад</button><span>{trail.map(n=>n.title).join(' / ')}</span></div>}<div className="btn-row">{nodes.map((node:any,i:number)=><button type="button" key={node.id||i} style={colors[node.style]?{backgroundColor:colors[node.style],color:'#fff'}:undefined} onClick={()=>node.type==='folder'?setPath(p=>[...p,node.id]):run(node)}><Emoji node={node} request={request} assetBase={assetBase}/> {node.title}{node.type==='folder'?' ›':''}</button>)}</div>{!nodes.length&&<p>В этой папке пока нет кнопок.</p>}</section>;
}
