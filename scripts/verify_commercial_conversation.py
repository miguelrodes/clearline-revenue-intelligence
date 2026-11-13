"""Real model + explicitly synthetic test approvals, simulator-only, disposable demo reset.
Never run against actual portfolio DBs or any existing customer identity.
"""
import argparse,asyncio,json
from pathlib import Path
from dataclasses import replace
from dotenv import load_dotenv
from clearline.config import Settings
from clearline.demo import initialize,paths,reset
from clearline.store import Store
from clearline.services import ApplicationService
from clearline.transport import SimulatedProvider
from clearline.worker import execute_job

async def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--folder',type=Path,required=True);p.add_argument('--env-file',type=Path);args=p.parse_args()
    if args.env_file:load_dotenv(args.env_file)
    source=Store(args.source);row=source.rows("SELECT * FROM opportunities WHERE name='Evaluation 01 County Jail'")
    if len(row)!=1 or 'evaluation_notice' not in json.loads(row[0]['evidence']):raise ValueError('Only the explicitly synthetic evaluation fixture is allowed')
    if (args.folder/'manifest.json').exists():reset(args.folder)
    else:initialize(args.source,args.folder)
    _,db,_=paths(args.folder);store=Store(db)
    settings=replace(Settings.load(),db_path=db,data_dir=args.source.parent/'sources',investigation_timeout_seconds=600)
    svc=ApplicationService(settings);oid=row[0]['id']
    counts=lambda:{t:store.rows('SELECT count(*) n FROM '+t)[0]['n'] for t in ('drafts','approvals','outbox','messages','investigation_tasks','commercial_signals')}
    before=counts();d=store.rows("SELECT * FROM drafts WHERE opportunity_id=? AND status='awaiting_approval' ORDER BY version DESC",(oid,))[0]
    # Explicit automated-test human-input fixture; these are not live customer approvals.
    review=svc.review_outreach([d['id']]);svc.decide_review(review['review_id'],True,review['required_confirmation'])
    j=store.claim(['deliver']);store.deliver(j);store.deliver(j);store.finish(j['id'])
    assert store.rows('SELECT count(*) n FROM outbox')[0]['n']==before['outbox']+1
    parent=store.rows("SELECT * FROM messages WHERE opportunity_id=? AND direction='outbound' ORDER BY created_at DESC",(oid,))[0]
    incoming=SimulatedProvider(store).ingest(oid,parent['id'],'synthetic-current-training-request','Thanks for following up. We now need training for the night shift on the fentanyl surface swabs. Could you help us arrange a suitable session?')
    job=store.claim(['reply']);assert job['id']==incoming['job_id']
    await execute_job(store,settings,job)
    state=store.rows('SELECT status,error FROM jobs WHERE id=?',(job['id'],))[0]
    if state['status']!='completed':raise ValueError('Real reply failed: '+json.dumps(state))
    new=store.rows("SELECT * FROM drafts WHERE opportunity_id=? AND status='awaiting_approval' ORDER BY version DESC",(oid,))
    if not new:raise ValueError('The current explicit training request failed to produce a supervised response; inspect persisted decision')
    assert new[0]['version']>d['version'] and len(store.rows('SELECT * FROM approvals'))==before['approvals']+1
    assert store.rows("SELECT count(*) n FROM jobs WHERE kind='followup' AND opportunity_id=? AND status='queued'",(oid,))[0]['n']==0
    review=svc.review_outreach([new[0]['id']]);svc.decide_review(review['review_id'],True,review['required_confirmation'])
    j=store.claim(['deliver']);store.deliver(j);store.deliver(j);store.finish(j['id'])
    assert store.rows('SELECT count(*) n FROM outbox')[0]['n']==before['outbox']+2
    assert store.rows('PRAGMA integrity_check')[0]['integrity_check']=='ok'
    usage=store.rows("SELECT count(*) calls,SUM(json_extract(details,'$.cost_usd')) cost FROM events WHERE kind='api_response' AND job_id=?",(job['id'],))
    a=json.loads(new[0]['analysis']);report={'synthetic_only':True,'reply_outcome':a['commercial_plan']['outcome'],'subject':new[0]['subject'],'body':new[0]['body'],'exact_version_approval':True,'duplicate_delivery_prevented':True,'followup_cancelled':True,'usage':usage}
    reset(args.folder);assert counts()==before;report['reset_restores_baseline']=True
    (args.folder/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
