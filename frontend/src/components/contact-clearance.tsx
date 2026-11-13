"use client";
import {useEffect,useState} from 'react';
import {useApi,request,refresh,money} from '@/lib/api';
import type {Account} from '@/lib/types';

export type ContactTask={id:string;title:string;owner:string;reason:string;evidence_refs:string;blocking:number;status:string};
export type ContactAuthorization={recipient:string;role:string;route:string;evidence:string;authorized:number;updated_at:string};
export type ClearanceNote={task_id:string|null;contact_name:string;recipient:string;role:string;phone:string;route:string;distributor:string;verification_evidence:string;status:string;updated_at:string};
export type ContactWorkData={tasks:ContactTask[];signals:{signals:{id:string;category:string;disposition:string|null;next_action:string|null;investigation_status:string}[]};authorizations:ContactAuthorization[];contact_clearance:ClearanceNote|null};
type ContactFields={contact_name:string;recipient:string;role:string;phone:string;route:''|'direct'|'distributor';distributor:string;verification_evidence:string;verified:boolean};
const empty:ContactFields={contact_name:'',recipient:'',role:'',phone:'',route:'',distributor:'',verification_evidence:'',verified:false};

export function ContactClearanceEditor({id,taskId,data,autoOpen=false}:{id:string;taskId?:string|null;data:ContactWorkData;autoOpen?:boolean}){
 const auth=data.authorizations.find(a=>a.authorized===1)||null;const note=data.contact_clearance;
 const selectedTask=data.tasks.find(t=>t.id===taskId);const selectedText=selectedTask?`${selectedTask.title} ${selectedTask.reason}`.toLowerCase():'';
 const taskCanResolve=Boolean(selectedTask&&/contact|recipient|authoriz|route|purchasing relationship/.test(selectedText)&&!/(identity|match|mapping|alias)/.test(selectedText));
 const [fields,setFields]=useState<ContactFields>(empty);const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 useEffect(()=>{
  const saved=note||auth;
  if(!saved){setFields(empty);return}
  setFields({contact_name:('contact_name' in saved?saved.contact_name:'')||'',recipient:saved.recipient||auth?.recipient||'',role:saved.role||auth?.role||'',phone:('phone' in saved?saved.phone:'')||'',route:(saved.route==='direct'||saved.route==='distributor'?saved.route:auth?.route==='direct'||auth?.route==='distributor'?auth.route:''),distributor:('distributor' in saved?saved.distributor:'')||'',verification_evidence:(('verification_evidence' in saved?saved.verification_evidence:'')||('evidence' in saved?saved.evidence:'')||auth?.evidence)||'',verified:note?.status==='verified'||auth?.authorized===1});
 },[note?.updated_at,auth?.updated_at]);
 function change<K extends keyof ContactFields>(key:K,value:ContactFields[K]){setFields(current=>({...current,[key]:value,verified:key==='verified'?Boolean(value):false}));setMessage('');setError('')}
 const hasDetails=Object.entries(fields).some(([key,value])=>key!=='verified'&&String(value).trim());
 const canVerify=Boolean(fields.recipient.trim()&&fields.role.trim()&&fields.route&&fields.verification_evidence.trim()&&fields.verified);
 async function save(verify:boolean){setBusy(true);setMessage('');setError('');try{const result=await request<{status:string;task_status:string|null;job_id:string|null;requires_reassessment:boolean;authorized:boolean}>(`/accounts/${id}/contact-clearance`,'POST',{...fields,verified:verify,task_id:taskId||undefined});setMessage(verify?(result.task_status==='resolved'?'Contact and route verified. This contact check is cleared; the agent will reassess, and any other blockers remain.':selectedTask?'Contact and route verified. The separate customer-matching check remains open; the agent will reassess.':'Contact and route verified. The agent will reassess; any other blockers remain.'):result.authorized?'Details saved. The existing verified authorization remains active.':'Partial information saved. This check stays open; no outreach is authorized.');refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <details className="contact-clearance-editor" open={autoOpen||undefined}><summary>{auth?'Purchasing contact and route · currently verified':'Purchasing contact and route · needs verification'}</summary>
  <p>Save what you know as a partial note, or verify the contact and purchasing route. Entering an email address alone never authorizes outreach.</p>
  {auth&&<p className="contact-clearance-status">Currently authorized: {auth.recipient} · {auth.route==='distributor'?'through distributor':'direct'} · verified {new Date(auth.updated_at).toLocaleDateString()}</p>}
  <div className="contact-clearance-fields">
   <label>Contact name<input value={fields.contact_name} onChange={e=>change('contact_name',e.target.value)} autoComplete="off"/></label>
   <label>Work email<input type="email" value={fields.recipient} onChange={e=>change('recipient',e.target.value)} autoComplete="off"/></label>
   <label>Purchasing role<input value={fields.role} onChange={e=>change('role',e.target.value)} autoComplete="off"/></label>
   <label>Phone (optional)<input value={fields.phone} onChange={e=>change('phone',e.target.value)} autoComplete="off"/></label>
   <label>Purchasing route<select value={fields.route} onChange={e=>change('route',e.target.value as ContactFields['route'])}><option value="">Not confirmed</option><option value="direct">Direct with this customer</option><option value="distributor">Through a distributor</option></select></label>
   {fields.route==='distributor'&&<label>Distributor name (if known)<input value={fields.distributor} onChange={e=>change('distributor',e.target.value)} autoComplete="off"/></label>}
  </div>
  <label>How was this information verified? <small>For example, the existing CRM record, a call with the agency, or confirmation from the account owner.</small><textarea rows={3} value={fields.verification_evidence} onChange={e=>change('verification_evidence',e.target.value)}/></label>
  <label className="contact-clearance-confirm"><input type="checkbox" checked={fields.verified} onChange={e=>change('verified',e.target.checked)}/> I verified that this contact is authorized to discuss purchasing for this customer through the route above.</label>
  <div className="contact-clearance-actions"><button className="action-link" disabled={busy||!hasDetails} onClick={()=>save(false)}>Save partial information</button><button className="primary" disabled={busy||!canVerify} onClick={()=>save(true)}>{taskId&&!taskCanResolve?'Save verified contact':'Verify contact and reassess'}</button></div>
  {message&&<p role="status">{message}</p>}{error&&<p role="alert" className="notice">{error}</p>}
 </details>
}

export function ContactClearanceReview({id,taskId,recommendedAction,declineCents}:{id:string;taskId?:string;recommendedAction?:string;declineCents?:number}){
 const {data:account,error:accountError}=useApi<Account>(`/accounts/${id}`);const {data:work,error:workError}=useApi<ContactWorkData>(`/accounts/${id}/commercial-work`);
 if(accountError||workError)return <p className="notice" role="alert">{accountError||workError}</p>;
 if(!account||!work)return <p className="empty">Loading customer evidence…</p>;
 const task=taskId?work.tasks.find(t=>t.id===taskId):work.tasks.find(t=>/contact|recipient|authoriz|identity|match|mapping|route|relationship/i.test(t.title+' '+t.reason));
 const details=account.assessment?.details;const others=work.tasks.filter(t=>t.id!==task?.id);const e=account.evidence;
 let refs:string[]=[];try{refs=task?.evidence_refs?JSON.parse(task.evidence_refs):[]}catch{}
 return <section className="contact-clearance-review" aria-label={`Contact clearance for ${account.name}`}>
  <div className="contact-clearance-context">
   <div className="contact-clearance-heading"><h2>{account.name}</h2><span className="badge">{money(declineCents??account.decline_cents)} historical decline</span></div>
   <p><strong>Opportunity:</strong> {details?.objective||recommendedAction||account.next_action||'Review this existing customer relationship.'}</p>
   <p><strong>Agent recommends:</strong> {details?.recommended_action||recommendedAction||account.next_action||'Confirm the current purchasing contact and permitted route before outreach.'}</p>
   {account.holds.includes('known_distributor_channel')&&!account.account_key?.startsWith('DISTRIBUTOR|')&&<p className="contact-clearance-channel-note">The records show purchases through a distributor. Keep that route and do not ask the distributor to identify or share its end customers’ purchase records.</p>}
   <div className="contact-clearance-evidence"><strong>What the records show</strong><p>{e.crm_notes||'No CRM note is saved.'}</p><small>Last identified purchase: {e.last_purchase||'not recorded'} · Last contacted: {e.last_contacted||'not recorded'} · 2025–2026 net purchases: {money(e.prior_cents||0)} → {money(e.current_cents||0)}</small></div>
  <div className="contact-clearance-blocker"><strong>Still needs verification</strong><p>{task?`${task.title}: ${task.reason}`:'No purchasing recipient and authorized route are recorded for this account.'}</p>{task&&<small>Owner: {task.owner}{refs.length?` · Evidence: ${refs.join(', ')}`:''}{task.blocking?' · Required before contact':''}</small>}</div>
   {others.length>0&&<div className="contact-clearance-other"><strong>Other open checks remain separate</strong><ul>{others.map(t=><li key={t.id}>{t.title} — {t.reason}</li>)}</ul></div>}
  </div>
  {task?<ContactClearanceEditor id={id} taskId={task.id} data={work} autoOpen/>:taskId?<p className="notice">This check has been completed or changed. Refresh the Action Center before editing it.</p>:<ContactClearanceEditor id={id} data={work}/>}
 </section>
}
