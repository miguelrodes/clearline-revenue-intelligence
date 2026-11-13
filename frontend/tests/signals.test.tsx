import {it,expect,vi} from 'vitest';
import {render,screen,within} from '@testing-library/react';
import {SignalDetail} from '../src/components/signal-detail';

const cases=[
 ['inactivity','Reconnect inactive customers'],
 ['partial','Follow up on reduced purchasing'],
 ['product_decline','Discuss products with declining purchases'],
 ['direct_gap_channel_review','Review direct purchase gaps'],
] as const;

function detail(metric:string){
 const groups=Array.from({length:6},(_,i)=>({id:`messages:${metric}:${i}`,kind:'messages',title:i===0?cases.find(([key])=>key===metric)?.[1]:`Existing recovery action ${i+1}`,why:i===0?'Personalized messages are prepared for these customers; review the changes in their purchasing and decide who to contact.':`Review the saved work for this signal group.`,button_label:'Review prepared emails',rank:i,accounts:2,financial_cents:(6-i)*10000,financial_label:'Historical purchasing decline associated with these accounts',status:'ready',href:`/actions?group=messages%3A${metric}%3A${i}&signal=${metric}`}));
 return {key:metric,fact_summary:'2 customer records show this signal.',ai_advice:'Review the saved evidence.',limits:'Categories overlap.',chart:[],groups,actions:[{id:'customer-1',name:'Customer One',decline_cents:12000,status:'awaiting_approval',disposition:'human_decision',next_step:'Review the prepared email',recommendation:'Confirm current requirements.',account_href:'/accounts/customer-1',links:[{group_id:groups[0].id,kind:'messages',title:'Review prepared emails',href:`/actions?group=${encodeURIComponent(groups[0].id)}&focus=customer-1&signal=${metric}`}]}]};
}

it.each(cases)('%s shows prioritized, signal-specific rows and preserves Next Steps',async(metric,title)=>{
 const response=detail(metric);
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>String(path)===`/api/signals/${metric}`?response:[]})));
 render(<SignalDetail metric={metric}/>);
 expect(await screen.findByRole('heading',{name:'Top Recommended Actions'})).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Next Steps'})).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:title})).toBeInTheDocument();
 expect(screen.getByText(/Personalized messages are prepared/)).toBeInTheDocument();
 const actionList=screen.getByRole('list',{name:'Top signal-specific actions'});
 expect(within(actionList).getAllByRole('listitem')).toHaveLength(5);
 expect(within(actionList).getByRole('link',{name:new RegExp(`Review prepared emails: ${title}`)})).toHaveAttribute('href',response.groups[0].href);
 expect(screen.getByRole('link',{name:/See all recovery actions/})).toHaveAttribute('href','/actions');
 expect(screen.getByRole('link',{name:/Review prepared emails →/})).toHaveAttribute('href',response.actions[0].links[0].href);
 expect(screen.getByText('$600')).toBeInTheDocument();
 expect(screen.getByRole('textbox',{name:'Find a signal customer'})).toBeInTheDocument();
});
