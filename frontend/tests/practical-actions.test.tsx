import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {GroupReview} from '../src/components/sales-surface';
import {PracticalActions,PracticalNext} from '../src/components/practical-actions';
import type {ContactWorkData} from '../src/components/contact-clearance';
import type {InquiryData,InternalInquiry,PracticalAction,PracticalTask} from '../src/lib/practical-actions';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

function task(id:string, title:string, orderId?:string):PracticalTask {
 return {id,title,question:'What does the supporting record confirm?',record_ids:orderId?[orderId]:[],record_refs:orderId?[id+'-line']:[],blocking:true};
}
function action(category:PracticalAction['category'],tasks:PracticalTask[],options:Partial<PracticalAction>={}):PracticalAction {
 return {id:'group:'+category,category,role_key:category,role:'Person responsible for the account',title:'Confirm '+category,found:'Saved finding for '+category,why:'Commercial reason for '+category,next_step:'Check the evidence for '+category,afterward:'Clearline will reassess this account when material evidence changes.',control:'finding',can_prepare_internal:true,task_ids:tasks.map(t=>t.id),tasks,lines:[],...options};
}
function work(actions:PracticalAction[]):ContactWorkData {
 return {practical_actions:actions,tasks:actions.flatMap(a=>a.tasks.map(t=>({id:t.id,title:t.title,owner:a.role,reason:t.question,evidence_refs:'[]',blocking:1,status:'pending',contact_check:a.control==='contact',contact_resolvable:a.control==='contact'}))),signals:{signals:[]},authorizations:[],contact_clearance:null};
}
function setup(data:InquiryData,onPost:(path:string,body:any)=>unknown=()=>({})){
 const fetcher=vi.fn(async(path:string,options:RequestInit)=>({ok:true,json:async()=>structuredClone(options.method==='POST'?onPost(path,JSON.parse(String(options.body))):data)}));
 vi.stubGlobal('fetch',fetcher);
 return ()=>fetcher.mock.calls.filter(([,options])=>options.method==='POST').map(([path,options])=>[path,JSON.parse(String(options.body))]);
}
const first=task('t1','Check the larger order','SO-105040'),second=task('t2','Check the remaining order','SO-101546');
const orders=action('orders',[first,second],{role_key:'fulfillment',role:'Person responsible for fulfilling orders',lines:[{ref:'t1-line',order_id:'SO-105040',sku:'CL-FS10',qty:'65',date:'2026-09-25',status:'open',amount_cents:845010,age_days:37}]});
const contact=action('contacts',[task('tc','Verify the authorized buyer')],{control:'contact'});
const needs=action('needs',[task('tn','Confirm the requested training')]);
const records=action('records',[task('tr','Verify the CRM match')],{can_prepare_internal:false});

it('opens the same evidence and controls for the four categories; reading creates no work',async()=>{
 const posts=setup({recipients:[],inquiries:[]});const evidence=work([orders,contact,needs,records]);
 render(<><PracticalNext work={evidence}/><PracticalActions oid="acct" work={evidence}/></>);
 await screen.findAllByRole('button',{name:'Prepare internal email'});
 for(const a of evidence.practical_actions!){
  const card=within(screen.getByRole('article',{name:a.title}));
  expect(card.getByText(a.found)).toBeInTheDocument();
  expect(card.getByText(a.why,{exact:false})).toBeInTheDocument();
  expect(card.getByText(a.next_step,{exact:false})).toBeInTheDocument();
  expect(card.getByRole('button',{name:a.control==='contact'?'Enter purchasing details':'Record a verified finding'})).toBeEnabled();
  expect(!!card.queryByRole('button',{name:'Prepare internal email'})).toBe(a.can_prepare_internal);
 }
 const hash=screen.getByRole('link',{name:'Complete this in What Needs Verification'}).getAttribute('href')!;
 expect(document.getElementById(decodeURIComponent(hash.slice(1)))).toBe(screen.getByRole('article',{name:orders.title}));
 const card=within(screen.getByRole('article',{name:orders.title}));
 fireEvent.click(card.getByText('Inspect 1 saved order or credit line'));
 expect(card.getByText('$8,450.10')).toBeInTheDocument();
 expect(card.getByText('37 days')).toBeInTheDocument();
 expect(posts()).toEqual([]);
});

it('scopes group review to the selected account tasks; verified direct findings need evidence',async()=>{
 const posts=setup({recipients:[],inquiries:[]},()=>({requires_reassessment:true}));
 render(<PracticalActions oid="acct" work={work([orders,needs,records])} scope={['tn']}/>);
 expect(screen.queryByRole('article',{name:orders.title})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Record a verified finding'}));
 fireEvent.change(screen.getByLabelText('Verified finding'),{target:{value:'The buyer requested refresher training for the night shift.'}});
 expect(screen.getByRole('button',{name:'Confirm this finding'})).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Supporting record or person'),{target:{value:'Account owner’s logged call.'}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm this finding'}));
 expect(await screen.findByRole('status')).toHaveTextContent('review this account automatically');
 expect(posts()).toEqual([['/api/investigations/tn/resolve',{resolution:'The buyer requested refresher training for the night shift.\nVerified source: Account owner’s logged call.'}]]);
});

it('only requests missing purchasing details and keeps a contact partial without explicit permission',async()=>{
 const posts=setup({recipients:[],inquiries:[]},()=>({status:'partial',task_status:'pending',requires_reassessment:false}));
 const data=work([contact]);
 data.contact_clearance={task_id:'tc',contact_name:'',recipient:'',role:'Buyer',phone:'',route:'direct',distributor:'',verification_evidence:'Buyer identified in CRM',status:'partial',updated_at:'2026-11-01'};
 render(<PracticalActions oid="acct" work={data}/>);
 fireEvent.click(screen.getByRole('button',{name:'Enter purchasing details'}));
 expect(screen.queryByLabelText('Purchasing role')).not.toBeInTheDocument();expect(screen.queryByLabelText('Purchasing route')).not.toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Work email'),{target:{value:'buyer@example.invalid'}});
 expect(screen.queryByRole('button',{name:'Verify purchasing details'})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Review purchasing permission'})).toBeEnabled();
 fireEvent.click(screen.getByRole('button',{name:'Save partial information'}));
 await waitFor(()=>expect(posts()).toHaveLength(1));
 expect(posts()[0][1]).toMatchObject({task_id:'tc',verified:false});
});

it('never presents nonaction or internal reasoning tasks as email or verification work',async()=>{
 const posts=setup({recipients:[],inquiries:[]});const data=work([orders]);data.practical_actions=[];
 render(<PracticalActions oid="acct" work={data}/>);
 expect(screen.getByText('No verification checks are open for the current recommendation.')).toBeInTheDocument();
 expect(screen.queryAllByRole('button')).toHaveLength(0);
 expect(posts()).toEqual([]);
});

it('requires group-specific recipient proof, exact version approval and explicit per-task reply verification',async()=>{
 let saved:InternalInquiry|undefined;const box:InquiryData={recipients:[{group_id:'another-group',role_key:orders.role_key,responsibility:orders.role,recipient:'unrelated@example.invalid',evidence:'Different scope'}],inquiries:[]};
 const base='/api/accounts/acct/internal-inquiries';
 const posts=setup(box,(path,body)=>{
  if(path===base)saved={id:'mail',group_id:orders.id,responsibility:orders.role,task_ids:orders.task_ids,pending_task_ids:orders.task_ids,tasks:orders.tasks,lines:orders.lines,recipient:body.recipient,subject:'Existing orders',body:'Please check SO-105040 and SO-101546.',version:1,snapshot_hash:'v1',status:'awaiting_approval',replies:[],job_id:null};
  if(!saved)throw Error('Draft missing');
  if(path.endsWith('/edit'))saved={...saved,subject:body.subject,body:body.body,version:2,snapshot_hash:'v2'};
  if(path.endsWith('/approve'))saved={...saved,status:'sent_simulated'};
  if(path.endsWith('/reply'))saved={...saved,status:'reply_recorded',replies:[{id:'r1',body:body.body,record_refs:['SO-105040'],confirmed_task_ids:[],suggested_findings:{t1:'SO-105040 was fulfilled.'}}]};
  if(path.endsWith('/confirm'))saved={...saved,pending_task_ids:['t2'],replies:saved.replies.map(r=>({...r,confirmed_task_ids:['t1']})),job_id:'targeted-review'};
  box.inquiries=[saved];return saved;
 });
 render(<PracticalActions oid="acct" work={work([orders])}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Prepare internal email'}));
 expect(posts()).toEqual([]);
 fireEvent.change(screen.getByLabelText('Internal work email'),{target:{value:'fulfillment@example.invalid'}});
 fireEvent.change(screen.getByLabelText('How did you verify this internal recipient?'),{target:{value:'Directory lists the order owner.'}});
 expect(screen.getByRole('button',{name:'Prepare draft for review'})).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox',{name:/I verified this person/}));
 fireEvent.click(screen.getByRole('button',{name:'Prepare draft for review'}));
 await screen.findByRole('textbox',{name:'Internal email subject'});
 expect(posts()).toEqual([[base,{group_id:orders.id,recipient:'fulfillment@example.invalid',verification_evidence:'Directory lists the order owner.'}]]);
 fireEvent.click(screen.getByRole('button',{name:'Change internal recipient'}));
 expect(screen.queryByRole('button',{name:'Approve version 1 and simulate sending'})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Prepare draft for review'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Change internal recipient'}));
 const subject=screen.getByRole('textbox',{name:'Internal email subject'});
 fireEvent.change(subject,{target:{value:'Confirm the two open orders'}});
 expect(screen.getByRole('button',{name:'Approve version 1 and simulate sending'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Save edits for review'}));
 fireEvent.click(await screen.findByRole('button',{name:'Approve version 2 and simulate sending'}));
 await screen.findByText('Last action: Internal email sent');
 expect(posts()[2]).toEqual([base+'/mail/approve',{snapshot_hash:'v2'}]);
 fireEvent.click(screen.getByRole('button',{name:'Demo · Record simulated internal reply'}));
 fireEvent.change(screen.getByLabelText('What did the internal recipient say?'),{target:{value:'SO-105040 was fulfilled. Other order is unclear.'}});
 fireEvent.click(screen.getByRole('button',{name:'Record reply as unverified'}));
 fireEvent.click(await screen.findByRole('button',{name:'Review and record the finding'}));
 await screen.findByText('Recorded internal reply · unverified statement');
 expect(posts().filter(([p])=>p.endsWith('/confirm'))).toHaveLength(0);
 fireEvent.click(screen.getByRole('checkbox',{name:first.title}));
 expect(screen.getByLabelText('Verified finding for '+first.title)).toHaveValue('SO-105040 was fulfilled.');
 fireEvent.change(screen.getByLabelText('Verified finding for '+first.title),{target:{value:'Only one was confirmed.'}});
 fireEvent.change(screen.getByLabelText('Supporting source for '+first.title),{target:{value:'Signed proof of delivery'}});
 expect(screen.getByRole('button',{name:'Confirm selected findings'})).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Verified finding for '+first.title),{target:{value:'SO-105040 was fulfilled.'}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm selected findings'}));
 await screen.findByText('Reviewed internal response');
 expect(posts().at(-1)).toEqual([base+'/mail/confirm',{reply_id:'r1',findings:[{task_id:'t1',finding:'SO-105040 was fulfilled.',source:'Signed proof of delivery'}]}]);
 expect(screen.queryByRole('checkbox',{name:second.title})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Prepare internal email'})).not.toBeInTheDocument();
});

it('opens one account from a grouped recommendation and reuses its scoped practical check',async()=>{
 const group={id:'investigation:orders',kind:'investigation',title:'Check open orders and credits',why:'Clarify fulfillment and billing.',members:orders.tasks.map(t=>({id:'acct',name:'Range Line',task_id:t.id,workflow:'recovery',decline_cents:1500}))};
 const fetcher=vi.fn(async(path:string,options:RequestInit)=>({ok:true,json:async()=>path==='/api/work'?{groups:[group]}:path==='/api/opportunities'?[]:path.endsWith('/commercial-work')?work([orders,needs]):{recipients:[],inquiries:[]}}));
 vi.stubGlobal('fetch',fetcher);render(<GroupReview id={group.id}/>);
 const open=await screen.findByRole('button',{name:'Review checks'});
 expect(screen.getAllByRole('link',{name:'Range Line'})).toHaveLength(1);
 expect(fetcher.mock.calls.some(([path])=>path.endsWith('/commercial-work'))).toBe(false);
 fireEvent.click(open);const pane=await screen.findByRole('region',{name:'Checks for Range Line'});
 expect(within(pane).getByRole('article',{name:orders.title})).toBeInTheDocument();
 expect(within(pane).queryByRole('article',{name:needs.title})).not.toBeInTheDocument();
 expect(await within(pane).findByRole('button',{name:'Prepare internal email'})).toBeEnabled();
 expect(within(pane).getByRole('link',{name:/View account/})).toHaveAttribute('href','/accounts/acct#next-action');
 expect(fetcher.mock.calls.some(([,options])=>options.method==='POST')).toBe(false);
});

it('retains saved contact records as optional history when the current action is closed',async()=>{
 const posts=setup({recipients:[],inquiries:[]});const data=work([]);
 data.authorizations=[{recipient:'buyer@example.invalid',role:'Buyer',route:'direct',evidence:'Verified by the owner',authorized:1,updated_at:'2026-11-01'}];
 render(<PracticalActions oid="acct" work={data}/>);
 const closed=screen.getByText('Saved purchasing contact and route');
 expect(closed.closest('details')).not.toHaveAttribute('open');
 expect(screen.getByText('No verification checks are open for the current recommendation.')).toBeInTheDocument();
 fireEvent.click(closed);expect(await screen.findByText('buyer@example.invalid')).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Prepare internal email'})).not.toBeInTheDocument();
 expect(posts()).toEqual([]);
});

it('keeps only one task form open and preserves entries when switching methods',()=>{
 const box={recipients:[],inquiries:[]};const posts=setup(box);
 render(<PracticalActions oid="acct" work={work([orders,contact])} inquiries={box}/>);
 const orderCard=within(screen.getByRole('article',{name:orders.title}));
 const prepare=orderCard.getByRole('button',{name:'Prepare internal email'}),record=orderCard.getByRole('button',{name:'Record a verified finding'});
 fireEvent.click(prepare);
 fireEvent.change(screen.getByRole('textbox',{name:'Internal work email'}),{target:{value:'order.team@example.invalid'}});
 fireEvent.click(record);
 expect(prepare).toHaveAttribute('aria-expanded','false');expect(record).toHaveAttribute('aria-expanded','true');
 expect(screen.queryByRole('textbox',{name:'Internal work email'})).toBeNull();
 fireEvent.click(prepare);
 expect(screen.getByRole('textbox',{name:'Internal work email'})).toHaveValue('order.team@example.invalid');
 const buyer=screen.getByRole('button',{name:'Enter purchasing details'});fireEvent.click(buyer);
 expect(prepare).toHaveAttribute('aria-expanded','false');expect(buyer).toHaveAttribute('aria-expanded','true');
 fireEvent.click(prepare);
 expect(screen.getByRole('textbox',{name:'Internal work email'})).toHaveValue('order.team@example.invalid');
 expect(buyer).toHaveAttribute('aria-expanded','false');
 expect(screen.queryByRole('textbox',{name:'Verified finding'})).toBeNull();
 fireEvent.click(prepare);
 expect(prepare).toHaveAttribute('aria-expanded','false');
 expect(posts()).toEqual([]);
});

it('projects seven requested Range Line orders, preserves the sent version, and tracks one verified finding separately from six pending orders',()=>{
 const recordIds=['SO-105040','SO-101546','SO-100219','SO-100762','SO-103115','SO-105677','SO-104185'];
 const allLines=[...recordIds,recordIds[0]].map((order_id,index)=>({...orders.lines[0],ref:'ref-'+index,order_id}));
 const identity=action('contacts',[task('channel','Verify authorized buyer')],{control:'contact'});
 const credit=action('orders',[task('credit','Confirm credit status')],{id:'credit-check',title:'Confirm credit status',role_key:'billing'});
 const tasks=[{...first,record_refs:['ref-0','ref-7']},{...second,record_ids:recordIds.slice(1),record_refs:allLines.slice(1,7).map(l=>l.ref)}];
 const fulfillment={...orders,tasks,task_ids:tasks.map(t=>t.id),lines:allLines};
 const sent:InternalInquiry={id:'sent',group_id:fulfillment.id,role_key:'fulfillment',responsibility:orders.role,
  task_ids:fulfillment.task_ids,pending_task_ids:fulfillment.task_ids,tasks,lines:allLines,recipient:'fulfillment.test@example.invalid',
  subject:'Range Line open order status',body:'Original sent body covering all seven orders.',version:2,snapshot_hash:'v2',status:'sent_simulated',sent_at:'2026-11-15T12:00:00Z',sent_version:2,replies:[],job_id:null,
  record_states:recordIds.map((order_id,i)=>({order_id,line_refs:allLines.filter(l=>l.order_id===order_id).map(l=>l.ref),task_ids:[tasks[i===0?0:1].id],status:'status_requested'})),
  previous_versions:[{version:1,subject:'Earlier draft',recipient:'fulfillment.test@example.invalid',body:'Earlier draft text.',created_at:'2026-11-15T11:00:00Z'}]};
 const ui=(action:PracticalAction,inquiry:InternalInquiry)=>{
  const evidence=work([action,credit,identity]),box={recipients:[],inquiries:[inquiry]};
  return <><PracticalNext work={evidence} inquiries={box}/><PracticalActions oid="acct" work={evidence} inquiries={box}/></>;
 };
 const posts=setup({recipients:[],inquiries:[]});
 const preview=render(ui(fulfillment,sent));let card=within(screen.getByRole('article',{name:orders.title}));
 expect(screen.getAllByText('Awaiting fulfillment update')).toHaveLength(2);
 expect(screen.getAllByText(/covers 7 orders \(8 lines\)/)).toHaveLength(2);
 expect(card.getAllByText(/Status requested/)).toHaveLength(7);
 expect(card.getByText('View sent email').closest('details')).not.toHaveAttribute('open');
 expect(card.getByText('Earlier draft versions (1)').closest('details')).not.toHaveAttribute('open');
 expect(card.getByText(/Version 2 · Simulated delivery/)).toBeInTheDocument();
 expect(card.getByText('Last action: Internal email sent').parentElement?.querySelector('time')).toHaveAttribute('datetime',sent.sent_at);
 expect(card.queryByRole('button',{name:'Prepare internal email'})).toBeNull();
 // The consolidated request keeps its original scope when its first task is verified.
 const finding='SO-105040: both lines are on hold. The fulfillment owner is resolving the address mismatch.';
 const partial:InternalInquiry={...sent,status:'reply_recorded',workflow_state:'partially_verified',pending_task_ids:[tasks[1].id],
  replies:[{id:'r',body:'Update on SO-105040 only',record_refs:['SO-105040'],confirmed_task_ids:[tasks[0].id]}],
  record_states:sent.record_states!.map((r,i)=>({...r,status:i===0?'verified':'status_requested'})),
  task_states:[{task_id:tasks[0].id,status:'verified',finding},{task_id:tasks[1].id,status:'status_requested',finding:null}]};
 const remaining={...fulfillment,task_ids:[tasks[1].id],tasks:[tasks[1]],lines:allLines.slice(1,7)};
 preview.rerender(ui(remaining,partial));card=within(screen.getByRole('article',{name:orders.title}));
 expect(screen.getAllByText(/SO-105040 has a verified finding\. 6 orders still need confirmation/)).toHaveLength(2);
 expect(card.getByText('Sent internal email')).toBeInTheDocument();expect(card.queryByText('Last action: Internal email sent')).toBeNull();
 expect(card.getAllByText(/Status requested/)).toHaveLength(6);expect(card.getByText(/Finding verified/)).toBeInTheDocument();
 expect(card.getByText(finding,{exact:false})).toBeInTheDocument();
 expect(card.queryByRole('button',{name:'Prepare internal email'})).toBeNull();
 expect(card.queryByRole('button',{name:'Review and record the finding'})).toBeNull();
 expect(within(screen.getByRole('article',{name:credit.title})).getByRole('button',{name:'Prepare internal email'})).toBeEnabled();
 expect(within(screen.getByRole('article',{name:identity.title})).getByRole('button',{name:'Enter purchasing details'})).toBeEnabled();
 expect(posts()).toEqual([]);
});

it('keeps the highest priority check visible and reports a send for a different check in Next Action',()=>{
 const billing=action('orders',[task('bill','Check credit memo','SO-7-CR')],{id:'billing:current',title:'Check the issued credit',role_key:'billing',role:'Accounts receivable'});
 const inquiry:InternalInquiry={id:'credit-mail',group_id:billing.id,role_key:'billing',responsibility:billing.role,
  task_ids:billing.task_ids,pending_task_ids:billing.task_ids,tasks:billing.tasks,lines:[],recipient:'billing.test@example.invalid',subject:'Check credit',body:'Please confirm.',
  version:1,snapshot_hash:'v1',status:'sent_simulated',replies:[],job_id:null,sent_at:'2026-11-15T13:00:00Z',sent_version:1};
 const evidence=work([orders,billing]);
 render(<PracticalNext work={evidence} inquiries={{recipients:[],inquiries:[inquiry]}}/>);
 expect(screen.getByText(orders.title)).toBeInTheDocument();
 expect(screen.getByText('Awaiting billing update',{exact:false})).toBeInTheDocument();
 expect(screen.getByRole('link',{name:billing.title})).toHaveAttribute('href','#check-billing%3Acurrent');
});
