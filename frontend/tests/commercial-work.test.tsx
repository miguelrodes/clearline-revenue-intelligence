import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {it,expect,vi,afterEach} from 'vitest';
import {CommercialWork} from '../src/components/commercial-work';
import {cleanup} from '@testing-library/react';
afterEach(()=>cleanup());
it('records a specific human finding and requests reassessment without approving a draft',async()=>{
 const fetcher=vi.fn(async (_path:unknown,options?:RequestInit)=>({ok:true,json:async()=>options?.method==='POST'?{requires_reassessment:true}:{tasks:[{id:'task',title:'Reconcile invoice credit',owner:'Finance',reason:'The credit reason is missing.',blocking:1}],signals:{signals:[]}}}));
 vi.stubGlobal('fetch',fetcher);
 render(<CommercialWork id="account"/>);
 await screen.findByText('Reconcile invoice credit');
 const button=screen.getByRole('button',{name:'Record finding and reassess'});expect(button).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Verified finding'),{target:{value:'Duplicate invoice corrected. Billing reference 100.'}});fireEvent.click(button);
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/investigations/task/resolve'&&options?.method==='POST')).toBe(true));
 expect(fetcher.mock.calls.some(([path])=>String(path).includes('decision'))).toBe(false);
});
it('requires recipient, role and authorization evidence before recording permission',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({tasks:[],signals:{signals:[]}})})));
 render(<CommercialWork id="account"/>);
 const button=await screen.findByRole('button',{name:'Confirm authorization and reassess',hidden:true});expect(button).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Recipient'),{target:{value:'buyer@example.org'}});
 fireEvent.change(screen.getByLabelText('Role'),{target:{value:'Purchasing'}});expect(button).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Authorization evidence'),{target:{value:'Confirmed existing purchasing relationship in account record.'}});expect(button).toBeEnabled();
});
