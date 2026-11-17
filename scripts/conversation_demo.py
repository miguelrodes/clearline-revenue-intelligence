"""Start or reset a separate, source-derived customer conversation rehearsal."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from uuid import uuid4

from screening_dev import configuration
from phase12_acceptance_worker import Ledger, bounded_clients
from clearline.config import ROOT
from clearline.demo import CONVERSATION_DIR, CONVERSATION_BUDGET, backup, exclusive, manifest, paths, use_guard
from clearline.screening_budget import BudgetLimit
from clearline.store import Store, utcnow
from clearline.worker import execute_job, worker_lock

FOLDER = CONVERSATION_DIR
SOURCE = ROOT/'runtime/phase3/screening.sqlite3'
BASELINE, SESSION, MARKER = paths(FOLDER)
PIDFILE = FOLDER/'conversation-server.json'
SENT = FOLDER/'approved-outbound.sqlite3'
LONE_TREE = 'c966fd651cca1e9020fa'


class ConversationBudget(Ledger):
    kinds = ('analyze','reply','revise_draft','review_sent')
    # Rounded up from the completed Lone Tree rehearsal ($0.259966 for the
    # assessment and up to $0.362818 per reply). Edits use the larger estimate.
    projection = {'analyze':260_000,'reply':363_000,'revise_draft':363_000,'review_sent':30_000}

    def record_credit_refusal(self, request_id, *, job_id=None):
        # Keep the original reservation amount as an audit record. A definitive
        # pre-generation refusal costs zero. A timeout or missing response cannot use this path.
        states = ('unknown',) if job_id is not None else ('reserved','unknown')
        with self.connect() as con:
            row=con.execute('SELECT job_id,state,charged_micro FROM requests WHERE id=?',(request_id,)).fetchone()
            if row is None or (job_id is not None and row['job_id']!=job_id):
                return False
            if row['state'] not in states or row['charged_micro'] is not None:
                return False
            con.execute("""UPDATE requests SET state='rejected_credit_balance',input_tokens=0,
                output_tokens=0,charged_micro=0 WHERE id=?""",(request_id,))
            con.execute("UPDATE preflights SET detail='generation_rejected_credit_balance_exhausted' WHERE id=?",(request_id,))
            return True

    def settle(self, request_id, body, status):
        if (status==429 and isinstance(body,dict) and set(body)=={'error'}
                and isinstance(body['error'],dict) and body['error'].get('code')=='credit_balance_exhausted'):
            self.record_credit_refusal(request_id)
            return
        super().settle(request_id,body,status)

    def admit_attempt(self, business, job):
        if not job['attempts']:
            self.admit(job)
            return
        # Older versions did not store the provider error code alongside its
        # reservation. Only reconcile a single unambiguous terminal response in
        # this same serial job attempt. Other unknown costs remain reserved.
        tail=business.execute("""SELECT kind,details FROM events WHERE job_id=? AND kind IN
            ('job_started','model_request_started','model_request_finished','model_output',
             'api_response','job_blocked_config','job_failed','job_completed')
            ORDER BY id DESC LIMIT 4""",(job['id'],)).fetchall()[::-1]
        if [r['kind'] for r in tail]==['model_request_started','model_request_finished','api_response','job_blocked_config']:
            start,finish,response,failure=[json.loads(r['details']) for r in tail]
            rid=start.get('request_id')
            if (rid and finish.get('request_id')==rid and finish.get('status')==response.get('status')==429
                    and response.get('usage_available') is False and response.get('requests')==1
                    and response.get('input_tokens')==response.get('output_tokens')==response.get('cached_tokens')==0
                    and failure.get('error')=='RateLimitError (status=429, code=credit_balance_exhausted)'):
                self.record_credit_refusal(rid,job_id=job['id'])
        self.admit(job)
        # admit() reuses the original job identity; an explicit new attempt
        # must still fit within the remaining cumulative allowance.
        with self.connect() as con:
            self.check_new_job(con,job)

    @staticmethod
    def _guard(con,job_id,model):
        limit,used=Ledger._guard(con,job_id,model)
        if con.execute("SELECT 1 FROM requests WHERE state IN ('reserved','unknown') LIMIT 1").fetchone():
            raise BudgetLimit('A prior model request has unsettled usage. Its reservation is retained and additional paid work is blocked.')
        return limit,used

    def check_new_job(self,con,job):
        limit,used=self._guard(con,job['id'],'gpt-6.1-sol')
        observed=con.execute("""SELECT MAX(total) FROM (
            SELECT SUM(r.charged_micro) total FROM requests r JOIN admitted_jobs j ON j.id=r.job_id
            WHERE j.kind=? GROUP BY j.id)""",(job['kind'],)).fetchone()[0] or 0
        estimate=max(observed,self.projection[job['kind']])
        if estimate>limit-used:
            raise BudgetLimit(f'Rehearsal budget cannot admit this {job["kind"]} job: projected ${estimate/1e6:.4f}, remaining ${(limit-used)/1e6:.4f}.')


def interactive_budget(*,create=False):
    data=manifest(FOLDER)
    ledger=ConversationBudget(CONVERSATION_BUDGET)
    if create and 'interactive_budget_id' not in data:
        if ledger.path.exists():raise ValueError('Unregistered spending ledger exists; refusing to replace it.')
        inherited=set()
        for snapshot in (BASELINE,SENT):
            with sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True) as con:
                if not con.execute("SELECT 1 FROM opportunities WHERE id=? AND workflow='recovery' AND active=1",(LONE_TREE,)).fetchone():
                    raise ValueError('Lone Tree is missing from a registered rehearsal checkpoint')
                inherited.update(r[0] for r in con.execute('SELECT id FROM jobs'))
        ledger.initialize(SESSION,[LONE_TREE],inherited,budget_usd=2)
        ledger.path.chmod(0o600)
        budget_id=uuid4().hex
        with ledger.connect() as con:
            con.execute("INSERT INTO metadata VALUES('interactive_budget_id',?)",(budget_id,))
        data['interactive_budget_id']=budget_id
        temp=MARKER.with_suffix('.new')
        temp.write_text(json.dumps(data,indent=2))
        temp.replace(MARKER)
    if not data.get('interactive_budget_id') or not ledger.path.is_file() or ledger.path.is_symlink():
        raise ValueError('The registered interactive spending ledger is unavailable. Paid execution is disabled.')
    meta=ledger.metadata()
    accounts=json.loads(meta['accounts'])
    if (meta.get('interactive_budget_id')!=data['interactive_budget_id'] or meta.get('db_path')!=str(SESSION)
            or meta.get('limit_micro')!='2000000' or not isinstance(accounts,list) or len(accounts) not in (1,2)
            or accounts[0]!=LONE_TREE or len(set(accounts))!=len(accounts)):
        raise ValueError('Interactive budget identity, session, account or ceiling does not match.')
    return ledger

def select_account(oid):
    """Select the optional rehearsal account without replacing the spending ledger."""
    ledger=interactive_budget()
    for path in (SESSION,BASELINE,SENT):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            if path==SESSION and db.execute("SELECT value FROM controls WHERE name='paused'").fetchone()!=('1',):
                raise ValueError('Pause the rehearsal before changing the account scope.')
            if not db.execute("SELECT 1 FROM opportunities WHERE id=? AND workflow='recovery' AND active=1",(oid,)).fetchone():
                raise ValueError('Select an active existing customer present in the rehearsal checkpoints.')
    with ledger.connect() as db:
        accounts=json.loads(db.execute("SELECT value FROM metadata WHERE key='accounts'").fetchone()[0])
        if oid not in accounts:
            if db.execute("SELECT 1 FROM requests WHERE charged_micro IS NULL").fetchone():
                raise ValueError('A model request has unsettled usage; keep the current account selection.')
            db.execute("UPDATE metadata SET value=? WHERE key='accounts'",(json.dumps([LONE_TREE,oid]),))


def checksum(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def initialize():
    if MARKER.exists():
        return manifest(FOLDER)
    FOLDER.mkdir(parents=True,exist_ok=True)
    if BASELINE.exists() or SESSION.exists():
        ledger=FOLDER/'acceptance-budget.sqlite3'
        if not (BASELINE.is_file() and SESSION.is_file() and ledger.is_file()
                and Ledger(ledger).metadata()['db_path']==str(SESSION)):
            raise ValueError('Existing unregistered files cannot be overwritten')
    else:
        backup(SOURCE,BASELINE)
        backup(BASELINE,SESSION)
    data=dict(kind='clearline-disposable-demo-v1',source=str(SOURCE),baseline=str(BASELINE),session=str(SESSION),
              baseline_sha256=checksum(BASELINE),captured_at=utcnow())
    MARKER.write_text(json.dumps(data,indent=2))
    return manifest(FOLDER)

def restore(sent=False):
    data=manifest(FOLDER)
    with exclusive(FOLDER):
        source=SENT if sent else BASELINE
        expected=data['approved_outbound_sha256'] if sent else data['baseline_sha256']
        if source.is_symlink() or checksum(source)!=expected:raise ValueError('Checkpoint changed')
        backup(source,SESSION)

def checkpoint(oid):
    data=manifest(FOLDER)
    with exclusive(FOLDER):
        if SENT.exists():raise ValueError('Approved checkpoint already exists')
        with sqlite3.connect(SESSION.as_uri()+'?mode=ro',uri=True) as con:
            con.row_factory=sqlite3.Row
            row=con.execute("""SELECT d.*,a.snapshot_hash FROM outbox b JOIN drafts d ON b.draft_id=d.id
                JOIN approvals a ON a.draft_id=d.id AND a.decision='approved' JOIN opportunities o ON o.id=b.opportunity_id
                WHERE b.opportunity_id=? AND o.status='awaiting_response' AND b.delivery_mode='simulated'
                ORDER BY b.created_at DESC LIMIT 1""",(oid,)).fetchone()
            if not row or Store.draft_hash(row)!=row['snapshot_hash']:
                raise ValueError('An exact human-approved simulated send is required')
        backup(SESSION,SENT)
        data['approved_outbound_sha256']=checksum(SENT)
        MARKER.write_text(json.dumps(data,indent=2))

def claim_interactive(store,ledger,inherited,*,reply_job_id=None,accounts_json=None,job_id=None):
    if accounts_json is None:
        accounts_json=ledger.metadata()['accounts']
    with store.connect(write=True) as con:
        # Rehearsal workers never automatically retry. An explicitly requeued
        # job keeps its lifetime attempt count; a failed or interrupted row stays blocked.
        rows=con.execute("""SELECT * FROM jobs WHERE opportunity_id IN (SELECT value FROM json_each(?)) AND status='queued' AND error IS NULL
            AND kind IN ('analyze','reply','revise_draft','review_sent','deliver') AND due_at<=?
            AND (? IS NULL OR (id=? AND kind='reply' AND opportunity_id=?))
            AND (? IS NULL OR (id=? AND kind IN ('analyze','reply','revise_draft','review_sent')))
            ORDER BY created_at,rowid""",(accounts_json,utcnow(),reply_job_id,reply_job_id,LONE_TREE,job_id,job_id))
        for row in rows:
            job=dict(row)
            if job['id'] in inherited:continue
            if job['kind']!='deliver':
                try:ledger.admit_attempt(con,job)
                except BudgetLimit as exc:
                    con.execute("UPDATE jobs SET status='blocked_config',error=?,finished_at=? WHERE id=?",(str(exc),utcnow(),job['id']))
                    continue
            now=utcnow()
            con.execute("UPDATE jobs SET status='running',attempts=attempts+1,started_at=?,finished_at=NULL,error=NULL WHERE id=?",(now,job['id']))
            return dict(job,payload=json.loads(job['payload']),attempts=job['attempts']+1,
                        status='running',started_at=now,finished_at=None,error=None)


async def run_claimed(store,settings,job):
    task=asyncio.create_task(execute_job(store,settings,job))
    while not task.done():
        await asyncio.wait({task},timeout=5)
        store.heartbeat('running')
    await task


async def run_one_job(settings, ledger, job_id):
    """Run one explicitly selected model job while the general rehearsal queue stays paused."""
    store=Store(SESSION)
    if settings.model!='gpt-6.1-sol':raise ValueError('The rehearsal requires the priced model.')
    settings=replace(settings,concurrency=1,max_concurrency=1,max_attempts=1)
    with exclusive(FOLDER),worker_lock(SESSION),bounded_clients(ledger):
        if not store.paused() or store.rows("SELECT 1 FROM controls WHERE name='api_blocked'") or store.rows("SELECT 1 FROM jobs WHERE status='running'"):
            raise ValueError('Stop the rehearsal with the queue paused, idle and API access unblocked.')
        with ledger.connect() as con:
            inherited={r[0] for r in con.execute('SELECT id FROM baseline_jobs')}
        job=claim_interactive(store,ledger,inherited,job_id=job_id)
        if not job:raise ValueError('Selected job is not eligible; check its account, queue status and spending guard.')
        await run_claimed(store,settings,job)
        return store.rows('SELECT id,status,attempts,error FROM jobs WHERE id=?',(job_id,))[0]


async def conversation_worker(settings,ledger,*,reply_job_id=None):
    store=Store(SESSION)
    if settings.model!='gpt-6.1-sol':raise ValueError('This rehearsal requires the priced gpt-6.1-sol standard tier.')
    settings=replace(settings,concurrency=1,max_concurrency=1,max_attempts=1)
    with use_guard(SESSION),worker_lock(SESSION),bounded_clients(ledger):
        accounts_json=ledger.metadata()['accounts']
        with ledger.connect() as con:
            inherited={row[0] for row in con.execute('SELECT id FROM baseline_jobs')}
        # A lost worker cannot prove whether its in-flight request was billed.
        # Leave that reservation intact and never redispatch an interrupted job.
        for row in store.rows("SELECT id FROM jobs WHERE opportunity_id IN (SELECT value FROM json_each(?)) AND status='running' AND (? IS NULL OR (id=? AND kind='reply' AND opportunity_id=?))",(accounts_json,reply_job_id,reply_job_id,LONE_TREE)):
            if row['id'] not in inherited:
                store.finish(row['id'],'blocked_config','Rehearsal worker interrupted. Check the budget before retrying.')
        if reply_job_id:
            if not store.paused() or store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):
                raise ValueError('The single-reply run requires a paused rehearsal and a cleared API block.')
            try:
                job=claim_interactive(store,ledger,inherited,reply_job_id=reply_job_id)
                if job:await run_claimed(store,settings,job)
            finally:
                store.set_paused(True)
        while True:
            store.heartbeat('running')
            if not store.paused() and not store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):
                job=claim_interactive(store,ledger,inherited,accounts_json=accounts_json)
                if job:
                    await run_claimed(store,settings,job)
                    continue
            await asyncio.sleep(1)

def identity(pid):
    return subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart=','-o','command='],capture_output=True,text=True).stdout.strip()

def stop():
    if not PIDFILE.exists():return
    info=json.loads(PIDFILE.read_text())
    if identity(info['pid']) != info['identity']:raise ValueError('Rehearsal process identity changed; refusing to stop it')
    os.kill(info['pid'],signal.SIGTERM)
    for _ in range(200):
        if not PIDFILE.exists():return
        time.sleep(.1)
    raise ValueError('Rehearsal is still stopping')

def serve(args):
    interactive_budget()
    if PIDFILE.exists():raise ValueError('The rehearsal is already running')
    env={**os.environ,'CLEARLINE_API_ORIGIN':'http://127.0.0.1:8003','CLEARLINE_NEXT_DIST_DIR':'.next-conversation'}
    frontend=ROOT/'frontend'
    if not (frontend/'.next-conversation/BUILD_ID').exists():raise ValueError('Build the rehearsal frontend first; see docs/customer-conversation-demo.md')
    commands=[
        ([sys.executable,'scripts/screening_dev.py','api','--enable-screening','--db-path',str(SESSION),'--port','8003'],ROOT),
        (['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3002'],frontend),
        ([sys.executable,__file__,'worker']+(['--reply-job-id',args.reply_job_id] if args.reply_job_id else []),ROOT),
    ]
    children=[]
    try:
        signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
        with use_guard(SESSION):
            PIDFILE.write_text(json.dumps({'pid':os.getpid(),'identity':identity(os.getpid())}))
            for cmd,cwd in commands:
                if args.env_file and cmd[0]==sys.executable:cmd.extend(['--env-file',str(args.env_file)])
                children.append(subprocess.Popen(cmd,cwd=cwd,env=env))
            print('Customer conversation rehearsal: http://127.0.0.1:3002',flush=True)
            while all(child.poll() is None for child in children):time.sleep(.5)
            raise RuntimeError('A rehearsal service stopped; check the local service log')
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:child.wait()
        PIDFILE.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','serve','stop','reset','checkpoint','worker','budget-init','budget-status','select-account','run-job'])
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--acceptance',action='store_true',help=argparse.SUPPRESS)  # Older launch commands remain guarded.
    parser.add_argument('--sent',action='store_true',help='Restore the separately saved human-approved outbound')
    parser.add_argument('--start',action='store_true',help='Start the rehearsal immediately after a reset')
    parser.add_argument('--account-id')
    parser.add_argument('--job-id',help='Exact queued model job for a paused run-job.')
    parser.add_argument('--reply-job-id',help='On serve or worker, process only this queued Lone Tree reply once with the general queue paused.')
    args=parser.parse_args()
    if bool(args.job_id)!=(args.command=='run-job'):
        parser.error('--job-id is required and only valid for run-job')
    if args.reply_job_id and args.command not in ('serve','worker'):
        parser.error('--reply-job-id is only valid on serve or worker')
    if args.command=='init':initialize()
    elif args.command=='budget-init':
        with exclusive(FOLDER):print(json.dumps(interactive_budget(create=True).summary(),indent=2))
    elif args.command=='select-account':
        if not args.account_id:parser.error('select-account requires --account-id')
        with exclusive(FOLDER):select_account(args.account_id)
    elif args.command=='budget-status':print(json.dumps(interactive_budget().summary(),indent=2))
    elif args.command=='run-job':
        settings=configuration(args.env_file,True,SESSION)
        print(json.dumps(asyncio.run(run_one_job(settings,interactive_budget(),args.job_id))))
    elif args.command=='stop':stop()
    elif args.command=='reset':
        stop();restore(args.sent)
        if args.start:serve(args)
    elif args.command=='checkpoint':stop();checkpoint(args.account_id)
    elif args.command=='serve':serve(args)
    else:
        settings=configuration(args.env_file,True,SESSION)
        asyncio.run(conversation_worker(settings,interactive_budget(),reply_job_id=args.reply_job_id))

if __name__=='__main__':main()
