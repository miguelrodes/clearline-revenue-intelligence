"""Persisted portfolio batches, campaign authorization and commercial read models."""
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .data import digest
from .store import utcnow, STOPPED_STATUSES

SCHEMA = """
CREATE TABLE IF NOT EXISTS outcome_outreach(outcome_id TEXT PRIMARY KEY, outbox_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch_accounts(batch_id TEXT, opportunity_id TEXT, job_id TEXT, disposition TEXT,
 PRIMARY KEY(batch_id,opportunity_id));
CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, name TEXT, created_at TEXT, status TEXT, simulated_contacts INTEGER);
CREATE TABLE IF NOT EXISTS campaign_accounts(campaign_id TEXT, opportunity_id TEXT, job_id TEXT, exclusion TEXT,
 PRIMARY KEY(campaign_id,opportunity_id));
CREATE TABLE IF NOT EXISTS execution_attempts(job_id TEXT, attempt INTEGER, started_at TEXT, seconds REAL, status TEXT,
 concurrency INTEGER, PRIMARY KEY(job_id,attempt));
CREATE TABLE IF NOT EXISTS operational_briefs(id TEXT PRIMARY KEY, source_hash TEXT, snapshot TEXT, body TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS revenue_briefs(id TEXT PRIMARY KEY, source_hash TEXT, snapshot TEXT, body TEXT, created_at TEXT);
"""


def latest_assessment(store, oid):
    rows=store.rows("SELECT e.details,j.payload FROM events e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.opportunity_id=? AND e.kind='agent_decision' ORDER BY e.id DESC LIMIT 1",(oid,))
    if not rows: return None
    a=json.loads(rows[0]['details']); payload=json.loads(rows[0]['payload'] or '{}')
    a.setdefault('evidence_hash',payload.get('evidence_hash'))
    return a


def start_batch(store, ids=None, request_id=None):
    bid=uuid4().hex
    # Membership and queue entries are one atomic operation, including after interruption.
    with store.connect(write=True) as con:
        cached_request=_request(con,request_id,'batch',{'ids':ids})
        if cached_request:return cached_request['batch_id']
        accounts=con.execute("SELECT * FROM opportunities WHERE active=1 AND workflow='recovery' ORDER BY decline_cents DESC").fetchall()
        if ids is not None and not set(ids).issubset({o['id'] for o in accounts}):
            raise ValueError('Select active recovery accounts')
        con.execute('INSERT INTO batches VALUES(?,?)',(bid,utcnow()))
        for o in accounts:
            oid=o['id']
            if ids is not None and oid not in ids: continue
            previous=con.execute("SELECT e.details,j.payload FROM events e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.opportunity_id=? AND e.kind='agent_decision' ORDER BY e.id DESC LIMIT 1",(oid,)).fetchone()
            cached=False
            if previous:
                a=json.loads(previous['details']); payload=json.loads(previous['payload'] or '{}')
                from .evidence import current_assessment
                cached=current_assessment(con,oid,a)
            from .evidence import context_hash,ENGINE_VERSION
            revision=context_hash(con,oid)
            jid=None if cached else store._enqueue(con,'analyze',{'evidence_hash':o['evidence_hash'],'context_hash':revision,'engine_version':ENGINE_VERSION,'followup_of':None,'portfolio':True,'allow_simulation':False},oid,f"analyze:{oid}:{revision}:{ENGINE_VERSION}:initial")
            con.execute('INSERT INTO batch_accounts VALUES(?,?,?,?)',(bid,oid,jid,'cached' if cached else 'queued'))
        _save_request(con,request_id,'batch',{'ids':ids},{'batch_id':bid})
    return bid


def batches(store):
    result=[]
    for b in store.rows('SELECT * FROM batches ORDER BY created_at DESC,rowid DESC LIMIT 10'):
        counts={}
        for r in store.rows('SELECT COALESCE(j.status,b.disposition) AS status,COUNT(*) AS n FROM batch_accounts b LEFT JOIN jobs j ON b.job_id=j.id WHERE b.batch_id=? GROUP BY 1',(b['id'],)):
            counts[r['status']]=r['n']
        result.append({**b,'counts':counts,'total':sum(counts.values())})
    return result


def create_campaign(store, name, ids, simulated_contacts=False, request_id=None):
    if not ids or len(ids)!=len(set(ids)): raise ValueError('Select distinct accounts')
    # Validate namespace before making any changes.
    accounts=[store.opportunity(oid) for oid in ids]
    if any(o['workflow']!='recovery' for o in accounts): raise ValueError('Recovery campaigns cannot include real prospects')
    cid=uuid4().hex
    with store.connect(write=True) as con:
        inputs={'name':name,'ids':ids,'simulated_contacts':simulated_contacts}
        cached_request=_request(con,request_id,'campaign',inputs)
        if cached_request:return cached_request['campaign_id']
        con.execute('INSERT INTO campaigns VALUES(?,?,?,?,?)',(cid,name,utcnow(),'preparing',int(simulated_contacts)))
        for o in accounts:
            reason=None; jid=None
            from .action_policy import permitted
            a=latest_assessment(store,o['id'])
            if o['holds'] and not permitted(o,a): reason='Evidence verification required: '+', '.join(o['holds'])
            elif not o['active'] or o['status'] in STOPPED_STATUSES: reason='Stopped, rejected or inactive account'
            elif o['status'] in ('approved','awaiting_response') or con.execute('SELECT 1 FROM outbox WHERE opportunity_id=?',(o['id'],)).fetchone(): reason='Already contacted or approved'
            elif not simulated_contacts: reason='Verify a recipient, or explicitly choose simulated role inboxes for this fictional campaign'
            if not reason:
                from .evidence import context_hash,ENGINE_VERSION
                revision=context_hash(con,o['id'])
                jid=store._enqueue(con,'prepare',{'evidence_hash':o['evidence_hash'],'context_hash':revision,'portfolio':True,'allow_simulation':True},o['id'],f"prepare:{o['id']}:{revision}:{ENGINE_VERSION}")
            con.execute('INSERT INTO campaign_accounts VALUES(?,?,?,?)',(cid,o['id'],jid,reason))
        _save_request(con,request_id,'campaign',inputs,{'campaign_id':cid})
    return cid


def campaign_view(store, cid):
    rows=store.rows('SELECT * FROM campaigns WHERE id=?',(cid,))
    if not rows: raise ValueError('Campaign not found')
    members=[]
    for m in store.rows('SELECT c.*,j.status AS job_status FROM campaign_accounts c LEFT JOIN jobs j ON c.job_id=j.id WHERE campaign_id=?',(cid,)):
        o=store.opportunity(m['opportunity_id']); a=latest_assessment(store,o['id'])
        drafts=store.rows('SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1',(o['id'],))
        d=drafts[0] if drafts and not m['exclusion'] else None
        from .reporting import valid_draft
        ready=bool(m['job_status']=='completed' and d and d['status']=='awaiting_approval' and valid_draft(store,d))
        if d: d={**d,'snapshot_hash':store.draft_hash(d)}
        members.append({**m,'name':o['name'],'state':o['state'],'decline_cents':o['decline_cents'],'status':o['status'], 'assessment':a,'draft':d,'ready':ready})
    pending=sum(m['job_status'] in ('queued','running') for m in members)
    status=rows[0]['status']
    if status=='preparing' and not pending: status='awaiting_approval' if any(m['ready'] for m in members) else 'needs_review'
    return {**rows[0],'status':status,'members':members,'pending':pending,
            'simulated_deliveries':store.rows('SELECT COUNT(*) n FROM outbox b JOIN campaign_accounts c ON c.opportunity_id=b.opportunity_id WHERE c.campaign_id=?',(cid,))[0]['n'],
            'scheduled_followups':store.rows("SELECT COUNT(*) n FROM jobs j JOIN campaign_accounts c ON c.opportunity_id=j.opportunity_id WHERE c.campaign_id=? AND j.kind='followup' AND j.status='queued'",(cid,))[0]['n'],
            'recorded_outcomes':store.rows('SELECT COUNT(*) n FROM outcomes o JOIN campaign_accounts c ON c.opportunity_id=o.opportunity_id WHERE c.campaign_id=?',(cid,))[0]['n'],
            'ready':sum(m['ready'] for m in members),'historical_decline_cents':sum(m['decline_cents'] for m in members if not m['exclusion'])}


def decide_campaign(store,cid,snapshots,approve):
    if not snapshots: raise ValueError('No saved drafts selected')
    if len({s['draft_id'] for s in snapshots})!=len(snapshots): raise ValueError('Duplicate approval')
    with store.connect(write=True) as con:
        campaign=con.execute('SELECT * FROM campaigns WHERE id=?',(cid,)).fetchone()
        if not campaign or campaign['status'] in ('approved','rejected'): raise ValueError('Campaign already decided or missing')
        if con.execute("SELECT 1 FROM campaign_accounts c JOIN jobs j ON c.job_id=j.id WHERE c.campaign_id=? AND j.status IN ('queued','running')",(cid,)).fetchone():
            raise ValueError('Campaign preparation is still running; wait and review the complete campaign')
        ready=con.execute("""SELECT d.id FROM campaign_accounts c JOIN jobs j ON c.job_id=j.id
            JOIN opportunities o ON o.id=c.opportunity_id JOIN drafts d ON d.opportunity_id=o.id
            WHERE c.campaign_id=? AND c.exclusion IS NULL AND j.status='completed'
            AND d.status='awaiting_approval' AND d.evidence_hash=o.evidence_hash AND o.active=1""",(cid,)).fetchall()
        from .reporting import valid_draft
        ready=[r for r in ready if valid_draft(store,dict(con.execute('SELECT * FROM drafts WHERE id=?',(r['id'],)).fetchone()))]
        if {r['id'] for r in ready}!={s['draft_id'] for s in snapshots}:
            raise ValueError('Campaign changed; reload and review all ready messages')
        for s in snapshots:
            d=con.execute('SELECT * FROM drafts WHERE id=?',(s['draft_id'],)).fetchone()
            if not d or d['status']!='awaiting_approval' or store.draft_hash(d)!=s['snapshot_hash']: raise ValueError('Draft changed; reload campaign and review before approving')
            m=con.execute('SELECT * FROM campaign_accounts WHERE campaign_id=? AND opportunity_id=?',(cid,d['opportunity_id'])).fetchone()
            if not m or m['exclusion']: raise ValueError('Draft is not an eligible campaign member')
        # All decisions and jobs commit together, or none do.
        for s in snapshots: store._decide(con,s['draft_id'],approve)
        con.execute('UPDATE campaigns SET status=? WHERE id=?',('approved' if approve else 'rejected',cid))
        store.event('campaign_human_decision',{'campaign_id':cid,'approve':approve,'draft_ids':[s['draft_id'] for s in snapshots]},con=con)


def financial_segments(store):
    from .reporting import opportunities
    rows=opportunities(store); result=[]
    for key in ('inactivity','partial','product_decline','direct_gap_channel_review'):
        group=[r for r in rows if (r['partial_decline'] if key=='partial' else key in r['signals'])]
        amount=sum(r['decline_cents'] for r in group)
        prior=sum(r['prior_cents'] for r in group); current=sum(r['current_cents'] for r in group)
        if key=='product_decline':
            pairs=[]
            for r in group:
                e=store.opportunity(r['id'])['evidence']; skus={s['sku'] for s in e['signals'] if s['type']==key}
                pairs.extend(p for p in e['products'] if p['sku'] in skus)
            prior=sum(p['prior_cents'] for p in pairs); current=sum(p['current_cents'] for p in pairs)
            amount=sum(max(0,p['prior_cents']-p['current_cents']) for p in pairs)
        result.append({'key':key,'accounts':len(group),'decline_cents':amount,'decline_pct':(prior-current)*100/prior if prior else None,
                       'analyzed':sum(bool(r['assessment']) for r in group),'actionable':sum(r['assessment']=='pursue' and (not r['holds'] or r['status'] in ('awaiting_approval','approved','awaiting_response')) for r in group),
                       'awaiting_action':sum(r['status'] in ('awaiting_approval','needs_contact','agent_held') for r in group)})
    return result


def metrics(store):
    jobs=store.rows("SELECT status,COUNT(*) AS n FROM jobs WHERE kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft') GROUP BY status")
    attempts=store.rows("SELECT a.* FROM execution_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft') ORDER BY a.started_at")
    usage=[json.loads(r['details']) for r in store.rows("SELECT e.details FROM events e WHERE e.kind='api_response' OR (e.kind='model_usage' AND NOT EXISTS (SELECT 1 FROM events n WHERE n.job_id=e.job_id AND n.kind='api_response'))")]
    completed=[a for a in attempts if a['status']=='completed']
    active=store.rows("""SELECT j.id,j.kind,j.started_at,o.name AS account_name FROM jobs j
        LEFT JOIN opportunities o ON o.id=j.opportunity_id WHERE j.status='running'
        AND j.kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft') ORDER BY j.started_at,j.id""")
    now=utcnow()
    ready=store.rows("SELECT COUNT(*) n FROM jobs WHERE status='queued' AND due_at<=? AND kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft')",(now,))[0]['n']
    retry_wait=store.rows("SELECT COUNT(*) n FROM jobs WHERE status='queued' AND due_at>? AND attempts>0 AND kind IN ('analyze','prepare','prospect_research','prospect_qualify','reply','revise_draft')",(now,))[0]['n']
    requests_inflight=store.rows("""SELECT COUNT(*) n FROM events e JOIN jobs j ON j.id=e.job_id
        WHERE e.kind='model_request_started' AND j.status='running' AND NOT EXISTS(
        SELECT 1 FROM events f WHERE f.kind='model_request_finished' AND f.job_id=e.job_id
        AND json_extract(f.details,'$.request_id')=json_extract(e.details,'$.request_id'))""")[0]['n']
    known=[u.get('cost_usd') for u in usage if u.get('cost_usd') is not None]
    cap=store.rows("SELECT value FROM controls WHERE name='capacity'")
    cutoff=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds')
    recent=store.rows("SELECT COUNT(*) n FROM jobs WHERE kind IN ('analyze','prospect_qualify') AND status='completed' AND finished_at>=?",(cutoff,))[0]['n']
    blocked=store.rows("SELECT value FROM controls WHERE name='api_blocked'")
    return {'api_blocked':json.loads(blocked[0]['value']) if blocked else None,'jobs':{r['status']:r['n'] for r in jobs},'active_investigations':active,'model_requests_inflight':requests_inflight,'queue_ready':ready,'retry_wait':retry_wait,'average_seconds':sum(a['seconds'] for a in completed)/len(completed) if completed else None,
            'recommendations_per_minute_5m':recent/5,'model_requests':sum(u.get('requests',1) for u in usage),'input_tokens':sum(u.get('input_tokens',0) for u in usage),
            'output_tokens':sum(u.get('output_tokens',0) for u in usage),'estimated_cost_usd':sum(known) if known else None,
            'unpriced_records':sum(u.get('cost_usd') is None for u in usage),'attempts':len(attempts),
            'capacity':json.loads(cap[0]['value']) if cap else None,'batches':batches(store)}


def brief_snapshot(store):
    from .briefing import snapshot
    return snapshot(store)


def queue_brief(store,force=False):
    snapshot=brief_snapshot(store); h=digest(snapshot)
    with store.connect(write=True) as con:
        existing=con.execute("SELECT id FROM jobs WHERE kind='revenue_brief' AND status IN ('queued','running') AND json_extract(payload,'$.source_hash')=?",(h,)).fetchone()
        if existing:return existing['id']
        last=con.execute("SELECT id,status,error FROM jobs WHERE kind='revenue_brief' AND json_extract(payload,'$.source_hash')=? ORDER BY created_at DESC,rowid DESC LIMIT 1",(h,)).fetchone()
        if not force and last and (last['status'] in ('failed','blocked_config') or (last['status']=='cancelled' and last['error']!='Superseded operational briefing')):
            return last['id']
        # Coalesce queued snapshots; never spend on an already-obsolete briefing.
        con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error='Superseded operational briefing' WHERE kind='revenue_brief' AND status='queued' AND json_extract(payload,'$.source_hash')!=?",(utcnow(),h))
        saved=con.execute('SELECT created_at FROM operational_briefs WHERE source_hash=? ORDER BY created_at DESC LIMIT 1',(h,)).fetchone()
        if saved and not force:return last['id'] if last else None
        key='operational-brief:'+h
        previous=con.execute('SELECT status,error FROM jobs WHERE dedupe_key=?',(key,)).fetchone()
        if previous and (previous['status']=='completed' or previous['error']=='Superseded operational briefing') and not con.execute('SELECT 1 FROM operational_briefs WHERE source_hash=?',(h,)).fetchone():
            key+=':refresh:'+uuid4().hex
        return store._enqueue(con,'revenue_brief',{'snapshot':snapshot,'source_hash':h},key=key+(':'+uuid4().hex if force else ''))


def review_recommendation(store,oid,decision,note):
    with store.connect(write=True) as con:
        o=con.execute('SELECT * FROM opportunities WHERE id=?',(oid,)).fetchone()
        if not o or o['status'] in STOPPED_STATUSES: raise ValueError('Account is already stopped or deferred')
        if o['status'] in ('approved','awaiting_response'): raise ValueError('Use the recorded-outcome workflow for approved outreach')
        if decision in ('defer','reject'):
            status='deferred' if decision=='defer' else 'rejected'
            con.execute('UPDATE opportunities SET status=?,updated_at=? WHERE id=?',(status,utcnow(),oid))
            con.execute("UPDATE drafts SET status='rejected' WHERE opportunity_id=? AND status='awaiting_approval'",(oid,))
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE opportunity_id=? AND kind IN ('prepare','deliver','followup') AND status IN ('queued','running')",(utcnow(),oid))
        store.event('human_verification_decision',{'decision':decision,'note':note,'holds_unchanged':True},opportunity_id=oid,con=con)


def _request(con,key,operation,inputs):
    if key is None:return None
    row=con.execute('SELECT * FROM operation_requests WHERE id=?',(str(key),)).fetchone()
    if row:
        if row['operation']!=operation or row['input_hash']!=digest(inputs):raise ValueError('Request ID already used with different inputs')
        return json.loads(row['result'])

def _save_request(con,key,operation,inputs,result):
    if key is not None:con.execute('INSERT INTO operation_requests VALUES(?,?,?,?)',(str(key),operation,digest(inputs),json.dumps(result)))
