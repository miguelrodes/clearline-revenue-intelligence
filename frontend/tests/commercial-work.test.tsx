import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {it,expect,vi,afterEach} from 'vitest';
import {CommercialWork} from '../src/components/commercial-work';

afterEach(()=>cleanup());
const signals={signals:[]};
function response(tasks:any[]=[],post:any={status:'partial',task_status:'pending',authorized:false,requires_reassessment:false}){
 return vi.fn(async (_path:unknown,options?:RequestInit)=>({ok:true,json:async()=>options?.method==='POST'?post:{tasks,signals,authorizations:[],contact_clearance:null}}));
}

it('records a specific non-contact finding through the existing task resolver',async()=>{
 const task={id:'task',title:'Reconcile invoice credit',owner:'Finance',reason:'The credit reason is missing.',evidence_refs:'[]',blocking:1,status:'pending'};
 const fetcher=response([task]);vi.stubGlobal('fetch',fetcher);
 render(<CommercialWork id="account"/>);
 await screen.findByText('Reconcile invoice credit');
 const input=screen.getByRole('textbox',{name:'Verified finding: Reconcile invoice credit'});
 const button=screen.getByRole('button',{name:'Record finding and reassess'});expect(button).toBeDisabled();
 fireEvent.change(input,{target:{value:'Duplicate invoice corrected. Billing reference 100.'}});fireEvent.click(button);
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/investigations/task/resolve'&&options?.method==='POST')).toBe(true));
 expect(fetcher.mock.calls.some(([path])=>String(path).includes('decision'))).toBe(false);
});

it('requires verified contact details, purchasing route, and provenance before clearing the selected check',async()=>{
 const task={id:'contact',title:'Verify purchasing contact',owner:'Sales',reason:'The current buyer is not verified.',evidence_refs:'["crm_notes"]',blocking:1,status:'pending'};
 const fetcher=response([task],{status:'verified',task_status:'resolved',authorized:true,requires_reassessment:true});vi.stubGlobal('fetch',fetcher);
 render(<CommercialWork id="account"/>);
 await screen.findByText('The current buyer is not verified.');
 const verify=screen.getByRole('button',{name:'Verify contact and reassess'});expect(verify).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Contact name'),{target:{value:'Morgan Reyes'}});
 fireEvent.change(screen.getByLabelText('Work email'),{target:{value:'morgan@example.test'}});
 fireEvent.change(screen.getByLabelText('Purchasing role'),{target:{value:'Purchasing coordinator'}});
 fireEvent.change(screen.getByLabelText('Purchasing route'),{target:{value:'direct'}});
 fireEvent.change(screen.getByLabelText(/How was this information verified/),{target:{value:'Account owner confirmed in the CRM.'}});
 expect(verify).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox',{name:/I verified that this contact is authorized/}));
 expect(verify).toBeEnabled();fireEvent.click(verify);
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')!;
 expect(JSON.parse(call[1]?.body as string)).toMatchObject({task_id:'contact',recipient:'morgan@example.test',route:'direct',verified:true});
 expect(await screen.findByRole('status')).toHaveTextContent('This contact check is cleared');
 expect(fetcher.mock.calls.some(([path])=>String(path).includes('/decision'))).toBe(false);
});

it('saves partial information while leaving the blocker open and authorization absent',async()=>{
 const task={id:'contact',title:'Verify purchasing contact',owner:'Sales',reason:'The current buyer is not verified.',evidence_refs:'[]',blocking:1,status:'pending'};
 const fetcher=response([task]);vi.stubGlobal('fetch',fetcher);
 render(<CommercialWork id="account"/>);await screen.findByText('The current buyer is not verified.');
 fireEvent.change(screen.getByLabelText('Contact name'),{target:{value:'Purchasing office'}});
 fireEvent.click(screen.getByRole('button',{name:'Save partial information'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')!;
 expect(JSON.parse(call[1]?.body as string)).toMatchObject({task_id:'contact',contact_name:'Purchasing office',verified:false});
 expect(await screen.findByRole('status')).toHaveTextContent('This check stays open');
});
