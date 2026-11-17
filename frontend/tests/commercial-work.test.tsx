import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {it,expect,vi,afterEach} from 'vitest';
import {CommercialWork} from '../src/components/commercial-work';
import {ContactClearanceEditor,type ContactWorkData} from '../src/components/contact-clearance';

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
 expect(screen.getAllByRole('textbox')).toHaveLength(2);
 expect(screen.queryByLabelText('Purchasing route')).toBeNull();
 expect(screen.queryByRole('button',{name:'Verify purchasing details'})).toBeNull();
 fireEvent.change(screen.getByLabelText('Work email'),{target:{value:'morgan@example.test'}});
 fireEvent.change(screen.getByLabelText('Purchasing role'),{target:{value:'Purchasing coordinator'}});
 fireEvent.click(screen.getByRole('button',{name:'Review purchasing permission'}));
 const verify=screen.getByRole('button',{name:'Verify purchasing details'});
 expect(verify).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Purchasing route'),{target:{value:'direct'}});
 expect(verify).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Record authorizing this buyer and route'),{target:{value:'Account owner confirmed in the CRM.'}});
 expect(screen.queryByRole('checkbox')).toBeNull();
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
 fireEvent.change(screen.getByLabelText('Purchasing role'),{target:{value:'Purchasing office'}});
 fireEvent.click(screen.getByRole('button',{name:'Save partial information'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([path,options])=>path==='/api/accounts/account/contact-clearance'&&options?.method==='POST')!;
 expect(JSON.parse(call[1]?.body as string)).toMatchObject({task_id:'contact',role:'Purchasing office',verified:false});
 expect(await screen.findByRole('status')).toHaveTextContent('This check stays open');
});

it('keeps an internal interaction check separate from contact verification despite a contact warning',async()=>{
 const task={id:'kimball',title:'Reconcile the October 24 interaction with the undated purchasing-handoff note',owner:'Dana K.',reason:'Review the existing interaction record. This is an internal resolution check, not a task to solicit a new contact from the customer.',evidence_refs:'["crm_accounts:216"]',blocking:1,status:'pending',contact_check:false,contact_resolvable:false};
 vi.stubGlobal('fetch',response([task]));render(<CommercialWork id="kimball"/>);
 expect(await screen.findByRole('textbox',{name:`Verified finding: ${task.title}`})).toBeInTheDocument();
 expect(screen.queryByLabelText('Work email')).not.toBeInTheDocument();
 expect(screen.getByText(/Suggested team \/ owner: Dana K/)).toBeInTheDocument();
});

it('shows the exact open-order finding first and leaves the separate contact form collapsed',async()=>{
 const order={id:'order',title:'Extend existing disposition task: SO-102281 and SO-101701',owner:'Order operations',reason:'Check SO-102281’s 75-pack open line and SO-101701’s 88-pack open line, supporting shipment records and any authorized next step.',evidence_refs:'["orders:6063"]',blocking:1,status:'pending',contact_check:false,contact_resolvable:false};
 const contact={id:'contact',title:'Complete existing Bluewater recipient-authorization task',owner:'Channel sales manager',reason:'Confirm the established purchasing recipient. This is not required to begin internal investigation.',evidence_refs:'[]',blocking:1,status:'pending',contact_check:true,contact_resolvable:true};
 vi.stubGlobal('fetch',response([contact,order]));const {container}=render(<CommercialWork id="bluewater"/>);
 const finding=await screen.findByRole('textbox',{name:`Verified finding: ${order.title}`});
 expect(finding).toBeInTheDocument();
 const editor=container.querySelector('details.contact-clearance-editor');expect(editor).not.toHaveAttribute('open');
 expect(finding.compareDocumentPosition(editor!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
 expect(screen.getByText(/Check SO-102281/)).toHaveTextContent('75-pack');
});

it('does not invent a contact-verification action for a no-action account with no open checks',async()=>{
 vi.stubGlobal('fetch',response());render(<CommercialWork id="falcon"/>);
 expect(await screen.findByText(/No verification checks are open/)).toBeInTheDocument();
 expect(screen.queryByLabelText('Work email')).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:/reassess/i})).not.toBeInTheDocument();
});

it('uses the task title rather than incidental reason keywords for older task responses',async()=>{
 const task={id:'order',title:'Verify operational disposition of SO-102281',owner:'Order operations',reason:'Record any authorized next step before contacting anyone.',evidence_refs:'[]',blocking:1,status:'pending'};
 vi.stubGlobal('fetch',response([task]));render(<CommercialWork id="account"/>);
 expect(await screen.findByRole('textbox',{name:`Verified finding: ${task.title}`})).toBeInTheDocument();
 expect(screen.queryByLabelText('Work email')).not.toBeInTheDocument();
});

const contactTask={id:'contact',title:'Verify purchasing contact',owner:'Sales',reason:'Confirm buyer',evidence_refs:'[]',blocking:1,status:'pending',contact_check:true,contact_resolvable:true};
const confirmed={recipient:'buyer@example.test',role:'Buyer',route:'distributor',evidence:'Account owner recorded approval through the distributor in CRM-5.',authorized:1,updated_at:'2026-11-01'};

it('applies the exact saved authorization to a contact check without asking for the details again',async()=>{
 const data:ContactWorkData={tasks:[contactTask],signals,authorizations:[confirmed],contact_clearance:null};
 const fetcher=response([], {task_status:'resolved',requires_reassessment:true,authorized:true});vi.stubGlobal('fetch',fetcher);
 render(<ContactClearanceEditor id="account" taskId="contact" data={data} autoOpen/>);
 expect(screen.queryByRole('textbox')).toBeNull();
 expect(screen.getByText(/Verified purchasing contact/)).toHaveTextContent('Through a distributor');
 fireEvent.click(screen.getByRole('button',{name:'Complete check with saved contact'}));
 await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
 expect(JSON.parse(fetcher.mock.calls[0][1]?.body as string)).toMatchObject({
  task_id:'contact',recipient:confirmed.recipient,role:confirmed.role,route:confirmed.route,verification_evidence:confirmed.evidence,verified:true,
 });
});

it.each([['Work email','newbuyer@example.test'],['Purchasing role','Different buyer'],['Purchasing route','direct']])('requires new supporting evidence after changing %s on an authorized contact',async(field,value)=>{
 const data:ContactWorkData={tasks:[contactTask],signals,authorizations:[confirmed],contact_clearance:null};
 const fetcher=response();vi.stubGlobal('fetch',fetcher);
 render(<ContactClearanceEditor id="account" taskId="contact" data={data} autoOpen/>);
 fireEvent.click(screen.getByRole('button',{name:'Review or correct saved details'}));
 fireEvent.click(screen.getByRole('button',{name:'Review purchasing permission'}));
 fireEvent.change(screen.getByLabelText(field),{target:{value}});
 expect(screen.getByLabelText('Record authorizing this buyer and route')).toHaveValue('');
 expect(screen.getByRole('button',{name:'Verify purchasing details'})).toBeDisabled();
 expect(screen.queryByRole('button',{name:'Complete check with saved contact'})).toBeNull();
 expect(fetcher).not.toHaveBeenCalled();
});

it('keeps a different partial buyer separate from an earlier verified contact',()=>{
 const note={task_id:'contact',contact_name:'',recipient:'newbuyer@example.test',role:'',phone:'',route:'',distributor:'',verification_evidence:'',status:'partial',updated_at:'2026-11-02'};
 const data:ContactWorkData={tasks:[contactTask],signals,authorizations:[confirmed],contact_clearance:note};
 render(<ContactClearanceEditor id="account" taskId="contact" data={data} autoOpen/>);
 expect(screen.getByLabelText('Purchasing role')).toHaveValue('');
 fireEvent.change(screen.getByLabelText('Purchasing role'),{target:{value:'Purchasing assistant'}});
 fireEvent.click(screen.getByRole('button',{name:'Review purchasing permission'}));
 expect(screen.getByLabelText('Purchasing route')).toHaveValue('');
 expect(screen.getByRole('button',{name:'Verify purchasing details'})).toBeDisabled();
 expect(screen.queryByText(confirmed.evidence,{exact:false})).toBeNull();
});

it('does not offer to complete an identity check using contact authorization',()=>{
 const data:ContactWorkData={tasks:[{...contactTask,id:'identity',contact_resolvable:false}],signals,authorizations:[confirmed],contact_clearance:null};
 render(<ContactClearanceEditor id="account" taskId="identity" data={data} autoOpen/>);
 expect(screen.queryByRole('button',{name:'Complete check with saved contact'})).toBeNull();
 expect(screen.getByText(/Verified purchasing contact/)).toHaveTextContent(confirmed.recipient);
});
