"""Isolated Phase 3 entry point. No stable demo writes or recovery jobs."""
import argparse,asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dataclasses import replace
from dotenv import load_dotenv
from clearline.config import Settings,ROOT
from clearline.store import Store
from clearline.screening import screen

def configuration(env_file,enabled):
    if env_file:load_dotenv(env_file,override=False)
    settings=Settings.load()
    return replace(settings,db_path=ROOT/'runtime/phase3/screening.sqlite3',screening_budget_path=ROOT/'runtime/phase3/screening.sqlite3',screening_enabled=enabled,concurrency=3,max_concurrency=6)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['screen','api','worker']);p.add_argument('--env-file',type=Path);p.add_argument('--enable-screening',action='store_true');p.add_argument('--port',type=int,default=8001);args=p.parse_args()
    settings=configuration(args.env_file,args.enable_screening)
    if not settings.screening_enabled and args.command!='api':raise SystemExit('Review feature disabled. Pass --enable-screening explicitly in this isolated worktree.')
    store=Store(settings.db_path)
    if args.command=='screen':print(screen(store,settings))
    elif args.command=='api':
        import uvicorn
        from clearline.api import create_app
        uvicorn.run(create_app(settings),host='127.0.0.1',port=args.port)
    else:
        from clearline.worker import run_pool,worker_lock
        with worker_lock(settings.db_path):
            with store.connect(write=True) as con:
                con.execute("UPDATE jobs SET status='queued',error='Recovered isolated agency worker' WHERE status='running' AND kind IN ('agency_scan','agency_qualify','agency_outreach','agency_deliver')")
            asyncio.run(run_pool(store,settings,auto_brief=False,kinds=['agency_scan','agency_qualify','agency_outreach','agency_deliver']))
if __name__=='__main__':main()
