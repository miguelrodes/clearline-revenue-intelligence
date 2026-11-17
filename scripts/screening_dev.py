"""Combined isolated preview; explicit jobs only, with portfolio automation off."""
import argparse,asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dataclasses import replace
from dotenv import load_dotenv
from clearline.config import Settings,ROOT
from clearline.store import Store
from clearline.screening import screen

PREVIEW_JOB_KINDS = (
    'analyze', 'prepare', 'reply', 'revise_draft', 'review_sent', 'followup', 'deliver',
    'revenue_brief', 'pipeline_discover', 'pipeline_research', 'pipeline_qualify',
    'agency_scan', 'agency_qualify', 'agency_outreach', 'agency_deliver',
)


def configuration(env_file,enabled,db_path=None):
    if env_file:load_dotenv(env_file,override=False)
    settings=Settings.load()
    selected=Path(db_path) if db_path is not None else Path('runtime/phase3/screening.sqlite3')
    selected=(selected if selected.is_absolute() else ROOT/selected).resolve()
    if not selected.is_relative_to((ROOT/'runtime').resolve()):
        raise ValueError('The isolated preview database must be inside this checkout\'s runtime directory')
    return replace(settings,db_path=selected,screening_budget_path=selected,screening_enabled=enabled,concurrency=3,max_concurrency=6)


def run_preview_worker(store,settings,*,drain=False):
    from clearline.worker import run_pool,worker_lock
    with worker_lock(settings.db_path):
        # Resume only already-requested work owned by this preview. Never create
        # scan jobs, invalidate evidence, or enqueue missing portfolio reviews.
        with store.connect(write=True) as con:
            only_delivery=con.execute("SELECT 1 FROM controls WHERE name='delivery_only' AND value='1'").fetchone()
            kinds=('deliver','agency_deliver') if only_delivery else PREVIEW_JOB_KINDS
            placeholders=','.join('?' for _ in kinds)
            con.execute(f"UPDATE jobs SET status='queued',error='Recovered isolated preview worker' WHERE status='running' AND kind IN ({placeholders})",kinds)
        # Both controls matter: auto_brief=False disables source refresh,
        # portfolio catch-up and automatic briefs; an allowlist disables tick().
        asyncio.run(run_pool(store,settings,drain=drain,auto_brief=False,kinds=PREVIEW_JOB_KINDS,preview_delivery=True))

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['screen','api','worker','delivery-on','delivery-off']);p.add_argument('--env-file',type=Path);p.add_argument('--enable-screening',action='store_true');p.add_argument('--port',type=int,default=8002);p.add_argument('--db-path',type=Path,help='Database inside this checkout\'s runtime directory; use the same path for API and worker');args=p.parse_args()
    settings=configuration(args.env_file,args.enable_screening,args.db_path)
    if not settings.screening_enabled and args.command!='api':raise SystemExit('Review feature disabled. Pass --enable-screening explicitly in this isolated worktree.')
    store=Store(settings.db_path)
    if args.command in ('delivery-on','delivery-off'):
        enabled=args.command=='delivery-on'
        store.set_delivery_only(enabled)
        print('Approved simulated delivery enabled for the preview worker.' if enabled else 'Automatic simulated delivery disabled.')
    elif args.command=='screen':print(screen(store,settings))
    elif args.command=='api':
        import uvicorn
        from clearline.api import create_app
        uvicorn.run(create_app(settings),host='127.0.0.1',port=args.port)
    else:run_preview_worker(store,settings)
if __name__=='__main__':main()
