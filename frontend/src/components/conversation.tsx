'use client';
import {conversationSummary} from '@/lib/account-presentation';
import {StatusBadge} from './status-badge';
import {useId,useRef,useState,type FormEvent} from 'react';
import {label,request,refresh,time,useApi} from '@/lib/api';

type Interpretation={intent:string;effective_status:string;conversation_status:string;rationale:string;recommended_action:string;facts:{fact:string;quote:string}[];products:{description:string;sku:string|null;quantity:number|null;unit:string|null}[];uncertainties:string[]};
type Message={sent_review?:string|null;id:string;direction:string;subject:string;body:string;created_at:string;status:string;reply_to:string|null;interpretation:Interpretation|null;job:{id:string;status:string;error:string|null}|null};
type Thread={provider?:string;status:string;messages:Message[];context:{outreach_policy:string;contact:{name?:string;email?:string;phone?:string}|null;channel:{route:string;distributor?:string}|null};tasks:{id:string;title:string;status:string}[]};

function MessageText({message,parentSubject}:{message:Message;parentSubject?:string}){
 const [expanded,setExpanded]=useState(false);
 const bodyId=useId();
 const subject=message.subject?.trim()||'No subject';
 const toggleLabel=expanded?'Hide message':'Show message';
 return <>
  <div className="conversation-message-subject">
   <b>{subject}</b>
   <button type="button" className="text-button" aria-label={`${toggleLabel}: ${subject}`}
    aria-expanded={expanded} aria-controls={bodyId} onClick={()=>setExpanded(!expanded)}>{toggleLabel}</button>
  </div>
  <div id={bodyId} hidden={!expanded}>
   <p className="email-copy">{message.body}</p>
   {message.sent_review&&<p><strong>After-send review</strong> · {message.sent_review}</p>}
   {message.reply_to&&<small>In response to: {parentSubject||'Earlier message'}</small>}
  </div>
 </>;
}

function SimulatedReplyControls({accountId,delivered}:{accountId:string;delivered:Message[]}){
 const [selected,setSelected]=useState('');
 const [body,setBody]=useState('');
 const [saving,setSaving]=useState(false);
 const [feedback,setFeedback]=useState('');
 const [error,setError]=useState('');
 const pending=useRef(false);
 const attempt=useRef<{parent:string;body:string;id:string}|null>(null);
 // The API returns conversation history oldest first. Keep the parent fixed once typing starts.
 const parentId=selected||delivered[delivered.length-1].id;
 const parent=delivered.find(message=>message.id===parentId);

 async function save(event:FormEvent){
  event.preventDefault();
  const text=body.trim();
  if(!parent||!text||pending.current)return;
  pending.current=true;
  setSaving(true);setError('');setFeedback('');
  try{
   if(attempt.current?.parent!==parent.id||attempt.current.body!==text){
    attempt.current={parent:parent.id,body:text,id:crypto.randomUUID()};
   }
   const result=await request<{duplicate:boolean}>(`/accounts/${accountId}/conversation/replies`,'POST',{
    reply_to:parent.id,message_id:attempt.current.id,body:text
   });
   setFeedback(result.duplicate?'This reply was already recorded.':'Reply saved. AI interpretation is queued.');
   setBody('');setSelected('');attempt.current=null;
   refresh();
  }catch(e){setError((e as Error).message)}
  finally{pending.current=false;setSaving(false)}
 }

 return <details className="agent-guidance"><summary>Demo / Testing Controls</summary>
  <form className="practical-entry" onSubmit={save}>
   <label>Record simulated reply
    <textarea rows={3} maxLength={12000} value={body} disabled={saving} onChange={e=>{
     setSelected(parentId);setBody(e.target.value);setError('');setFeedback('');
    }}/>
   </label>
   {delivered.length===1?<small>Replying to: {parent?.subject}</small>:<label>Replying to
    <select value={parentId} disabled={saving} onChange={e=>{setSelected(e.target.value);setFeedback('');setError('')}}>
     {delivered.map(m=><option key={m.id} value={m.id}>{m.subject} · {time(m.created_at)}</option>)}
    </select></label>}
   <button className="action-link" type="submit" disabled={saving||!body.trim()||!parent}>{saving?'Saving…':'Save'}</button>
   {error&&<p role="alert">{error}</p>}
   {feedback&&<p role="status">{feedback}</p>}
  </form>
 </details>;
}

export function ConversationPanel({id,accountStatus,crmNote,canRecordReply=false}:{id:string;accountStatus?:string;crmNote?:string;canRecordReply?:boolean}){
 const {data:t,error}=useApi<Thread>(`/accounts/${id}/conversation`);const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');
 if(error)return <p role="alert">{error}</p>;if(!t)return null;
 const delivered=t.messages.filter(m=>m.direction==='outbound'&&m.status==='sent_simulated');
 return <section className="panel" id="conversation"><div className="panel-head"><h2>Customer Conversations</h2><StatusBadge value={t.status} text={`Simulated · ${t.status==='not_started'?'Not started':label(t.status)}`}/></div><div className="content-stack">
 <p className="conversation-summary">{conversationSummary(t,crmNote)}</p>
 {!t.messages.length&&<p>{accountStatus==='approved'?'The approved email is queued for simulated delivery.':accountStatus==='awaiting_approval'?'Review the prepared outreach in Next Action before starting this fictional conversation.':'No email is currently ready for approval. Follow the account recommendation before starting a conversation.'}</p>}
 {t.context.outreach_policy==='stop'&&<p className="notice">Outreach is stopped. This conversation cannot automatically restart sales emails.</p>}
 {t.context.outreach_policy==='channel_review'&&<p className="notice">The customer reports buying through a distributor. Direct outreach is paused until the purchasing route is checked.</p>}
 {t.context.contact&&<p><b>Reported purchasing contact:</b> {[t.context.contact.name,t.context.contact.email,t.context.contact.phone].filter(Boolean).join(' · ')} <small>Fictional reply data · not independently verified</small></p>}
 {t.messages.map(m=><article key={m.id} className="conversation-message"><div className="inline-between"><h3>{m.direction==='outbound'?'Sales email':'Customer reply'}</h3><small>{time(m.created_at)} · Simulated</small></div>
 <MessageText message={m} parentSubject={m.reply_to?t.messages.find(p=>p.id===m.reply_to)?.subject:undefined}/>
 {m.job&&['queued','running','blocked_config','failed'].includes(m.job.status)&&<div role="status"><p>{m.job.status==='running'?'AI is interpreting this reply…':m.job.status==='queued'?'Waiting for AI review…':m.job.error||'AI review could not finish.'}</p>{['failed','blocked_config'].includes(m.job.status)&&<button disabled={busy} onClick={async()=>{setBusy(true);try{await request(`/jobs/${m.job!.id}/retry`,'POST');refresh()}catch(e){setNotice((e as Error).message)}finally{setBusy(false)}}}>Retry AI review</button>}</div>}
 {m.interpretation&&<div className="reply-decision"><h4>AI interpretation · {label(m.interpretation.intent)}</h4><p>{m.interpretation.rationale}</p><p><b>Next step:</b> {m.interpretation.recommended_action}</p><p><b>Result:</b> {label(m.interpretation.conversation_status)}</p>{m.interpretation.products.map((p,i)=><p key={i}><b>Requested:</b> {p.quantity??'Quantity not specified'} {p.unit||''} · {p.description}{p.sku&&` (${p.sku})`}</p>)}<details><summary>Extracted facts and open questions</summary>{m.interpretation.facts.map((f,i)=><p key={i}>{f.fact}<br/><small>Customer said: “{f.quote}”</small></p>)}{m.interpretation.uncertainties.map((u,i)=><p key={i}>{u}</p>)}</details></div>}
 </article>)}
 {t.tasks.filter(x=>['pending','awaiting_approval','approved'].includes(x.status)&&!['no_action','monitor','defer','deferred','lost','opted_out','outreach_paused'].includes(accountStatus||'')).map(x=><div key={x.id} className="notice"><b>{label(x.status)}</b><p>{x.title}</p>{x.status==='awaiting_approval'&&<button className="text-button" onClick={e=>{
   const next=e.currentTarget.closest('.account-profile')?.querySelector('#next-action');
   const response=next?.querySelector<HTMLDetailsElement>('.next-action-draft[data-draft-kind="response"]');
   if(response){response.open=true;response.querySelector('summary')?.focus({preventScroll:true})}
   (response||next)?.scrollIntoView?.({behavior:'smooth',block:'start'});
  }}>Review the prepared response</button>}</div>)}
 {notice&&<p role="status" className="notice">{notice}</p>}
 {canRecordReply&&t.provider==='simulated'&&delivered.length>0&&<SimulatedReplyControls key={id} accountId={id} delivered={delivered}/>}
 </div></section>
}
