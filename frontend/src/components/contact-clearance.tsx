"use client";
import {Fragment,useState} from 'react';
import {useApi,request,refresh,money} from '@/lib/api';
import type {Account} from '@/lib/types';
import type {InquiryData,PracticalAction,ReviewJob} from '@/lib/practical-actions';

export type ContactTask={id:string;title:string;owner:string;reason:string;evidence_refs:string;blocking:number;status:string;contact_check?:boolean;contact_resolvable?:boolean};
export type ContactAuthorization={recipient:string;role:string;route:string;evidence:string;authorized:number;updated_at:string};
export type ClearanceNote={task_id:string|null;contact_name:string;recipient:string;role:string;phone:string;route:string;distributor:string;verification_evidence:string;status:string;updated_at:string};
export type ContactWorkData={inquiry_data?:InquiryData;practical_actions?:PracticalAction[];review_job?:ReviewJob|null;tasks:ContactTask[];signals:{signals:{id:string;category:string;disposition:string|null;next_action:string|null;investigation_status:string}[]};authorizations:ContactAuthorization[];contact_clearance:ClearanceNote|null};
type ContactFields={contact_name:string;recipient:string;role:string;phone:string;route:''|'direct'|'distributor';distributor:string;verification_evidence:string};
const empty:ContactFields={contact_name:'',recipient:'',role:'',phone:'',route:'',distributor:'',verification_evidence:''};

// Live responses classify the task's purpose in the backend. The title-only fallback
// supports older saved responses without mistaking a warning in its reason for a task.
export function isPurchasingContactTask(task:ContactTask){
 return task.contact_check??/\bcontact\b|recipient|authoriz|permission|\broute\b|routing|purchasing relationship/i.test(task.title);
}
function canResolveContactTask(task:ContactTask){
 return task.contact_resolvable??(isPurchasingContactTask(task)&&!/(identity|match|mapping|alias)/i.test(task.title));
}

type ContactEditorProps={id:string;taskId?:string|null;data:ContactWorkData;autoOpen?:boolean;missingOnly?:boolean;savedOnly?:boolean};
const routeLabel=(route:string)=>route==='distributor'?'Through a distributor':'Direct with this customer';

function initialContact(note:ClearanceNote|null,auth:ContactAuthorization|null):ContactFields {
 // Never transfer an authorization from an earlier recipient onto a different partial record.
 const matchingAuth=auth&&(!note||(note.recipient===auth.recipient&&(!note.role||note.role===auth.role)&&(!note.route||note.route===auth.route)))?auth:null;
 const route=note?.route||matchingAuth?.route;
 return {
  ...empty,contact_name:note?.contact_name||'',recipient:note?.recipient||matchingAuth?.recipient||'',
  role:note?.role||matchingAuth?.role||'',phone:note?.phone||'',route:route==='direct'||route==='distributor'?route:'',
  distributor:note?.distributor||'',verification_evidence:note?.verification_evidence||matchingAuth?.evidence||'',
 };
}

export function ContactClearanceEditor(props:ContactEditorProps) {
 const auth=props.data.authorizations.find(a=>a.authorized===1)||null;
 const note=props.data.contact_clearance;
 return <ContactEntry key={JSON.stringify([props.id,props.taskId,note?.updated_at,auth?.updated_at])} {...props} auth={auth} note={note}/>;
}

function ContactEntry({id,taskId,data,autoOpen=false,savedOnly=false,auth,note}:ContactEditorProps&{auth:ContactAuthorization|null;note:ClearanceNote|null}) {
 const [initial]=useState(()=>initialContact(note,auth));
 const [fields,setFields]=useState(initial);
 const [editing,setEditing]=useState(false);
 const [permissionOpen,setPermissionOpen]=useState(false);
 const [needsFreshSource,setNeedsFreshSource]=useState(false);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState('');
 const [error,setError]=useState('');
 const task=data.tasks.find(t=>t.id===taskId);
 const resolvable=Boolean(task&&canResolveContactTask(task));
 const verified=Boolean(auth?.evidence.trim()&&auth.recipient===fields.recipient&&auth.role===fields.role&&auth.route===fields.route&&auth.evidence===fields.verification_evidence);
 const knownDetails=Boolean(initial.recipient||initial.role||initial.route||initial.verification_evidence);
 const dirty=Object.keys(fields).some(key=>fields[key as keyof ContactFields]!==initial[key as keyof ContactFields]);
 const hasDetails=Object.values(fields).some(value=>value.trim());
 const hasBuyer=Boolean(fields.recipient.trim()&&fields.role.trim());
 const canVerify=hasBuyer&&Boolean(fields.route&&fields.verification_evidence.trim());

 function change(key:keyof ContactFields,value:string) {
  const changedScope=['recipient','role','route'].includes(key)&&fields[key].trim()!==value.trim();
  if(changedScope)setNeedsFreshSource(true);
  setFields(current=>{
   // Evidence for one buyer, role and route cannot authorize a different combination.
   return {...current,[key]:value,...(changedScope?{verification_evidence:''}:{}),
    ...(key==='recipient'&&initial.recipient&&initial.recipient!==value?{contact_name:'',phone:''}:{}),
    ...(key==='route'&&value==='direct'?{distributor:''}:{})};
  });
  setMessage('');setError('');
 }
 async function save(verify:boolean) {
  if(busy||(verify&&!canVerify))return;
  setBusy(true);setMessage('');setError('');
  try {
   const result=await request<{task_status:string|null;requires_reassessment:boolean;authorized:boolean}>(
    `/accounts/${id}/contact-clearance`,'POST',{...fields,verified:verify,task_id:taskId||undefined});
   const saved=verify?(result.task_status==='resolved'?'Contact and route verified. This contact check is cleared.':task?'Contact and route verified. The separate check remains open.':'Contact and route verified.'):result.authorized?'Details saved. The existing verified authorization remains active.':'Partial information saved. This check stays open.';
   setMessage(saved+(result.requires_reassessment?' Clearline is reviewing this account.':''));
   setPermissionOpen(false);setEditing(false);refresh();
  } catch(e){setError((e as Error).message)} finally{setBusy(false)}
 }

 const entry=<>
  {knownDetails&&<p>{verified?'Verified purchasing contact':'Saved purchasing details'}{[initial.recipient,initial.role,initial.route&&routeLabel(initial.route)].filter(Boolean).map((part,index)=><Fragment key={index}> · <span>{part}</span></Fragment>)}</p>}
  {verified&&!editing&&<p>Authorization record · {auth?.evidence}</p>}
  {knownDetails&&<button type="button" className="action-link" aria-expanded={editing} onClick={()=>setEditing(!editing)}>{editing?'Hide saved fields':'Review or correct saved details'}</button>}
  {(!verified||editing)&&<>
   <div className="contact-clearance-fields">
    {(editing||!initial.recipient)&&<label>Work email<input type="email" value={fields.recipient} onChange={e=>change('recipient',e.target.value)} autoComplete="off"/></label>}
    {(editing||!initial.role)&&<label>Purchasing role<input value={fields.role} onChange={e=>change('role',e.target.value)} autoComplete="off"/></label>}
   </div>
   {!verified&&<p>{hasBuyer?(fields.route?'Confirm that this buyer may be contacted through the recorded route before outreach.':'The buying route and permission for outreach still need confirmation.'):'Save the buyer’s details as you find them. Outreach stays on hold until their buying route and permission are confirmed.'}</p>}
   <div className="contact-clearance-actions">
    <button type="button" className="action-link" disabled={busy||!dirty||!hasDetails} onClick={()=>save(false)}>Save partial information</button>
    {hasBuyer&&<button type="button" className="action-link" aria-expanded={permissionOpen} onClick={()=>setPermissionOpen(!permissionOpen)}>Review purchasing permission</button>}
   </div>
   {hasBuyer&&permissionOpen&&<div className="content-stack">
    {(editing||!fields.route||!initial.route)&&<label>Purchasing route<select value={fields.route} onChange={e=>change('route',e.target.value)}><option value="">Choose the authorized route</option><option value="direct">Direct with this customer</option><option value="distributor">Through a distributor</option></select></label>}
    {fields.route&&<>
     {(!initial.verification_evidence||editing||needsFreshSource)?<label>Record authorizing this buyer and route<textarea rows={2} placeholder="Identify the record or confirmation that authorizes this recipient through the selected route." value={fields.verification_evidence} onChange={e=>change('verification_evidence',e.target.value)}/></label>:<p>Saved authorization evidence · {fields.verification_evidence}</p>}
     <p>Verify only if the record authorizes <strong>{fields.recipient}</strong> as {fields.role} · {routeLabel(fields.route)}.</p>
    </>}
    <button type="button" className="action-link" disabled={busy||!canVerify} onClick={()=>save(true)}>{task&&!resolvable?'Save verified contact':'Verify purchasing details'}</button>
   </div>}
  </>}
  {verified&&!editing&&resolvable&&<button type="button" className="action-link" disabled={busy} onClick={()=>save(true)}>Complete check with saved contact</button>}
  {message&&<p role="status">{message}</p>}{error&&<p role="alert" className="notice">{error}</p>}
 </>;
 return autoOpen?<div className="contact-clearance-editor">{entry}</div>:<details className="contact-clearance-editor"><summary>{savedOnly?'Saved purchasing contact and route':'Purchasing contact and route'}</summary>{entry}</details>;
}

export function ContactClearanceReview({id,taskId,recommendedAction,declineCents}:{id:string;taskId?:string;recommendedAction?:string;declineCents?:number}){
 const {data:account,error:accountError}=useApi<Account>(`/accounts/${id}`);const {data:work,error:workError}=useApi<ContactWorkData>(`/accounts/${id}/commercial-work`);
 if(accountError||workError)return <p className="notice" role="alert">{accountError||workError}</p>;
 if(!account||!work)return <p className="empty">Loading customer evidence…</p>;
 const task=taskId?work.tasks.find(t=>t.id===taskId):work.tasks.find(isPurchasingContactTask);
 const details=account.assessment?.details;const others=work.tasks.filter(t=>t.id!==task?.id);const e=account.evidence;
 let refs:string[]=[];try{refs=task?.evidence_refs?JSON.parse(task.evidence_refs):[]}catch{}
 return <section className="contact-clearance-review" aria-label={`Contact clearance for ${account.name}`}>
  <div className="contact-clearance-context">
   <div className="contact-clearance-heading"><h2>{account.name}</h2><span className="badge">{money(declineCents??account.decline_cents)} historical decline</span></div>
   <p><strong>Opportunity:</strong> {details?.objective||recommendedAction||account.next_action||'Review this existing customer relationship.'}</p>
   <p><strong>Agent recommends:</strong> {details?.recommended_action||recommendedAction||account.next_action||'Confirm the current purchasing contact and permitted route before outreach.'}</p>
   {account.holds.includes('known_distributor_channel')&&!account.account_key?.startsWith('DISTRIBUTOR|')&&<p className="contact-clearance-channel-note">The records show purchases through a distributor. Keep that route and do not ask the distributor to identify or share its end customers’ purchase records.</p>}
   <div className="contact-clearance-evidence"><strong>What the records show</strong><p>{e.crm_notes||'No CRM note is saved.'}</p><small>Last identified purchase: {e.last_purchase||'not recorded'} · Last contacted: {e.last_contacted||'not recorded'} · 2025–2026 net purchases: {money(e.prior_cents||0)} → {money(e.current_cents||0)}</small></div>
  {(task||(account.status!=='no_action'&&!work.authorizations.some(a=>a.authorized===1)))&&<div className="contact-clearance-blocker"><strong>Still needs verification</strong><p>{task?`${task.title}: ${task.reason}`:'No purchasing recipient and authorized route are recorded for this account.'}</p>{task&&<small>Owner: {task.owner}{refs.length?` · Evidence: ${refs.join(', ')}`:''}{task.blocking?' · Required for the recommended action':''}</small>}</div>}
   {others.length>0&&<div className="contact-clearance-other"><strong>Other open checks remain separate</strong><ul>{others.map(t=><li key={t.id}>{t.title} — {t.reason}</li>)}</ul></div>}
  </div>
  {task?(isPurchasingContactTask(task)?<ContactClearanceEditor id={id} taskId={task.id} data={work} autoOpen/>:<a className="action-link" href={`/accounts/${id}#commercial-work`}>Record this finding in customer checks</a>):taskId?<p className="notice">This check has been completed or changed. Refresh the Action Center before editing it.</p>:account.status==='no_action'?<p>No contact check is requested for this account.</p>:<ContactClearanceEditor id={id} data={work}/>}
 </section>
}
