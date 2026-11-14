"""Explicit bounded Phase 3 run, no continuation or portfolio work."""
import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from screening_dev import configuration
from clearline.store import Store
from clearline.screening import detail,queue
from clearline.screening_budget import summary
from clearline.worker import execute_job,worker_lock

async def run(settings,ids):
    store=Store(settings.db_path)
    with worker_lock(settings.db_path):
        for aid in ids:
            row=detail(store,aid);queued=queue(store,settings,aid,row['evidence_hash'])
            if queued.get('reused'):
                print(json.dumps({'agency':row['name'],'reused':True}),flush=True);continue
            # Explicit job only: do not drain pre-existing demo work.
            with store.connect(write=True) as con:
                changed=con.execute("UPDATE jobs SET status='running',attempts=attempts+1,started_at=datetime('now') WHERE id=? AND status='queued'",(queued['job_id'],)).rowcount
            if not changed:raise SystemExit('Selected job is not queued; inspect before retrying')
            job=store.rows('SELECT * FROM jobs WHERE id=?',(queued['job_id'],))[0];job['payload']=json.loads(job['payload'])
            await execute_job(store,settings,job)
            r=detail(store,aid)
            result={'agency':r['name'],'id':aid,'qualification':r['qualification'],'jobs':r['jobs'],'usage':summary(store)}
            (settings.db_path.parent/(aid+'-qualification.json')).write_text(json.dumps(result,indent=2))
            print(json.dumps({'agency':r['name'],'outcome':(r['qualification'] or {}).get('decision',{}).get('outcome'),'review_passed':(r['qualification'] or {}).get('review_passed'),'usage':summary(store),'jobs':r['jobs']}),flush=True)
            if not r['qualification_current']:raise SystemExit('Qualification failed; stop and inspect')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);p.add_argument('agency_ids',nargs='+');a=p.parse_args()
    if len(a.agency_ids)>15:raise SystemExit('Maximum 15 agencies')
    asyncio.run(run(configuration(a.env_file,True),a.agency_ids))
