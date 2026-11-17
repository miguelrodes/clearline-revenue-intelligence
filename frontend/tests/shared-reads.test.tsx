import {act,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {refresh,useApi} from '../src/lib/api';
import {OverviewPage} from '../src/components/sales-surface';

vi.mock('next/navigation',()=>({useRouter:()=>({}),useSearchParams:()=>new URLSearchParams()}));

it('starts the saved brief while financial data is pending and requests the overview only once',async()=>{
 const fetcher=vi.fn((_path:RequestInfo|URL)=>new Promise<Response>(()=>{}));
 vi.stubGlobal('fetch',fetcher);
 render(<OverviewPage/>);
 const paths=fetcher.mock.calls.map(([path])=>path);
 expect(paths.filter(p=>p==='/api/overview')).toHaveLength(1);
 expect(paths).toContain('/api/brief');
 expect(screen.getByRole('heading',{name:'Overview Brief'})).toBeInTheDocument();
});

it('shares polling and repeats a read invalidated by an edit while in flight',async()=>{
 let finish:(r:Response)=>void=()=>{};
 const fetcher=vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve}));
 vi.stubGlobal('fetch',fetcher);
 function Reader(){const {data}=useApi<string>('/shared-test');return <span>{data}</span>}
 render(<><Reader/><Reader/></>);
 expect(fetcher).toHaveBeenCalledTimes(1);
 act(()=>refresh());
 const respond=(str:string)=>act(async()=>finish({ok:true,json:async()=>str} as Response));
 await respond('before edit');
 expect(fetcher).toHaveBeenCalledTimes(2);
 expect(screen.queryByText('before edit')).toBeNull();
 await respond('after edit');
 await waitFor(()=>expect(screen.getAllByText('after edit')).toHaveLength(2));
});
