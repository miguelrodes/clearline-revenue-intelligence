import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {OperationalBriefing,ExecutionPanel} from '../src/components/operations';
const brief={summary:'You have 15 emails ready to review.',created_at:'2026-11-12T06:00:00Z',actions:[{id:'campaign:1',title:'Review 15 emails',why:'Investigation and drafting are complete.',accounts:15,historical_decline_cents:16119700,href:'/campaigns?campaign=1&pending=1'},{id:'contacts',title:'Review 35 contact gaps',why:'Recipients need verification.',accounts:35,historical_decline_cents:9239700,href:'/opportunities?queue=contacts'},{id:'followups',title:'Review 3 scheduled follow-ups',why:'Already scheduled.',accounts:3,historical_decline_cents:10368000,href:'/actions?category=scheduled&workflow=recovery&kind=followup'}]};
beforeEach(()=>{vi.restoreAllMocks();vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({brief,stale:false,job:null})}))});
it('appends scoped historical revenue context without changing the saved explanation or inventing a forecast',async()=>{
 const priorities=[
  {action_id:'orders',title:'Orders and credits',text:'39 customers need order or credit checks; ask owners for findings.',revenue_context:{historical_decline_cents:11966508,accounts:36,excludes_distributors:true}},
  {action_id:'contacts',title:'Purchasing contacts',text:'Verify the purchasing contacts.',revenue_context:{historical_decline_cents:11612600,accounts:27,excludes_distributors:false}},
  {action_id:'unknown',title:'Customer replies',text:'Review the customer reply.'},
  {action_id:'already_priced',title:'Lower purchasing',text:'27 customers have $116,126 in historical decline; review emails.',revenue_context:{historical_decline_cents:11612600,accounts:27,excludes_distributors:false}},
 ];
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,priority_items:priorities},stale:false,job:null})} as Response);
 render(<OperationalBriefing/>);
 const list=await screen.findByRole('list',{name:'Overview brief priorities'});
 expect(list.children[0]).toHaveTextContent(`${priorities[0].text} — $120K historical decline (excl. distributors).`);
 expect(list.children[1]).toHaveTextContent('$116K historical decline.');
 expect(list.children[2]).not.toHaveTextContent('$');
 expect(list.children[3].querySelector('.brief-revenue-context')).toBeNull();
 expect(list.children[0].querySelector('.brief-revenue-context')).toHaveAttribute('title',expect.stringContaining('$119,665 historical purchasing decline across 36 customer accounts'));
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
it('shows the four mixed-group totals, covered counts and exclusions beside unchanged action links',async()=>{
 const samples=[['orders',39,36,11966508,'$119,665.08'],['contacts',268,265,133758460,'$1,337,584.60'],['needs',32,31,7254196,'$72,541.96'],['records',151,149,56882798,'$568,827.98']] as const;
 const actions=samples.map(([key,total,included,cents],i)=>({id:`investigation:${key}`,title:`Check ${key}`,why:'Saved commercial recommendation',accounts:total,financial_cents:null,historical_decline_cents:null,href:`/actions?group=investigation:${key}`,recommended_order:i,revenue_context:{historical_decline_cents:cents,total_accounts:total,accounts:included,excluded_distributor_accounts:total-included,excludes_distributors:true,metric:'positive_account_net_purchasing_decline',comparison:{current_start:'2026-01-01',current_end_exclusive:'2026-11-01',prior_start:'2025-01-01',prior_end_exclusive:'2025-11-01'},unavailable_reason:null}}));
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,actions,priority_items:actions.map(a=>({title:a.title,text:'Saved priority explanation.',action_id:a.id,revenue_context:a.revenue_context}))},stale:false,job:null})} as Response);
 const {container}=render(<OperationalBriefing/>);await screen.findByRole('link',{name:'Check orders'});
 const rows=container.querySelectorAll('.brief-actions>li');expect(rows).toHaveLength(4);
 samples.forEach(([key,total,included,,amount],i)=>{
  expect(rows[i]).toHaveTextContent(amount);expect(rows[i]).toHaveTextContent(`${included} of ${total} accounts`);
  expect(rows[i]).toHaveTextContent(`${total-included} distributor${total-included===1?'':'s'} excluded`);
  expect(screen.getByRole('link',{name:`Check ${key}`})).toHaveAttribute('href',`/?group=investigation:${key}`);
  expect(screen.getByRole('link',{name:`Check ${key}`})).toHaveTextContent(/^Review →$/);
  expect(rows[i]).toHaveTextContent('groups overlap and must not be added');
 });
 expect(container).not.toHaveTextContent('A combined revenue total is not provided');
 fireEvent.change(screen.getByLabelText('Sort recommended actions'),{target:{value:'revenue'}});
 expect(container.querySelector('.brief-actions>li')).toHaveTextContent('Check contacts');
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
it('provides real destinations and exposes historical decline without a forecast',async()=>{
 render(<OperationalBriefing/>);
 for(const a of brief.actions)expect(await screen.findByRole('link',{name:a.title})).toHaveAttribute('href',a.href);
 expect(screen.getByText('$161,197').closest('span')).toHaveTextContent('$161,197 associated historical decline');
 expect(screen.getByText('$161,197').tagName).toBe('STRONG');
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
it('never leaves stale approval recommendations actionable',async()=>{
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:null,stale:true,job:{status:'queued'}})} as Response);
 render(<OperationalBriefing/>);
 expect(await screen.findByText(/Things have changed/)).toBeInTheDocument();
 expect(screen.queryByRole('link',{name:'Review 15 emails'})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Updating…'})).toBeDisabled();
});
it('manual refresh queues a briefing without approving any outreach',async()=>{
 render(<OperationalBriefing/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Refresh briefing'})).toBeEnabled());
 fireEvent.click(screen.getByRole('button',{name:'Refresh briefing'}));
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(c=>c[0]==='/api/brief'&&c[1]?.method==='POST')).toBe(true));
 expect(vi.mocked(fetch).mock.calls.every(c=>!String(c[0]).includes('decision'))).toBe(true);
});
it('distinguishes actual model execution from ready and deferred work',async()=>{
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({jobs:{running:15,queued:37,completed:30},active_investigations:[],model_requests_inflight:12,queue_ready:35,retry_wait:2,average_seconds:20,recommendations_per_minute_5m:18,model_requests:70,input_tokens:1000,output_tokens:500,estimated_cost_usd:.4,unpriced_records:0,capacity:{active_limit:15,configured_max:15,peak_investigations:15},batches:[]})} as Response);
 render(<ExecutionPanel/>);
 expect(await screen.findByText('AI requests in flight')).toBeInTheDocument();
 expect(screen.getByText('Waiting to start')).toBeInTheDocument();
 expect(screen.getByText('Waiting to retry')).toBeInTheDocument();
});

it('shows a grouped request instead of a record-by-record review count',async()=>{
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,actions:[{id:'record_checks',title:'Confirm pending orders',why:'Ask your orders team whether they went through.',accounts:35,historical_decline_cents:null,href:'/checks?group=orders',button_label:'Review request',scope_label:'One request · 35 customer records'}]},stale:false,job:null})} as Response);
 render(<OperationalBriefing/>);
 expect(await screen.findByRole('link',{name:'Confirm pending orders'})).toHaveTextContent(/^Review →$/);
 expect(screen.getByText('One request · 35 customer records')).toBeInTheDocument();
 expect(screen.queryByText(/associated historical decline/)).not.toBeInTheDocument();
});

it('keeps all recommendations and sorts using saved amounts and due priority',async()=>{
 const actions=Array.from({length:7},(_,i)=>({id:`a${i}`,title:`Action ${i}`,why:'Prepared work',accounts:1,href:`/actions?group=a${i}`,financial_cents:i*100,recommended_order:i,time_priority:i===5?0:3,earliest_due_at:i===5?'2026-11-10T00:00:00Z':null}));
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,actions},stale:false,job:null})} as Response);
 render(<OperationalBriefing/>);
 await screen.findByRole('link',{name:'Action 6'});
 const names=()=>screen.getAllByRole('link').map(x=>x.getAttribute('aria-label'));
 expect(names()).toHaveLength(7);expect(names()[0]).toBe('Action 0');
 fireEvent.change(screen.getByLabelText('Sort recommended actions'),{target:{value:'revenue'}});expect(names()[0]).toBe('Action 6');
 fireEvent.change(screen.getByLabelText('Sort recommended actions'),{target:{value:'time'}});expect(names()[0]).toBe('Action 5');
 fireEvent.change(screen.getByLabelText('Sort recommended actions'),{target:{value:'recommended'}});expect(names()[0]).toBe('Action 0');
});

it('caps recommendations after sorting and expands saved customer context',async()=>{
 const actions=Array.from({length:12},(_,i)=>({id:`a${i}`,title:`Action ${i}`,why:'Review purchasing needs.',accounts:1,href:`/actions?group=a${i}`,financial_cents:i*100,recommended_order:i,members:[{id:`c${i}`,name:`Customer ${i}`,href:`/accounts/c${i}?tab=outreach`,task:'Confirm who handles purchasing.',subject:'Purchasing contact',due_at:'2026-11-19T12:00:00Z',historical_decline_cents:12300}]}));
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,actions},stale:false,job:null})} as Response);
 const {container}=render(<OperationalBriefing/>);
 await screen.findByRole('link',{name:'Action 9'});
 expect(container.querySelectorAll('.brief-actions>li')).toHaveLength(10);
 expect(screen.queryByRole('link',{name:'Action 11'})).not.toBeInTheDocument();
 expect(container.querySelector('.brief-rank')).toBeNull();
 fireEvent.change(screen.getByLabelText('Sort recommended actions'),{target:{value:'revenue'}});
 expect(await screen.findByRole('link',{name:'Action 11'})).toHaveAttribute('href','/?group=a11');
 fireEvent.click(screen.getAllByText('View 1 customer')[0]);
 expect(screen.getByRole('link',{name:'Customer 11'})).toHaveAttribute('href','/accounts/c11?tab=outreach');
 expect(container.querySelector('details')).toHaveAttribute('open');
 expect(container.querySelector('details')).toHaveTextContent('Prepared email: Purchasing contact');
});

it('renders separate sales briefing bullets with the saved explanations',async()=>{
 const points=['Review the prepared emails and approve the customers you want to contact.','Ask the orders team to confirm pending purchases before restarting outreach.'];
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,summary_points:points},stale:false,job:null})} as Response);
 render(<OperationalBriefing/>);
 const list=await screen.findByRole('list',{name:'Overview brief priorities'});
 expect(list.querySelectorAll('li')).toHaveLength(2);
 for(const point of points)expect(list).toHaveTextContent(point);
});

it('renders current records when the saved briefing is stale and rereads them on rehearsal refresh',async()=>{
 const live={...brief,source:'live_actions',created_at:null,summary:'Lone Tree has a reply ready to review.'};
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:live,stale:true,job:null,last_generated_at:'2026-11-12T06:00:00Z',refresh_mode:'read'})} as Response);
 render(<OperationalBriefing/>);
 expect(await screen.findByRole('list',{name:'Overview brief priorities'})).toHaveTextContent(live.summary);
 expect(screen.getByText('From current account records')).toBeVisible();
 expect(screen.queryByText(/Last updated/)).toBeNull();
 expect(screen.getByRole('link',{name:brief.actions[0].title})).toHaveAttribute('href',brief.actions[0].href);
 const reads=()=>vi.mocked(fetch).mock.calls.filter(c=>c[0]==='/api/brief').length;
 const before=reads();
 fireEvent.click(screen.getByRole('button',{name:'Refresh briefing'}));
 await waitFor(()=>expect(reads()).toBeGreaterThan(before));
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});

it('keeps sent inquiries visible under Waiting and outside recommended actions',async()=>{
 const waiting={id:'internal:waiting',title:'Awaiting internal findings',why:'The fulfillment team already has the order references.',
  accounts:1,tasks:2,href:'/actions?group=internal%3Awaiting',button_label:'View sent inquiry'};
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({brief:{...brief,waiting:[waiting]},stale:false,job:null})} as Response);
 render(<OperationalBriefing/>);
 const region=await screen.findByRole('region',{name:'Waiting'});
 expect(region).toHaveTextContent('1 customer · 2 waiting tasks');
 expect(region.querySelector('a')?.getAttribute('href')).toEqual(waiting.href);
 expect(screen.getByRole('list',{name:'Prioritized recommendations'})).not.toHaveTextContent(waiting.title);
});
