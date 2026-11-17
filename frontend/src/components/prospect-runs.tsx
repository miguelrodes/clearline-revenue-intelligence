'use client';
import {useEffect,useRef,useState,type FormEvent,type ReactNode} from 'react';
import {request,refresh,useApi} from '@/lib/api';
import {display,pipelinePath} from '@/lib/prospect-pipeline';

type Scope={eligible_count:number;scope:string;max_cost_usd:number;remaining_usd:number;enabled:boolean;disabled_reason?:string;skipped?:unknown[]};
type Result={job_ids:string[];skipped?:unknown[]};
type RequestBody=Record<string,unknown>;
type Mode='discovery'|'research';
const dollars=(value:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:3}).format(value);
function RunStatus({id}:{id:string}){
 const {data,error}=useApi<{kind:string;status:string;error?:string|null;result?:{candidate_ids?:string[]}}>(pipelinePath+'/jobs/'+encodeURIComponent(id));
 const finished=data&&['completed','failed','cancelled','blocked_config'].includes(data.status);
 const wasFinished=useRef(false);
 useEffect(()=>{if(finished&&!wasFinished.current){wasFinished.current=true;refresh()}},[finished]);
 if(error)return <p role="alert">{error}</p>;
 return <p role="status">{data?.kind.includes('discover')?'Discovery':'Prospect work'} · {data?display(data.status):'Queued'}{data?.error?' · '+data.error:''}{data?.status==='completed'&&data.result?.candidate_ids?' · '+data.result.candidate_ids.length+' candidates recorded':''}</p>;
}
function ConfirmRun({mode,body,buttonLabel,allowed=true,children}:{mode:Mode;body:RequestBody;buttonLabel:string;allowed?:boolean;children?:ReactNode}){
 const [scope,setScope]=useState<{key:string;value:Scope}|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[jobIds,setJobIds]=useState<string[]>([]),[notice,setNotice]=useState('');
 const lock=useRef(false);
 const key=JSON.stringify(body);
 const currentKey=useRef(key);currentKey.current=key;
 const preview=scope?.key===key?scope.value:null;
 const bounded=!!preview&&Number.isFinite(preview.max_cost_usd)&&preview.max_cost_usd>=0&&Number.isFinite(preview.remaining_usd)&&preview.remaining_usd>=preview.max_cost_usd;
 const canConfirm=Boolean(preview?.enabled&&preview.eligible_count>0&&bounded);
 async function submit(e:FormEvent){
  e.preventDefault();if(lock.current||!allowed)return;
  lock.current=true;setBusy(true);setError('');setNotice('');
  try{
   if(!preview){
    const value=await request<Scope>(pipelinePath+'/'+mode+'/preview','POST',body);
    if(key===currentKey.current)setScope({key,value});
   }else{
    if(!canConfirm)return;
    const result=await request<Result>(pipelinePath+'/'+mode,'POST',{...body,confirmed:true});
    setJobIds(result.job_ids);setScope(null);
    setNotice(result.job_ids.length?'Request saved. Progress will appear below.':'This scope has no new work to run.');refresh();
   }
  }catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
 }
 return <form onSubmit={submit} className="prospect-run-form">
  {children}
  {preview&&<div className="run-estimate" role="status">
   <strong>{mode==='discovery'?'Discovery scope':'Research scope'}</strong>
   <p>{preview.scope}</p>
   {Number.isFinite(preview.max_cost_usd)&&Number.isFinite(preview.remaining_usd)?<p>Spending limit for this request: {dollars(preview.max_cost_usd)}. Remaining budget: {dollars(preview.remaining_usd)}.</p>:<p>Spending limits are unavailable. This request cannot start.</p>}
   {!!preview.skipped?.length&&<p>{preview.skipped.length} already researched or ineligible prospect{preview.skipped.length===1?' will':'s will'} be skipped.</p>}
   {!preview.enabled&&<p>{preview.disabled_reason||'This environment cannot start paid work.'}</p>}
  </div>}
  <div className="button-row"><button className="action-link" type="submit" disabled={busy||!allowed||Boolean(preview&&!canConfirm)}>
   {busy?'Checking…':preview?mode==='discovery'?'Confirm discovery':'Confirm research':buttonLabel}
  </button>{preview&&<button className="action-link" type="button" disabled={busy} onClick={()=>{setScope(null);setError('')}}>Cancel</button>}</div>
  {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  {jobIds.map(id=><RunStatus key={id} id={id}/>)}
 </form>;
}

export function DiscoveryForm(){
 const [state,setState]=useState('WY'),[category,setCategory]=useState('Correctional institutions'),[keywords,setKeywords]=useState('');
 const [maximum,setMaximum]=useState(10),[instructions,setInstructions]=useState(''),[directory,setDirectory]=useState('');
 return <ConfirmRun mode="discovery" buttonLabel="Preview discovery" allowed={Boolean(state.trim()&&category.trim()&&maximum>=1&&maximum<=15)} body={{
  state:state.trim().toUpperCase(),category:category.trim(),keywords:keywords.trim(),instructions:instructions.trim(),maximum,...(directory.trim()?{directory_url:directory.trim()}:{})
 }}>
  <p>Find real institutions in an official directory. New candidates receive a screening score; you choose which ones to research.</p>
  <div className="prospect-discovery-fields"><label>State abbreviation<input value={state} required pattern="[a-zA-Z]{2}" maxLength={2} onChange={e=>setState(e.target.value.toUpperCase())}/></label>
   <label>Institution category<input value={category} required onChange={e=>setCategory(e.target.value)}/></label>
   <label>Maximum new candidates<input type="number" required min={1} max={15} value={Number.isNaN(maximum)?'':maximum} onChange={e=>setMaximum(e.target.valueAsNumber)}/></label>
  </div>
  <label>Official directory URL <span className="muted">(optional for Wyoming and California corrections)</span><input type="url" placeholder="https://agency.gov/directory" value={directory} onChange={e=>setDirectory(e.target.value)}/></label>
  <label>Keywords <span className="muted">(optional)</span><input value={keywords} onChange={e=>setKeywords(e.target.value)}/></label>
  <label>Discovery instructions <span className="muted">(optional)</span><textarea rows={2} placeholder="For example, focus on correctional institutions with documented mail-screening operations." value={instructions} onChange={e=>setInstructions(e.target.value)}/></label>
 </ConfirmRun>;
}

export function ResearchForm({selected,refreshExisting=false}:{selected:{id:string;name:string}[];refreshExisting?:boolean}){
 return <ConfirmRun mode="research" body={{candidate_ids:selected.map(r=>r.id),refresh:refreshExisting}} allowed={selected.length>0&&selected.length<=3} buttonLabel={refreshExisting?'Preview research refresh':'Research selected prospects'}>
  {selected.length>0&&<p><strong>{selected.length} selected for research</strong> · {selected.map(r=>r.name).join(', ')}</p>}
  {refreshExisting&&<p>A fresh report uses the research budget. The current saved research remains available.</p>}
 </ConfirmRun>;
}
