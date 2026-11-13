"use client";
import Link from 'next/link';
import {usePathname,useRouter,useSearchParams} from 'next/navigation';
import {useState,type MouseEvent} from 'react';
import {LayoutDashboard,Inbox,Search,Menu,X} from 'lucide-react';
import {useApi} from '@/lib/api';
import {OverviewPage,SalesActions,AccountSummary,Overlay,SystemStatus,MetricDetail,GroupReview} from './sales-surface';
import {OpportunityList,ActivityView,RevenueLedger} from './detail-views';
import {CampaignCenter} from './operations';
import {ReviewChecks} from './review-checks';
export {OpportunityTable,DraftEditor} from './detail-views';

export default function Workspace(){
 const path=usePathname();const params=useSearchParams();const router=useRouter();const [menu,setMenu]=useState(false);const [query,setQuery]=useState('');
 const {data:found}=useApi<{id:string;name:string;state:string;workflow:string}[]>(query.trim().length>=2?`/search?q=${encodeURIComponent(query.trim())}`:null);
 const base=path==='/'?'/':'/actions';const account=params.get('account');const metric=params.get('metric');const group=params.get('group');
 function close(){const p=new URLSearchParams(params);(account?['account']:metric?['metric']:['group','focus','product','signal']).forEach(k=>p.delete(k));router.replace(path+(p.size?'?'+p:''))}
 function openAccount(id:string){const p=new URLSearchParams(params);p.set('account',id);router.push(path+'?'+p);setQuery('')}
 function contextual(e:MouseEvent){if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0)return;const a=(e.target as HTMLElement).closest('a');if(!a)return;const url=new URL(a.href,window.location.origin);if(url.origin!==window.location.origin)return;const match=url.pathname.match(/^\/accounts\/([^/]+)$/);if(match){e.preventDefault();openAccount(match[1])}}
 return <div className="shell" onClickCapture={contextual}><aside className={menu?'sidebar open':'sidebar'}><Link href="/" className="brand"><span className="brand-mark">C<span/></span><div>Clearline</div></Link><nav aria-label="Main navigation">{[{href:'/',name:'Overview',Icon:LayoutDashboard},{href:'/actions',name:'Action Center',Icon:Inbox}].map(n=><Link key={n.href} href={n.href} onClick={()=>setMenu(false)} className={base===n.href?'nav-item selected':'nav-item'}><n.Icon size={18}/>{n.name}</Link>)}</nav></aside>
 <div className="main-wrap"><header className="topbar"><button className="mobile-menu icon-button" aria-label="Toggle navigation" onClick={()=>setMenu(!menu)}>{menu?<X size={20}/>:<Menu size={20}/>}</button><div className="global-search"><label><Search size={16}/><input aria-label="Search all accounts" placeholder="Find a customer, prospect, or account..." value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Escape')setQuery('')}}/></label>{query.trim().length>=2&&<div className="search-results">{found?.length?found.map(a=><button key={a.id} onClick={()=>openAccount(a.id)}><strong>{a.name}</strong><small>{a.state} · {a.workflow==='prospecting'?'Real SwabTek prospect':'Clearline case-study account'}</small></button>):<p>{found?'No matching customers.':'Searching…'}</p>}</div>}</div><SystemStatus/></header>
 <main>{path==='/'?<OverviewPage/>:path==='/actions'?<SalesActions/>:path.startsWith('/accounts/')?<AccountSummary id={path.split('/')[2]}/>:path==='/campaigns'?<><Link className="back-link" href="/actions">← Action Center</Link><CampaignCenter/></>:path==='/activity'?<ActivityView/>:path==='/checks'?<ReviewChecks/>:path==='/prospects'?<section className="panel"><h1>New prospect work is paused</h1><p>The workspace is focused on Phase 1 customer recovery.</p></section>:path==='/revenue'?<RevenueLedger/>:<OpportunityList intelligence={path==='/accounts'}/>}</main>
 <footer>Clearline case-study records are fictional.</footer></div>
 {metric&&<Overlay title="Metric details" onClose={close}><MetricDetail metric={metric}/></Overlay>}{group&&!metric&&<Overlay title="Review prepared work" onClose={close}><GroupReview id={group} focus={params.get('focus')} product={params.get('product')} signal={params.get('signal')}/></Overlay>}{account&&<Overlay title="Account" onClose={close}><AccountSummary id={account}/></Overlay>}
 </div>;
}
