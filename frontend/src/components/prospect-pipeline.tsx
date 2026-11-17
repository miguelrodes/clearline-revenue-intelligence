'use client';
import Link from 'next/link';
import {useEffect,useId,useRef,useState,type FormEvent,type MouseEventHandler} from 'react';
import {refresh,request,useApi,number} from '@/lib/api';
import {display,metrics,origins,pipelinePath,stages,type Candidate,type CandidateDetail,type Pipeline,type PipelineAction} from '@/lib/prospect-pipeline';
import {RecommendedActionList,RecommendedActionRow} from './recommended-action';
import {DiscoveryForm,ResearchForm} from './prospect-runs';

import {ProspectActivity} from './prospect-activity';
function prospectBriefTitle(point:string){
 if (/latest discovery run/i.test(point)) return 'Newly discovered';
 if (/discovery emails?/i.test(point)) return 'Emails to review';
 if (/research/i.test(point)) return 'Ready for research';
 return 'Prospect screening';
}
export function PipelineBrief({data,showTitles=false}:{data:Pipeline;showTitles?:boolean}){
 return data.brief.length ? <ul className="brief-summary brief-summary-points">{data.brief.map(point=>
  <li key={point}>{showTitles&&<><strong>{prospectBriefTitle(point)}</strong>{': '}</>}<span>{point}</span></li>
 )}</ul> : <p>No prospect work is waiting.</p>;
}
export function PipelineMetrics({data,compact=false,onMetricClick}:{data:Pipeline;compact?:boolean;onMetricClick?:MouseEventHandler<HTMLAnchorElement>}){
 const id=useId();
 const [hovered,setHovered]=useState<string|null>(null);
 const [focused,setFocused]=useState<string|null>(null);
 const active=hovered??focused;
 useEffect(()=>{
  if(!active)return;
  function dismiss(event:KeyboardEvent){if(event.key==='Escape'){setHovered(null);setFocused(null)}}
  document.addEventListener('keydown',dismiss);
  return ()=>document.removeEventListener('keydown',dismiss);
 },[active]);
 return <div className={compact?'prospect-metrics compact':'prospect-metrics'} aria-label="Prospect pipeline metrics">
  {metrics.filter(([key])=>!compact||['total','high_priority','awaiting_research','awaiting_approval'].includes(key)).map(([key,title,query,description])=>
   <div key={key} className="prospect-metric" onMouseEnter={()=>setHovered(key)} onMouseLeave={()=>setHovered(null)}>
    <Link href={'/screening'+(query?'?'+query:'')+'#candidates'} scroll={false} onClick={onMetricClick}
     aria-describedby={id+'-'+key} onFocus={()=>setFocused(key)} onBlur={()=>setFocused(null)}>
     <span>{title}</span><strong>{number(data.metrics[key]??0)}</strong>
    </Link>
    <span id={id+'-'+key} role="tooltip" className="kpi-tooltip" hidden={active!==key}>{description}</span>
   </div>
  )}
 </div>;
}
export function ProspectActionRow({action,concise=false}:{action:PipelineAction;concise?:boolean}){
 return <RecommendedActionRow title={action.title} description={concise?action.description.split(/(?<=[.!?])\s+/)[0]:action.description}
  href={action.href} buttonLabel={action.button_label} scopeLabel={action.count!=null&&action.count>0?`${number(action.count)} candidate${action.count===1?'':'s'}`:undefined}/>;
}
export function PipelineActions({actions,label='Prospect recommendations',concise=false}:{actions:PipelineAction[];label?:string;concise?:boolean}){
 return actions.length?<RecommendedActionList label={label} rowsKey={actions.map(a=>a.id).join('|')}>
  {actions.map(a=><li key={a.id}><ProspectActionRow action={a} concise={concise}/></li>)}
 </RecommendedActionList>:<p>No prospect actions require attention.</p>;
}
export function PipelineOverview(){
 const {data,error}=useApi<Pipeline>(pipelinePath+'?limit=1');
 return <section className="overview-area" aria-label="Prospecting priorities">
  <h2>Prospect actions</h2>
  {error?<p role="alert">{error}</p>:!data?.metrics?<p role="status">Loading prospect priorities…</p>:<div className="operational-brief"><PipelineActions actions={data.actions}/></div>}
 </section>;
}
function filterState(params:string){
 const q=new URLSearchParams(params);
 if(q.get('stage')==='outreach_draft_ready')q.set('stage','awaiting_delivery');
 return Object.fromEntries(['q','state','segment','origin','qualification','stage','min_score'].map(key=>[key,q.get(key)||'']));
}
function researchChoice(row:Candidate){return row.origin!=='fictional_csv'&&row.verified&&row.researchable&&!row.researched}
function tableHref(row:Candidate,filters:Record<string,string>){
 const detail=row.origin==='fictional_csv'?row.href:row.detail_href||'/screening?candidate='+encodeURIComponent(row.id);
 const forAction=['awaiting_approval','needs_verification','research_completed','awaiting_research'].includes(filters.stage);
 const href=forAction&&row.action_href?row.action_href:detail;
 if(!href.startsWith('/screening?'))return href;
 const [path,fragment]=href.split('#');
 const query=new URLSearchParams(path.slice('/screening?'.length));
 for(const [key,value] of Object.entries(filters))if(value)query.set(key,value);
 return '/screening?'+query.toString()+(fragment?'#'+fragment:'');
}
function researchStatus(row:Candidate){
 if(row.origin==='fictional_csv')return row.qualification&&display(row.qualification);
 const unassessed=['unassessed','not_assessed',''].includes(row.qualification);
 if(row.researched){
  const qualification=row.qualification==='discovery_only'?'Discovery conversation only':unassessed?'Qualification pending':display(row.qualification);
  return row.stage==='research_completed'?qualification:'Research completed · '+qualification;
 }
 if(researchChoice(row)&&row.stage==='screened')return 'Awaiting in-depth research';
 return unassessed?'':display(row.qualification);
}
function sameScreeningFactors(rows:Candidate[]){
 const first=rows[0];
 return rows.length>1&&first.score!=null&&first.factors.length>0&&rows.every(row=>
  row.origin!=='fictional_csv'&&row.score===first.score&&row.score_version===first.score_version&&row.factors.length===first.factors.length&&
  first.factors.every((f,i)=>row.factors[i].key===f.key&&row.factors[i].points===f.points&&row.factors[i].maximum===f.maximum));
}
function CandidateTable({rows,selected,toggle,filters}:{rows:Candidate[];selected:{id:string;name:string}[];toggle:(row:Candidate)=>void;filters:Record<string,string>}){
 return <>{sameScreeningFactors(rows)&&<p className="table-foot">The {rows.length} institutions shown earned the same points on every screening factor.
  {rows[0].factors.some(f=>f.key==='scale'&&f.points===0)&&' Size contributed no points.'} Use their individual source records to choose which to research.</p>}
  <div className="table-scroll"><table><thead><tr><th scope="col">Select</th><th scope="col">Institution</th><th scope="col">Screening score</th><th scope="col">Pipeline stage</th><th scope="col">Next step</th></tr></thead><tbody>
  {rows.map(row=>{const checked=selected.some(s=>s.id===row.id);return <tr key={row.id}>
   <td>{researchChoice(row)?<input type="checkbox" aria-label={'Select '+row.name+' for research'} checked={checked} disabled={!checked&&selected.length>=3} onChange={()=>toggle(row)}/>:<span className="muted" aria-label="Unavailable for new real-world research">—</span>}</td>
   <td><Link className="action-link" href={tableHref(row,filters)}>{row.name}</Link>
    <small>{[row.state,display(row.segment),origins[row.origin]].filter(Boolean).join(' · ')}</small></td>
   <td>{row.score==null?'Awaiting evidence':<strong>{row.score.toFixed(1)} / 100</strong>}<small>{row.segment&&row.reason.startsWith(row.segment+':')?display(row.segment)+row.reason.slice(row.segment.length):row.reason}</small>
    {row.comparison&&<details><summary>Customer comparison</summary><p>{row.comparison}</p></details>}</td>
   <td>{display(row.stage)}<small>{researchStatus(row)}</small></td>
   <td>{row.next_action}</td>
  </tr>})}
 </tbody></table></div></>;
}
export function PipelineWorkspace({params=''}:{params?:string}){
 const [filters,setFilters]=useState(()=>filterState(params)),[offset,setOffset]=useState(0);
 const [selected,setSelected]=useState<{id:string;name:string}[]>([]);
 const [discover,setDiscover]=useState(()=>new URLSearchParams(params).get('discover')==='1');
 const search=new URLSearchParams({limit:'25',offset:String(offset)});
 for(const [key,value] of Object.entries(filters))if(value)search.set(key,value);
 const {data,error}=useApi<Pipeline>(pipelinePath+'?'+search);
 const candidates=useRef<HTMLElement>(null);
 const [jump,setJump]=useState(0),lastJump=useRef<number|null>(null);
 const loaded=Boolean(data?.rows);
 useEffect(()=>{
  const section=candidates.current;
  if(!loaded||!section||window.location.hash!=='#candidates'||lastJump.current===jump)return;
  lastJump.current=jump;
  const results=section.querySelector<HTMLElement>('.table-scroll, .empty');
  if(results)results.scrollTop=0;
  const first=results?.querySelector('tbody tr')||results;
  const margin=parseFloat(getComputedStyle(section).scrollMarginTop)||0;
  const room=window.innerHeight-margin;
  // Keep the heading in view unless the filters would push the first result below the viewport.
  const showResults=first&&first.getBoundingClientRect().top-section.getBoundingClientRect().top+Math.min(first.clientHeight,80)>room;
  (showResults&&results?results:section).scrollIntoView?.({block:'start'});
 },[loaded,jump]);
 const clickCurrentMetric:MouseEventHandler<HTMLAnchorElement>=e=>{
  const link=e.currentTarget;
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||
     link.pathname!==window.location.pathname||link.search!==window.location.search)return;
  // The URL may already be open after the user has changed the table's filters or page.
  e.preventDefault();
  if(window.location.hash!==link.hash)window.history.pushState(null,'',link.href);
  setFilters(filterState(link.search));setOffset(0);setJump(n=>n+1);
 };
 function filter(key:string,value:string){setFilters(old=>({...old,[key]:value}));setOffset(0)}
 function toggle(row:Candidate){setSelected(old=>old.some(r=>r.id===row.id)?old.filter(r=>r.id!==row.id):old.length<3?[...old,{id:row.id,name:row.name}]:old)}
 const hasDiscoveryAction=!!data?.actions?.some(a=>a.href.includes('discover=1'));
 const scopedSearch=filters.q.trim()&&Object.entries(filters).some(([key,value])=>key!=='q'&&value);
 return <>
  <div className="page-heading"><h1 className="section-page-title">Prospect Screening</h1>{(discover||!hasDiscoveryAction)&&<button className="action-link" type="button" aria-expanded={discover} aria-controls="discover-prospects" onClick={()=>setDiscover(!discover)}>{discover?'Close discovery':'Discover prospects'}</button>}</div>
  {discover&&<section id="discover-prospects" className="account-section prospect-discovery"><h2>Discover real prospects</h2><DiscoveryForm/></section>}
  {error&&<p role="alert">{error}</p>}
  {data?.metrics&&<section className="operational-brief screening-brief"><div className="brief-heading"><h2>Prospecting brief</h2></div>
   <PipelineBrief data={data}/><PipelineMetrics data={data} onMetricClick={clickCurrentMetric}/>
   <p className="priority-note">High priority ranks candidates for investigation. {(data.metrics.high_priority>2*(data.metrics.real_web+data.metrics.real_manual))?'Most high-priority records are fictional agencies. ':''}Demand, buying intent and revenue potential remain unverified.</p>
  </section>}
  <section id="candidates" ref={candidates} className="prospect-candidates">
   <div className="page-heading"><h2>Candidate pipeline</h2></div>
   <div className="panel"><div className="screening-filters pipeline-filters">
    <label>Institution name<input type="search" placeholder="Find a candidate…" value={filters.q} onChange={e=>filter('q',e.target.value)}/></label>
    <label>Source<select value={filters.origin} onChange={e=>filter('origin',e.target.value)}><option value="">All sources</option><option value="real">All real institutions</option>{Object.entries(origins).map(([key,title])=><option key={key} value={key}>{title}</option>)}</select></label>
    <label>Stage<select value={filters.stage} onChange={e=>filter('stage',e.target.value)}><option value="">All stages</option>{Object.entries(stages).map(([key,title])=><option key={key} value={key}>{title}</option>)}</select></label>
    <label>State<input placeholder="All states" value={filters.state} maxLength={2} onChange={e=>filter('state',e.target.value.toUpperCase())}/></label>
    <label>Institution type<select value={filters.segment} onChange={e=>filter('segment',e.target.value)}><option value="">All types</option>{Array.from(new Set([...(data?.filters?.segments||[]),...(filters.segment?[filters.segment]:[])])).map(v=><option key={v} value={v}>{display(v)}</option>)}</select></label>
    <label>Qualification<select value={filters.qualification} onChange={e=>filter('qualification',e.target.value)}><option value="">All qualifications</option>{Array.from(new Set([...(data?.filters?.qualifications||['not_assessed','qualified','investigate','human_verification','defer','reject']),...(filters.qualification?[filters.qualification]:[])])).map(s=><option key={s} value={s}>{display(s)}</option>)}</select></label>
    <label>Minimum score<input type="number" min="0" max="100" placeholder="Any" value={filters.min_score} onChange={e=>filter('min_score',e.target.value===''?'':String(Math.max(0,Math.min(100,+e.target.value))))}/></label>
    {scopedSearch&&<button className="action-link" onClick={()=>{setFilters({...filterState(''),q:filters.q});setOffset(0)}}>Search all candidates</button>}
    {Object.values(filters).some(Boolean)&&<button className="action-link" onClick={()=>{setFilters(filterState(''));setOffset(0)}}>Clear filters</button>}
   </div>
   {!data?.rows?(error?null:<p className="empty">Loading candidates…</p>):<>
    {!!data.rows.length&&<CandidateTable rows={data.rows} selected={selected} toggle={toggle} filters={filters}/>}
    {!data.rows.length&&<p className="empty">No candidates match these filters.{' '}
     {filters.stage==='awaiting_approval'&&!filters.q&&data.metrics.awaiting_delivery>0&&<Link className="action-link" href="/screening?stage=awaiting_delivery#candidates">View approved outreach awaiting delivery ({number(data.metrics.awaiting_delivery)})</Link>}
    </p>}
    <div className="screening-pagination"><span>{data.total?offset+1:0}–{Math.min(offset+25,data.total)} of {number(data.total)} candidates</span>
     <button className="action-link" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button>
     <button className="action-link" disabled={offset+25>=data.total} onClick={()=>setOffset(offset+25)}>Next</button>
    </div>
   </>}
   </div>
   <div className="research-selection"><h3>In-depth research</h3>{!selected.length&&<p>Select up to three verified real institutions to check their product fit and purchasing process.</p>}
    <ResearchForm selected={selected}/>{!!selected.length&&<button className="action-link" onClick={()=>setSelected([])}>Clear selection</button>}
   </div>
  </section>
  {data?.metrics&&<section className="operational-brief screening-actions"><div className="brief-actions-header"><h2>Recommended actions</h2></div>
   <PipelineActions concise actions={discover?data.actions.filter(a=>!a.href.includes('discover=1')):data.actions}/>
  </section>}
 </>;
}

function publicLink(value:string|undefined){if(!value)return null;try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:null}catch{return null}}
function ContactAuthorization({id}:{id:string}){
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;const values=Object.fromEntries(new FormData(e.currentTarget).entries());setBusy(true);
  try{await request(pipelinePath+'/candidates/'+encodeURIComponent(id)+'/authorization','POST',{...values,authorized:true});refresh();setNotice('Authorization saved. Review the exact outreach version before approving it.')}
  catch(e){setNotice((e as Error).message)}finally{setBusy(false)}
 }
 return <details id="prospect-permission"><summary>Record verified outreach permission</summary><form className="prospect-run-form" onSubmit={submit}>
  <label>Authorized recipient<input required type="email" name="recipient"/></label><label>Purchasing role<input required name="role"/></label>
  <label>Authorized route<select required name="route" defaultValue=""><option value="">Choose route</option><option value="direct">Direct</option><option value="distributor">Through a distributor</option></select></label>
  <label>Evidence of permission<textarea required name="evidence" rows={2}/></label>
  <label className="screening-check"><input required type="checkbox"/>I verified permission to contact this recipient through the specified route.</label>
  <button className="action-link" disabled={busy}>{busy?'Saving…':'Save verification'}</button>{notice&&<p role="status">{notice}</p>}
 </form></details>;
}
function ProspectDisposition({candidate}:{candidate:Candidate}){
 const [choice,setChoice]=useState(''),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const held=['hold','rejected'].includes(candidate.stage);
 const options=held?[['resume','Resume screening']]:[
  ...(researchChoice(candidate)&&candidate.stage!=='selected_for_research'?[['select_for_research','Shortlist for research']]:[]),
  ['hold','Put on hold'],['reject','Remove from consideration']
 ];
 async function submit(e:FormEvent){
  e.preventDefault();if(!choice||busy)return;setBusy(true);
  try{await request(pipelinePath+'/candidates/'+encodeURIComponent(candidate.id)+'/decision','POST',{decision:choice,rationale:reason.trim()});setChoice('');setReason('');setNotice('Decision saved.');refresh()}
  catch(e){setNotice((e as Error).message)}finally{setBusy(false)}
 }
 if(candidate.researched||(!held&&!['screened','discovered','selected_for_research'].includes(candidate.stage))||
    (held&&!['hold','reject'].includes(candidate.manual_decision||''))||(!held&&!candidate.researchable))return null;
 return <details><summary>Manage shortlist and disposition</summary><form className="prospect-run-form" onSubmit={submit}>
  <label>Decision<select required value={choice} onChange={e=>setChoice(e.target.value)}><option value="">Choose a decision</option>{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
  <label>{choice==='hold'||choice==='reject'?'Reason':'Reason (optional)'}<textarea required={choice==='hold'||choice==='reject'} rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
  {choice==='select_for_research'&&<p>Shortlisting saves your selection. Start paid research separately when you are ready.</p>}
  <button className="action-link" disabled={!choice||(['hold','reject'].includes(choice)&&!reason.trim())||busy}>Save decision</button>{notice&&<p role="status">{notice}</p>}
 </form></details>;
}
export function PipelineCandidate({id}:{id:string}){
 const {data:c,error}=useApi<CandidateDetail>(pipelinePath+'/candidates/'+encodeURIComponent(id));
 const detail=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  const fragment=window.location.hash.slice(1);
  if(!c?.id||!['prospect-permission','prospect-evidence'].includes(fragment))return;
  const target=detail.current?.querySelector<HTMLElement>('#'+fragment);
  if(target instanceof HTMLDetailsElement)target.open=true;
  target?.scrollIntoView?.({block:'start'});
 },[c?.id]);
 if(error)return <p role="alert">{error}</p>;if(!c)return <p role="status">Loading candidate…</p>;
 return <div ref={detail} className="screening-detail"><h1>{c.name}</h1><p>{[c.state,display(c.segment),origins[c.origin]].filter(Boolean).join(' · ')}</p>
  <h2>Next action</h2><p><strong>{display(c.stage)}</strong> · {c.next_action}</p>
  <ProspectActivity activity={c.latest_activity} version={c.draft?.version}/>
  {researchChoice(c)&&<ResearchForm selected={[c]}/>}
  {c.researched&&<Link className="action-link" href={c.href+(c.draft?'#prospect-outreach':'#prospect-research')}>{c.draft?(c.stage==='awaiting_approval'?'Review saved outreach':'View saved email'):'Open saved research'} →</Link>}
  {c.origin!=='fictional_csv'&&c.verified&&<ProspectDisposition candidate={c}/>}
  {c.outreach_permission_required&&<ContactAuthorization id={id}/>}
  {c.researched&&c.researchable&&<details><summary>Request updated research</summary><ResearchForm selected={[c]} refreshExisting/></details>}
  <h2>Screening score</h2><p>Prioritizes which institutions to investigate. Buying intent and expected spending remain unverified.</p><p><strong>{c.score==null?'Insufficient evidence':c.score.toFixed(1)+' / 100'}</strong> · {c.reason}</p>
  {!!c.factors?.length&&<ul>{c.factors.map(f=><li key={f.key}><strong>{f.label} · {f.points}/{f.maximum}</strong> — {f.reason}</li>)}</ul>}{c.score_version&&<small>Scoring version · {c.score_version}</small>}
  {c.comparison&&<><h3>Customer comparison</h3><p>{c.comparison}</p></>}
  <h2 id="prospect-evidence">Discovery evidence</h2>
  {c.identity_confidence&&<p>Identity confidence: {display(c.identity_confidence)}</p>}
  <dl>{Object.entries(c.attributes||{}).filter(([key,value])=>!['name','state','segment','official_url'].includes(key)&&['number','string','boolean'].includes(typeof value)&&value!=='').map(([key,value])=><div key={key}><dt>{display(key)}</dt><dd>{String(value)}</dd></div>)}</dl>
  {!!c.missing_fields?.length&&<p>Missing information: {c.missing_fields.map(v=>display(v).toLowerCase()).join(', ')}.</p>}
  {!!Object.keys(c.field_sources||{}).length&&<details><summary>Sources for individual fields</summary><dl>{Object.entries(c.field_sources).map(([name,source])=>{
   const text=typeof source==='string'?source:source&&typeof source==='object'&&'url' in source?String(source.url):'';
   const href=publicLink(text);return text?<div key={name}><dt>{display(name)}</dt><dd>{href?<a href={href} target="_blank" rel="noreferrer">{new URL(href).hostname}</a>:text}</dd></div>:null
  })}</dl></details>}
  {!!c.limitations?.length&&<details><summary>Evidence limitations</summary><ul>{c.limitations.map(fact=><li key={fact}>{fact}</li>)}</ul></details>}
  <ul>{(c.sources||[]).map((s,i)=>{const href=publicLink(s.url);return <li key={(s.url||'')+i}>{href?<a href={href} target="_blank" rel="noreferrer">{s.title||new URL(href).hostname}</a>:s.title}{s.retrieved_at&&<small> · Retrieved {s.retrieved_at.slice(0,10)}</small>}{s.identity_quote&&<p>{s.identity_quote}</p>}</li>})}</ul>
 </div>;
}
