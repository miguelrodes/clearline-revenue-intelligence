'use client';
import {useState} from 'react';
import Link from 'next/link';
import {refresh,request,useApi,label} from '@/lib/api';
import {exactMoney} from '@/lib/account-presentation';
import {currentInquiries,inquiryNext,practicalAnchor,recordCoverage,reviewStatus,type PracticalAction,type PracticalTask,type InquiryData} from '@/lib/practical-actions';
import {ContactClearanceEditor,type ContactWorkData} from './contact-clearance';
import {ActionDisclosure,DisclosureGroup,PrepareInternal,InquiryReview,RecordGuidance} from './internal-inquiry';

type InquiryProps={inquiries?:InquiryData;inquiryError?:string};

export function PracticalActions({oid,work,scope,inquiries,inquiryError}:InquiryProps&{oid:string;work:ContactWorkData;scope?:string[]}){
 const remote=useApi<InquiryData>(inquiries||inquiryError!==undefined?null:`/accounts/${encodeURIComponent(oid)}/internal-inquiries`);
 const data=inquiries??remote.data,error=inquiryError??remote.error;
 const actions=(work.practical_actions||[]).filter(a=>!scope||a.task_ids.some(id=>scope.includes(id)));
 const displayed=new Set(actions.map(a=>a.id));
 const history=(data?.inquiries??[]).filter(i=>!displayed.has(i.group_id)&&(!scope||i.task_ids.some(id=>scope.includes(id))));
 const latest=reviewStatus(work.review_job);
 return <DisclosureGroup><div className="content-stack">{latest&&<p role="status">{latest}</p>}
  {!actions.length&&<p>{scope?'This check is no longer actionable. Review the latest account recommendation.':latest?'No additional information is requested while the review is pending.':'No verification checks are open for the current recommendation.'}</p>}
  {actions.map(a=><PracticalCard key={a.id} action={a} oid={oid} work={work} scoped={!!scope} inquiries={data} inquiryError={error}/>)}
  {!scope&&!actions.some(a=>a.control==='contact')&&(work.contact_clearance||work.authorizations.some(a=>a.authorized===1))&&<ContactClearanceEditor id={oid} data={work} savedOnly/>}
  {!!history.length&&<details className="practical-support"><summary>Previous internal inquiries ({history.length})</summary>{history.map(i=><InquiryReview key={i.id} oid={oid} inquiry={i} eligible={false} allowedFindingTasks={[]}/>)}</details>}
  {!scope&&!!work.signals?.signals?.length&&<details className="practical-support"><summary>Detected commercial opportunities ({work.signals.signals.length})</summary>{work.signals.signals.map(s=><p key={s.id}><strong>{label(s.category)}</strong> · {label(s.disposition||s.investigation_status)}</p>)}</details>}
 </div></DisclosureGroup>;
}

function PracticalCard({action:a,oid,work,scoped,inquiries,inquiryError}:InquiryProps&{action:PracticalAction;oid:string;work:ContactWorkData;scoped:boolean}){
 const [taskId,setTaskId]=useState('');
 const task=a.tasks.find(t=>t.id===taskId)||a.tasks[0];
 const related=(inquiries?.inquiries??[]).filter(i=>i.group_id===a.id);
 const active=currentInquiries(a,inquiries),history=related.filter(i=>!active.includes(i));
 const hasUnrequested=a.task_ids.some(id=>!active.some(i=>i.task_ids.includes(id)));
 const prepare=a.can_prepare_internal&&hasUnrequested&&!!inquiries;
 const contact=a.control==='contact';
 const findingPrimary=contact?(!active.length||active.some(i=>i.replies.length)):(!a.can_prepare_internal&&!active.length);
 const finding=task&&<ActionDisclosure primary={findingPrimary} label={contact?'Enter purchasing details':'Record a verified finding'}>
  <div className="practical-entry">
   {a.tasks.length>1&&<label>Which check did you verify?<select value={task.id} onChange={e=>setTaskId(e.target.value)}>{a.tasks.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select></label>}
   {contact?<ContactClearanceEditor key={task.id} id={oid} data={work} taskId={task.id} autoOpen missingOnly/>:<FindingEntry key={task.id} task={task} lines={a.lines}/>}
  </div>
 </ActionDisclosure>;
 return <article tabIndex={-1} id={scoped?undefined:practicalAnchor(a.id)} className="commercial-check" aria-label={a.title}>
  <h3>{a.title}</h3>
  {active.length===0&&<><p>{a.found}</p><p><strong>Why it matters:</strong> {a.why}</p><p><strong>Your next step:</strong> {a.next_step}</p></>}
  {active.map(i=>{const next=inquiryNext(a,i);return <div key={i.id}><strong className="practical-current">{next.title}</strong><p>{next.text}</p>
   <InquiryReview key={`${i.version}:${i.status}`} oid={oid} inquiry={i} eligible={a.can_prepare_internal||i.status!=='awaiting_approval'} allowedFindingTasks={contact?[]:a.task_ids} contact={contact} routing={inquiries&&{action:a,data:inquiries}}/>
  </div>})}
  {findingPrimary&&finding}
  {prepare&&<PrepareInternal oid={oid} action={a} data={inquiries!} primary={!findingPrimary&&!active.length}/>}
  {!findingPrimary&&finding}
  {inquiryError&&a.can_prepare_internal&&<p role="alert">Internal correspondence could not load: {inquiryError}</p>}
  <small>Check with: {a.role}{a.assigned_owner?` · ${a.assigned_owner}`:''}</small>
  {a.lines.length>0&&<details className="practical-support"><summary>Inspect {a.lines.length} saved order or credit {a.lines.length===1?'line':'lines'}</summary><div className="table-scroll"><table><thead><tr><th>Record</th><th>Product</th><th>Quantity</th><th>Status in export</th><th>Recorded value</th><th>Age at cutoff</th></tr></thead><tbody>{a.lines.map(l=><tr key={l.ref}><td>{l.order_id}</td><td>{l.sku}</td><td>{l.qty}</td><td>{l.status}</td><td>{typeof l.amount_cents==='number'?exactMoney(l.amount_cents):'Unknown'}</td><td>{l.age_days!=null?`${l.age_days} days`:'Unknown'}</td></tr>)}</tbody></table></div></details>}
  <details className="practical-support"><summary>About this check</summary>{!!active.length&&<p>{a.why}</p>}<p>{a.afterward}</p></details>
  {!!history.length&&<details className="practical-support"><summary>Earlier internal inquiries</summary>{history.map(i=><InquiryReview key={i.id} oid={oid} inquiry={i} eligible={false} allowedFindingTasks={[]}/>)}</details>}
 </article>;
}
function FindingEntry({task,lines}:{task:PracticalTask;lines:PracticalAction['lines']}){
 const [finding,setFinding]=useState(''),[source,setSource]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(''),[error,setError]=useState('');
 async function submit(){setBusy(true);setError('');try{const r=await request<{requires_reassessment:boolean}>(`/investigations/${encodeURIComponent(task.id)}/resolve`,'POST',{resolution:`${finding.trim()}\nVerified source: ${source.trim()}`});setSaved(r.requires_reassessment?'Finding recorded. Clearline will review this account automatically.':'Finding recorded. No new account review was needed.');refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <><p>{task.question}</p><RecordGuidance task={task} lines={lines}/><label>Verified finding<textarea value={finding} onChange={e=>setFinding(e.target.value)} placeholder="Record what you confirmed; leave the check open if you cannot verify it."/></label><label>Supporting record or person<input value={source} onChange={e=>setSource(e.target.value)}/></label><button type="button" className="action-link" disabled={busy||!!saved||!finding.trim()||!source.trim()||!recordCoverage(task,lines,finding)} onClick={submit}>Confirm this finding</button>{saved&&<p role="status">{saved}</p>}{error&&<p role="alert">{error}</p>}</>;
}
export function PracticalNext({work,inquiries,inquiryError}:InquiryProps&{work:ContactWorkData}){
 const action=work.practical_actions?.[0],latest=reviewStatus(work.review_job);
 const pendingReview=work.review_job&&['running','queued'].includes(work.review_job.status);
 if(pendingReview){
  const inquiry=inquiries?.inquiries.find(i=>i.job_id===work.review_job?.id);
  const next=inquiry?.pending_task_ids.length?inquiryNext({role_key:inquiry.role_key??'',role:inquiry.responsibility,control:'finding',task_ids:inquiry.pending_task_ids},inquiry):undefined;
  return <div className="practical-next"><strong>{work.review_job?.status==='running'?'Clearline is reassessing this account':'Account reassessment queued'}</strong><p>Clearline will update the recommendation using the verified evidence.</p>{next&&<p>{next.text}</p>}
   {inquiry&&<Link className="practical-reference" href="#commercial-work">See progress in What Needs Verification</Link>}</div>;
 }
 if(!action)return <p>{latest||'No additional human verification is requested for the current recommendation.'}</p>;
 if(inquiryError&&!inquiries&&action.can_prepare_internal)return <p role="alert">The current internal correspondence could not load. Refresh to check whether this request was sent.</p>;
 if(!inquiries&&inquiryError!==undefined&&action.can_prepare_internal)return <p>Checking current internal correspondence…</p>;
 const [inquiry,...otherRequests]=currentInquiries(action,inquiries);
 const otherProgress=[...otherRequests.map(i=>({action,inquiry:i})),...(work.practical_actions??[]).slice(1).flatMap(other=>
  currentInquiries(other,inquiries).map(i=>({action:other,inquiry:i})))];

 const next=inquiry?inquiryNext(action,inquiry):{title:action.title,text:action.next_step};
 return <div className="practical-next"><strong>{next.title}</strong><p>{next.text}</p><p>{action.why}</p>
  <Link className="practical-reference" href={`#${encodeURIComponent(practicalAnchor(action.id))}`}>{inquiry&&inquiry.status!=='awaiting_approval'?'See progress in What Needs Verification':'Complete this in What Needs Verification'}</Link>
  {otherProgress.map(({action:other,inquiry:i})=><p key={i.id} className="practical-progress">
   <Link className="practical-reference" href={`#${encodeURIComponent(practicalAnchor(other.id))}`}>{other.title}</Link> · {inquiryNext(other,i).title}
  </p>)}
  {latest&&<p role="status">{latest}</p>}
 </div>;
}
