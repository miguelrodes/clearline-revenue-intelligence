import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
const params=new URLSearchParams('group=orders');
vi.mock('next/navigation',()=>({useSearchParams:()=>params}));
import {ReviewChecks} from '../src/components/review-checks';
const group={id:'orders',title:'Confirm pending orders',team:'Orders team',description:'Ask your orders team whether these orders went through.',accounts:6,only_check_accounts:2};
const detail={...group,subject:'Confirm these orders',request_body:'Please confirm the attached list.',source_error:null,members:Array.from({length:6},(_,i)=>({id:String(i),name:`Customer ${i}`,state:'MA',order_ids:[`ORDER-${i}`],only_check:i<2,checks_left:i<2?[]:['Match customer names and locations']}))};
beforeEach(()=>{
 vi.restoreAllMocks();params.set('group','orders');
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path==='/api/checks'?{priority_records:6,background_records:218,groups:[group]}:detail})));
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:vi.fn().mockResolvedValue(undefined)}});
});
it('prepares one request and download without sending or approving anything',async()=>{
 render(<ReviewChecks/>);
 fireEvent.click(await screen.findByRole('button',{name:'Copy request'}));
 expect(await screen.findByRole('status')).toHaveTextContent('Copied. Nothing has been sent.');
 expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Subject: Confirm these orders\n\nPlease confirm the attached list.');
 expect(screen.getByRole('link',{name:'Download customer list'})).toHaveAttribute('href','/api/checks/orders/export');
 expect(screen.queryByRole('link',{name:'Customer 5'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Show all 6 customers'}));
 expect(screen.getByRole('link',{name:'Customer 5'})).toBeInTheDocument();
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
 expect(screen.getByText(/218 records have questions but no current recovery signal/)).toBeInTheDocument();
});
it('blocks a stale source export and leaves the user a recovery instruction',async()=>{
 vi.mocked(fetch).mockImplementation(async path=>({ok:true,json:async()=>path==='/api/checks'?{priority_records:6,background_records:218,groups:[group]}:{...detail,source_error:'Source records changed. Run a new scan.'}} as Response));
 render(<ReviewChecks/>);
 expect(await screen.findByRole('alert')).toHaveTextContent('Run a new scan');
 expect(screen.getByRole('button',{name:'Copy request'})).toBeDisabled();
 expect(screen.queryByRole('link',{name:'Download customer list'})).not.toBeInTheDocument();
});
