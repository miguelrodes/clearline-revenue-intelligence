"use client";
import {useState} from 'react';
import {useApi,request,refresh,label} from '@/lib/api';
import {ContactClearanceEditor,type ContactWorkData} from './contact-clearance';

type Task={id:string;title:string;owner:string;reason:string;evidence_refs:string;blocking:number};
type Signal={id:string;category:string;disposition:string|null;next_action:string|null;investigation_status:string};

function isPurchasingContactTask(task:Task){
 const text=`${task.title} ${task.reason}`.toLowerCase();
 return /contact|recipient|authoriz|route|purchasing relationship/.test(text)&&!/(identity|match|mapping|alias)/.test(text);
}

export function CommercialWork({id}:{id:string}){
 const {data}=useApi<ContactWorkData&{tasks:Task[];signals:{signals:Signal[]}}>(`/accounts/${id}/commercial-work`);
 const [answers,setAnswers]=useState<Record<string,string>>({});const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
 async function run(path:string,body:unknown){setBusy(true);try{await request(path,'POST',body);setMessage('Finding recorded. The agent will reassess this account; other checks remain open.');refresh()}catch(e){setMessage((e as Error).message)}finally{setBusy(false)}}
 if(!data?.tasks||!data?.signals?.signals)return null;
 const contactTasks=data.tasks.filter(isPurchasingContactTask);const task=contactTasks[0];const otherTasks=data.tasks.filter(t=>!isPurchasingContactTask(t));
 return <section id="commercial-work" className="panel commercial-work-panel"><div className="panel-head"><h2>Customer checks</h2></div><div className="content-stack">
  {task&&<div><strong>{task.title}</strong><p>{task.reason}</p><small>{task.owner}{task.blocking?' · Required before contact':''}</small></div>}
  <ContactClearanceEditor id={id} taskId={task?.id} data={data} autoOpen={Boolean(task)}/>
  {contactTasks.length>1&&<p className="contact-clearance-other"><strong>Additional contact checks stay open:</strong> {contactTasks.slice(1).map(t=>t.title).join('; ')}</p>}
  {otherTasks.map(t=><div className="commercial-check" key={t.id}><strong>{t.title}</strong><p>{t.reason}</p><small>{t.owner}{t.blocking?' · Required before contact':''}</small><label>Verified finding<textarea aria-label={`Verified finding: ${t.title}`} value={answers[t.id]||''} onChange={e=>setAnswers({...answers,[t.id]:e.target.value})}/></label><button className="action-link" disabled={busy||!answers[t.id]?.trim()} onClick={()=>run(`/investigations/${t.id}/resolve`,{resolution:answers[t.id]})}>Record finding and reassess</button></div>)}
  <details><summary>Detected commercial opportunities ({data.signals.signals.length})</summary>{data.signals.signals.map(s=><p key={s.id}><strong>{label(s.category)}</strong> · {label(s.disposition||s.investigation_status)}{s.next_action&&` — ${s.next_action}`}</p>)}</details>
  {message&&<p role="status">{message}</p>}
 </div></section>
}
