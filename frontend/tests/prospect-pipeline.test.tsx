import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {PipelineCandidate,PipelineMetrics,PipelineWorkspace} from '@/components/prospect-pipeline';
import {DiscoveryForm,ResearchForm} from '@/components/prospect-runs';
import {OverviewPage} from '@/components/sales-surface';
import {request,useApi} from '@/lib/api';
import type {Candidate,Pipeline} from '@/lib/prospect-pipeline';
vi.mock('@/lib/api',async()=>({...await vi.importActual('@/lib/api'),useApi:vi.fn(),request:vi.fn(),refresh:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({}),useSearchParams:()=>new URLSearchParams()}));

const candidate:Candidate={id:'real-1',name:'Sample Real Institution',state:'WY',segment:'prison',origin:'real_web',score:64,
 stage:'screened',qualification:'not_assessed',factors:[],reason:'Documented correctional setting.',comparison:'Comparable fictional customers purchased screening kits.',
 next_action:'Consider in-depth research.',href:'/accounts/real-1',detail_href:'/screening?candidate=real-1',verified:true,researchable:true,researched:false};
const agency:Candidate={...candidate,id:'fictional-1',name:'Fictional County Jail',origin:'fictional_csv',href:'/screening?agency=fictional-1',verified:false,researchable:false};
const data:Pipeline={metrics:{total:2,real_web:1,fictional_csv:1},brief:['One real prospect is awaiting research.'],actions:[],
 rows:[candidate,agency],offset:0,limit:25,total:2};
const budget={eligible_count:1,scope:'One verified Wyoming institution',max_cost_usd:.35,remaining_usd:.8,enabled:true};
function stub(result:unknown){return {data:result,error:'',reload:vi.fn()} as ReturnType<typeof useApi>}
beforeEach(()=>{vi.clearAllMocks();window.localStorage.clear();vi.mocked(useApi).mockImplementation(path=>stub(path?.startsWith('/prospect-pipeline?')?data:path==='/features'?{prospect_screening:true}:undefined));});
it('drills into both sources and routes research only to explicitly selected verified real prospects',async()=>{
 render(<PipelineWorkspace params="stage=awaiting_research"/>);
 expect(vi.mocked(useApi).mock.calls.at(-1)?.[0]).toContain('stage=awaiting_research');
 expect(screen.getByRole('link',{name:agency.name})).toHaveAttribute('href',agency.href+'&stage=awaiting_research');
 expect(screen.getByRole('link',{name:candidate.name})).toHaveAttribute('href',candidate.detail_href+'&stage=awaiting_research');
 expect(screen.queryByRole('checkbox',{name:'Select '+agency.name+' for research'})).toBeNull();
 expect(screen.getByRole('button',{name:'Research selected prospects'})).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox',{name:'Select '+candidate.name+' for research'}));
 vi.mocked(request).mockResolvedValueOnce(budget).mockResolvedValueOnce({job_ids:['job-real-1']});
 fireEvent.click(screen.getByRole('button',{name:'Research selected prospects'}));
 await screen.findByText('One verified Wyoming institution');
 expect(request).toHaveBeenCalledTimes(1);
 expect(request).toHaveBeenCalledWith('/prospect-pipeline/research/preview','POST',{candidate_ids:['real-1'],refresh:false});
 fireEvent.click(screen.getByRole('button',{name:'Confirm research'}));
 await waitFor(()=>expect(request).toHaveBeenCalledWith('/prospect-pipeline/research','POST',{candidate_ids:['real-1'],refresh:false,confirmed:true}));
});
it('explains every metric on hover and keyboard focus while retaining concise link names',()=>{
 const view=render(<PipelineMetrics data={data}/>);
 const links=screen.getAllByRole('link');
 expect(links).toHaveLength(10);
 for(const link of links){
  const tooltip=document.getElementById(link.getAttribute('aria-describedby')!)!;
  expect(link).toHaveAccessibleDescription(tooltip.textContent!);
  expect(tooltip).not.toBeVisible();
  fireEvent.mouseEnter(link);
  expect(screen.getByRole('tooltip')).toBe(tooltip);
  expect(tooltip).toBeVisible();
  fireEvent.mouseLeave(link);
  expect(tooltip).not.toBeVisible();
 }
 const priority=screen.getByRole('link',{name:'High priority 0'});
 fireEvent.focus(priority);
 expect(screen.getByRole('tooltip')).toHaveTextContent('70 or higher out of 100');
 fireEvent.keyDown(document,{key:'Escape'});
 expect(screen.queryByRole('tooltip')).toBeNull();
 view.rerender(<PipelineMetrics data={data} compact/>);
 expect(screen.getAllByRole('link')).toHaveLength(4);
 expect(screen.getByRole('link',{name:'High priority 0'})).toHaveAccessibleDescription(/priorities for investigation/);
});
it('invalidates a discovery estimate after the salesperson edits the scope and holds confirmation within budget',async()=>{
 render(<DiscoveryForm/>);vi.mocked(request).mockResolvedValue(budget);
 fireEvent.click(screen.getByRole('button',{name:'Preview discovery'}));await screen.findByRole('button',{name:'Confirm discovery'});
 fireEvent.change(screen.getByLabelText('Maximum new candidates'),{target:{value:'5'}});
 expect(screen.queryByRole('button',{name:'Confirm discovery'})).toBeNull();
 vi.mocked(request).mockResolvedValue({...budget,enabled:false,disabled_reason:'Read-only rehearsal.'});
 fireEvent.click(screen.getByRole('button',{name:'Preview discovery'}));
 expect(await screen.findByText('Read-only rehearsal.')).toBeVisible();
 expect(screen.getByRole('button',{name:'Confirm discovery'})).toBeDisabled();
 expect(vi.mocked(request).mock.calls.every(([path])=>path.endsWith('/preview'))).toBe(true);
});
it('fails closed when a preview has no dollar limit',async()=>{
 vi.mocked(request).mockResolvedValue({...budget,max_cost_usd:undefined});
 render(<ResearchForm selected={[candidate]}/>);
 fireEvent.click(screen.getByRole('button',{name:'Research selected prospects'}));
 expect(await screen.findByRole('button',{name:'Confirm research'})).toBeDisabled();
 expect(screen.getByText(/Spending limits are unavailable/)).toBeVisible();
});
it('separates saved evidence and shortlist decisions from actual research',async()=>{
 vi.mocked(useApi).mockReturnValue(stub({...candidate,identity_confidence:'verified',attributes:{jail_beds:200},missing_fields:['procurement_route'],
   sources:[{url:'https://example.gov/agency',title:'Official directory',retrieved_at:'2026-11-16'}]}));
 render(<PipelineCandidate id="real-1"/>);
 expect(screen.getByRole('link',{name:'Official directory'})).toHaveAttribute('href','https://example.gov/agency');
 expect(screen.getByText(/Missing information: procurement route/)).toBeVisible();
 fireEvent.click(screen.getByText('Manage shortlist and disposition'));
 fireEvent.change(screen.getByLabelText('Decision'),{target:{value:'select_for_research'}});
 fireEvent.change(screen.getByLabelText('Reason (optional)'),{target:{value:'Verify the documented operational setting.'}});
 fireEvent.click(screen.getByRole('button',{name:'Save decision'}));
 await waitFor(()=>expect(request).toHaveBeenCalledWith('/prospect-pipeline/candidates/real-1/decision','POST',{decision:'select_for_research',rationale:'Verify the documented operational setting.'}));
 expect(request).toHaveBeenCalledTimes(1);
});
it('explains tied screening factors while distinguishing saved research from candidates awaiting research',()=>{
 const factors=[{key:'fit',label:'Product fit',points:38,maximum:40,reason:'Plausible product fit.'},
  {key:'scale',label:'Operational scale',points:0,maximum:25,reason:'No verified scale.'}];
 const ready={...candidate,score:38,factors,qualification:'unassessed'};
 const researched={...ready,id:'completed',name:'Researched institution',researched:true,stage:'needs_verification',qualification:'discovery_only'};
 vi.mocked(useApi).mockReturnValue(stub({...data,rows:[ready,researched]}));
 const page=render(<PipelineWorkspace/>);
 expect(screen.getByText(/2 institutions shown earned the same points/)).toHaveTextContent('Size contributed no points.');
 expect(within(screen.getByRole('row',{name:new RegExp(ready.name)})).getByText('Awaiting in-depth research')).toBeVisible();
 expect(within(screen.getByRole('row',{name:/Researched institution/})).getByText('Research completed · Discovery conversation only')).toBeVisible();
 const offsetting=[{...factors[0],points:37},{...factors[1],points:1}];
 vi.mocked(useApi).mockReturnValue(stub({...data,rows:[ready,{...researched,factors:offsetting}]}));
 page.rerender(<PipelineWorkspace/>);
 expect(screen.queryByText(/same points on every screening factor/)).toBeNull();
 expect(request).not.toHaveBeenCalled();
});
it('lands on filtered results when they load and opens the existing permission form without submitting',()=>{
 const original=HTMLElement.prototype.scrollIntoView;
 const scroll=vi.fn();
 HTMLElement.prototype.scrollIntoView=scroll;
 try{
  window.history.replaceState(null,'','/screening?origin=real&stage=needs_verification#candidates');
  const view=render(<PipelineWorkspace params="origin=real&stage=needs_verification"/>);
  expect(scroll.mock.contexts).toContain(document.getElementById('candidates'));
  view.unmount();
  const verification={...candidate,stage:'needs_verification',researched:true,outreach_permission_required:true,action_href:'/screening?candidate=real-1#prospect-permission'};
  vi.mocked(useApi).mockReturnValue(stub({...data,rows:[verification]}));
  const list=render(<PipelineWorkspace params="origin=real&stage=needs_verification"/>);
  const href=screen.getByRole('link',{name:candidate.name}).getAttribute('href')!;
  expect(href).toBe('/screening?candidate=real-1&origin=real&stage=needs_verification#prospect-permission');
  list.unmount();
  window.history.replaceState(null,'',href);
  vi.mocked(useApi).mockReturnValue(stub(verification));
  render(<PipelineCandidate id={candidate.id}/>);
  expect(screen.getByLabelText('Authorized recipient')).toBeVisible();
  expect(scroll.mock.contexts).toContain(document.getElementById('prospect-permission'));
  expect(request).not.toHaveBeenCalled();
 }finally{
  window.history.replaceState(null,'','/');
  HTMLElement.prototype.scrollIntoView=original;
 }
});
it('reapplies the current metric after a manual filter and scrolls once its results arrive',()=>{
 const original=HTMLElement.prototype.scrollIntoView;
 const scroll=vi.fn();HTMLElement.prototype.scrollIntoView=scroll;
 const bounds=vi.spyOn(HTMLElement.prototype,'getBoundingClientRect');
 let ready=true;
 vi.mocked(useApi).mockImplementation(path=>stub(path?.includes('q=')?{...data,rows:[agency]}:ready?data:undefined));
 try{
  window.history.replaceState(null,'','/screening?stage=high_priority#candidates');
  const view=render(<PipelineWorkspace params="stage=high_priority"/>);
  const search=screen.getByPlaceholderText('Find a candidate…');
  fireEvent.change(search,{target:{value:'Fictional'}});
  scroll.mockClear();ready=false;
  fireEvent.click(screen.getByRole('link',{name:/^High priority/i}));
  expect(search).toHaveValue('');
  expect(useApi).toHaveBeenLastCalledWith('/prospect-pipeline?limit=25&offset=0&stage=high_priority');
  expect(scroll).not.toHaveBeenCalled();
  bounds.mockImplementation(function(this:HTMLElement){
   return new DOMRect(0,this.matches('tbody tr')?window.innerHeight+100:0,300,50);
  });
  ready=true;view.rerender(<PipelineWorkspace params="stage=high_priority"/>);
  expect(scroll.mock.contexts).toEqual([document.querySelector('#candidates .table-scroll')]);
  expect(screen.getByRole('link',{name:candidate.name})).toBeVisible();
  view.rerender(<PipelineWorkspace params="stage=high_priority"/>);
  expect(scroll).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('link',{name:/^High priority/i}));
  expect(scroll).toHaveBeenCalledTimes(2);
 }finally{
  bounds.mockRestore();HTMLElement.prototype.scrollIntoView=original;
  window.history.replaceState(null,'','/');
 }
});
it('keeps both briefs visible and filters only the shared recommended actions',()=>{
 const prospectAction={id:'research',title:'Investigate a prospect',description:'Inspect the evidence.',href:'/screening?stage=screened',button_label:'View candidate',count:1};
 const accountAction={id:'order',title:'Check an order',why:'Verify the order status.',href:'/actions?group=order',accounts:1};
 vi.mocked(useApi).mockImplementation(path=>stub(path?.startsWith('/prospect-pipeline?')?{...data,actions:[prospectAction]}:path==='/features'?{prospect_screening:true}:path==='/brief'?{brief:{summary:'One order needs attention.',actions:[accountAction]}}:undefined));
 const page=render(<OverviewPage/>);
 const list=()=>within(screen.getByRole('list',{name:'Prioritized recommendations'}));
 expect(screen.queryByText('Scope',{exact:true})).toBeNull();
 expect(within(screen.getByRole('region',{name:'New prospects'})).getByText('Ready for research').tagName).toBe('STRONG');
 expect(screen.getAllByRole('heading',{name:'Recommended Actions'})).toHaveLength(1);
 expect(list().getByRole('link',{name:prospectAction.title})).toHaveAttribute('href',prospectAction.href);
 expect(list().getByRole('link',{name:accountAction.title})).toBeVisible();
 fireEvent.change(screen.getByLabelText('Scope'),{target:{value:'prospects'}});
 expect(list().queryByText(accountAction.title)).toBeNull();
 expect(screen.getByText('One order needs attention.')).toBeVisible();
 page.unmount();render(<OverviewPage/>);
 expect(screen.getByLabelText('Scope')).toHaveValue('prospects');
 fireEvent.change(screen.getByLabelText('Scope'),{target:{value:'existing'}});
 expect(list().queryByText(prospectAction.title)).toBeNull();
 expect(screen.getByText(data.brief[0])).toBeVisible();
 expect(list().getByRole('link',{name:accountAction.title})).toBeVisible();
 expect(request).not.toHaveBeenCalled();
});

it('finds an approved candidate from an empty review queue and searches outside the current filters',async()=>{
 const approved={...candidate,name:'Named prospect',stage:'awaiting_delivery',awaiting_research:false,researchable:false};
 const metrics={awaiting_approval:0,awaiting_delivery:1,awaiting_response:0,in_conversation:0};
 vi.mocked(useApi).mockImplementation(path=>stub({...data,metrics,rows:path?.includes('stage=awaiting_approval')?[]:[approved]}));
 render(<PipelineWorkspace params="stage=awaiting_approval"/>);
 expect(screen.getByRole('link',{name:'View approved outreach awaiting delivery (1)'})).toHaveAttribute('href','/screening?stage=awaiting_delivery#candidates');
 expect(screen.queryByRole('link',{name:'Awaiting simulated delivery 1'})).toBeNull();
 expect(screen.getByRole('option',{name:'Approved · awaiting simulated delivery'})).toHaveValue('awaiting_delivery');
 fireEvent.change(screen.getByLabelText('Institution name'),{target:{value:'Named prospect'}});
 fireEvent.click(screen.getByRole('button',{name:'Search all candidates'}));
 expect(screen.getByLabelText('Institution name')).toHaveValue('Named prospect');
 expect(screen.getByLabelText('Stage')).toHaveValue('');
 expect(screen.getByRole('row',{name:/Named prospect/})).toHaveTextContent('Approved · awaiting simulated delivery');
 expect(request).not.toHaveBeenCalled();
});
