"""Resume the isolated overhaul portfolio after API billing is confirmed.

Never reads credentials into output, sends messages, promotes results, or replaces a baseline.
Run with the project virtual environment. The existing audit snapshot must be present.
"""
import argparse
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

from clearline.config import ROOT, Settings
from clearline.data import ScanPolicy, scan
from clearline.evidence import ENGINE_VERSION, context_hash, current_assessment
from clearline.operations import latest_assessment, start_batch
from clearline.store import Store, utcnow
from clearline.worker import run_pool, worker_lock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-api-ready',action='store_true',help='Explicitly resume billable isolated evaluation after fixing billing.')
    parser.add_argument('--cost-ceiling-usd',type=float,default=90,help='Recorded portfolio-only cost threshold; in-flight jobs finish safely.')
    args=parser.parse_args()
    if not args.confirm_api_ready:parser.error('Confirm API billing before resuming with --confirm-api-ready')
    if not 0<args.cost_ceiling_usd<=100:parser.error('Use a positive bounded evaluation ceiling of at most $100')
    target=ROOT/'runtime/overhaul/portfolio.sqlite3'
    if not target.is_file():raise SystemExit('Existing isolated portfolio snapshot is required')
    store=Store(target);settings=replace(Settings.load(),db_path=target)
    started=time.monotonic();batch=None
    with worker_lock(target):
        store.recover_interrupted()
        old=json.loads(store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')[0]['summary'])
        summary,items=scan(settings.data_dir,ScanPolicy(as_of=settings.as_of),True)
        for key in ('prior_cents','current_cents','prior_tests','current_tests','net_cents_whole_export','rows','duplicate_excess_retained','hashes'):
            if old[key]!=summary[key]:raise ValueError('Evaluation source snapshot changed: '+key)
        store.save_scan(summary,items)
        with store.connect(write=True) as con:
            con.execute('UPDATE schedules SET enabled=0')
            # Only unfinished obsolete investigations are cancelled. Completed history is retained.
            for job in con.execute("SELECT * FROM jobs WHERE kind='analyze' AND status IN ('queued','blocked_config')").fetchall():
                payload=json.loads(job['payload'])
                if payload.get('engine_version')!=ENGINE_VERSION or payload.get('context_hash')!=context_hash(con,job['opportunity_id']):
                    con.execute("UPDATE jobs SET status='cancelled',error='Superseded investigation engine or evidence',finished_at=? WHERE id=?",(utcnow(),job['id']))
            con.execute("DELETE FROM controls WHERE name='api_blocked'")
            con.execute("UPDATE jobs SET status='queued',due_at=?,error=NULL WHERE kind='analyze' AND status='blocked_config'",(utcnow(),))
        store.set_paused(False)
        batch=start_batch(store)
        # Count only this experiment's investigations, excluding copied historical usage.
        def usage():
            values=[json.loads(row['details']) for row in store.rows("SELECT e.details FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.kind='api_response' AND json_extract(j.payload,'$.engine_version') IS NOT NULL")]
            return {'responses':len(values),'input_tokens':sum(x.get('input_tokens',0) for x in values),
                    'output_tokens':sum(x.get('output_tokens',0) for x in values),'estimated_cost_usd':sum(x.get('cost_usd') or 0 for x in values),
                    'unpriced_responses':sum(x.get('cost_usd') is None for x in values)}
        def counts():
            return store.rows('SELECT COALESCE(j.status,a.disposition) status,COUNT(*) n FROM batch_accounts a LEFT JOIN jobs j ON j.id=a.job_id WHERE a.batch_id=? GROUP BY 1',(batch,))
        async def monitor(task):
            while not task.done():
                data=usage()
                print(json.dumps({'elapsed_seconds':round(time.monotonic()-started),'batch':batch,'counts':counts(),'usage':data}),flush=True)
                if data['estimated_cost_usd']>=args.cost_ceiling_usd:
                    store.set_paused(True)
                await asyncio.sleep(30)
        async def run():
            while not store.paused() and not store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):
                if usage()['estimated_cost_usd']>=args.cost_ceiling_usd:
                    store.set_paused(True);break
                task=asyncio.create_task(run_pool(store,settings,drain=True,auto_brief=False))
                watch=asyncio.create_task(monitor(task))
                try:await task
                finally:
                    watch.cancel();await asyncio.gather(watch,return_exceptions=True)
                if not store.rows("SELECT 1 FROM jobs WHERE kind='analyze' AND status='queued'"):break
                await asyncio.sleep(2)
        asyncio.run(run())
        current=0
        for item in items:
            with store.connect() as con:
                current+=bool(current_assessment(con,item['id'],latest_assessment(store,item['id'])))
        result={'engine':ENGINE_VERSION,'batch_id':batch,'accounts':len(items),'current_assessments':current,'counts':counts(),
                'usage':usage(),'elapsed_seconds':round(time.monotonic()-started),'api_blocked':bool(store.rows("SELECT 1 FROM controls WHERE name='api_blocked'")),
                'paused':store.paused(),'complete':current==len(items)}
        (target.parent/'portfolio_results.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
        if not result['complete']:raise SystemExit(2)

if __name__=='__main__':main()
