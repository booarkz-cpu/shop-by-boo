import React from "react";

type Node = {id:string;parent:string|null;level:number};
export function ReferralNetwork({data}:{data:{nodes:Node[];truncated:boolean;level_counts:{level:number;count:number}[]} | undefined}) {
 if(!data)return null;
 const groups=Array.from({length:6},(_,level)=>(data.nodes||[]).filter(n=>n.level===level));
 const height=Math.max(100,...groups.map(g=>g.length*38+40));
 const positions=new Map<string,{x:number;y:number}>();
 groups.forEach((group,level)=>group.forEach((node,index)=>positions.set(node.id,{x:45+level*135,y:height*(index+1)/(group.length+1)})));
 return <section><h3>Ваша реферальная сеть</h3><p>Участники обезличены. Показано {data.nodes.length-1} приглашений.</p>
 <div className="metrics">{(data.level_counts||[]).map(x=><div className="metric" key={x.level}><span className="label">Уровень {x.level}</span><strong className="value">{x.count}</strong></div>)}</div>
 <div style={{overflowX:"auto",maxHeight:500,overflowY:"auto"}}><svg width="800" height={height} role="img" aria-label="Обезличенный граф реферальной сети">
 {data.nodes.filter(n=>n.parent).map(n=>{const p=positions.get(n.parent!)!,c=positions.get(n.id)!;return <line key={n.id} x1={p.x} y1={p.y} x2={c.x} y2={c.y} stroke="#888"/>})}
 {data.nodes.map((n,i)=>{const p=positions.get(n.id)!;return <g key={n.id}><circle cx={p.x} cy={p.y} r="7" fill="#7169e8"/><text x={p.x+11} y={p.y+4} fontSize="11" fill="currentColor">{n.level===0?"Вы":`Участник ${i}`}</text></g>})}
 </svg></div>{data.truncated&&<p>Показаны первые 100 узлов и до пяти уровней; сеть продолжается за пределами графа.</p>}</section>
}
