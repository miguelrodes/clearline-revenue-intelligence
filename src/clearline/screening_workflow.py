"""Human decisions and verified evidence for fictional agency discovery.

Agency records stay separate from recovery and real-world prospecting. Only a
cleared, reviewed outreach proposal enters the existing exact-version outbox.
"""
import json
from uuid import uuid4
from .data import digest
from .store import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS agency_workflow(
 agency_id TEXT PRIMARY KEY REFERENCES agency_screenings(id),decision TEXT NOT NULL DEFAULT 'new',
 rationale TEXT NOT NULL DEFAULT '',information TEXT NOT NULL DEFAULT '{}',stage TEXT NOT NULL DEFAULT 'not_contacted',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agency_activity(
 id TEXT PRIMARY KEY,agency_id TEXT NOT NULL REFERENCES agency_screenings(id),kind TEXT NOT NULL,
 note TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);
"""

def state(store, aid):
    rows=store.rows('SELECT * FROM agency_workflow WHERE agency_id=?',(aid,))
    result=rows[0] if rows else dict(agency_id=aid,decision='new',rationale='',information='{}',stage='not_contacted',updated_at=None)
    result['information']=json.loads(result['information'])
    result['activity_revision']=activity_revisions(store).get(aid)
    return result

def context_hash(evidence_hash, information, activity_revision=None):
    base=digest([evidence_hash,information]) if information else evidence_hash
    return digest([base,activity_revision]) if activity_revision else base

def activity_revisions(store):
    """Only material replies/progress change reasoning context; not our own logs."""
    grouped={}
    for row in store.rows("SELECT agency_id,id,kind,note,details FROM agency_activity WHERE kind IN ('response_received','advanced') ORDER BY created_at,rowid"):
        grouped.setdefault(row.pop('agency_id'),[]).append(row)
    return {aid:digest(records) for aid,records in grouped.items()}

def current_context(con, aid, evidence_hash):
    row=con.execute('SELECT information FROM agency_workflow WHERE agency_id=?',(aid,)).fetchone()
    records=[dict(r) for r in con.execute("SELECT id,kind,note,details FROM agency_activity WHERE agency_id=? AND kind IN ('response_received','advanced') ORDER BY created_at,rowid",(aid,))]
    return context_hash(evidence_hash,json.loads(row['information']) if row else {},digest(records) if records else None)

def log(con, aid, kind, note, details=None):
    con.execute('INSERT INTO agency_activity VALUES(?,?,?,?,?,?)',(uuid4().hex,aid,kind,note,json.dumps(details or {}),utcnow()))

def invalidate(con, aid):
    oid='agency:'+aid
    con.execute("UPDATE drafts SET status='superseded' WHERE opportunity_id=? AND status IN ('awaiting_approval','approved')",(oid,))
    con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE (opportunity_id=? OR json_extract(payload,'$.agency_id')=?) AND status IN ('queued','running','blocked_config')",(utcnow(),oid,aid))

def record_decision(store, aid, decision, rationale):
    from .screening import detail
    detail(store,aid)
    if decision not in ('accepted','held','rejected') or not rationale.strip():
        raise ValueError('Choose accept, hold or reject and record a specific reason')
    with store.connect(write=True) as con:
        rationale = rationale.strip()
        previous = con.execute('SELECT decision,rationale FROM agency_workflow WHERE agency_id=?',(aid,)).fetchone()
        if previous is None or tuple(previous) != (decision, rationale):
            con.execute("INSERT INTO agency_workflow(agency_id,decision,rationale,updated_at) VALUES(?,?,?,?) ON CONFLICT(agency_id) DO UPDATE SET decision=excluded.decision,rationale=excluded.rationale,updated_at=excluded.updated_at",(aid,decision,rationale,utcnow()))
            if decision!='accepted':invalidate(con,aid)
            log(con,aid,'decision',rationale,{'decision':decision})
    return state(store,aid)

def record_information(store, aid, information, expected_context):
    from .screening import detail
    row=detail(store,aid)
    allowed={'facts','evidence','recipient','role','route','contact_verified','authorized','relationship_checked','synthetic'}
    if set(information)-allowed:raise ValueError('Unknown verification field')
    for k,v in information.items():
        if k in ('contact_verified','authorized','relationship_checked','synthetic'):
            if not isinstance(v,bool):raise ValueError('Verification confirmations must be true or false')
        elif not isinstance(v,str) or len(v)>6000:raise ValueError('Use bounded text for verified information')
    info={k:v.strip() if isinstance(v,str) else v for k,v in information.items()}
    if info.get('route') not in (None,'','direct','distributor'):raise ValueError('Choose direct or distributor routing')
    with store.connect(write=True) as con:
        old=con.execute('SELECT information FROM agency_workflow WHERE agency_id=?',(aid,)).fetchone()
        prior=json.loads(old['information']) if old else {}
        if current_context(con,aid,row['evidence_hash'])!=expected_context:raise ValueError('Information changed; reload before saving')
        if info==prior:return {'changed':False,'ai_triggered':False}
        con.execute("INSERT INTO agency_workflow(agency_id,information,updated_at) VALUES(?,?,?) ON CONFLICT(agency_id) DO UPDATE SET information=excluded.information,updated_at=excluded.updated_at",(aid,json.dumps(info),utcnow()))
        invalidate(con,aid)
        log(con,aid,'information','Human-provided information saved; prior outreach invalidated. Reassessment is explicit.',info)
    return {'changed':True,'ai_triggered':False}

def prerequisites(row):
    issues=[];w=row['workflow'];i=w['information'];q=row['qualification']
    if row['classification']!='unverified_prospect':issues.append('Resolve the existing-customer or identity conflict outside this new-prospect queue')
    if w['decision']!='accepted':issues.append('Accept this prospect for further pursuit and record why')
    if w['stage']!='not_contacted':issues.append('Contact already tracked; review the recorded response before preparing another introduction')
    if not q or not row['qualification_current'] or not q.get('review_passed') or q['decision']['outcome']!='qualified':issues.append('Obtain a current, independently accepted qualification')
    if not i.get('facts') or not i.get('evidence'):issues.append('Record a verified operational application and its supporting evidence')
    if not i.get('recipient') or '@' not in i['recipient'] or not i.get('role') or not i.get('contact_verified'):issues.append('Verify the intended recipient and purchasing role with evidence')
    if not i.get('authorized'):issues.append('Confirm that outreach to this recipient is authorized')
    if not i.get('route') or not i.get('relationship_checked'):issues.append('Verify the purchasing route and check for an existing customer or distributor relationship')
    return issues

def queue_outreach(store, settings, aid, expected_context):
    from .screening import detail
    if not settings.screening_enabled:raise ValueError('Prospect Screening is not enabled')
    row=detail(store,aid)
    if row['context_hash']!=expected_context:raise ValueError('Information changed; reload first')
    missing=prerequisites(row)
    if missing:raise ValueError('; '.join(missing))
    return {'job_id':store.enqueue('agency_outreach',{'agency_id':aid,'evidence_hash':row['evidence_hash'],'context_hash':expected_context},key='agency_outreach:'+aid+':'+expected_context)}

def save_outreach(store, job, result):
    from .screening import detail
    from .screening_agent import passes
    aid=job['payload']['agency_id'];row=detail(store,aid)
    if prerequisites(row) or row['context_hash']!=job['payload']['context_hash']:
        raise ValueError('Prospect prerequisites or evidence changed during drafting')
    if not passes(result['review']):raise ValueError('Independent outreach review did not pass; see saved review findings')
    proposal=result['proposal'];oid='agency:'+aid
    analysis=dict(agency_id=aid,agency_engine_version='agency-outreach-1',context_hash=row['context_hash'],
        subject=proposal['subject'],body=proposal['body'],recipient='simulation@example.invalid',
        intended_recipient=row['workflow']['information']['recipient'],review=result['review'],strategy=proposal['strategy'],
        proposal_hash=digest([proposal['subject'],proposal['body'],'simulation@example.invalid',row['context_hash']]))
    with store.connect(write=True) as con:
        current=con.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()
        evidence=con.execute('SELECT evidence_hash FROM agency_screenings WHERE id=? AND active=1',(aid,)).fetchone()
        wf=con.execute('SELECT * FROM agency_workflow WHERE agency_id=?',(aid,)).fetchone()
        if not current or current['status']!='running' or not evidence or not wf or wf['decision']!='accepted' or current_context(con,aid,evidence['evidence_hash'])!=row['context_hash']:
            raise ValueError('Draft cancelled or information changed; no draft saved')
        con.execute("INSERT INTO opportunities(id,account_key,name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at,workflow) VALUES(?,?,?,?,0,?,?,'[]','awaiting_approval',1,?,'agency_screening') ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence,evidence_hash=excluded.evidence_hash,status='awaiting_approval',updated_at=excluded.updated_at",(oid,'AGENCY|'+aid,row['name'],row['state'],json.dumps({'agency_id':aid,'provenance':'fictional_agency_dataset'}),row['context_hash'],utcnow()))
        con.execute("UPDATE drafts SET status='superseded' WHERE opportunity_id=? AND status IN ('awaiting_approval','approved')",(oid,))
        version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM drafts WHERE opportunity_id=?',(oid,)).fetchone()[0]
        did=uuid4().hex
        con.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)',(did,oid,version,row['context_hash'],'simulation@example.invalid',proposal['subject'],proposal['body'],'awaiting_approval',json.dumps(analysis),utcnow()))
        log(con,aid,'draft_prepared','Personalized introduction independently reviewed; exact version requires human approval.',{'draft_id':did,'version':version})
    return did

def assert_current(con, opp, analysis):
    from .screening import QUALIFICATION_ENGINE
    aid=analysis.get('agency_id');r=con.execute('SELECT * FROM agency_screenings WHERE id=? AND active=1',(aid,)).fetchone()
    w=con.execute('SELECT * FROM agency_workflow WHERE agency_id=?',(aid,)).fetchone()
    if not r or not w:raise ValueError('Prospect verification is missing')
    info=json.loads(w['information']);h=current_context(con,aid,r['evidence_hash'])
    q=con.execute('SELECT result FROM agency_qualifications WHERE agency_id=? AND evidence_hash=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(aid,r['evidence_hash'])).fetchone()
    report=json.loads(q['result']) if q else None
    row=dict(r,workflow={**dict(w),'information':info},qualification=report,qualification_current=bool(report and report.get('context_hash',r['evidence_hash'])==h and report.get('qualification_engine',QUALIFICATION_ENGINE)==QUALIFICATION_ENGINE))
    if prerequisites(row) or analysis.get('context_hash')!=h or opp['id']!='agency:'+aid:
        raise ValueError('Prospect evidence, decision or contact prerequisites changed')

def record_activity(store, aid, kind, note):
    if kind not in ('contact_attempted','response_received','advanced') or not note.strip():raise ValueError('Record a supported activity and specific evidence')
    stages={'contact_attempted':'contact_attempted','response_received':'responded','advanced':'advanced'}
    with store.connect(write=True) as con:
        workflow=con.execute("""SELECT w.decision,w.stage FROM agency_workflow w JOIN agency_screenings a
            ON a.id=w.agency_id WHERE w.agency_id=? AND a.active=1""",(aid,)).fetchone()
        if not workflow or workflow['decision']!='accepted':raise ValueError('Only accepted prospects can advance')
        previous=con.execute("""SELECT kind,note FROM agency_activity WHERE agency_id=? AND kind IN
            ('contact_attempted','response_received','advanced','simulated_send') ORDER BY rowid DESC LIMIT 1""",(aid,)).fetchone()
        if workflow['stage']!=stages[kind] or not previous or (previous['kind'],previous['note'])!=(kind,note.strip()):
            invalidate(con,aid)
            con.execute('UPDATE agency_workflow SET stage=?,updated_at=? WHERE agency_id=?',(stages[kind],utcnow(),aid))
            log(con,aid,kind,note.strip(),{'provenance':'human_reported_simulation','verified_revenue':False})
    return state(store,aid)

def sent(con, aid, draft_id):
    con.execute("UPDATE agency_workflow SET stage='contact_attempted',updated_at=? WHERE agency_id=?",(utcnow(),aid))
    log(con,aid,'simulated_send','Contact attempted in simulation only; no real message sent.',{'draft_id':draft_id})
