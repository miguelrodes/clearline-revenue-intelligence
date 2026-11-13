import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {AssessmentView} from '../src/components/detail-views';
import {ConversationPanel} from '../src/components/conversation';
const outbound={id:'sent-1',direction:'outbound',subject:'Purchasing question',body:'Do you still need supplies?',created_at:'2026-11-12T14:00:00Z',status:'sent_simulated',reply_to:null,interpretation:null,job:null};
const thread={status:'awaiting_response',messages:[outbound],context:{outreach_policy:'normal',contact:null,channel:null},tasks:[]};
it('injects only user text and the selected parent, without predefined AI classification or approval',async()=>{
 const fetcher=vi.fn(async(_url:unknown,options?:RequestInit)=>({ok:true,json:async()=>options?.method==='POST'?{duplicate:false}:thread}));vi.stubGlobal('fetch',fetcher);
 render(<ConversationPanel id="lone"/>);await screen.findByText('Purchasing question');
 fireEvent.change(screen.getByLabelText('Optional example'),{target:{value:'Training request'}});
 fireEvent.change(screen.getByLabelText('Fictional customer reply'),{target:{value:'Can you help our night shift?'}});
 fireEvent.click(screen.getByRole('button',{name:'Inject reply & run AI'}));
 await screen.findByText(/Reply saved/);
 const call=fetcher.mock.calls.find(c=>c[1]?.method==='POST')!;
 expect(call[0]).toBe('/api/accounts/lone/conversation/replies');
 const payload=JSON.parse(String(call[1]?.body));expect(Object.keys(payload).sort()).toEqual(['body','message_id','reply_to']);
 expect(payload.body).toBe('Can you help our night shift?');expect(payload.reply_to).toBe('sent-1');
 expect(fetcher.mock.calls.some(c=>String(c[0]).includes('decision'))).toBe(false);
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

it('uses a local scroll control for the prepared response instead of opening another account overlay',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...thread,tasks:[{id:'t',title:'Review response.',status:'awaiting_approval'}]})})));
 render(<ConversationPanel id="lone"/>);
 expect(await screen.findByRole('button',{name:'Review the prepared response below'})).toBeInTheDocument();
 expect(screen.queryByRole('link',{name:'Review the prepared response below'})).not.toBeInTheDocument();
});
