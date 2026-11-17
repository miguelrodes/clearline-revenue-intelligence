import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor,within} from '@testing-library/react';
const state=vi.hoisted(()=>({path:'/',params:new URLSearchParams(),push:vi.fn(),replace:vi.fn()}));
vi.mock('next/navigation',()=>({usePathname:()=>state.path,useSearchParams:()=>state.params,useRouter:()=>({push:state.push,replace:state.replace})}));
import Workspace from '../src/components/workspace';
import {GroupReview,OverviewPage,RecoveryPerformance,SalesActions,AccountSummary} from '../src/components/sales-surface';
const keys=['inactivity','partial','product_decline','direct_gap_channel_review'];
const overview={summary:{prior_cents:100000,current_cents:50000},counts:{},primary_declines:{},segments:keys.map((key,i)=>({key,accounts:i,decline_cents:i*10000})),trends:{rows:[]},last_scan:'2026-11-01'};
const performance={simulated:{contacted:18,responded:0,purchased:0,net_cents:0,series:[]},verified:null,incremental_cents:null,outcomes:[],unlinked_outcomes:0,contacted_accounts:[],method:'Only simulated post-outreach outcomes are included.'};
const group={id:'messages:inactivity',title:'Follow up with inactive customers',kind:'messages',accounts:2,tasks:2,why:'The emails are prepared. Choose which ones to approve.',button_label:'Review drafts',rank:1,status:'ready',historical_decline_cents:20000,members:[0,1].map(i=>({id:String(i),name:`Customer ${i}`,workflow:'recovery',strategy:'inactive',products:['CL-FS10'],decline_cents:10000,draft:{id:`draft-${i}`,opportunity_id:String(i),version:1,recipient:'simulation@example.invalid',subject:`Question ${i}`,body:`Personalized message ${i}`,status:'awaiting_approval',can_review:true,created_at:'2026-11-12',evidence_hash:'e',snapshot_hash:`hash-${i}`}}))};
function setup(){vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>String(path).startsWith('/api/work')?{groups:[group],counts:{ready_messages:2},checks:{priority_records:0,background_records:0}}:path==='/api/portfolio/coverage'?{total:2,assessed:2,failed:0,counts:{human_decision:2}}:path==='/api/overview'?overview:path==='/api/performance'?performance:path==='/api/health'?{alive:true,paused:false}:path==='/api/execution'?{active_investigations:[],queue_ready:0}:path==='/api/brief'?{brief:null,stale:false,job:null}:[]})))}
beforeEach(()=>{vi.restoreAllMocks();state.path='/';state.params=new URLSearchParams();state.push.mockReset();setup()});
it('has exactly two primary destinations and global account search',async()=>{
 render(<Workspace/>);
 const nav=screen.getByRole('navigation',{name:'Main navigation'});
 expect(within(nav).getAllByRole('link').map(a=>a.textContent)).toEqual(['Overview','Action Center']);
 expect(screen.getByRole('textbox',{name:'Search all accounts'})).toBeInTheDocument();
 expect(await screen.findByRole('heading',{name:'Revenue overview'})).toBeInTheDocument();
 expect(screen.queryByRole('heading',{name:'Needs your attention'})).not.toBeInTheDocument();
 expect(screen.queryByRole('heading',{name:'Recent agent activity'})).not.toBeInTheDocument();
});
it('keeps identical four categories in both signal measurements including zero',async()=>{
 render(<OverviewPage/>);await screen.findByRole('button',{name:'By revenue'});
 const urls=()=>screen.getAllByRole('link').map(a=>a.getAttribute('href')).filter(x=>x?.startsWith('/?metric='));
 const before=urls();fireEvent.click(screen.getByRole('button',{name:'By revenue'}));expect(urls()).toEqual(before);
 expect(screen.getByRole('link',{name:'Direct purchase gap $300'})).toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Inactive customers $0'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'By accounts'}));expect(screen.getByRole('link',{name:'Direct purchase gap 3'})).toBeInTheDocument();
});
it('bulk approves only selected saved versions after explicit confirmation',async()=>{
 render(<GroupReview id={group.id}/>);
 fireEvent.click(await screen.findByRole('checkbox',{name:'Select Customer 1'}));
 fireEvent.click(screen.getByRole('button',{name:'Approve 1 & simulate sending'}));
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Confirm simulated sending'}));
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));
 const call=vi.mocked(fetch).mock.calls.find(c=>c[1]?.method==='POST')!;
 expect(call[0]).toBe('/api/work/messages%3Ainactivity/decision');
 expect(JSON.parse(call[1]?.body as string)).toEqual({approve:true,snapshots:[{draft_id:'draft-0',snapshot_hash:'hash-0'}]});
});
it('disables batch approval when selected messages have unsaved edits',async()=>{
 render(<GroupReview id={group.id}/>);await screen.findByRole('checkbox',{name:'Select Customer 0'});
 fireEvent.click(screen.getByText('Question 0 · Review or edit'));
 fireEvent.change(screen.getAllByLabelText('Subject')[0],{target:{value:'Edited subject'}});
 expect(screen.getByRole('button',{name:'Approve 2 & simulate sending'})).toBeDisabled();
 expect(screen.getByText('Edits save automatically. Approval is available once saving finishes.')).toBeInTheDocument();
});
it('separates simulated outcomes from verified revenue and incremental claims',async()=>{
 render(<RecoveryPerformance/>);
 expect(await screen.findByText(/No verified results have been recorded/)).toBeInTheDocument();
 expect(screen.queryByText('18')).not.toBeInTheDocument();
 fireEvent.change(screen.getByRole('combobox',{name:'Revenue recovery results'}),{target:{value:'simulation'}});expect(screen.getByText('18')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'How it is measured'}));expect(screen.getByText('Estimated incremental recovery: unavailable.')).toBeInTheDocument();
});
it('keeps prepared work readable with product and status grouping',async()=>{
 render(<SalesActions/>);
 expect(await screen.findByRole('link',{name:'Review drafts →'})).toHaveAttribute('href','/actions?group=messages%3Ainactivity');
 fireEvent.change(screen.getByRole('combobox',{name:'Group actions by'}),{target:{value:'product'}});
 expect(screen.getByRole('heading',{name:'CL-FS10'})).toBeInTheDocument();
 expect(screen.getByText(/An email may concern several products/)).toBeInTheDocument();
});

it('opens customer evidence over the current group before Next Link handles navigation',async()=>{
 state.params=new URLSearchParams({group:group.id});
 render(<Workspace/>);
 fireEvent.click(await screen.findByRole('checkbox',{name:'Select Customer 1'}));
 fireEvent.click(screen.getByText('Question 0 · Review or edit'));
 const link=screen.getAllByRole('link',{name:'View customer'})[0];
 // Next Link handles ordinary clicks by preventing native navigation.
 link.addEventListener('click',e=>e.preventDefault());
 fireEvent.click(link);
 expect(state.push).toHaveBeenCalledWith('/?group=messages%3Ainactivity&account=0');
 expect(screen.getByRole('button',{name:'Approve 1 & simulate sending'})).toBeEnabled();
});

it('presents a short practical next step while retaining the detailed agent assessment',async()=>{
 const account={id:'juniper',name:'Juniper Hills',workflow:'recovery',status:'agent_held',holds:['open_orders_require_review'],decline_cents:3295700,evidence:{prior_cents:5426100,current_cents:2130400,last_purchase:'2026-07-16',crm_notes:'Wants training for night shift'},assessment:{created_at:'2026-11-12',details:{decision:'hold',hypotheses:[],unresolved_questions:[],evidence_fields:[],rationale:'The account has an explicit open_orders_require_review hold. Test purchases fell across both products.',recommended_action:'Assign the owner to reconcile all source rows and aliases before reopening outreach.'}},drafts:[],outbox:[],outcomes:[]};
 vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>String(url).endsWith('/conversation')?{status:'not_started',messages:[],context:{outreach_policy:'normal',contact:null,channel:null},tasks:[]}:account})));
 render(<AccountSummary id="juniper"/>);
 expect(await screen.findByText('The account has pending orders that need checking. Test purchases fell across both products.')).toBeInTheDocument();
 expect(screen.getByText(/Confirm whether the order was fulfilled, canceled, or is still pending/)).toBeInTheDocument();
 expect(screen.getByText('Inspect the full assessment and evidence')).toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Review the prepared information request'})).toHaveAttribute('href','/actions?group=check:orders');
});

it('renders the expanded business situation from the existing account response without requesting analysis or changing the recommendation',async()=>{
 const account={id:'growing',name:'Growing customer',workflow:'recovery',status:'no_action',holds:[],decline_cents:0,evidence:{comparison:{prior_start:'2025-01-01',prior_end_exclusive:'2025-11-01',current_start:'2026-01-01',current_end_exclusive:'2026-11-01'},prior_cents:200000,current_cents:250000,prior_tests:500,current_tests:600,last_purchase:'2026-09-01',crm_notes:'Budget resets Oct 1'},assessment:{created_at:'2026-11-12',details:{engine_version:'recovery-4',decision:'no_action',objective:'Continue ordinary account management.',hypotheses:[],unresolved_questions:[],evidence_fields:[],rationale:'Purchasing is growing.',recommended_action:'No recovery outreach is justified.'}},drafts:[],outbox:[],outcomes:[]};
 const original=JSON.stringify(account);
 vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>String(url).endsWith('/conversation')?{status:'not_started',messages:[],context:{outreach_policy:'normal',contact:null,channel:null},tasks:[]}:account})));
 render(<AccountSummary id="growing"/>);
 const heading=await screen.findByRole('heading',{name:'Business Situation'});
 const section=heading.closest('section')!;
 expect(section).toHaveTextContent('rose from $2,000 to $2,500 (up $500, 25%)');
 expect(section).toHaveTextContent('test quantities changed from 500 to 600');
 expect(section).toHaveTextContent('An undated CRM note says “Budget resets Oct 1”');
 expect(section).not.toHaveTextContent('Continue ordinary account management.');
 expect(screen.getAllByText('Continue ordinary account management.').length).toBeGreaterThan(0);
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
 expect(vi.mocked(fetch).mock.calls.every(c=>!String(c[0]).includes('/assess'))).toBe(true);
 expect(JSON.stringify(account)).toBe(original);
});

it('limits signal bulk approval to matching customers even when a campaign spans signals',async()=>{
 const original=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(path,opts)=>path==='/api/opportunities'?{ok:true,json:async()=>[{id:'0',signals:['inactivity'],partial_decline:false},{id:'1',signals:['product_decline'],partial_decline:false}]} as Response:original(path,opts));
 render(<GroupReview id={group.id} signal="inactivity"/>);
 await screen.findByRole('checkbox',{name:'Select Customer 0'});
 await waitFor(()=>expect(screen.queryByRole('checkbox',{name:'Select Customer 1'})).not.toBeInTheDocument());
 fireEvent.click(screen.getByRole('button',{name:'Approve 1 & simulate sending'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm simulated sending'}));
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));
 const call=vi.mocked(fetch).mock.calls.find(c=>c[1]?.method==='POST')!;
 expect(JSON.parse(call[1]?.body as string).snapshots).toEqual([{draft_id:'draft-0',snapshot_hash:'hash-0'}]);
});

it('uses the requested search placeholder and distinguishes real prospects from fictional customers',async()=>{
 const original=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(path,opts)=>String(path).startsWith('/api/search?')?{ok:true,json:async()=>[{id:'real',name:'Pennsylvania DOC',state:'PA',workflow:'prospecting'},{id:'case',name:'Pennsylvania Case Account',state:'PA',workflow:'recovery'}]} as Response:original(path,opts));
 render(<Workspace/>);
 fireEvent.change(screen.getByPlaceholderText('Find a customer, prospect, or account...'),{target:{value:'Pennsylvania'}});
 expect(await screen.findByText('PA · Real SwabTek prospect')).toBeInTheDocument();
 expect(screen.getByText('PA · Clearline case-study account')).toBeInTheDocument();
});

it('uses a lightweight summary and sends guidance only for selected exact drafts',async()=>{
 const original=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(path,opts)=>String(path).endsWith('/revise')?{ok:true,json:async()=>({count:1,job_ids:['revision-1']})} as Response:original(path,opts));
 const {container}=render(<GroupReview id={group.id}/>);
 fireEvent.click(await screen.findByRole('checkbox',{name:'Select Customer 1'}));
 expect(screen.getAllByText(group.why)).toHaveLength(1);
 expect(container.querySelector('.review-summary')).toBeNull();
 expect(container.querySelector('.outreach-summary li')).toHaveTextContent('2 personalized emails prepared');
 fireEvent.click(screen.getByText('Want to adjust the approach? Add instructions for the agents before approving.'));
 fireEvent.change(screen.getByLabelText('Instructions for selected emails'),{target:{value:'Emphasize replenishment and offer a quote'}});
 expect(screen.getByRole('button',{name:'Approve 1 & simulate sending'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Revise 1 selected emails'}));
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(c=>String(c[0]).endsWith('/revise'))).toBe(true));
 const call=vi.mocked(fetch).mock.calls.find(c=>String(c[0]).endsWith('/revise'))!;
 expect(JSON.parse(call[1]?.body as string)).toEqual({instructions:'Emphasize replenishment and offer a quote',snapshots:[{draft_id:'draft-0',snapshot_hash:'hash-0'}]});
 expect(vi.mocked(fetch).mock.calls.some(c=>String(c[0]).endsWith('/decision'))).toBe(false);
});

it('blocks approval while selected revisions run and preserves review controls',async()=>{
 const revised={...group,members:group.members.map(m=>({...m,revision:{id:'job-'+m.id,status:'running'}}))};
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>String(path).startsWith('/api/work')?{groups:[revised]}:[]})));
 render(<GroupReview id={group.id}/>);
 expect(await screen.findByRole('button',{name:'Approve 2 & simulate sending'})).toBeDisabled();
 expect(screen.getAllByText('Agent reviewing this email…')).toHaveLength(2);
 expect(screen.getByText('Question 0 · Review or edit')).toBeInTheDocument();
});

it('opens Lone Tree contact evidence and saves a partial note directly in the clearance group',async()=>{
 const contactGroup={id:'investigation:contacts',title:'Confirm purchasing contacts and buying routes',kind:'contacts',accounts:1,tasks:1,why:'Confirm the buyer before outreach.',button_label:'Review contact checks',rank:2,status:'needs_information',historical_decline_cents:5022500,members:[{id:'lone-tree',task_id:'contact-lone-tree',name:'ID DOC – Lone Tree',workflow:'recovery',decline_cents:5022500,recommended_action:'Identify and verify the current purchasing contact.'}]};
 const account={id:'lone-tree',name:'ID DOC – Lone Tree',state:'ID',workflow:'recovery',status:'needs_contact',holds:[],evidence:{crm_notes:'Captain retired - new contact TBD.',last_purchase:'2026-07-16',last_contacted:'2025-05-05',prior_cents:100000,current_cents:50000},assessment:{created_at:'2026-11-12',details:{objective:'Reestablish purchasing relationship.',recommended_action:'Verify the current purchasing contact.'}},decline_cents:5022500,next_action:'Verify the current purchasing contact.',drafts:[],events:[],jobs:[],outbox:[],outcomes:[],trends:null};
 const task={id:'contact-lone-tree',title:'Identify current purchasing contact',owner:'Sales',reason:'The CRM says the captain retired; the current buyer is not identified.',evidence_refs:'["crm_notes"]',blocking:1,status:'pending'};
 const work={groups:[contactGroup],counts:{ready_messages:0,groups:1},checks:{priority_records:0,background_records:0}};
 const clearance={tasks:[task],signals:{signals:[]},authorizations:[],contact_clearance:null};
 const fetcher=vi.fn(async(path,options?:RequestInit)=>({ok:true,json:async()=>options?.method==='POST'?{status:'partial',task_status:'pending',authorized:false,requires_reassessment:false}:path==='/api/work'?work:path==='/api/opportunities'?[]:path==='/api/accounts/lone-tree'?account:path==='/api/accounts/lone-tree/commercial-work'?clearance:[]}));
 vi.stubGlobal('fetch',fetcher);
 render(<GroupReview id="investigation:contacts"/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review contact details'}));
 expect(await screen.findByRole('heading',{level:2,name:'ID DOC – Lone Tree'})).toBeInTheDocument();
 expect(screen.getByText('Captain retired - new contact TBD.')).toBeInTheDocument();
 expect(screen.getByText(/The CRM says the captain retired/)).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Work email'),{target:{value:'buyer@example.test'}});
 fireEvent.click(screen.getByRole('button',{name:'Save partial information'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/accounts/lone-tree/contact-clearance'&&options?.method==='POST')).toBe(true));
 const review=screen.getByRole('button',{name:'Review contact details'});
 expect(review).toHaveAttribute('aria-expanded','true');fireEvent.click(review);
 expect(review).toHaveAttribute('aria-expanded','false');
});

it('keeps a reviewed soft-warning action and a pending human edit visible without reintroducing the old hold instruction',async()=>{
 const objective='Scope night-shift training alongside the existing order.';
 const account={id:'juniper',name:'Juniper Hills',workflow:'recovery',status:'awaiting_approval',holds:['open_orders_require_review'],decline_cents:3295700,evidence:{prior_cents:5426100,current_cents:2130400},assessment:{created_at:'2026-11-12',details:{engine_version:'recovery-4',decision:'pursue',objective,hypotheses:[],unresolved_questions:[],evidence_fields:[],rationale:'Full evidence and alternatives remain available.',recommended_action:'Review the training proposal; the order warning remains attached.'}},drafts:[{id:'edited',opportunity_id:'juniper',version:2,recipient:'simulation@example.invalid',subject:'Training discussion',body:'Could a training discussion help?',status:'awaiting_approval',created_at:'2026-11-12',can_edit:true,can_review:false,review_status:'queued'}],outbox:[],outcomes:[]};
 vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>String(url).endsWith('/conversation')?{status:'not_started',messages:[],context:{outreach_policy:'normal',contact:null,channel:null},tasks:[]}:account})));
 render(<AccountSummary id="juniper"/>);
 expect((await screen.findAllByText(objective)).length).toBeGreaterThan(0);
 expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('Could a training discussion help?');
 expect(screen.getByText('An agent is working on your requested rewrite.')).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Approve simulated send'})).not.toBeInTheDocument();
 expect(screen.queryByRole('link',{name:'Review the prepared information request'})).not.toBeInTheDocument();
});

it('keeps the organization, pending request and expandable checks together under each account',async()=>{
 const members=[
  {id:'range',name:'Range Line Distributors',task_id:'fulfillment',decline_cents:2000,inquiry_state:'status_requested'},
  {id:'juniper',name:'Juniper Hills',task_id:'order',decline_cents:1100}
 ];
 const accounts=[
  {id:'range',organization_profile:{description:'Distributor with documented purchases from Clearline.'}},
  {id:'juniper',organization_profile:{description:'Correctional facility in Kansas.'}}
 ];
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path==='/api/work'
  ?{groups:[{id:'investigation:orders',title:'Check open orders and credits',why:'Verify order status.',kind:'accounts',members}]}
  :path==='/api/opportunities'?accounts:{tasks:[],practical_actions:[],signals:{signals:[]},authorizations:[],contact_clearance:null,inquiry_data:{recipients:[],inquiries:[]}}})));
 render(<GroupReview id="investigation:orders"/>);
 const range=(await screen.findByRole('heading',{name:'Range Line Distributors'})).closest('article')!;
 const juniper=screen.getByRole('heading',{name:'Juniper Hills'}).closest('article')!;
 expect(within(range).getByText(accounts[0].organization_profile.description)).toBeVisible();
 expect(within(range).getByText(/request sent · awaiting response/i)).toBeVisible();
 expect(within(juniper).queryByText(/request sent/i)).toBeNull();
 const button=within(range).getByRole('button',{name:'Review checks'});
 fireEvent.click(button);
 const contents=await within(range).findByRole('region',{name:'Checks for Range Line Distributors'});
 expect(document.getElementById(button.getAttribute('aria-controls')!)).toContainElement(contents);
 expect(within(juniper).getByRole('button')).toHaveAttribute('aria-expanded','false');
 fireEvent.click(button);
 expect(button).toHaveAttribute('aria-expanded','false');
 expect(contents).not.toBeInTheDocument();
 expect(vi.mocked(fetch).mock.calls.every(call=>call[1]?.method==='GET')).toBe(true);
});

it('follows a verification link on a standalone account without opening another account dialog',async()=>{
 state.path='/accounts/range';
 window.history.replaceState({},'',state.path);
 const action={id:'fulfillment:range',title:'Check order status',found:'An order is open.',why:'Confirm whether support is needed.',next_step:'Check the order with fulfillment.',category:'orders',role:'Fulfillment',role_key:'fulfillment',control:'finding',tasks:[{id:'t',title:'Check the order',question:'Was it shipped?',record_refs:[],record_ids:[]}],task_ids:['t'],lines:[],can_prepare_internal:true};
 const account={id:'range',name:'Range Line',workflow:'recovery',status:'internal_investigation',evidence:{prior_cents:100,current_cents:50},assessment:null,holds:[],drafts:[],outbox:[],outcomes:[]};
 const work={signals:{signals:[]},tasks:[],authorizations:[],contact_clearance:null,practical_actions:[action],inquiry_data:{inquiries:[],recipients:[]}};
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path==='/api/accounts/range'?account:path==='/api/accounts/range/commercial-work'?work:path==='/api/accounts/range/conversation'?{status:'not_started',messages:[],context:{},tasks:[]}:path==='/api/health'?{alive:true}:path==='/api/execution'?{active_investigations:[]}:[]})));
 try{
  render(<Workspace/>);
  const link=await screen.findByRole('link',{name:'Complete this in What Needs Verification'});
  const check=screen.getByRole('article',{name:action.title});
  check.scrollIntoView=vi.fn();
  fireEvent.click(link);
  expect(check.scrollIntoView).toHaveBeenCalledOnce();
  expect(document.activeElement).toBe(check);
  expect(state.push).not.toHaveBeenCalled();
 }finally{window.history.replaceState({},'','/')}
});
