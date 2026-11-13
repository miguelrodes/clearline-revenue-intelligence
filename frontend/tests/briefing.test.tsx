import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {OperationalBriefing,ExecutionPanel} from '../src/components/operations';
const brief={summary:'You have 15 emails ready to review.',created_at:'2026-11-12T06:00:00Z',actions:[{id:'campaign:1',title:'Review 15 emails',why:'Investigation and drafting are complete.',accounts:15,historical_decline_cents:16119700,href:'/campaigns?campaign=1&pending=1'},{id:'contacts',title:'Review 35 contact gaps',why:'Recipients need verification.',accounts:35,historical_decline_cents:9239700,href:'/opportunities?queue=contacts'},{id:'followups',title:'Review 3 scheduled follow-ups',why:'Already scheduled.',accounts:3,historical_decline_cents:10368000,href:'/actions?category=scheduled&workflow=recovery&kind=followup'}]};
beforeEach(()=>{vi.restoreAllMocks();vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({brief,stale:false,job:null})}))});
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
 fireEvent.click(await screen.findByRole('button',{name:'Refresh briefing'}));
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
 expect(await screen.findByRole('link',{name:'Confirm pending orders'})).toHaveTextContent('Review request');
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
