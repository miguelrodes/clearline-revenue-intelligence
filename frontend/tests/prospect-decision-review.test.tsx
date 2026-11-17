import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {ProspectGroupReview} from '@/components/prospect-overview';

it('records a reasoned hold inside the Overview disclosure and refreshes the saved population', async () => {
  const member = {id:'sample-agency',name:'Example County Jail',status:'Qualified for discovery',
    href:'/screening?agency=sample-agency',description:'Fictional county facility.',commercial_context:'A mail-screening use case needs confirmation.',
    next_step:'Decide whether to pursue.',evidence:['Source row 8'],action_label:'Review qualification'};
  const group = {id:'decision',source:'phase3',title:'Decide which qualified institutions to pursue',
    description:'Review each institution’s qualification.',count:1,members:[member]};
  const saved: {decision:string;rationale:string}[] = [];
  const fetch = vi.fn(async (url:string, options:RequestInit) => {
    if (url==='/api/overview/prospects' && options.method==='GET') {
      return Response.json({brief:[],groups:saved.some(d=>d.decision==='held')?[]:[group]});
    }
    if (url==='/api/screening/agencies/sample-agency/decision' && options.method==='POST') {
      saved.push(JSON.parse(String(options.body)));
      return Response.json(saved[0]);
    }
    throw Error('Unexpected request to '+url);
  });
  vi.stubGlobal('fetch', fetch);
  try {
    render(<ProspectGroupReview id="decision"/>);
    fireEvent.click(await screen.findByRole('button',{name:'Review next step'}));
    expect(screen.getByRole('link',{name:'Review qualification →'})).toHaveAttribute('href',member.href);
    const hold = screen.getByRole('button',{name:'Hold pending a check'});
    expect(hold).toBeDisabled();
    const rationale='Confirm whether purchasing goes through the county before approaching the facility.';
    fireEvent.change(screen.getByLabelText('Reason or specific check needed'),{target:{value:rationale}});
    fireEvent.click(hold);
    await waitFor(()=>expect(saved).toEqual([{decision:'held',rationale}]));
    expect(await screen.findByText(/no remaining work/)).toBeVisible();
    expect(screen.getByText(/prospect put on hold/i)).toBeVisible();
    expect(screen.queryByRole('heading',{name:member.name})).toBeNull();
    expect(fetch.mock.calls.filter(([,opts])=>opts.method==='POST')).toHaveLength(1);
  } finally {
    vi.unstubAllGlobals();
  }
});
