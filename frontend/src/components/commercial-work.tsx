"use client";
import {useState} from 'react';
import type {SavedCommercialSignal} from '@/lib/types';
import {verificationExplanation} from '@/lib/account-presentation';
import {useApi,request,refresh,label} from '@/lib/api';
import {ContactClearanceEditor,isPurchasingContactTask,type ContactWorkData} from './contact-clearance';

export function CommercialWork({id,signals=[]}:{id:string;signals?:SavedCommercialSignal[]}){
 const {data,error}=useApi<ContactWorkData>(`/accounts/${id}/commercial-work`);
 const [answers,setAnswers]=useState<Record<string,string>>({});const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
 async function run(path:string,body:unknown){setBusy(true);try{const result=await request<{requires_reassessment:boolean}>(path,'POST',body);setMessage(result.requires_reassessment?'Finding recorded. A review of this account is queued; other checks remain open.':'Finding recorded. The existing assessment is unchanged.');refresh()}catch(e){setMessage((e as Error).message)}finally{setBusy(false)}}
 if(error)return <p role="alert" className="notice">What Needs Verification could not load: {error}</p>;
 if(!data?.tasks||!data?.signals?.signals)return null;
 const contactTasks=data.tasks.filter(isPurchasingContactTask);const task=contactTasks[0];const otherTasks=data.tasks.filter(t=>!isPurchasingContactTask(t));
 const savedContact=Boolean(data.contact_clearance||data.authorizations.length);
 return <section id="commercial-work" className="panel commercial-work-panel"><div className="panel-head"><h2>What Needs Verification</h2></div><div className="content-stack">
  {!data.tasks.length&&<p>No verification checks are open. There is nothing to verify for the current recommendation.</p>}
  {otherTasks.map(t=><div className="commercial-check" key={t.id}><strong>{t.title}</strong><TaskExplanation task={t} signals={signals}/><small>Suggested team / owner: {t.owner||'Unassigned'}{t.blocking?' · Required for the recommended action':''}</small><label>Verified finding<textarea aria-label={`Verified finding: ${t.title}`} placeholder="Record what was confirmed, the supporting record or person, and any unresolved issue." value={answers[t.id]||''} onChange={e=>setAnswers({...answers,[t.id]:e.target.value})}/></label><button className="action-link" disabled={busy||!answers[t.id]?.trim()} onClick={()=>run(`/investigations/${t.id}/resolve`,{resolution:answers[t.id]})}>Record finding and reassess</button></div>)}
  {task&&<div><strong>{task.title}</strong><TaskExplanation task={task} signals={signals}/><small>Suggested team / owner: {task.owner||'Unassigned'}{task.blocking?' · Required before contact':''}</small></div>}
  {(task||savedContact)&&<ContactClearanceEditor id={id} taskId={task?.id} data={data} autoOpen={Boolean(task)&&!otherTasks.length}/>}
  {contactTasks.length>1&&<p className="contact-clearance-other"><strong>Additional contact checks stay open:</strong> {contactTasks.slice(1).map(t=>t.title).join('; ')}</p>}
  <details><summary>Detected commercial opportunities ({data.signals.signals.length})</summary>{data.signals.signals.map(s=><p key={s.id}><strong>{label(s.category)}</strong> · {label(s.disposition||s.investigation_status)}{s.next_action&&` — ${s.next_action}`}</p>)}</details>
  {message&&<p role="status">{message}</p>}
 </div></section>
}

function TaskExplanation({task,signals}:{task:import('./contact-clearance').ContactTask;signals:SavedCommercialSignal[]}){
 const explanation=verificationExplanation(task,signals);
 return <><p>{explanation.context}</p>{explanation.next&&<p><strong>Next step:</strong> {explanation.next}</p>}{explanation.financial&&<p className="task-financial"><strong>Financial significance:</strong> {explanation.financial}</p>}{explanation.next&&<details><summary>Record details and original instructions</summary><p>{task.reason}</p></details>}</>;
}
