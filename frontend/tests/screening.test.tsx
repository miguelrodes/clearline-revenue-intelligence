import {describe,it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {ProspectScreening,ScreeningDetail} from '@/components/prospect-screening';
import {useApi,request} from '@/lib/api';
vi.mock('@/lib/api',async()=>({...await vi.importActual('@/lib/api'),useApi:vi.fn(),request:vi.fn(),refresh:vi.fn()}));
vi.mock('@/components/sales-surface',()=>({Overlay:({children}:{children:React.ReactNode})=><div>{children}</div>}));
const row={id:'agency',name:'Example Jail',state:'KS',agency_type:'county_jail',classification:'unverified_prospect',priority:1,evidence_hash:'hash',qualification_status:'not_assessed',product_fit:['CL-MAIL50'],ranking_reason:'Possible physical screening application',source_refs:['public_agencies:2'],next_action:'Verify internal evidence',review_passed:null,jobs:[],qualification:null,evidence:{classification_reason:'No named history; not proof of net-new',ranking_reason:'Possible physical screening application',agency:[{agency_name:'Example Jail',jail_beds:'300'}],relationship_records:[],segment_patterns:{},limits:['No authorized contact']}};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useApi).mockImplementation((path)=>({data:path==='/features'?{prospect_screening:true}:path==='/screening'?{source_records:2600,unique_records:2600,classifications:{},qualification_counts:{},assessed:0}:path==='/screening/agencies/agency'?row:path?.startsWith('/screening/agencies?')?{items:[row],total:26}:undefined,error:'',reload:vi.fn()}) as ReturnType<typeof useApi>)});
describe('Isolated prospect screening',()=>{
 it('keeps disabled section unavailable',()=>{vi.mocked(useApi).mockReturnValue({data:{prospect_screening:false},error:'',reload:vi.fn()});render(<ProspectScreening/>);expect(screen.getByText(/not enabled/)).toBeTruthy();expect(screen.queryByText('Example Jail')).toBeNull()});
 it('shows source evidence and filters/searches actual API records',async()=>{render(<ProspectScreening/>);fireEvent.click(screen.getByText('Agency file qualification tools'));await screen.findByText('Example Jail');fireEvent.change(screen.getByLabelText('Customer relationship'),{target:{value:'possible_existing_channel'}});expect(vi.mocked(useApi).mock.calls.some(([p])=>p?.includes('classification=possible_existing_channel'))).toBe(true);fireEvent.change(screen.getByLabelText('Qualification status'),{target:{value:'reject'}});expect(vi.mocked(useApi).mock.calls.some(([p])=>p?.includes('outcome=reject'))).toBe(true);fireEvent.click(screen.getByText('Next'));expect(vi.mocked(useApi).mock.calls.some(([p])=>p?.includes('offset=25'))).toBe(true)});
 it('queues exact evidence without an approval or send control',async()=>{vi.mocked(request).mockResolvedValue({job_id:'job'});render(<ScreeningDetail id="agency"/>);fireEvent.click(screen.getByText('Investigate and qualify'));await waitFor(()=>expect(request).toHaveBeenCalledWith('/screening/agencies/agency/qualify','POST',{evidence_hash:'hash'}));expect(screen.queryByText(/Approve/)).toBeNull();expect(screen.getByText(/No authorized contact/)).toBeTruthy()});
 it('surfaces unavailable backend errors',()=>{vi.mocked(useApi).mockReturnValue({data:undefined,error:'Unavailable',reload:vi.fn()});render(<ProspectScreening/>);expect(screen.getByRole('alert').textContent).toBe('Unavailable')});
});

describe('Prospect decisions and clearance',()=>{
 it('shows ranking factors and sends a reasoned hold decision',async()=>{
  const detailed={...row,context_hash:'ctx',qualification_current:false,workflow:{decision:'new',rationale:'',information:{},stage:'not_contacted'},outreach_prerequisites:['Verify the intended recipient'],drafts:[],history:[],ranking:{score:85,eligible:true,interpretation:'Not a purchase probability',restriction:'Channel unknown',factors:[{key:'fit',label:'Institution and product fit',points:40,maximum:40,reason:'Mail screening hypothesis'}]}};
  vi.mocked(useApi).mockReturnValue({data:detailed,error:'',reload:vi.fn()});vi.mocked(request).mockResolvedValue({});render(<ScreeningDetail id="agency"/>);
  expect(screen.getByText(/Discovery score: 85.0/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Reason or specific check needed'),{target:{value:'Confirm operational use before spending more time'}});
  fireEvent.click(screen.getByText('Hold pending a check'));
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/screening/agencies/agency/decision','POST',{decision:'held',rationale:'Confirm operational use before spending more time'}));
  expect((screen.getByText('Prepare personalized email') as HTMLButtonElement).disabled).toBe(true);
 });
 it('saves partial contact information without auto qualification or permission',async()=>{
  vi.mocked(useApi).mockReturnValue({data:{...row,context_hash:'ctx',workflow:{decision:'accepted',rationale:'Fit',information:{},stage:'not_contacted'},outreach_prerequisites:['Verify contact'],drafts:[],history:[]},error:'',reload:vi.fn()});vi.mocked(request).mockResolvedValue({changed:true,ai_triggered:false});render(<ScreeningDetail id="agency"/>);
  fireEvent.change(screen.getByLabelText('Intended contact address'),{target:{value:'buyer@example.invalid'}});fireEvent.click(screen.getByText('Save verified information'));
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/screening/agencies/agency/information','POST',{information:{recipient:'buyer@example.invalid'},context_hash:'ctx'}));
  expect(request).toHaveBeenCalledTimes(1);expect((screen.getByLabelText('Outreach to this contact is authorized') as HTMLInputElement).checked).toBe(false);
 });
 it('requires an explicit click to approve the exact displayed version',async()=>{
  const d={id:'draft',version:2,recipient:'simulation@example.invalid',subject:'Application discussion',body:'Would a discussion of the mailroom application help?',status:'awaiting_approval'};
  vi.mocked(useApi).mockReturnValue({data:{...row,context_hash:'ctx',workflow:{decision:'accepted',rationale:'Fit',information:{},stage:'not_contacted'},outreach_prerequisites:[],drafts:[d],history:[]},error:'',reload:vi.fn()});vi.mocked(request).mockResolvedValue({});render(<ScreeningDetail id="agency"/>);
  expect(request).not.toHaveBeenCalled();fireEvent.click(screen.getByText('Approve version 2 & simulate sending'));
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/drafts/draft/decision','POST',{version:2,recipient:d.recipient,subject:d.subject,body:d.body,approve:true}));
 });
});
