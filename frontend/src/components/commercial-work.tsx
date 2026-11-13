"use client";
import {useState} from 'react';
import {useApi,request,refresh,label} from '@/lib/api';
type Task={id:string;title:string;owner:string;reason:string;blocking:number};
type Signal={id:string;category:string;disposition:string|null;next_action:string|null;investigation_status:string};
export function CommercialWork({id}:{id:string}){
 const {data}=useApi<{tasks:Task[];signals:{signals:Signal[]}}>(`/accounts/${id}/commercial-work`);
 const [answers,setAnswers]=useState<Record<string,string>>({});const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
 const [recipient,setRecipient]=useState('');const [role,setRole]=useState('');const [route,setRoute]=useState('direct');const [evidence,setEvidence]=useState('');
 async function run(path:string,body:unknown){setBusy(true);try{await request(path,'POST',body);setMessage('Saved. The agent will reassess the next action.');refresh()}catch(e){setMessage((e as Error).message)}finally{setBusy(false)}}
 if(!data?.tasks||!data?.signals?.signals)return null;
 return <div id="commercial-work" className="content-stack">{data.tasks.map(t=><div key={t.id}><strong>{t.title}</strong><p>{t.reason}</p><small>{t.owner}{t.blocking?' · Required before contact':''}</small><label>Verified finding<textarea value={answers[t.id]||''} onChange={e=>setAnswers({...answers,[t.id]:e.target.value})}/></label><button className="action-link" disabled={busy||!answers[t.id]?.trim()} onClick={()=>run(`/investigations/${t.id}/resolve`,{resolution:answers[t.id]})}>Record finding and reassess</button></div>)}
 <details><summary>Purchasing relationship and contact authorization</summary><p>Record an existing authorized recipient and the evidence for this relationship. A simulation address does not establish permission.</p><label>Recipient<input value={recipient} onChange={e=>setRecipient(e.target.value)}/></label><label>Role<input value={role} onChange={e=>setRole(e.target.value)}/></label><label>Purchasing route<select value={route} onChange={e=>setRoute(e.target.value)}><option value="direct">Direct relationship</option><option value="distributor">Through the distributor</option></select></label><label>Authorization evidence<textarea value={evidence} onChange={e=>setEvidence(e.target.value)}/></label><button className="action-link" disabled={busy||![recipient,role,evidence].every(x=>x.trim())} onClick={()=>run(`/accounts/${id}/contact-authorization`,{recipient,role,route,evidence,authorized:true})}>Confirm authorization and reassess</button></details>
 <details><summary>Detected commercial opportunities ({data.signals.signals.length})</summary>{data.signals.signals.map(s=><p key={s.id}><strong>{label(s.category)}</strong> · {label(s.disposition||s.investigation_status)}{s.next_action&&` — ${s.next_action}`}</p>)}</details>{message&&<p role="status">{message}</p>}</div>
}
