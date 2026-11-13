import {it,expect,vi} from 'vitest';
import {render,screen} from '@testing-library/react';
import {SignalDetail} from '../src/components/signal-detail';
it('shows grounded signal values, the saved AI advice, and existing group destinations',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({key:'inactivity',fact_summary:'2 account records show this signal, associated with $200 in historical purchasing decline.',ai_advice:'Confirm the purchasing contact before reconnecting. A distributor switch is a hypothesis.',limits:'Categories overlap.',chart:[],actions:[{id:'a',name:'Customer A',decline_cents:20000,status:'awaiting_approval',disposition:'human_decision',next_step:'Review email',recommendation:'Reconnect about purchasing.',account_href:'/accounts/a',links:[{group_id:'messages:inactivity',kind:'messages',title:'Review emails',href:'/actions?group=messages%3Ainactivity&focus=a&signal=inactivity'}]}],groups:[{id:'messages:inactivity',kind:'messages',title:'Reconnect customers',accounts:1,href:'/actions?group=messages%3Ainactivity&signal=inactivity'}]})})));
 render(<SignalDetail metric="inactivity"/>);
 expect(await screen.findByText(/2 account records show this signal/)).toBeInTheDocument();
 expect(screen.getByText(/distributor switch is a hypothesis/)).toBeInTheDocument();
 expect(screen.getByText('$200')).toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Review prepared emails · 1'})).toHaveAttribute('href','/actions?group=messages%3Ainactivity&signal=inactivity');
 expect(screen.getByRole('link',{name:'Review emails →'})).toHaveAttribute('href','/actions?group=messages%3Ainactivity&focus=a&signal=inactivity');
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});
