import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within} from '@testing-library/react';
import type {Opportunity,OrganizationProfile} from '../src/lib/types';
const params=new URLSearchParams();
vi.mock('next/navigation',()=>({useSearchParams:()=>params,useRouter:()=>({push:vi.fn(),replace:vi.fn()})}));
vi.mock('../src/components/commercial-work',()=>({CommercialWork:()=> <section><h2>What Needs Verification</h2></section>}));
vi.mock('../src/components/conversation',()=>({ConversationPanel:()=> <section><h2>Customer Conversations</h2></section>}));
import {AccountSummary} from '../src/components/sales-surface';
import {OpportunityTable} from '../src/components/detail-views';
const profile:OrganizationProfile={account_type:'End buyer',purchasing_channel:'Both',description:'Correctional facility in Idaho with recorded purchases from Clearline, both directly and through a distributor.',evidence:['Named order evidence.'],channel_scope:'Recorded purchasing routes, not contact authorization.'};
it('shows identity above business situation without changing workflow controls or issuing mutations',async()=>{
 const a={id:'lone-tree',name:'Lone Tree',status:'needs_contact',workflow:'recovery',holds:[],evidence:{},organization_profile:profile,assessment:null,drafts:[],events:[],outcomes:[],outbox:[],jobs:[],trends:null};
 const fetch=vi.fn(async()=>({ok:true,json:async()=>a}));vi.stubGlobal('fetch',fetch);
 render(<AccountSummary id="lone-tree"/>);
 expect(await screen.findByText(profile.description)).toBeVisible();
 const controls=await screen.findByRole('group',{name:'Customer contact actions'});
 expect(within(controls).getByRole('button',{name:'Pause outreach'})).toBeVisible();
 expect(within(controls).getByRole('button',{name:'Do not contact'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Lone Tree'}).compareDocumentPosition(controls) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(controls.compareDocumentPosition(screen.getByText(profile.description)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 const order=['Business Situation','AI Recommendation','Next Action','What Needs Verification','Customer Conversations','Full Account History'];
 for(let i=1;i<order.length;i++)expect(screen.getByRole('heading',{name:order[i-1]}).compareDocumentPosition(screen.getByRole('heading',{name:order[i]})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(screen.getByRole('region',{name:'Full Account History'})).toBeVisible();
 expect(screen.getByRole('region',{name:'Full Account History'}).closest('details')).toBeNull();
 expect(screen.queryByText('Record a simulated sales outcome')).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Record outcome'})).not.toBeInTheDocument();
 expect(screen.getByText('End buyer')).toBeVisible();expect(screen.getByText('Both')).toBeVisible();
 expect(screen.getByRole('link',{name:'Review purchasing contacts'})).toHaveAttribute('href','/actions?group=contacts');
 expect(screen.getByText(profile.description).compareDocumentPosition(screen.getByRole('heading',{name:'Business Situation'})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(fetch.mock.calls.every(args=>!(args as unknown[])[1] || [undefined,'GET'].includes(((args as unknown[])[1] as RequestInit).method))).toBe(true);
});
it('filters the existing table by account type while keeping account links',()=>{
 const rows=(['End buyer','Distributor','Unknown'] as const).map((type,i)=>({id:String(i),name:['Lone Tree','Range Line','Unresolved record'][i],workflow:'recovery',change_cents:0,prior_tests:0,current_tests:0,partial_decline:false,evidence_quality:'',assessment:null,evidence_hash:'e',last_purchase:null,state:'ID',owner:'Sales',signals:[],holds:[],status:'no_action',next_action:'No action',prior_cents:0,current_cents:0,decline_cents:0,decline_pct:null,organization_profile:{...profile,account_type:type,description:`Description ${i}.`}} as Opportunity));
 render(<OpportunityTable rows={rows}/>);
 fireEvent.change(screen.getByLabelText('Account type filter'),{target:{value:'Distributor'}});
 expect(screen.getByRole('link',{name:/Range Line/})).toHaveAttribute('href','/accounts/1');
 expect(screen.queryByRole('link',{name:/Lone Tree/})).not.toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Account type filter'),{target:{value:'Unknown'}});
 expect(within(screen.getByRole('table')).getByText('Unresolved record')).toBeVisible();
});

it.each([
 ['response',{outreach_kind:'reply',reply_message_id:'incoming-1'}],
 ['response',{reply_to:'older-inbound-outcome'}],
 ['outreach',{outreach_kind:'initial'}],
 ['outreach',{outreach_kind:'followup'}],
] as const)('puts the %s editor inside Next Action and opens it only for review',async(kind,analysis)=>{
 const draft={id:'draft-1',version:4,recipient:'buyer@example.org',subject:'Purchasing question',body:'Saved draft text.',
  created_at:'2026-11-15',status:'awaiting_approval',can_review:true,analysis};
 const account={id:'account',name:'Account',workflow:'recovery',status:'awaiting_approval',holds:[],evidence:{},
  assessment:null,drafts:[draft],events:[],outcomes:[],outbox:[],jobs:[],trends:null};
 const fetcher=vi.fn(async(_url:unknown,_opts?:RequestInit)=>({ok:true,json:async()=>account}));
 vi.stubGlobal('fetch',fetcher);
 render(<AccountSummary id={account.id}/>);
 const toggle=await screen.findByText('Review personalized '+kind);
 const next=screen.getByRole('heading',{name:'Next Action'}).closest('section')!;
 expect(next).toContainElement(toggle);expect(toggle.closest('details')).not.toHaveAttribute('open');
 expect(within(next).getByLabelText('Message')).not.toBeVisible();
 fireEvent.click(toggle);
 expect(within(next).getByRole('textbox',{name:'Message'})).toHaveValue(draft.body);
 expect(within(next).getByRole('button',{name:'Approve simulated send'})).toBeVisible();
 expect(within(next).queryByRole('heading',{name:/personalized/i})).toBeNull();
 fireEvent.click(toggle);
 expect(toggle.closest('details')).not.toHaveAttribute('open');
 expect(fetcher.mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
