import {fireEvent,render,screen,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {ProspectGroupReview,ProspectOverview} from '@/components/prospect-overview';
import {useApi,request} from '@/lib/api';

vi.mock('@/lib/api',async()=>({...await vi.importActual('@/lib/api'),useApi:vi.fn(),request:vi.fn()}));

const fictional={id:'county',name:'Sample County Jail',href:'/screening?agency=county',status:'Qualified for internal review',
 description:'Fictional county detention facility.',commercial_context:'Comparable county buyers purchased mailroom tests.',
 next_step:'Verify the mail screening application.',evidence:['Agency source row 62'],action_label:'Open qualification'};
const real={id:'pa',name:'Pennsylvania Department of Corrections',href:'/accounts/pa#prospect-outreach',status:'Draft awaiting approval',
 description:'Real state corrections agency.',commercial_context:'Saved research documents a suspect-paper screening use case.',
 next_step:'Review the intended discovery inquiry.',evidence:['DOC report'],action_label:'Review saved email'};
const groups=[
 {id:'qualification',title:'Review qualified institutions',source:'phase3',description:'Review the saved findings for these institutions.',count:1,members:[fictional]},
 {id:'draft',title:'Review a prepared discovery email',source:'phase4',description:'Prior research supports a technical discovery inquiry.',count:1,members:[real]},
];
function setup(groupsToShow=groups) {
 vi.mocked(useApi).mockReturnValue({data:{brief:[{title:'Discovery',text:'A saved qualification needs review.'}],groups:groupsToShow},error:'',reload:vi.fn()});
}
beforeEach(()=>{vi.clearAllMocks();setup()});

it('uses Overview action rows, with separate populations and filtered Review links',()=>{
 const actions=groups.map(g=>({id:g.id,title:g.title,description:g.description,button_label:'Review',href:g.source==='phase3'?'/screening?qualification=qualified':'/screening?stage=awaiting_approval',count:g.count}));
 vi.mocked(useApi).mockReturnValue({data:{metrics:{total:2},brief:['One saved email is awaiting approval.'],actions},error:'',reload:vi.fn()});
 render(<ProspectOverview/>);
 const list=within(screen.getByRole('list',{name:'Prospect recommendations'}));
 for(const action of actions) {
  const link=list.getByRole('link',{name:action.title});
  expect(link).toHaveAttribute('href',action.href);
  expect(link).toHaveTextContent('Review');
  expect(link.closest('.brief-action-main')).toBeTruthy();
 }
 expect(list.getAllByText('1 candidate')).toHaveLength(2);
 expect(request).not.toHaveBeenCalled();
});

it.each(groups)('opens only the members in $title and reveals their saved evidence and next action',group=>{
 render(<ProspectGroupReview id={group.id}/>);
 const member=group.members[0];
 expect(screen.getByRole('heading',{name:member.name})).toBeVisible();
 expect(screen.queryByText(groups.find(g=>g.id!==group.id)!.members[0].name)).toBeNull();
 const toggle=screen.getByRole('button',{name:'Review next step'});
 expect(toggle).toHaveAttribute('aria-expanded','false');
 fireEvent.click(toggle);
 expect(toggle).toHaveAttribute('aria-expanded','true');
 expect(screen.getByText(member.commercial_context)).toBeVisible();
 expect(screen.getByText(member.next_step,{exact:false})).toBeVisible();
 expect(screen.getByText(member.evidence[0])).toBeInTheDocument();
 expect(screen.getByRole('link',{name:member.action_label+' →'})).toHaveAttribute('href',member.href);
 expect(request).not.toHaveBeenCalled();
});

it('removes a group when its last candidate leaves that saved workflow state',()=>{
 const view=render(<ProspectGroupReview id="qualification"/>);
 setup([groups[1]]);
 view.rerender(<ProspectGroupReview id="qualification"/>);
 expect(screen.queryByText(fictional.name)).toBeNull();
 expect(screen.getByText(/no remaining work/)).toBeVisible();
});
