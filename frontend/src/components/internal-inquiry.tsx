'use client';
import {createContext,useContext,useId,useState,type ReactNode} from 'react';
import {refresh,request,time} from '@/lib/api';
import {recordCoverage,replyTasks,sentScope,type InquiryData,type InternalInquiry,type InquiryReply,type PracticalAction,type PracticalTask} from '@/lib/practical-actions';

type Finding={task_id:string;finding:string;source:string};
const endpoint=(oid:string)=>`/accounts/${encodeURIComponent(oid)}/internal-inquiries`;
const GroupContext=createContext<{active:string;select:(id:string)=>void}|null>(null);

export function DisclosureGroup({children}:{children:ReactNode}){
 const [active,select]=useState('');
 return <GroupContext.Provider value={{active,select}}>{children}</GroupContext.Provider>;
}

/** Sibling forms share one open slot. A visited form retains its unsaved fields. */
export function ActionDisclosure({label,children,primary=false,onOpen}:{label:string;children:ReactNode;primary?:boolean;onOpen?:()=>void}){
 const id=useId(),group=useContext(GroupContext);
 const [visited,setVisited]=useState(false);
 const expanded=group?.active===id;
 return <div><button type="button" className={`practical-disclosure ${primary?'action-link':'practical-secondary'}`} aria-expanded={expanded} aria-controls={id} onClick={()=>{
  if(!expanded){setVisited(true);onOpen?.()}
  group?.select(expanded?'':id);
 }}>{label}</button><div id={id} hidden={!expanded}>{visited&&children}</div></div>;
}

function useWrite(){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function write(path:string,body:unknown,done?:(v:InternalInquiry)=>void){
  if(busy)return;setBusy(true);setError('');try{const saved=await request<InternalInquiry>(path,'POST',body);done?.(saved);refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return {busy,error,write};
}

export function PrepareInternal({oid,action,data,primary}:{oid:string;action:PracticalAction;data:InquiryData;primary:boolean}){
 const {busy,error,write}=useWrite();
 const saved=data.recipients.find(r=>r.group_id===action.id);
 return <ActionDisclosure label="Prepare internal email" primary={primary} onOpen={()=>{
  if(saved?.recipient&&!busy)void write(endpoint(oid),{group_id:action.id});
 }}>
  {saved?.recipient?<p role="status">{error||`Preparing the request for ${saved.recipient}…`}</p>:<RecipientEntry oid={oid} action={action}/>}
 </ActionDisclosure>;
}

function RecipientEntry({oid,action,done}:{oid:string;action:PracticalAction;done?:()=>void}){
 const [recipient,setRecipient]=useState(''),[evidence,setEvidence]=useState(''),[verified,setVerified]=useState(false);
 const {busy,error,write}=useWrite();
 return <div className="practical-entry"><p>Who can answer this request for Clearline? Use the internal contact responsible for this check.</p>
  <label>Internal work email<input type="email" value={recipient} onChange={e=>setRecipient(e.target.value)}/></label>
  <label>How did you verify this internal recipient?<input value={evidence} placeholder="Internal directory entry or confirmation from the account owner" onChange={e=>setEvidence(e.target.value)}/></label>
  <label className="contact-clearance-confirm"><input type="checkbox" checked={verified} onChange={e=>setVerified(e.target.checked)}/> I verified this person can receive these internal records.</label>
  <button type="button" className="action-link" disabled={busy||!/^\S+@\S+\.\S+$/.test(recipient.trim())||evidence.trim().length<8||!verified}
   onClick={()=>write(endpoint(oid),{group_id:action.id,recipient:recipient.trim(),verification_evidence:evidence.trim()},done)}>{busy?'Preparing…':'Prepare draft for review'}</button>
  {error&&<p role="alert">{error}</p>}
 </div>;
}

function DraftReview({oid,inquiry,routing}:{oid:string;inquiry:InternalInquiry;routing:{action:PracticalAction;data:InquiryData}}){
 const {busy,error,write}=useWrite();
 const [subject,setSubject]=useState(inquiry.subject),[body,setBody]=useState(inquiry.body),[visited,setVisited]=useState(false);
 const group=useContext(GroupContext);
 const id=useId(),base=`${endpoint(oid)}/${encodeURIComponent(inquiry.id)}`;
 const dirty=subject!==inquiry.subject||body!==inquiry.body,changing=group?.active===id;
 return <section className="practical-entry" aria-label="Internal draft for approval"><p>To {inquiry.recipient} · Version {inquiry.version} · Simulated delivery</p>
  <button type="button" className="practical-secondary practical-disclosure" aria-expanded={changing} aria-controls={id} disabled={busy||dirty} onClick={()=>{setVisited(true);group?.select(changing?'':id)}}>Change internal recipient</button>
  <div id={id} hidden={!changing}>{visited&&<RecipientEntry oid={oid} action={routing.action} done={()=>group?.select('')}/>}</div>
  <div data-save-pending={dirty} hidden={changing}>
   <label>Internal email subject<input value={subject} onChange={e=>setSubject(e.target.value)}/></label>
   <label>Internal message<textarea rows={6} value={body} onChange={e=>setBody(e.target.value)}/></label>
   {dirty&&<button type="button" className="action-link" disabled={busy||!subject.trim()||!body.trim()} onClick={()=>write(base+'/edit',{snapshot_hash:inquiry.snapshot_hash,subject:subject.trim(),body:body.trim()})}>Save edits for review</button>}
   <button type="button" className="action-link" disabled={busy||dirty} onClick={()=>write(base+'/approve',{snapshot_hash:inquiry.snapshot_hash})}>Approve version {inquiry.version} and simulate sending</button>
  </div>
  {error&&<p role="alert">{error}</p>}
  {/prepare (?:the request again|and review a current draft)/i.test(error)&&<button type="button" className="action-link" disabled={busy} onClick={()=>write(endpoint(oid),{group_id:inquiry.group_id})}>Prepare the current request for review</button>}
 </section>;
}

function EarlierVersions({inquiry}:{inquiry:InternalInquiry}){
 if(!inquiry.previous_versions?.length)return null;
 return <details className="practical-support"><summary>Earlier draft versions ({inquiry.previous_versions.length})</summary>{inquiry.previous_versions.map(v=><details key={v.version}><summary>Version {v.version} · {v.subject}</summary><p>{v.recipient} · {time(v.created_at)}</p><p className="email-copy">{v.body}</p></details>)}</details>;
}

function SentHistory({inquiry}:{inquiry:InternalInquiry}){
 const states=inquiry.record_states??[];
 const names={draft:'Draft',status_requested:'Status requested',response_recorded:'Response recorded · unverified',verified:'Finding verified',closed:'Check closed'};
 return <div className="inquiry-history">
  <strong>{inquiry.replies.length?'Sent internal email':'Last action: Internal email sent'}</strong>
  <p>{inquiry.sent_at&&<><time dateTime={inquiry.sent_at}>{time(inquiry.sent_at)}</time> · </>}{inquiry.recipient} · Version {inquiry.sent_version??inquiry.version} · Simulated delivery</p>
  <p>{inquiry.subject} · {sentScope(inquiry)}</p>
  <details className="practical-support"><summary>View sent email</summary><p className="email-copy">{inquiry.body}</p></details>
  {!!states.length&&<details className="practical-support"><summary>View requested records ({states.length})</summary>
   <ul>{states.map(r=><li key={r.order_id}><strong>{r.order_id}</strong> · {r.line_refs.length} {r.line_refs.length===1?'line':'lines'} · {names[r.status]}</li>)}</ul>
  </details>}
 </div>;
}

export function InquiryReview({oid,inquiry,eligible,allowedFindingTasks,contact=false,routing}:{oid:string;inquiry:InternalInquiry;eligible:boolean;allowedFindingTasks:string[];contact?:boolean;routing?:{action:PracticalAction,data:InquiryData}}){
 const {busy,error,write}=useWrite();const [reply,setReply]=useState('');
 const base=`${endpoint(oid)}/${encodeURIComponent(inquiry.id)}`;
 const editable=eligible&&inquiry.status==='awaiting_approval'&&routing;
 const sent=!!inquiry.sent_at||['sent_simulated','reply_recorded','verified'].includes(inquiry.status);
 const findings=(inquiry.task_states??[]).filter(t=>t.status==='verified'&&t.finding);
 const receiving=sent&&eligible&&inquiry.pending_task_ids.length>0;
 return <section aria-label="Internal email">
  {editable?<DraftReview inquiry={inquiry} oid={oid} routing={routing}/>:sent?<SentHistory inquiry={inquiry}/>:<details className="practical-support"><summary>{inquiry.subject} · {inquiry.status.replaceAll('_',' ')}</summary><p className="email-copy">{inquiry.body}</p></details>}
  {findings.length===1?<p><strong>Verified finding</strong> · {findings[0].finding}</p>:findings.length>1?<details className="practical-support"><summary>Verified findings ({findings.length})</summary>{findings.map(t=><p key={t.task_id}>{t.finding}</p>)}</details>:null}
  {inquiry.workflow_state==='verified'&&<p>Verification complete. The recorded findings are available for the account recommendation.</p>}
  {sent&&(inquiry.replies??[]).map(r=>{
   const pending=replyTasks(r,inquiry,allowedFindingTasks);
   if(eligible&&!contact&&pending.length)return <ActionDisclosure key={r.id} primary label="Review and record the finding"><ReplyReview reply={r} inquiry={inquiry} base={base} pending={pending}/></ActionDisclosure>;
   return <details key={r.id} className="practical-support"><summary>{r.confirmed_task_ids.length?'Reviewed internal response':'Read unverified internal response'}</summary><p className="email-copy">{r.body}</p>
    {r.confirmations?.map(c=><p key={c.task_id}>{c.finding} · {c.source}</p>)}</details>;
  })}
  <EarlierVersions inquiry={inquiry}/>
  {receiving&&<ActionDisclosure label="Demo · Record simulated internal reply"><div className="practical-entry"><label>What did the internal recipient say?<textarea value={reply} onChange={e=>setReply(e.target.value)} rows={3}/></label>
   <button type="button" className="practical-secondary" disabled={busy||!reply.trim()} onClick={()=>write(base+'/reply',{body:reply.trim()},()=>setReply(''))}>Record reply as unverified</button>
   {error&&<p role="alert">{error}</p>}</div></ActionDisclosure>}
 </section>;
}

function ReplyReview({reply,inquiry,base,pending}:{reply:InquiryReply;inquiry:InternalInquiry;base:string;pending:PracticalTask[]}){
 const {busy,error,write}=useWrite();const [answers,setAnswers]=useState<Record<string,Finding>>({});
 const chosenTasks=pending.filter(t=>answers[t.id]);const chosen=chosenTasks.map(t=>answers[t.id]);
 function toggle(t:PracticalTask){setAnswers(prev=>{const copy={...prev};if(copy[t.id])delete copy[t.id];else copy[t.id]={task_id:t.id,finding:reply.suggested_findings?.[t.id]??(pending.length===1?(reply.suggested_finding||reply.body):''),source:''};return copy})}
 return <div className="practical-entry"><strong>Recorded internal reply · unverified statement</strong><p className="email-copy">{reply.body}</p>{reply.record_refs?.length>0&&<p>Referenced records: {reply.record_refs.join(', ')}</p>}
  <p>Select the checks you can verify against a supporting record. Other checks stay open.</p>
  {pending.map(t=><div key={t.id}><label className="contact-clearance-confirm"><input type="checkbox" checked={!!answers[t.id]} onChange={()=>toggle(t)}/> {t.title}</label>{answers[t.id]&&<><RecordGuidance task={t} lines={inquiry.lines||[]}/><label>Verified finding for {t.title}<textarea value={answers[t.id].finding} onChange={e=>setAnswers({...answers,[t.id]:{...answers[t.id],finding:e.target.value}})}/></label><label>Supporting source for {t.title}<input value={answers[t.id].source} onChange={e=>setAnswers({...answers,[t.id]:{...answers[t.id],source:e.target.value}})}/></label></>}</div>)}
  <button type="button" className="action-link" disabled={busy||!chosen.length||chosenTasks.some(t=>!answers[t.id].finding.trim()||!answers[t.id].source.trim()||!recordCoverage(t,inquiry.lines||[],answers[t.id].finding))} onClick={()=>write(base+'/confirm',{reply_id:reply.id,findings:chosen},()=>setAnswers({}))}>Confirm selected findings</button>
  {error&&<p role="alert">{error}</p>}</div>;
}
export function RecordGuidance({task,lines}:{task:PracticalTask;lines:PracticalAction['lines']}){
 if(!task.record_ids.length)return null;
 const multi=task.record_ids.some(id=>lines.filter(l=>l.order_id===id&&task.record_refs.includes(l.ref)).length>1);
 return <p>Include the verified outcome for {task.record_ids.join(', ')}.{multi?' State the outcome for each product or explicitly confirm it covers all lines.':''}</p>;
}
