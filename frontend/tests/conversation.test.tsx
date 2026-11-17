import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {AssessmentView} from '../src/components/detail-views';
import {ConversationPanel} from '../src/components/conversation';
import {OutreachControls} from '../src/components/outreach-controls';
const outbound={id:'sent-1',direction:'outbound',subject:'Purchasing question',body:'Do you still need supplies?',created_at:'2026-11-12T14:00:00Z',status:'sent_simulated',reply_to:null,interpretation:null,job:null};
const thread={provider:'simulated',status:'awaiting_response',messages:[outbound],context:{outreach_policy:'normal',contact:null,channel:null},tasks:[]};
it('keeps the inbound editor unavailable until the account has a sent message',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,messages:[],status:'not_started'})})));
 render(<ConversationPanel id="uncontacted" accountStatus="no_action" canRecordReply/>);
 await screen.findByText('Customer Conversations');
 expect(screen.queryByText('Simulate Incoming Reply')).toBeNull();
 expect(screen.queryByText('Demo / Testing Controls')).toBeNull();
});
it('posts the manual pause reason and optional date without authorizing a send',async()=>{
 const fetcher=vi.fn(async(_url:unknown,_options?:RequestInit)=>({ok:true,json:async()=>({restrictions:[]})}));vi.stubGlobal('fetch',fetcher);
 render(<OutreachControls id="sample" restrictions={[]}/>);
 fireEvent.click(screen.getByRole('button',{name:'Pause outreach'}));
 fireEvent.change(screen.getByLabelText('Reason for the pause'),{target:{value:'Waiting for the purchasing handoff.'}});
 fireEvent.change(screen.getByLabelText('Reconsider on (optional)'),{target:{value:'2026-12-01'}});
 fireEvent.click(screen.getByRole('button',{name:'Save pause'}));
 await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
 expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({action:'pause',scope:'account',reason:'Waiting for the purchasing handoff.',reconsider_on:'2026-12-01'});
});
it('keeps demo reply controls out of ineligible account profiles',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>thread})));
 render(<ConversationPanel id="lone"/>);
 expect(await screen.findByText('Purchasing question')).toBeVisible();
 expect(screen.queryByText('Simulate Incoming Reply')).toBeNull();
 expect(screen.queryByText('Demo / Testing Controls')).toBeNull();
 expect(screen.queryByText('Outreach controls')).toBeNull();
});

it('opens a collapsed demo editor and saves one linked reply through the conversation endpoint',async()=>{
 const prior={...outbound,id:'sent-earlier',subject:'Earlier email'};
 const fetcher=vi.fn(async(_url:unknown,options?:RequestInit)=>({ok:true,json:async()=>options?.method==='POST'
  ? {duplicate:false} : {...thread,messages:[prior,outbound]}}));
 vi.stubGlobal('fetch',fetcher);
 render(<ConversationPanel id="eligible-account" canRecordReply/>);
 const toggle=await screen.findByText('Demo / Testing Controls');
 expect(toggle.closest('details')).not.toHaveAttribute('open');
 fireEvent.click(toggle);
 const parent=screen.getByRole('combobox',{name:'Replying to'});
 expect(parent).toHaveValue(outbound.id);
 fireEvent.change(parent,{target:{value:prior.id}});
 const save=screen.getByRole('button',{name:'Save'});
 expect(save).toBeDisabled();
 fireEvent.change(screen.getByRole('textbox',{name:'Record simulated reply'}),{target:{value:'  A fixture reply  '}});
 fireEvent.click(save);
 expect(await screen.findByText('Reply saved. AI interpretation is queued.')).toBeVisible();
 const writes=fetcher.mock.calls.filter(([,options])=>options?.method==='POST');
 expect(writes).toHaveLength(1);
 expect(writes[0][0]).toBe('/api/accounts/eligible-account/conversation/replies');
 expect(JSON.parse(String(writes[0][1]?.body))).toEqual({reply_to:prior.id,message_id:expect.any(String),body:'A fixture reply'});
 expect(save).toBeDisabled();
});

it('retains the reply text and reuses its message identifier after a save failure',async()=>{
 const writes:string[]=[];
 vi.stubGlobal('fetch',vi.fn(async(_url:unknown,options?:RequestInit)=>{
  if(options?.method==='POST'){
   writes.push(String(options.body));
   if(writes.length===1)throw new Error('Connection interrupted');
   return {ok:true,json:async()=>({duplicate:true})};
  }
  return {ok:true,json:async()=>thread};
 }));
 render(<ConversationPanel id="retry-example" canRecordReply/>);
 fireEvent.click(await screen.findByText('Demo / Testing Controls'));
 const box=screen.getByRole('textbox',{name:'Record simulated reply'});
 fireEvent.change(box,{target:{value:'Fixture for retry'}});
 fireEvent.click(screen.getByRole('button',{name:'Save'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
 expect(box).toHaveValue('Fixture for retry');
 fireEvent.click(screen.getByRole('button',{name:'Save'}));
 expect(await screen.findByText('This reply was already recorded.')).toBeVisible();
 expect(writes).toHaveLength(2);
 expect(writes[1]).toBe(writes[0]);
});

it('asks for the opt-out scope and source before saving a recipient restriction',async()=>{
 const fetcher=vi.fn(async(_url:unknown,_options?:RequestInit)=>({ok:true,json:async()=>({})}));
 vi.stubGlobal('fetch',fetcher);
 render(<OutreachControls id="sample" recipient="buyer@example.org" restrictions={[]}/>);
 fireEvent.click(screen.getByRole('button',{name:'Do not contact'}));
 const confirm=screen.getByRole('button',{name:'Confirm do not contact'});
 expect(confirm).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Who asked to stop contact?'),{target:{value:'recipient'}});
 expect(screen.getByLabelText('Recipient covered by the request')).toHaveValue('buyer@example.org');
 fireEvent.change(screen.getByLabelText('Original opt-out request or source'),{target:{value:'The buyer asked us to stop.'}});
 expect(fetcher).not.toHaveBeenCalled();
 fireEvent.click(confirm);
 await waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());
 expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({action:'do_not_contact',scope:'recipient',recipient:'buyer@example.org',reason:'The buyer asked us to stop.'});
});

it('shows the saved reason and the appropriate next control for restricted accounts',()=>{
 const restriction={id:'hold',kind:'pause',scope:'account',source:'manual_salesperson',recipient:'',reason:'Purchasing is on hold.'} as const;
 const view=render(<OutreachControls id="sample" restrictions={[restriction]}/>);
 expect(screen.getByRole('status')).toHaveTextContent(restriction.reason);
 expect(screen.getByRole('button',{name:'Resume outreach'})).toBeVisible();
 view.rerender(<OutreachControls id="sample" restrictions={[{...restriction,kind:'do_not_contact'}]}/>);
 expect(screen.getByRole('status')).toHaveTextContent('Do Not Contact · entire account');
 expect(screen.queryByRole('button',{name:'Resume outreach'})).toBeNull();
});
it('shows AI interpretation and restrictions without offering automatic sending',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,status:'channel_review',context:{...thread.context,outreach_policy:'channel_review'},messages:[outbound,{...outbound,id:'reply-1',direction:'inbound',reply_to:'sent-1',body:'We buy through Bluewater.',interpretation:{intent:'distributor',conversation_status:'channel_review',effective_status:'agent_held',rationale:'Purchases may have moved to a distributor.',recommended_action:'Confirm the buying route with your channel team.',facts:[],products:[],uncertainties:['Named end-customer records are unavailable.']}}],tasks:[{id:'task',title:'Confirm the buying route.',status:'pending'}]})})));
 render(<ConversationPanel id="lone"/>);expect(await screen.findByText(/Direct outreach is paused/)).toBeInTheDocument();
 expect(screen.getByText('Confirm the buying route with your channel team.')).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:/send/i})).not.toBeInTheDocument();
});

it('renders saved reply assessments with structured channel evidence from older rehearsal records',()=>{
 render(<AssessmentView assessment={{created_at:'2026-11-12',details:{decision:'hold',rationale:'Customer uses a distributor.',recommended_action:'Confirm that route.',channel:{route:'distributor',distributor:'Bluewater'},hypotheses:[],unresolved_questions:[],evidence_fields:[]}}}/>);
 expect(screen.getByText('distributor')).toBeInTheDocument();
});

it('starts each message collapsed and lets the reader toggle it independently of the AI summary',async()=>{
 const subject='Re: Purchasing question';
 const reply={...outbound,id:'reply-1',subject,direction:'inbound',reply_to:outbound.id,body:'We now have a new buyer.',
  interpretation:{intent:'contact_change',conversation_status:'needs_contact',effective_status:'needs_contact',
   rationale:'The purchasing contact has changed.',recommended_action:'Verify the new contact.',facts:[],products:[],uncertainties:[]}};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,messages:[outbound,reply]})})));
 render(<ConversationPanel id="lone"/>);
 const sales=await screen.findByRole('button',{name:'Show message: '+outbound.subject});
 const customer=screen.getByRole('button',{name:'Show message: '+subject});
 const summary=screen.getByText(/The latest simulated exchange/);
 const interpretation=screen.getByText(reply.interpretation.rationale);
 const salesText=screen.getByText(outbound.body), replyText=screen.getByText(reply.body);
 expect(sales).toHaveAttribute('aria-expanded','false');
 expect(customer).toHaveAttribute('aria-expanded','false');
 expect(salesText).not.toBeVisible();expect(replyText).not.toBeVisible();
 expect(summary).toBeVisible();expect(interpretation).toBeVisible();
 fireEvent.click(customer);
 expect(customer).toHaveAccessibleName('Hide message: '+subject);
 expect(customer).toHaveAttribute('aria-expanded','true');
 expect(replyText).toBeVisible();expect(salesText).not.toBeVisible();
 fireEvent.click(sales);fireEvent.click(customer);
 expect(salesText).toBeVisible();expect(replyText).not.toBeVisible();
 expect(summary).toBeVisible();expect(interpretation).toBeVisible();
 expect(vi.mocked(fetch).mock.calls.every(c=>c[1]?.method==='GET')).toBe(true);
});

it('uses a local scroll control for the prepared response instead of opening another account overlay',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,tasks:[{id:'t',title:'Review response.',status:'awaiting_approval'}]})})));
 render(<div className="account-profile"><section id="next-action"><details className="next-action-draft" data-draft-kind="response">
   <summary>Review personalized response</summary><p>Existing reply draft</p></details></section><ConversationPanel id="lone"/></div>);
 const shortcut=await screen.findByRole('button',{name:'Review the prepared response'});
 expect(screen.getByText('Existing reply draft')).not.toBeVisible();
 fireEvent.click(shortcut);
 expect(screen.getByText('Existing reply draft')).toBeVisible();
 expect(screen.getByText('Review personalized response')).toHaveFocus();
 expect(screen.queryByRole('link',{name:'Review the prepared response'})).not.toBeInTheDocument();
});


it('does not offer nonexistent outreach for verification and no-action decisions',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,status:'not_started',messages:[]})})));
 render(<ConversationPanel id="verified-later" accountStatus="human_verification"/>);
 expect(await screen.findByText(/No email is currently ready for approval/)).toBeInTheDocument();
 expect(screen.queryByText(/Approve the prepared outreach below/)).not.toBeInTheDocument();
 expect(screen.queryByText(/Ready to start/)).not.toBeInTheDocument();
});
