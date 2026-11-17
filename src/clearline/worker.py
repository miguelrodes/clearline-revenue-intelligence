"""One process, concurrent async agents, short serialized SQLite transactions."""
import asyncio
from contextlib import contextmanager
import fcntl
import json
import random
import signal
import time
from .agent import MissingCredentials, analyze
from .data import ScanPolicy, scan
from .store import Store, STOPPED_STATUSES, utcnow, later
from .prospect_agent import research_prospect, qualify_prospect
from .telemetry import reset_seconds
from .screening_budget import BudgetLimit

@contextmanager
def worker_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.worker.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError('A worker already owns this database') from exc
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)

class Capacity:
    def __init__(self,settings):
        self.current=settings.concurrency; self.maximum=settings.max_concurrency
        self.cooldown=0.; self.successes=0; self.headers={}; self.recent=[]; self.previous_rate=0.; self.completions=[]; self.peak=0; self.transient_failures=[]
    def limited(self,delay):
        self.current=max(1,self.current//2); self.successes=0; self.cooldown=max(self.cooldown,time.monotonic()+delay)
    def transient_failure(self,delay):
        # An isolated gateway failure is not evidence of a rate limit. Slow the
        # whole pool only for a burst; each failed job still receives backoff.
        now=time.monotonic()
        self.transient_failures=[t for t in self.transient_failures if now-t<=60]+[now]
        if len(self.transient_failures)>=3:
            self.limited(delay);self.transient_failures=[]
    def completed(self,seconds):
        self.successes+=1; self.recent.append(seconds); self.recent=self.recent[-12:]
        self.completions.append(time.monotonic()); self.completions=self.completions[-24:]
        rate=(len(self.completions)-1)*60/max(.001,self.completions[-1]-self.completions[0])
        requests=int(self.headers.get('x-ratelimit-remaining-requests','0'))
        tokens=min(int(self.headers.get('x-ratelimit-remaining-tokens','0')),int(self.headers.get('x-ratelimit-remaining-project-tokens',self.headers.get('x-ratelimit-remaining-tokens','0'))))
        if self.successes>=max(12,2*self.current) and requests>4*(self.current+1) and tokens>12000*(self.current+1) and rate>=self.previous_rate:
            self.previous_rate=rate; self.current=min(self.maximum,self.current+1); self.successes=0
    def save(self,store):
        row={'active_limit':self.current,'configured_max':self.maximum,'cooldown_seconds':max(0,round(self.cooldown-time.monotonic())), 'provider_limits':self.headers,'peak_investigations':self.peak}
        with store.connect(write=True) as con: con.execute("INSERT INTO controls VALUES('capacity',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(json.dumps(row),))

async def execute_job(store,settings,job,analyst=analyze,capacity=None):
    from .operations import start_batch, latest_assessment
    start=time.monotonic(); started_at=utcnow(); status='failed'; concurrency=capacity.current if capacity else 1
    store.event('job_started',{'kind':job['kind'],'concurrency':concurrency},job['id'],job['opportunity_id'])
    try:
        if job['kind'] in ('pipeline_discover','pipeline_research','pipeline_qualify'):
            from .prospect_discovery import execute
            await execute(store,job,settings)
        elif job['kind']=='agency_qualify':
            from .screening_agent import qualify
            from .screening import save_result
            save_result(store,job,await qualify(store,job,settings))
        elif job['kind']=='agency_outreach':
            from .screening_agent import prepare_outreach
            from .screening_workflow import save_outreach
            save_outreach(store,job,await prepare_outreach(store,job,settings))
        elif job['kind']=='agency_deliver':
            store.deliver(job,settings.followup_days)
        elif job['kind']=='agency_scan':
            from .screening import screen
            if not settings.screening_enabled:raise ValueError('Prospect Screening is not enabled')
            await asyncio.to_thread(screen,store,settings)
        elif job['kind']=='scan':
            policy=ScanPolicy(**{'as_of':settings.as_of,**job['payload'].get('policy',{})})
            summary,items=await asyncio.to_thread(scan,settings.data_dir,policy,True)
            store.save_scan(summary,items)
            limit=int(job['payload'].get('analysis_limit',-1))
            if limit: start_batch(store,None if limit<0 else [i['id'] for i in items[:limit]])
        elif job['kind'] in ('analyze','prepare','prospect_qualify','prospect_research'):
            opp=store.opportunity(job['opportunity_id']); portfolio=job['payload'].get('portfolio')
            if not opp['active'] or opp['evidence_hash']!=job['payload']['evidence_hash'] or (opp['status'] in STOPPED_STATUSES and not portfolio):
                status='cancelled'; store.finish(job['id'],status,'Opportunity changed or requires review'); return
            if job['kind']=='prospect_research': store.save_prospect_research(job,await research_prospect(store,job,settings))
            else:
                cached=latest_assessment(store,opp['id']) if job['kind']=='prepare' else None
                from .evidence import current_assessment
                with store.connect() as con: reusable=current_assessment(con,opp['id'],cached)
                if reusable: result=cached
                else: result=await (qualify_prospect if job['kind']=='prospect_qualify' else analyst)(store,job,settings)
                store.save_analysis(job,result)
        elif job['kind']=='reply':
            from .reply_agent import draft_reply
            opp=store.opportunity(job['opportunity_id'])
            inbound=store.rows('SELECT id FROM messages WHERE outcome_id=? AND opportunity_id=?',(job['payload']['outcome_id'],opp['id']))
            if not opp['active'] or not inbound:
                status='cancelled';store.finish(job['id'],status,'Inbound message or account unavailable');return
            store.save_analysis(job,await draft_reply(store,job,settings))
        elif job['kind']=='deliver': store.deliver(job,settings.followup_days)
        elif job['kind']=='followup':
            if not store.enqueue_due_followup(job):
                status='cancelled'; store.finish(job['id'],status,'Follow-up no longer appropriate'); return
        elif job['kind']=='review_sent':
            from .sent_review import review_sent
            await review_sent(store,job,settings)
        elif job['kind']=='revise_draft':
            from .draft_revision import run_revision
            await run_revision(store,job,settings)
        elif job['kind']=='revenue_brief':
            from .brief import generate
            await generate(store,job,settings)
        else: raise ValueError('Unknown job kind')
        store.finish(job['id']); status=store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']
        if capacity and status=='completed' and job['kind'] in ('analyze','prospect_research','prospect_qualify','agency_qualify'):
            capacity.completed(time.monotonic()-start)
        store.event('job_'+status,{'kind':job['kind']},job['id'],job['opportunity_id'])
    except BudgetLimit as exc:
        status='blocked_config';store.finish(job['id'],status,str(exc))
        store.event('agency_budget_blocked',{'reason':str(exc)},job['id'],job.get('opportunity_id'))
    except MissingCredentials as exc:
        status='blocked_config';store.finish(job['id'],status,str(exc))
    except asyncio.CancelledError:
        status='interrupted'
        # Persisted running jobs are reclaimed by the next lock owner.
        raise
    except Exception as exc:
        # The OpenAI client may wrap a pre-dispatch HTTP-hook rejection as an
        # APIConnectionError. A local budget stop must not enter network retries.
        cause=exc
        while cause is not None and not isinstance(cause,BudgetLimit):cause=cause.__cause__
        if isinstance(cause,BudgetLimit):
            status='blocked_config';store.finish(job['id'],status,str(cause))
            store.event('agency_budget_blocked',{'reason':str(cause)},job['id'],job.get('opportunity_id'))
            return
        code=getattr(exc,'code',None); http=getattr(exc,'status_code',None)
        safe=f'{type(exc).__name__} (status={http}, code={code})'
        if type(exc).__name__ in ('ModelBehaviorError','QualityFailure','ValueError'):
            import re
            detail=re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',str(exc))[:2000]
            store.event('execution_diagnostic',{'type':type(exc).__name__,'detail':detail},job['id'],job['opportunity_id'])
        quota=code in ('insufficient_quota','billing_hard_limit_reached','credit_balance_exhausted','billing_not_active','usage_limit_reached') or http in (401,403)
        transient=http in (408,409,429) or (http is not None and http>=500) or isinstance(exc,(TimeoutError,ConnectionError)) or type(exc).__name__ in ('APIConnectionError','APITimeoutError')
        response=getattr(exc,'response',None); headers=response.headers if response is not None else {}
        delay=max(float(headers.get('retry-after-ms',0))/1000,reset_seconds(headers.get('retry-after')),min(120,2**job['attempts']))+random.uniform(0,2)
        if transient and not quota and capacity:
            if http==429 or (http==503 and code in ('server_is_overloaded','slow_down')):capacity.limited(delay)
            else:capacity.transient_failure(delay)
        if transient and not quota and job['attempts']<settings.max_attempts:
            status='retry_wait'
            with store.connect(write=True) as con:
                con.execute("UPDATE jobs SET status='queued',due_at=?,error=?,finished_at=NULL WHERE id=? AND status='running'",(later(delay),safe,job['id']))
            store.event('job_retry_scheduled',{'delay_seconds':delay,'error':safe},job['id'],job['opportunity_id'])
        else:
            if quota:
                # Stop the entire queue: a billing/auth failure is not per-account rate throttling.
                with store.connect(write=True) as con:
                    con.execute("INSERT INTO controls VALUES('api_blocked',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(json.dumps({'code':code,'status':http,'at':utcnow(),'message':'Configure API billing or access, then retry the blocked job to resume.'}),))
            status='blocked_config' if quota else 'failed'; store.finish(job['id'],status,safe)
            store.event('job_'+status,{'error':safe},job['id'],job['opportunity_id'])
    finally:
        with store.connect(write=True) as con:
            con.execute('INSERT OR REPLACE INTO execution_attempts VALUES(?,?,?,?,?,?)',(job['id'],job['attempts'],started_at,time.monotonic()-start,status,concurrency))
        if capacity:
            hs=store.rows("SELECT details FROM events WHERE job_id=? AND kind='rate_headers' ORDER BY id DESC LIMIT 1",(job['id'],))
            if hs:
                capacity.headers=json.loads(hs[0]['details'])
                h=capacity.headers
                if any(k in h and int(h[k])<1 for k in ('x-ratelimit-remaining-requests','x-ratelimit-remaining-tokens','x-ratelimit-remaining-project-tokens')):
                    capacity.cooldown=max(capacity.cooldown,time.monotonic()+max(reset_seconds(h.get('x-ratelimit-reset-requests')),reset_seconds(h.get('x-ratelimit-reset-tokens')),reset_seconds(h.get('x-ratelimit-reset-project-tokens'))))
            capacity.save(store)

def run_one(store,settings,analyst=analyze):
    if store.paused(): return False
    store.tick()
    blocked=bool(store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"))
    job=store.claim(['scan','deliver','followup'] if blocked else None)
    if not job: return False
    asyncio.run(execute_job(store,settings,job,analyst));return True

async def run_pool(store,settings,analyst=analyze,drain=False,auto_brief=True,kinds=None,preview_delivery=False):
    from .operations import queue_brief
    capacity=Capacity(settings); active=set(); stopping=False; last_brief=0.; last_capacity=0.; last_coverage=0.; last_sources=0.
    def stop():
        nonlocal stopping
        stopping=True
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,stop)
    capacity.save(store)
    try:
        while not stopping or active:
            store.heartbeat('paused' if store.paused() else 'running')
            for task in active:
                if task.done(): task.result()
            active={t for t in active if not t.done()}
            paused=store.paused()
            if not stopping and paused and preview_delivery and not active and store.delivery_only():
                # Recheck the mode and enforce the two simulated job kinds in the claim transaction.
                job=store.claim(preview_mode='delivery')
                if job:
                    await execute_job(store,settings,job)
                    continue
            if not stopping and not paused:
                if kinds is None:store.tick()
                if time.monotonic()>=capacity.cooldown:
                    while len(active)<capacity.current:
                        blocked=bool(store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"))
                        eligible=kinds
                        if blocked:
                            eligible=([kind for kind in kinds if kind in ('deliver','agency_deliver')]
                                      if kinds is not None else ['scan','deliver','followup'])
                            if not eligible:break
                        job=store.claim(eligible,preview_mode='general') if preview_delivery else store.claim(eligible)
                        if not job: break
                        active.add(asyncio.create_task(execute_job(store,settings,job,analyst,capacity)))
                actual=store.rows("SELECT COUNT(*) n FROM jobs WHERE status='running' AND kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft')")[0]['n']
                capacity.peak=max(capacity.peak,actual)
                if time.monotonic()-last_capacity>=1:
                    capacity.save(store);last_capacity=time.monotonic()
                if auto_brief and time.monotonic()-last_sources>60:
                    from hashlib import sha256
                    from .data import digest
                    saved=store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
                    hashes=json.loads(saved[0]['summary']).get('hashes',{}) if saved else {}
                    if hashes:
                        actual={name:sha256((settings.data_dir/(name+'.csv')).read_bytes()).hexdigest() for name in hashes}
                        if actual!=hashes and not store.rows("SELECT 1 FROM jobs WHERE kind='scan' AND status IN ('queued','running')"):
                            store.enqueue('scan',{'analysis_limit':-1},key='source-refresh:'+digest(actual))
                    last_sources=time.monotonic()
                if auto_brief and time.monotonic()-last_coverage>30:
                    from .operations import latest_assessment,start_batch
                    from .evidence import current_assessment
                    missing=[]
                    for o in store.rows("SELECT id FROM opportunities WHERE workflow='recovery' AND active=1"):
                        if store.rows("SELECT 1 FROM jobs WHERE opportunity_id=? AND kind IN ('analyze','prepare','reply','revise_draft') AND status IN ('queued','running')",(o['id'],)):continue
                        with store.connect() as con: current=current_assessment(con,o['id'],latest_assessment(store,o['id']))
                        if not current:
                            from .evidence import context_hash,ENGINE_VERSION
                            with store.connect() as con:revision=context_hash(con,o['id'])
                            failed=store.rows("SELECT 1 FROM jobs WHERE opportunity_id=? AND kind='analyze' AND status IN ('failed','blocked_config') AND json_extract(payload,'$.context_hash')=? AND json_extract(payload,'$.engine_version')=?",(o['id'],revision,ENGINE_VERSION))
                            if not failed:missing.append(o['id'])
                    if missing:start_batch(store,missing)
                    last_coverage=time.monotonic()
                if auto_brief and time.monotonic()-last_brief>15:
                    if store.rows("SELECT 1 FROM events WHERE kind='agent_decision' LIMIT 1") and not store.rows("SELECT 1 FROM jobs WHERE kind='revenue_brief' AND status IN ('queued','running') LIMIT 1"):
                        await asyncio.to_thread(queue_brief,store);last_brief=time.monotonic()
            if drain and not active:
                if store.paused() or store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):break
                condition=" AND kind IN ("+",".join("?" for _ in kinds)+")" if kinds else ""
                due=store.rows("SELECT 1 FROM jobs WHERE status='queued' AND due_at<=?"+condition+" LIMIT 1",(utcnow(),*(kinds or [])))
                if not due: break
            await asyncio.sleep(.2 if active else 1)
    finally:
        for t in active: t.cancel()
        if active: await asyncio.gather(*active,return_exceptions=True)
        store.heartbeat('stopped')
        for sig in (signal.SIGTERM,signal.SIGINT): loop.remove_signal_handler(sig)

def run(settings,once=False):
    store=Store(settings.db_path)
    from .demo import use_guard
    with use_guard(settings.db_path),worker_lock(settings.db_path):
        store.recover_interrupted()
        if once: run_one(store,settings)
        else: asyncio.run(run_pool(store,settings))
