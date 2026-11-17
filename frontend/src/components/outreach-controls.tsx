'use client';
import {useId,useState} from 'react';
import {refresh,request} from '@/lib/api';

export type Restriction={id:string;kind:'pause'|'do_not_contact';scope:'account'|'recipient'|'thread';recipient:string;reason:string;source:string;reconsider_on?:string|null};
type Props={id:string;restrictions:Restriction[];recipient?:string|null};
type FormMode='pause'|'do_not_contact';

export function OutreachControls({id,restrictions,recipient}:Props){
 const formId=useId();
 const [mode,setMode]=useState<FormMode|null>(null);
 const [scope,setScope]=useState(''),[address,setAddress]=useState(recipient||'');
 const [reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [clarify,setClarify]=useState<string|null>(null);
 const paused=restrictions.some(r=>r.kind==='pause');
 const stopped=restrictions.some(r=>r.kind==='do_not_contact'&&r.scope==='account');

 function openForm(next:FormMode,restriction?:Restriction){
  setMode(next);setReason('');setError('');setClarify(restriction?.id||null);
  setScope(restriction?'recipient':'');setAddress(restriction?.recipient||recipient||'');
 }
 async function save(action:FormMode|'resume',date=''){
  setBusy(true);setError('');
  try{
   await request(`/accounts/${id}/outreach-control`,'POST',{action,scope:action==='do_not_contact'?scope:'account',
    reason,recipient:action==='do_not_contact'&&scope==='recipient'?address:'',reconsider_on:action==='pause'&&date?date:null,
    clarify_id:action==='do_not_contact'?clarify:null});
   setMode(null);setReason('');setClarify(null);refresh();
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <div className="account-contact-actions">
  {!stopped&&<div className="contact-action-row" role="group" aria-label="Customer contact actions">
   {paused?<button type="button" className="action-link" disabled={busy} onClick={()=>save('resume')}>Resume outreach</button>:
    <button type="button" className="action-link" disabled={busy} aria-expanded={mode==='pause'} aria-controls={mode==='pause'?formId:undefined} onClick={()=>mode==='pause'?setMode(null):openForm('pause')}>Pause outreach</button>}
   <button type="button" className="action-link contact-stop" disabled={busy} aria-expanded={mode==='do_not_contact'} aria-controls={mode==='do_not_contact'?formId:undefined} onClick={()=>mode==='do_not_contact'?setMode(null):openForm('do_not_contact')}>Do not contact</button>
  </div>}
  {restrictions.map(r=><div key={r.id} role="status" className="notice">
   <b>{r.kind==='pause'?'Outreach paused':r.scope==='account'?'Do Not Contact · entire account':r.scope==='recipient'?`Do Not Contact · ${r.recipient}`:'Opt-out scope needs verification'}</b>
   <p>{r.reason}</p>{r.reconsider_on&&<small>Reconsider on {r.reconsider_on}. Resume manually when appropriate.</small>}
   <small>{r.source==='simulated_customer_reply'?'Recorded from the simulated customer reply':'Recorded by a salesperson'}</small>
   {r.scope==='thread'&&<button type="button" disabled={busy} className="action-link" onClick={()=>openForm('do_not_contact',r)}>Verify who the opt-out covers</button>}
  </div>)}
  {mode&&<form key={mode} id={formId} className="contact-action-form" aria-label={mode==='pause'?'Pause outreach':'Record an opt-out'} onSubmit={e=>{e.preventDefault();void save(mode,String(new FormData(e.currentTarget).get('reconsider_on')||''))}}>
   {mode==='pause'?<p>Emails and follow-ups stay paused until you resume outreach.</p>:<><label>Who asked to stop contact?<select required value={scope} onChange={e=>setScope(e.target.value)}>
    <option value="">Choose who the request covers</option><option value="account">Entire account</option><option value="recipient">One recipient</option></select></label>
    {scope==='recipient'&&<label>Recipient covered by the request<input required type="email" value={address} onChange={e=>setAddress(e.target.value)}/></label>}</>}
   <label>{mode==='pause'?'Reason for the pause':'Original opt-out request or source'}<textarea required value={reason} onChange={e=>setReason(e.target.value)}/></label>
   {mode==='pause'&&<label>Reconsider on (optional)<input type="date" name="reconsider_on"/></label>}
   <div className="contact-action-row"><button type="submit" className="action-link" disabled={busy||!reason.trim()||(mode==='do_not_contact'&&!scope)}>{mode==='pause'?'Save pause':'Confirm do not contact'}</button>
    <button type="button" className="action-link" disabled={busy} onClick={()=>{setMode(null);setError('')}}>Cancel</button></div>
  </form>}{error&&<p role="alert">{error}</p>}
 </div>
}
