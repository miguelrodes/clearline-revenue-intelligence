'use client';
import Link from 'next/link';
import {useState} from 'react';
import {useApi} from '@/lib/api';
import {PipelineOverview} from './prospect-pipeline';
import {ReviewAccountRow} from './review-account-row';
import {ProspectDecision} from './prospect-decision';

type Member = {
 id:string; name:string; href:string; description:string; status:string;
 commercial_context:string; next_step:string; evidence:string[]; action_label:string;
};
type Group = {
 id:string; title:string; description:string; source:'phase3'|'phase4'; count:number; members:Member[];
};
type Overview = {brief:{title:string;text:string}[];groups:Group[]};
const endpoint='/overview/prospects';

function scope(group:Group) {
 const source=group.source==='phase3'?'fictional case-study institution':'real-world SwabTek prospect';
 return `${group.count} ${source}${group.count===1?'':'s'}`;
}

export function ProspectOverview(){return <PipelineOverview/>}

export function ProspectGroupReview({id}:{id:string}) {
 const {data,error}=useApi<Overview>(endpoint);
 const [open,setOpen]=useState<string|null>(null);
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 if(error)return <p role="alert">{error}</p>;
 if(!data)return <p role="status">Loading saved prospect work…</p>;
 const group=data.groups.find(g=>g.id===id);
 if(!group)return <>{notice&&<p role="status">{notice}</p>}<p>This group has no remaining work. Close the review to see the current priorities.</p></>;
 return <>
  <h1>{group.title}</h1><p className="review-description">{group.description}</p><small>{scope(group)}</small>
  {notice&&<p role="status">{notice}</p>}
  <div className="check-account-list">{group.members.map(member=><ReviewAccountRow key={member.id}
   name={member.name} href={member.href} sectionId={`prospect-step-${member.id}`} description={member.description}
   summary={member.status} expanded={open===member.id} onToggle={()=>setOpen(open===member.id?null:member.id)}
   disclosure="Review next step">
   <p>{member.commercial_context}</p>
   <p><strong>Next step</strong> — {member.next_step}</p>
   {!!member.evidence.length&&<details><summary>Saved evidence</summary><ul>{member.evidence.map((e,i)=><li key={i}>{e}</li>)}</ul></details>}
   {group.source==='phase3'&&group.id==='decision'&&<ProspectDecision id={member.id} busy={busy} onBusy={setBusy} onNotice={setNotice}/>}
   <Link className="action-link" href={member.href}>{member.action_label} →</Link>
  </ReviewAccountRow>)}</div>
 </>;
}
