"use client";
import Link from 'next/link';
import {useSearchParams} from 'next/navigation';
import {useState} from 'react';
import {useApi} from '@/lib/api';

type Member={id:string;name:string;state:string;only_check:boolean;checks_left:string[];order_ids:string[]};
type Group={id:string;title:string;team:string;description:string;accounts:number;only_check_accounts:number};
type CheckList={priority_records:number;background_records:number;groups:Group[]};
type Detail=Group&{members:Member[];subject:string;request_body:string;source_error:string|null};

export function RecordChecksSummary(){
 const {data,error}=useApi<CheckList>('/checks');
 if(error)return <p className="notice" role="alert">Customer checks could not load. <Link href="/checks">Try again</Link></p>;
 if(!data?.groups.length)return null;
 return <section className="panel"><div className="panel-head"><h2>Questions for your team</h2><Link className="button" href="/checks">Review requests →</Link></div><div className="content-stack"><p>{data.groups.length} prepared requests cover the missing information for {data.priority_records} customer records. You can pass each list to the team that can answer it.</p></div></section>;
}

export function ReviewChecks(){
 const params=useSearchParams();const {data,error}=useApi<CheckList>('/checks');
 if(error)return <p className="notice" role="alert">{error}</p>;
 if(!data)return <p className="empty">Preparing the customer lists…</p>;
 const selected=params.get('group')||data.groups[0]?.id;
 return <><Link href="/" className="back-link">← Back to overview</Link><div className="page-head"><h1>Customer record checks</h1></div>
 {!data.groups.length?<section className="panel"><p className="empty">No customer checks are needed for current recovery opportunities.</p></section>:<>
 <p className="checks-intro"><strong>{data.groups.length} requests for your team.</strong> We grouped {data.priority_records} customer records with a purchasing change into the lists below. Choose a request, copy it, and download the list to pass along.</p>
 <nav className="check-groups" aria-label="Customer check groups">{data.groups.map(g=><Link key={g.id} href={`/checks?group=${g.id}`} className={`check-group ${g.id===selected?'selected':''}`} aria-current={g.id===selected?'page':undefined}><strong>{g.title}</strong><span>{g.team}</span><small>{g.accounts} customer records</small></Link>)}</nav>
 {data.groups.some(g=>g.id===selected)?<CheckRequest key={selected} group={selected!}/>:<p className="notice">This check is no longer needed. Choose one of the requests above.</p>}
 </>}
 <details className="checks-background"><summary>What happened to the other records?</summary><p>{data.background_records} records have questions but no current recovery signal, so they are kept out of today’s sales tasks. They remain in Account Intelligence. Some customers appear in more than one request because they need more than one answer.</p><Link className="text-link" href="/opportunities?queue=held">View all records with unanswered questions</Link></details></>;
}

export function CheckRequest({group,signal,focus}:{group:string;signal?:string|null;focus?:string|null}){
 const query=new URLSearchParams({...signal?{signal}:{},...focus?{focus}:{}}).toString();
 const {data:d,error}=useApi<Detail>(`/checks/${group}${query?"?"+query:""}`);const [message,setMessage]=useState('');const [showAll,setShowAll]=useState(false);
 if(error)return <p className="notice" role="alert">{error}</p>;
 if(!d)return <p className="empty">Loading the request…</p>;
 const members=showAll?d.members:d.members.slice(0,5);
 return <section className="panel check-request"><div className="panel-head"><div><h2>{d.title}</h2><p>For your {d.team.toLowerCase()}</p></div></div><div className="content-stack">
 <p>{d.description}</p>
 <div className="button-row"><button className="primary" disabled={Boolean(d.source_error)} onClick={async()=>{try{await navigator.clipboard.writeText(`Subject: ${d.subject}\n\n${d.request_body}`);setMessage('Copied. Nothing has been sent.')}catch{setMessage('Could not copy automatically. Open the request below and copy its text.')}}}>Copy request</button>{!d.source_error&&<a className="button" href={`/api/checks/${group}/export${query?"?"+query:""}`} download>Download customer list</a>}</div>
 {message&&<p role="status">{message}</p>}
 {d.source_error&&<p className="notice warning" role="alert">{d.source_error}</p>}
 <details><summary>Read the prepared request</summary><label>Subject<input readOnly value={d.subject}/></label><label>Request<textarea readOnly rows={9} value={d.request_body}/></label></details>
 <div className="check-priority"><h3>Customers to check first</h3><p>{d.only_check_accounts?`${d.only_check_accounts} customer records need only this check before we can reassess them. Those appear first, starting with the largest sales drop.`:'These customers also have other questions to answer. The largest sales drops appear first.'}</p></div>
 </div><div className="table-scroll"><table><thead><tr><th>Customer</th>{['orders','dates'].includes(group)&&<th>Order reference</th>}<th>Other questions</th></tr></thead><tbody>{members.map(m=><tr key={m.id}><td><Link className="text-link" href={`/accounts/${m.id}?tab=assessment`}>{m.name}</Link><small className="block">{m.state}</small></td>{['orders','dates'].includes(group)&&<td>{m.order_ids.join(', ')||'See source records'}</td>}<td>{m.only_check?'None currently':m.checks_left.join('; ')}</td></tr>)}</tbody></table></div>
 <div className="content-stack checks-footer">{d.members.length>5&&<button className="text-button" onClick={()=>setShowAll(!showAll)}>{showAll?'Show first 5':`Show all ${d.members.length} customers`}</button>}
 <p><strong>When the team replies:</strong> update the original records, then choose Refresh portfolio intelligence on Overview. The app will reassess affected customers. Outreach stays on hold until the missing information is resolved.</p></div></section>;
}
