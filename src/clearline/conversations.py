"""Provider-independent conversation state, deduplication and validated reply effects."""
import json
from uuid import uuid4
from .data import digest
from .store import utcnow,STOPPED_STATUSES

SCHEMA='''
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,opportunity_id TEXT UNIQUE NOT NULL REFERENCES opportunities(id),status TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
 id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 provider TEXT NOT NULL,external_id TEXT NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
 reply_to TEXT REFERENCES messages(id),outbox_id TEXT UNIQUE,outcome_id TEXT UNIQUE,
 sender TEXT NOT NULL,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,
 simulated INTEGER NOT NULL CHECK(simulated=1),campaign_ids TEXT NOT NULL,created_at TEXT NOT NULL,fingerprint TEXT UNIQUE,
 UNIQUE(provider,external_id));
CREATE TABLE IF NOT EXISTS reply_interpretations(message_id TEXT PRIMARY KEY REFERENCES messages(id),job_id TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commercial_tasks(id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,message_id TEXT UNIQUE NOT NULL REFERENCES messages(id),kind TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customer_context(opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id),contact TEXT,channel TEXT,outreach_policy TEXT NOT NULL DEFAULT 'normal',updated_at TEXT NOT NULL);
'''


def ensure_conversation(con,oid):
    cid='conversation:'+oid
    con.execute("INSERT OR IGNORE INTO conversations VALUES(?,?,'awaiting_response',?)",(cid,oid,utcnow()))
    return cid


def outbound_record(con,outbox,draft,backfill=False):
    """Called in the same transaction as the approved simulated delivery."""
    cid=ensure_conversation(con,outbox['opportunity_id']);analysis=json.loads(draft['analysis'])
    parent=analysis.get('reply_message_id')
    if not parent and analysis.get('reply_to'):
        row=con.execute('SELECT id FROM messages WHERE outcome_id=?',(analysis['reply_to'],)).fetchone();parent=row['id'] if row else None
    campaigns=[r['campaign_id'] for r in con.execute('SELECT campaign_id FROM campaign_accounts WHERE opportunity_id=? AND exclusion IS NULL',(outbox['opportunity_id'],))]
    con.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('outbound:'+outbox['id'],cid,outbox['opportunity_id'],'simulated',outbox['id'],'outbound',parent,outbox['id'],None,'sales@example.invalid',outbox['recipient'],outbox['subject'],outbox['body'],'sent_simulated',1,json.dumps(campaigns),outbox['created_at'],None))
    if parent:con.execute("UPDATE commercial_tasks SET status='completed',updated_at=? WHERE message_id=?",(utcnow(),parent))
    if not backfill:con.execute("UPDATE conversations SET status='awaiting_response',updated_at=? WHERE id=?",(utcnow(),cid))


def migrate(con):
    con.executescript(SCHEMA)
    from .outreach_controls import SCHEMA as restriction_schema
    con.executescript(restriction_schema)
    for row in con.execute('SELECT b.* FROM outbox b WHERE NOT EXISTS(SELECT 1 FROM messages m WHERE m.outbox_id=b.id)').fetchall():
        d=con.execute('SELECT * FROM drafts WHERE id=?',(row['draft_id'],)).fetchone()
        outbound_record(con,row,d,backfill=True)
    # Legacy reply records remain readable; new messages always use ingest_message.
    for row in con.execute("SELECT x.*,l.outbox_id FROM outcomes x JOIN outcome_outreach l ON l.outcome_id=x.id WHERE x.kind='reply' AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.outcome_id=x.id)").fetchall():
        parent=con.execute('SELECT * FROM messages WHERE outbox_id=?',(row['outbox_id'],)).fetchone()
        if not parent:continue
        con.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('inbound:'+row['id'],parent['conversation_id'],row['opportunity_id'],'simulated','legacy:'+row['id'],'inbound',parent['id'],None,row['id'],parent['recipient'],parent['sender'],'Re: '+parent['subject'],row['note'],'legacy_recorded',1,parent['campaign_ids'],row['created_at'],None))


def saved_policy(con,oid):
    row=con.execute('SELECT outreach_policy FROM customer_context WHERE opportunity_id=?',(oid,)).fetchone()
    return row['outreach_policy'] if row else 'normal'

def policy(con,oid):
    if con.execute("SELECT 1 FROM outreach_restrictions WHERE opportunity_id=? AND scope='account' AND released_at IS NULL",(oid,)).fetchone():
        return 'stop'
    return saved_policy(con,oid)


def ingest_message(store,oid,parent_id,external_id,body,sender=None):
    if not body.strip() or len(body)>12000 or not external_id or len(external_id)>100:raise ValueError('A message identifier and reply of at most 12,000 characters are required')
    body=body.strip()
    with store.connect(write=True) as con:
        parent=con.execute("SELECT * FROM messages WHERE id=? AND opportunity_id=? AND direction='outbound' AND status='sent_simulated'",(parent_id,oid)).fetchone()
        if not parent:raise ValueError('Choose a delivered simulated message for this account')
        o=con.execute('SELECT * FROM opportunities WHERE id=?',(oid,)).fetchone()
        if not o or not o['active']:raise ValueError('Account is not active')
        sender=sender or parent['recipient'];fingerprint=digest([parent_id,body,sender])
        existing=con.execute("SELECT * FROM messages WHERE provider='simulated' AND external_id=?",(external_id,)).fetchone()
        if not existing:existing=con.execute("SELECT * FROM messages WHERE fingerprint=?",(fingerprint,)).fetchone()
        if existing:
            if existing['fingerprint']!=fingerprint:raise ValueError('This message identifier already belongs to different content')
            job=con.execute("SELECT id FROM jobs WHERE dedupe_key=?",('reply:'+existing['outcome_id'],)).fetchone()
            return {'message_id':existing['id'],'job_id':job['id'] if job else None,'duplicate':True}
        mid=uuid4().hex;outcome=uuid4().hex;now=utcnow()
        con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(mid,parent['conversation_id'],oid,'simulated',external_id,'inbound',parent_id,None,outcome,sender,parent['sender'],'Re: '+parent['subject'],body,'received',1,parent['campaign_ids'],now,fingerprint))
        con.execute("INSERT INTO outcomes(id,opportunity_id,kind,note,provenance,created_at) VALUES(?,?,'reply',?,'manual_demo_input',?)",(outcome,oid,body,now))
        con.execute('INSERT INTO outcome_outreach VALUES(?,?)',(outcome,parent['outbox_id']))
        # Replies replace unanswered-message reminders and invalidate unsent proposals.
        from .outreach_controls import cancel_outreach,intended_recipient
        cancel_outreach(con,oid,now,intended_recipient(con,parent_id) or None)
        con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE opportunity_id=? AND kind IN ('analyze','prepare') AND status IN ('queued','running','blocked_config')",(now,oid))
        con.execute("UPDATE commercial_tasks SET status='superseded',updated_at=? WHERE opportunity_id=? AND status IN ('pending','awaiting_approval','approved')",(now,oid))
        if policy(con,oid)!='stop' and o['status'] not in STOPPED_STATUSES-{'replied'}:con.execute("UPDATE opportunities SET status='replied',updated_at=? WHERE id=?",(now,oid))
        con.execute("UPDATE conversations SET status='analyzing_reply',updated_at=? WHERE id=?",(now,parent['conversation_id']))
        from .commercial import refresh_message_signals
        refresh_message_signals(con,oid,now)
        jid=store._enqueue(con,'reply',{'evidence_hash':o['evidence_hash'],'outcome_id':outcome,'message_id':mid},oid,'reply:'+outcome)
        store.event('inbound_received',{'message_id':mid,'reply_to':parent_id,'simulated':True},jid,oid,con=con)
        return {'message_id':mid,'job_id':jid,'duplicate':False}


def conversation(store,oid):
    c=store.rows('SELECT * FROM conversations WHERE opportunity_id=?',(oid,))
    messages=store.rows('SELECT * FROM messages WHERE opportunity_id=? ORDER BY created_at,rowid',(oid,))
    reviews={r['outbox_id']:r['note'] for r in store.rows("""SELECT json_extract(details,'$.outbox_id') outbox_id,
        json_extract(details,'$.note') note FROM events WHERE opportunity_id=? AND kind='sent_message_reviewed'""",(oid,))}
    for m in messages:
        m['sent_review']=reviews.get(m['outbox_id'])
        m['campaign_ids']=json.loads(m['campaign_ids'])
        interpretations=store.rows('SELECT body,created_at FROM reply_interpretations WHERE message_id=?',(m['id'],))
        m['interpretation']=json.loads(interpretations[0]['body']) if interpretations else None
        jobs=store.rows("SELECT id,status,error FROM jobs WHERE kind='reply' AND json_extract(payload,'$.outcome_id')=? ORDER BY created_at DESC,rowid DESC LIMIT 1",(m['outcome_id'],)) if m['outcome_id'] else []
        m['job']=jobs[0] if jobs else None
    context=store.rows('SELECT * FROM customer_context WHERE opportunity_id=?',(oid,))
    ctx=context[0] if context else {'contact':None,'channel':None,'outreach_policy':'normal'}
    for key in ('contact','channel'):
        if isinstance(ctx[key],str):ctx[key]=json.loads(ctx[key])
    from .outreach_controls import active
    with store.connect() as con:
        restrictions=active(con,oid)
        auth=con.execute('SELECT recipient FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(oid,)).fetchone()
    status=c[0]['status'] if c else 'not_started'
    if any(r['kind']=='do_not_contact' and r['scope']=='account' for r in restrictions):status='opted_out'
    elif any(r['kind']=='pause' for r in restrictions):status='outreach_paused'
    return {'id':c[0]['id'] if c else None,'status':status,'provider':'simulated','messages':messages,'context':ctx,
            'restrictions':restrictions,'authorized_recipient':auth[0] if auth else None,
            'tasks':store.rows('SELECT * FROM commercial_tasks WHERE opportunity_id=? ORDER BY created_at,rowid',(oid,))}


def save_reply(store,job,result):
    from .reply_agent import validate_reply
    with store.connect(write=True) as con:
        m=con.execute('SELECT * FROM messages WHERE outcome_id=?',(job['payload']['outcome_id'],)).fetchone()
        current=con.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone();o=con.execute('SELECT * FROM opportunities WHERE id=?',(job['opportunity_id'],)).fetchone()
        if not m or not current or current['status']!='running':return
        d=validate_reply(result,m['body'],json.loads(o['evidence']))
        from .service_access import regeneration_current
        if not regeneration_current(store,con,job):
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?",(utcnow(),job['id']));return
        if not job['payload'].get('regenerate_id') and con.execute('SELECT 1 FROM reply_interpretations WHERE message_id=?',(m['id'],)).fetchone():
            con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job['id']));return
        newest=con.execute("SELECT id FROM messages WHERE opportunity_id=? AND direction='inbound' ORDER BY created_at DESC,rowid DESC LIMIT 1",(o['id'],)).fetchone()['id']
        # A late opt-out still suppresses outreach. Other stale results cannot overwrite a new reply.
        if (not o['active'] or o['evidence_hash']!=job['payload']['evidence_hash'] or m['id']!=newest) and d.intent not in ('opt_out','not_interested'):
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?",(utcnow(),job['id']))
            con.execute("UPDATE messages SET status='superseded' WHERE id=?",(m['id'],));return
        from .evidence import context_hash,ENGINE_VERSION
        if d.engine_version==ENGINE_VERSION and d.context_hash!=context_hash(con,o['id']) and d.intent not in ('opt_out','not_interested'):
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?",(utcnow(),job['id']))
            return
        from .outreach_controls import intended_recipient, record, restriction
        target=intended_recipient(con,m['reply_to'])
        data=d.model_dump();now=utcnow();prior_policy=saved_policy(con,o['id'])
        existing=restriction(con,o['id'],d.recipient or target)
        blocked=bool(existing) or prior_policy=='stop' or o['status'] in STOPPED_STATUSES-{'replied'}
        state='awaiting_approval' if d.decision=='pursue' else 'agent_held'
        conversation_state=d.opportunity_status;outreach_policy=prior_policy
        if d.intent=='opt_out':
            scope=d.opt_out_scope
            if d.opt_out_recipient:target=d.opt_out_recipient.lower()
            if scope=='account':
                state='opted_out';outreach_policy='stop'
            else:
                scope='recipient' if scope=='recipient' and target else 'thread'
                state='recipient_opted_out' if scope=='recipient' else 'human_verification'
                if o['status'] in ('opted_out','outreach_paused','lost','closed','won'):state=o['status']
            record(con,store,o,'do_not_contact',scope,'' if scope=='account' else target,m['body'],
                   'simulated_customer_reply',message_id=m['id'])
            conversation_state='opted_out' if scope=='account' else 'recipient_opted_out' if scope=='recipient' else 'opt_out_scope_review'
            if scope=='recipient':
                auth=con.execute('SELECT recipient FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(o['id'],)).fetchone()
                if auth and auth[0].lower()!=target:state='needs_review' if o['status']=='replied' else o['status']
        elif d.intent=='not_interested':state='opted_out' if o['status']=='opted_out' else 'lost';outreach_policy='stop'
        elif blocked:state=o['status'];data.update(decision='hold',subject='',body='',recommended_action='Keep outreach stopped. Review the customer response internally before any change to this restriction.');conversation_state='outreach_stopped'
        elif d.intent=='distributor' or (d.channel and d.channel.route=='distributor'):outreach_policy='channel_review'
        from .action_policy import permitted,proposal_fingerprint
        from .evidence import context_hash,ENGINE_VERSION
        if not blocked and outreach_policy!='stop' and d.decision=='pursue' and not permitted(o,data,outreach_policy):
            if data.get('engine_version')==ENGINE_VERSION:raise ValueError('Reply proposal violates execution boundaries')
            state='agent_held';data.update(decision='hold',subject='',body='');conversation_state='needs_information'
        if d.decision=='hold' and not blocked:state=(data.get('commercial_plan') or {}).get('outcome','agent_held')
        from .commercial import persist_investigation,execution_issues
        if state=='awaiting_approval' and execution_issues(con,o['id'],data,reviewing_message=m['id']):raise ValueError('Reply requires resolved prerequisites and authorized recipient')
        if outreach_policy=='stop':data.update(subject='',body='')
        con.execute("INSERT INTO customer_context(opportunity_id,outreach_policy,updated_at) VALUES(?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET outreach_policy=excluded.outreach_policy,updated_at=excluded.updated_at",(o['id'],outreach_policy,now))
        for field in ('contact','channel'):
            if data[field]:
                value={**data[field],'source_message_id':m['id'],'provenance':'simulated_customer_reply','verified':False}
                con.execute('UPDATE customer_context SET '+field+'=? WHERE opportunity_id=?',(json.dumps(value),o['id']))
        if data.get('engine_version')==ENGINE_VERSION:
            data['context_hash']=context_hash(con,o['id'])
            if data.get('quality'):data['quality']['proposal_hash']=proposal_fingerprint(data)
        persist_investigation(con,o['id'],data,now)
        data.update(effective_status=state,conversation_status=conversation_state,outreach_policy=outreach_policy,simulated=True)
        con.execute('INSERT INTO reply_interpretations VALUES(?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET job_id=excluded.job_id,body=excluded.body,created_at=excluded.created_at',(m['id'],job['id'],json.dumps(data),now))
        con.execute("UPDATE messages SET status='processed' WHERE id=?",(m['id'],))
        passive=state in ('monitor','no_action','defer','deferred','lost','opted_out')
        task_status='completed' if passive or outreach_policy=='stop' or blocked or (d.intent=='opt_out' and scope!='thread') else 'awaiting_approval' if state=='awaiting_approval' else 'pending'
        con.execute('INSERT INTO commercial_tasks VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET kind=excluded.kind,title=excluded.title,status=excluded.status,updated_at=excluded.updated_at',(uuid4().hex,o['id'],m['id'],d.intent,data['recommended_action'],task_status,now,now))
        analysis={**data,'evidence_hash':o['evidence_hash'],'outreach_kind':'reply','strategy':'response_'+d.intent,'hypotheses':[], 'unresolved_questions':d.uncertainties,'evidence_fields':['action_history'],'reply_to':m['outcome_id'],'reply_message_id':m['id']}
        # Keep the existing assessment read model's route field scalar.
        analysis['reported_channel']=data['channel']
        analysis['channel']=data['channel']['route'] if data['channel'] else None
        if analysis.get('quality'):analysis['quality']['proposal_hash']=proposal_fingerprint(analysis)
        if job['payload'].get('regenerate_id'):
            con.execute("UPDATE drafts SET status='superseded' WHERE id=?",(job['payload']['regenerate_id'],))
        if state=='awaiting_approval':
            version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM drafts WHERE opportunity_id=?',(o['id'],)).fetchone()[0]
            con.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid4().hex,o['id'],version,o['evidence_hash'],'simulation@example.invalid',d.subject,d.body,'awaiting_approval',json.dumps(analysis),now))
        if outreach_policy=='stop':
            from .outreach_controls import cancel_outreach
            cancel_outreach(con,o['id'],now)
        con.execute('UPDATE opportunities SET status=?,updated_at=? WHERE id=?',(state,now,o['id']))
        con.execute('UPDATE conversations SET status=?,updated_at=? WHERE id=?',(conversation_state,now,m['conversation_id']))
        con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(now,job['id']))
        store.event('agent_decision',analysis,job['id'],o['id'],con=con)
