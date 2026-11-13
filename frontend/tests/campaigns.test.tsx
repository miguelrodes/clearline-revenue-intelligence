import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
const params=new URLSearchParams();
vi.mock('next/navigation',()=>({useSearchParams:()=>params}));
import {CampaignCenter} from '../src/components/operations';
const campaign={id:'campaign',name:'Recovery review',status:'preparing',pending:0,ready:1,historical_decline_cents:10000,simulated_deliveries:0,scheduled_followups:0,recorded_outcomes:0,members:[{opportunity_id:'account',name:'Example Jail',ready:true,status:'awaiting_approval',exclusion:null,job_status:'completed',assessment:{decision:'pursue',strategy:'contact_change',recommended_action:'Verify current purchasing contact'},draft:{id:'draft',version:3,subject:'Purchasing contact',body:'Who handles purchasing?',recipient:'simulation@example.invalid',snapshot_hash:'reviewed-hash'}}]};
beforeEach(()=>{params.delete("campaign");params.delete("pending");vi.restoreAllMocks();vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>[campaign]}))});
it('bulk preview does not authorize and final confirmation sends captured hashes',async()=>{
 render(<CampaignCenter/>);
 fireEvent.click(await screen.findByRole('button',{name:'Approve 1 saved messages'}));
 expect(screen.getByRole('dialog')).toBeInTheDocument();
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Confirm'}));
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));
 const call=vi.mocked(fetch).mock.calls.find(c=>c[1]?.method==='POST')!;
 expect(call[0]).toBe('/api/campaigns/campaign/decision');
 expect(JSON.parse(call[1]?.body as string)).toEqual({approve:true,snapshots:[{draft_id:'draft',snapshot_hash:'reviewed-hash'}]});
});
it('blocks bulk approval while any account is preparing',async()=>{
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>[{...campaign,pending:1}]} as Response);
 render(<CampaignCenter/>);
 expect(await screen.findByRole('button',{name:'Approve 1 saved messages'})).toBeDisabled();
});
it('reports stale version rejection instead of claiming campaign approval',async()=>{
 vi.mocked(fetch).mockImplementation(async(_url,options)=>({ok:options?.method!=='POST',json:async()=>options?.method==='POST'?{detail:'Campaign changed; reload and review'}:[campaign]}) as Response);
 render(<CampaignCenter/>);
 fireEvent.click(await screen.findByRole('button',{name:'Approve 1 saved messages'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm'}));
 expect(await screen.findByRole('status')).toHaveTextContent('Campaign changed');
 expect(screen.queryByText('Approved. Simulated deliveries are queued.')).not.toBeInTheDocument();
});

it('opens only the requested campaign and expands its pending messages',async()=>{
 params.set('campaign','campaign');params.set('pending','1');
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>[campaign,{...campaign,id:'other',name:'Other campaign'}]} as Response);
 render(<CampaignCenter/>);
 expect(await screen.findByText('Recovery review')).toBeInTheDocument();
 expect(screen.queryByText('Other campaign')).not.toBeInTheDocument();
 expect(screen.getByText('Purchasing contact').closest('details')).toHaveAttribute('open');
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
