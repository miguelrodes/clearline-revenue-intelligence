"""Evaluate a preserved portfolio copy, never sends, never writes the live database.

Run after regression and commercial-evaluation gates. Resume using the same database;
current evidence is cached. Costs are estimates from provider usage, not the invoice.
"""
import argparse,asyncio,json,sqlite3,time
from pathlib import Path
from dataclasses import replace
from dotenv import load_dotenv
from clearline.config import Settings,ROOT
from clearline.store import Store,utcnow
from clearline.data import scan,ScanPolicy
from clearline.worker import execute_job,Capacity
from clearline.evidence import ENGINE_VERSION,current_assessment
from clearline.operations import latest_assessment

NAMES=['Range Line Distributors','Kimball County Adult Probation','TX State Correctional Facility - Boulder Ridge','Granite Falls Police Department',"Hawk County Sheriff's Office",'ID DOC - Lone Tree','KS State Correctional Facility - Juniper Hills','Iron County Jail','Red Rock County Adult Probation']
async def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--all',action='store_true');p.add_argument('--db',type=Path,required=True);p.add_argument('--baseline',type=Path);p.add_argument('--env-file',type=Path);p.add_argument('--concurrency',type=int,default=6);p.add_argument('--budget',type=float,default=15);args=p.parse_args()
    if args.env_file:load_dotenv(args.env_file)
    if args.db.resolve()==Settings.load().db_path.resolve():raise ValueError('Evaluation cannot target configured live database')
    if not args.db.exists():
        if not args.baseline or not args.baseline.exists():raise ValueError('An original baseline is required')
        args.db.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(f'file:{args.baseline.resolve()}?mode=ro',uri=True) as source,sqlite3.connect(args.db) as dest:source.backup(dest)
    settings=replace(Settings.load(),db_path=args.db,concurrency=args.concurrency,max_concurrency=args.concurrency,investigation_timeout_seconds=600)
    store=Store(args.db);summary,items=scan(settings.data_dir,ScanPolicy(as_of=settings.as_of),True);store.save_scan(summary,items)
    items=[i for i in items if i['name'] in NAMES and i['state']!='UNRESOLVED'] if not args.all else items
    baseline_event=0
    if args.baseline:
        with sqlite3.connect(f'file:{args.baseline.resolve()}?mode=ro',uri=True) as original:
            baseline_event=original.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
    start=store.rows('SELECT COALESCE(MAX(id),0) n FROM events')[0]['n']
    capacity=Capacity(settings);pending={};active=set()
    for item in items:
        with store.connect() as c:current=current_assessment(c,item['id'],latest_assessment(store,item['id']))
        if not current:pending[store.queue_analysis(item['id'],investigation=True)]=item
    async def run(job,item):
        await execute_job(store,settings,job,capacity=capacity)
        last=store.rows('SELECT status,error FROM jobs WHERE id=?',(job['id'],))[0]
        a=latest_assessment(store,item['id']) or {}
        print(json.dumps({'id':item['id'],'name':item['name'],'state':item['state'],**last,'outcome':(a.get('commercial_plan') or {}).get('outcome'),'review_failed':a.get('review_failed'),'action':a.get('recommended_action')}),flush=True)
        return job['id']
    stopped=False
    while pending or active:
        used=store.rows("SELECT COALESCE(SUM(json_extract(details,'$.cost_usd')),0) n FROM events WHERE id>? AND kind='api_response'",(baseline_event,))[0]['n']
        stopped=stopped or used>=args.budget or bool(store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"))
        if not stopped and time.monotonic()>=capacity.cooldown:
            for jid,item in list(pending.items()):
                if len(active)>=capacity.current:break
                with store.connect(write=True) as c:
                    row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
                    if row['status'] in ('completed','failed','blocked_config','cancelled'):
                        pending.pop(jid);continue
                    if row['status']!='queued' or row['due_at']>utcnow():continue
                    changed=c.execute("UPDATE jobs SET status='running',started_at=?,attempts=attempts+1 WHERE id=? AND status='queued' AND attempts<?",(utcnow(),jid,settings.max_attempts)).rowcount
                    if not changed:pending.pop(jid);continue
                    job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone());job['payload']=json.loads(job['payload'])
                pending.pop(jid);active.add(asyncio.create_task(run(job,item)))
        capacity.peak=max(capacity.peak,len(active));capacity.save(store)
        if active:
            done,active=await asyncio.wait(active,timeout=1,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                jid=task.result();row=store.rows('SELECT status,opportunity_id FROM jobs WHERE id=?',(jid,))[0]
                if row['status']=='queued':pending[jid]=next(i for i in items if i['id']==row['opportunity_id'])
        elif stopped:break
        elif pending:await asyncio.sleep(1)
    if stopped:print(json.dumps({'stop':'Budget or API stop; incomplete coverage remains explicit','cost_since_baseline':used}),flush=True)
    results=[]
    for item in items:
        a=latest_assessment(store,item['id']) or {}
        with store.connect() as c:current=current_assessment(c,item['id'],a)
        results.append({'id':item['id'],'name':item['name'],'state':item['state'],'current':current,'review_failed':a.get('review_failed'),'outcome':(a.get('commercial_plan') or {}).get('outcome')})
    usage=store.rows("SELECT count(*) responses,SUM(json_extract(details,'$.cost_usd')) cost,SUM(json_extract(details,'$.input_tokens')) input_tokens,SUM(json_extract(details,'$.output_tokens')) output_tokens FROM events WHERE id>? AND kind='api_response'",(start,))
    report={'engine':ENGINE_VERSION,'accounts':results,'signals':store.rows('SELECT category,investigation_status,disposition,count(*) n FROM commercial_signals WHERE active=1 GROUP BY category,investigation_status,disposition'),'usage_this_run':usage}
    args.db.with_suffix('.report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'current':sum(r['current'] for r in results),'selected':len(items),'usage':usage}),flush=True)
if __name__=='__main__':asyncio.run(main())
