"""Real AI acceptance in a disposable copy; share the $5 ledger, never self-approve."""
import argparse,asyncio,json,sqlite3,sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from screening_dev import configuration
from clearline.store import Store
from clearline.screening import detail,queue
from clearline.screening_workflow import record_decision,record_information,queue_outreach,prerequisites
from clearline.screening_budget import summary
from clearline.worker import execute_job,worker_lock

async def run(base,aid):
    destination=base.db_path.parent/'outreach-validation.sqlite3'
    if destination.exists():raise SystemExit('Validation copy already exists; inspect before running again')
    source=sqlite3.connect(base.db_path);target=sqlite3.connect(destination);source.backup(target);source.close();target.close()
    settings=replace(base,db_path=destination);store=Store(destination);baseline=Store(base.db_path)
    before=detail(baseline,aid)
    record_decision(store,aid,'accepted','SYNTHETIC acceptance test: pursue a verified mailroom application')
    r=detail(store,aid)
    record_information(store,aid,{'recipient':'buyer@example.invalid','synthetic':True},r['context_hash'])
    assert prerequisites(detail(store,aid))
    assert not store.rows("SELECT 1 FROM jobs WHERE kind='agency_outreach'")
    info=dict(facts='SYNTHETIC TEST EVIDENCE: the institution screens incoming physical mail and wants to discuss whether CL-MAIL50 fits a manual screening step. This is an initial application discussion, not a request for a quote. No budget or buying deadline is known.',evidence='SYNTHETIC acceptance fixture dated 2026-11-01: purchasing team confirmed mailroom application, contact role, direct route and permission for an introductory application discussion. Internal relationship check found no known Clearline account or distributor arrangement; this is test evidence only.',recipient='buyer@example.invalid',role='Purchasing lead for the mailroom',route='direct',contact_verified=True,authorized=True,relationship_checked=True,synthetic=True)
    r=detail(store,aid);record_information(store,aid,info,r['context_hash'])
    async def execute(jid):
        with store.connect(write=True) as con:
            assert con.execute("UPDATE jobs SET status='running',attempts=attempts+1 WHERE id=? AND status='queued'",(jid,)).rowcount
        job=store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0];job['payload']=json.loads(job['payload'])
        await execute_job(store,settings,job)
        status=store.rows('SELECT status,error FROM jobs WHERE id=?',(jid,))[0]
        if status['status']!='completed':raise RuntimeError(status)
    with worker_lock(destination):
        r=detail(store,aid);job=queue(store,settings,aid,r['evidence_hash']);await execute(job['job_id'])
        r=detail(store,aid)
        if prerequisites(r):raise RuntimeError(prerequisites(r))
        job=queue_outreach(store,settings,aid,r['context_hash']);await execute(job['job_id'])
    r=detail(store,aid)
    assert r['drafts'][0]['status']=='awaiting_approval'
    assert not store.rows('SELECT * FROM approvals WHERE draft_id=?',(r['drafts'][0]['id'],))
    assert not store.rows('SELECT * FROM outbox WHERE opportunity_id=?',('agency:'+aid,))
    assert detail(baseline,aid)['workflow']==before['workflow'] and detail(baseline,aid)['qualification']==before['qualification']
    report=dict(agency=r['name'],id=aid,synthetic=True,partial_blocked=True,targeted_qualification=r['qualification'],draft=r['drafts'][0],human_approval='NOT granted. Awaiting human review. Automated synthetic fixtures test the approval/send path separately.',main_preview_agency_unchanged=True,usage=summary(baseline),db=str(destination))
    (destination.parent/'outreach-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('targeted_qualification',)}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);p.add_argument('agency_id');a=p.parse_args()
    asyncio.run(run(configuration(a.env_file,True),a.agency_id))
