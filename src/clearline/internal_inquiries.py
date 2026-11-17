"""On-demand operational requests. Internal correspondence is *not* customer evidence.

Use the same version hash, simulated provider, audit trail and targeted assessment queue
as outreach, but keep internal traffic out of the customer timeline, follow-ups and KPIs.
"""
import json
import re
from collections import Counter
from uuid import uuid4
from .data import digest
from .store import utcnow, STOPPED_STATUSES
from .evidence import context_hash
from .transport import SimulatedProvider

SCHEMA='''
CREATE TABLE IF NOT EXISTS internal_recipients(
 opportunity_id TEXT NOT NULL REFERENCES opportunities(id), group_id TEXT NOT NULL, role_key TEXT NOT NULL,
 responsibility TEXT NOT NULL, recipient TEXT NOT NULL, evidence TEXT NOT NULL,
 verified_at TEXT NOT NULL, PRIMARY KEY(opportunity_id,group_id));
CREATE TABLE IF NOT EXISTS internal_inquiries(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id), group_id TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, job_id TEXT REFERENCES jobs(id));
CREATE INDEX IF NOT EXISTS internal_inquiry_account ON internal_inquiries(opportunity_id);
CREATE TABLE IF NOT EXISTS internal_draft_versions(
 inquiry_id TEXT NOT NULL REFERENCES internal_inquiries(id), version INTEGER NOT NULL,
 recipient TEXT NOT NULL, verification_evidence TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
 evidence_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(inquiry_id,version));
CREATE TABLE IF NOT EXISTS internal_approvals(
 inquiry_id TEXT PRIMARY KEY REFERENCES internal_inquiries(id), version INTEGER NOT NULL,
 snapshot_hash TEXT NOT NULL, approved_at TEXT NOT NULL,
 FOREIGN KEY(inquiry_id,version) REFERENCES internal_draft_versions(inquiry_id,version));
CREATE TABLE IF NOT EXISTS internal_deliveries(
 inquiry_id TEXT PRIMARY KEY REFERENCES internal_approvals(inquiry_id), version INTEGER NOT NULL,
 mode TEXT NOT NULL CHECK(mode='simulated'), sent_at TEXT NOT NULL,
 FOREIGN KEY(inquiry_id,version) REFERENCES internal_draft_versions(inquiry_id,version));
CREATE TABLE IF NOT EXISTS internal_replies(
 id TEXT PRIMARY KEY, inquiry_id TEXT NOT NULL REFERENCES internal_deliveries(inquiry_id),
 body TEXT NOT NULL, record_refs TEXT NOT NULL, received_at TEXT NOT NULL, UNIQUE(inquiry_id,body));
CREATE TABLE IF NOT EXISTS internal_confirmations(
 reply_id TEXT NOT NULL REFERENCES internal_replies(id), task_id TEXT NOT NULL REFERENCES investigation_tasks(id),
 finding TEXT NOT NULL, source TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
 confirmed_at TEXT NOT NULL, PRIMARY KEY(reply_id,task_id));
'''


def _required(value,label,limit):
    value=(value or '').strip()
    if not value or len(value)>limit:raise ValueError(f'Enter {label} (up to {limit} characters)')
    return value


def _group(store,settings,oid,gid):
    from .practical_actions import practical_actions
    group=next((g for g in practical_actions(store,settings,oid) if g['id']==gid),None)
    if not group or not group['can_prepare_internal']:
        raise ValueError('No current internal inquiry is justified for that action. Refresh the account.')
    return group


def _account(con,oid):
    opp=con.execute("SELECT id,workflow,active,name,status,evidence_hash FROM opportunities WHERE id=?",(oid,)).fetchone()
    if not opp or opp['workflow']!='recovery':raise ValueError('Existing customer account required')
    return opp


def _active(opp):
    if not opp['active'] or opp['status'] in STOPPED_STATUSES|{'monitor','defer','no_action'}:
        raise ValueError('This account has no current actionable investigation')


def _load(con,oid,iid):
    row=con.execute('SELECT * FROM internal_inquiries WHERE id=? AND opportunity_id=?',(iid,oid)).fetchone()
    if not row:raise ValueError('Internal request not found on this account')
    return dict(row)


def _version(con,inquiry):
    row=dict(con.execute('SELECT * FROM internal_draft_versions WHERE inquiry_id=? AND version=?',(inquiry['id'],inquiry['version'])).fetchone())
    row['id']=row.pop('inquiry_id')
    return row


def _mentions(text, record_id):
    return bool(re.search(r'(?<![\w-])' + re.escape(record_id) + r'(?![\w-])', text, re.I))


def _suggested_findings(body, tasks):
    """Quote the respondent's own claims; never classify them as verified."""
    sentences = [part.strip() for part in re.split(r'(?<=[.!?])\s+|\n+', body) if part.strip()]
    suggestions = {}
    for task in tasks:
        if task['record_ids']:
            claims = [sentence for sentence in sentences if any(_mentions(sentence, ref) for ref in task['record_ids'])]
            if claims:
                suggestions[task['id']] = ' '.join(claims)
        elif len(tasks) == 1:
            suggestions[task['id']] = body
    return suggestions


def _pending_state(sent, record_ids, mentioned, unscoped_answer):
    if not sent:
        return 'draft'
    if mentioned.intersection(record_ids) or (not record_ids and unscoped_answer):
        return 'response_recorded'
    return 'status_requested'


def task_communication_work(con, opportunity_id=None):
    """Read current communication for pending tasks in one query, without loading email bodies."""
    query = """
        SELECT i.id, i.scope, d.sent_at,
               (SELECT json_group_array(json(r.record_refs)) FROM internal_replies r
                WHERE r.inquiry_id=i.id) AS reply_refs,
               (SELECT json_group_array(t.id) FROM json_each(i.scope,'$.task_ids') s
                JOIN investigation_tasks t ON t.id=s.value AND t.opportunity_id=i.opportunity_id
                WHERE t.status='pending') AS pending_ids
        FROM internal_inquiries i LEFT JOIN internal_deliveries d ON d.inquiry_id=i.id
    """
    args = ()
    if opportunity_id is not None:
        query += ' WHERE i.opportunity_id=?'
        args = (opportunity_id,)
    result = {}
    for row in con.execute(query + ' ORDER BY i.rowid DESC', args):
        pending = set(json.loads(row['pending_ids']))
        if not pending:
            continue
        group = json.loads(row['scope'])
        tasks = group['tasks']
        replies = json.loads(row['reply_refs'])
        mentioned = {ref for refs in replies for ref in refs}
        role = group['role_key'].replace('_', ' ')
        for task in tasks:
            tid = task['id']
            if tid not in pending or tid in result:
                continue  # The newest request covering this pending task owns it.
            ids = list(dict.fromkeys(task['record_ids']))
            state = _pending_state(row['sent_at'], ids, mentioned, len(tasks) == 1 and bool(replies))
            answered = [ref for ref in ids if ref in mentioned]
            outstanding = [ref for ref in ids if ref not in mentioned]
            if state == 'draft':
                status = 'draft_prepared'
                next_step = f'Review the prepared internal {role} inquiry and its current scope.'
            elif state == 'response_recorded':
                status = 'response_recorded'
                next_step = f'Review the internal {role} reply and verify its findings against the records.'
            else:
                status = 'awaiting_internal_findings'
                next_step = (f'An internal reply is recorded. These records still need {role} findings.'
                             if replies else f'The internal inquiry was sent. Wait for {role} findings.')
            result[tid] = dict(inquiry_id=row['id'], inquiry_state=state, status=status,
                               responsibility=group['role'], sent_at=row['sent_at'], delivery_mode='simulated',
                               order_ids=answered if state=='response_recorded' else ids,
                               outstanding_order_ids=outstanding if row['sent_at'] else [], next_step=next_step)
    return result


def task_communication_states(con, opportunity_id=None):
    return {tid:item['inquiry_state'] for tid,item in task_communication_work(con, opportunity_id).items()}


def _progress(con, inquiry, group, replies):
    """Project the immutable request scope against deliveries, claims and verified task findings."""
    delivery = con.execute('SELECT sent_at,version FROM internal_deliveries WHERE inquiry_id=?', (inquiry['id'],)).fetchone()
    task_rows = {r['id']: r for r in con.execute("""
        SELECT t.id,t.status,f.resolution FROM json_each(?,'$.task_ids') member
        JOIN investigation_tasks t ON t.id=member.value AND t.opportunity_id=?
        LEFT JOIN investigation_resolutions f ON f.task_id=t.id AND f.opportunity_id=t.opportunity_id
    """, (inquiry['scope'], inquiry['opportunity_id']))}
    mentioned = {ref for reply in replies for ref in reply['record_refs']}
    confirmed = {c['task_id']: c['finding'] for reply in replies for c in reply['confirmations']}
    tasks = {}
    for task in group['tasks']:
        tid = task['id']
        row = task_rows.get(tid)
        finding = confirmed.get(tid) or (row['resolution'] if row else None)
        if row and row['status'] == 'resolved' and finding:
            state = 'verified'
        elif row and row['status'] == 'pending':
            state = _pending_state(delivery, task['record_ids'], mentioned, len(group['tasks']) == 1 and bool(replies))
        else:
            state = 'closed'  # A superseded check is not a verified order outcome.
        tasks[tid] = {'task_id': tid, 'status': state, 'finding': finding}

    records = {}
    for line in group['lines']:
        record_id = line['order_id']
        record = records.setdefault(record_id, {'order_id': record_id, 'line_refs': [], 'task_ids': []})
        record['line_refs'].append(line['ref'])
        for task in group['tasks']:
            if line['ref'] in task['record_refs'] and task['id'] not in record['task_ids']:
                record['task_ids'].append(task['id'])
    for record in records.values():
        states = {tasks[tid]['status'] for tid in record['task_ids']}
        if states.intersection({'draft', 'status_requested', 'response_recorded'}):
            # A reply mentioning one order cannot supply a finding for the other orders in its task.
            state = _pending_state(delivery, [record['order_id']], mentioned, False)
        else:
            state = 'verified' if states == {'verified'} else 'closed'
        record['status'] = state

    states = {task['status'] for task in tasks.values()}
    if not states.intersection({'draft', 'status_requested', 'response_recorded'}):
        workflow = 'verified' if states == {'verified'} else 'closed'
    elif not delivery:
        workflow = 'awaiting_approval'
    elif 'verified' in states:
        workflow = 'partially_verified'
    elif replies:
        workflow = 'response_recorded'
    else:
        workflow = 'awaiting_response'
    job = con.execute('SELECT status FROM jobs WHERE id=?', (inquiry['job_id'],)).fetchone() if inquiry['job_id'] else None
    return {'workflow_state': workflow, 'sent_at': delivery['sent_at'] if delivery else None,
            'sent_version': delivery['version'] if delivery else None, 'task_states': list(tasks.values()),
            'record_states': list(records.values()), 'reassessment_status': job['status'] if job else None}


def _details(con,store,i):
    draft=_version(con,i);group=json.loads(i['scope'])
    replies=[]
    for reply in con.execute('SELECT * FROM internal_replies WHERE inquiry_id=? ORDER BY rowid',(i['id'],)):
        confirmations=[dict(r) for r in con.execute('SELECT task_id,finding,source,job_id,confirmed_at FROM internal_confirmations WHERE reply_id=? ORDER BY rowid',(reply['id'],))]
        replies.append({**dict(reply),'record_refs':json.loads(reply['record_refs']),'suggested_finding':reply['body'],
                        'suggested_findings':_suggested_findings(reply['body'],group['tasks']),
                        'confirmed_task_ids':[r['task_id'] for r in confirmations],'confirmations':confirmations})
    progress = _progress(con, i, group, replies)
    pending = {t['task_id'] for t in progress['task_states'] if t['status'] in {'draft','status_requested','response_recorded'}}
    previous = [dict(r) for r in con.execute("""SELECT version,recipient,subject,body,created_at FROM internal_draft_versions
        WHERE inquiry_id=? AND version<? ORDER BY version DESC""", (i['id'], i['version']))]
    return {**{k:i[k] for k in ('id','group_id','status','job_id','opportunity_id')},
            'responsibility':group['role'],'role_key':group['role_key'],'task_ids':group['task_ids'],
            'pending_task_ids':[tid for tid in group['task_ids'] if tid in pending],
            'tasks':group['tasks'],'lines':group['lines'],'replies':replies,
            **{k:draft[k] for k in ('subject','body','recipient','version','verification_evidence')},
            'snapshot_hash':store.draft_hash(draft),'delivery_mode':'simulated',
            'previous_versions':previous, **progress}


def list_inquiries(store,oid):
    with store.connect() as con:
        _account(con,oid)
        return {'recipients':[dict(r) for r in con.execute('SELECT group_id,role_key,responsibility,recipient,evidence FROM internal_recipients WHERE opportunity_id=?',(oid,))],
                'inquiries':[_details(con,store,dict(r)) for r in con.execute('SELECT * FROM internal_inquiries WHERE opportunity_id=? ORDER BY rowid DESC',(oid,))]}


def draft_text(account,group):
    purpose=group['role_key']
    lines=group['lines']
    issue={'fulfillment':'Open order status','billing':'Billing and credit details',
           'relationship':'Purchasing contact and route','distributor':'Purchasing relationship',
           'support':'Training and product needs','planning':'Purchasing plans and funding',
           'records':'Account records'}.get(purpose,'Account records')
    subject=f"{account} — {issue}"
    if purpose in ('fulfillment','billing') and lines:
        question=("For each open line below, could you confirm whether it was fulfilled, invoiced, canceled or is still open? If any line is on hold, what is needed and who can help?"
                  if purpose=='fulfillment' else
                  "For the credit records below, could you confirm the reason for each adjustment, its original invoice and whether a correction, replacement or closure was recorded?")
        record_lines=[f"• {line['order_id']} | {line['date'] or 'date not recorded'} | {line['qty']} × {line['sku']} | {line['status']}" for line in lines]
        rationale=('I want to confirm what still needs attention before suggesting any further purchases.'
                   if purpose=='fulfillment' else 'I want to distinguish settled adjustments from anything still needing correction.')
        content=[rationale,question,'',*record_lines,'','Please include the supporting shipment or invoice reference, or the record that confirms the status.' if purpose=='fulfillment' else 'Please include the reference supporting each answer and flag anything still unresolved.']
    else:
        content=['Could you check the following against our internal records?',*['• '+t['question'] for t in group['tasks']],
                 '','Please identify the source that supports your answer, or tell us what is still unknown.']
    return subject,'\n'.join(['Hello,','',f"I’m following up internally about {account}.",*content,'','Thank you.'])


def _route(con,oid,g,recipient,evidence):
    prior=con.execute('SELECT * FROM internal_recipients WHERE opportunity_id=? AND group_id=?',(oid,g['id'])).fetchone()
    email=(recipient or '').strip().lower() or (prior['recipient'] if prior else '')
    if not email or not re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',email) or len(email)>320:
        raise ValueError('Enter the verified internal recipient’s email address')
    evidence=(evidence or '').strip() or (prior['evidence'] if prior and prior['recipient']==email else '')
    if len(evidence)<8 or len(evidence)>2000:
        raise ValueError('Record how you verified this person is responsible and authorized to receive this internal request; an email address alone is insufficient')
    if con.execute('SELECT 1 FROM contact_authorizations WHERE lower(recipient)=? AND authorized=1',(email,)).fetchone():
        raise ValueError('This address is a customer purchasing recipient; use a verified internal recipient')
    if not prior or (prior['recipient'],prior['evidence'])!=(email,evidence):
        con.execute('INSERT INTO internal_recipients VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id,group_id) DO UPDATE SET recipient=excluded.recipient,evidence=excluded.evidence,verified_at=excluded.verified_at',
                    (oid,g['id'],g['role_key'],g['role'],email,evidence,utcnow()))
    return email,evidence


def _request_key(oid,group):
    return digest([oid,group['id'],sorted(group['task_ids']),sorted(l['ref'] for l in group['lines'])])


def _unrequested(con,oid,group):
    """Do not re-send a pending question after a consolidated request shrinks or grows."""
    pending=set(group['task_ids']);already=set();previous=None
    for i in con.execute("SELECT * FROM internal_inquiries WHERE opportunity_id=? AND group_id=? AND status IN ('sent_simulated','reply_recorded') ORDER BY rowid DESC",(oid,group['id'])):
        overlap=set(json.loads(i['scope'])['task_ids'])&pending
        if overlap:
            already.update(overlap)
            if previous is None:previous=i
    if not already:return group,None
    tasks=[t for t in group['tasks'] if t['id'] not in already]
    refs={ref for t in tasks for ref in t['record_refs']}
    return {**group,'tasks':tasks,'task_ids':[t['id'] for t in tasks],
            'lines':[l for l in group['lines'] if l['ref'] in refs]},previous


def prepare(store,settings,oid,group_id,recipient='',verification_evidence=''):
    # BEGIN IMMEDIATE keeps task membership and authorization fixed during preparation.
    with store.connect(write=True) as con:
        opp=_account(con,oid);_active(opp)
        group,previous=_unrequested(con,oid,_group(store,settings,oid,group_id))
        if not group['task_ids'] and previous is not None:return _details(con,store,previous)
        key=_request_key(oid,group)
        prior=con.execute('SELECT * FROM internal_inquiries WHERE request_key=?',(key,)).fetchone()
        if prior and prior['status']!='awaiting_approval':return _details(con,store,prior)
        # A change to the open tasks revises the existing unsent request rather
        # than leaving two approval controls for overlapping records.
        if not prior:
            prior=con.execute("""SELECT * FROM internal_inquiries WHERE opportunity_id=? AND group_id=?
                              AND status='awaiting_approval' ORDER BY rowid DESC LIMIT 1""",(oid,group_id)).fetchone()
        email,evidence=_route(con,oid,group,recipient,verification_evidence)
        revision=context_hash(con,oid)
        now=utcnow();iid=prior['id'] if prior else uuid4().hex;v=prior['version']+1 if prior else 1
        if prior:
            old=_version(con,prior)
            if prior['request_key']==key and (old['evidence_hash'],old['recipient'],old['verification_evidence'])==(revision,email,evidence):
                return _details(con,store,prior)
        subject,body=draft_text(opp['name'],group)
        if not prior:con.execute('INSERT INTO internal_inquiries VALUES(?,?,?,?,?,?,?,?,?)',(iid,oid,group_id,key,json.dumps(group),v,'awaiting_approval',now,None))
        else:con.execute('UPDATE internal_inquiries SET version=?,scope=?,request_key=? WHERE id=?',(v,json.dumps(group),key,iid))
        con.execute('INSERT INTO internal_draft_versions VALUES(?,?,?,?,?,?,?,?)',(iid,v,email,evidence,subject,body,revision,now))
        store.event('internal_request_prepared',{'inquiry_id':iid,'version':v,'task_ids':group['task_ids']},opportunity_id=oid,con=con)
        return _details(con,store,_load(con,oid,iid))


def _ready(con,store,settings,oid,iid,expected):
    i=_load(con,oid,iid);d=_version(con,i)
    if store.draft_hash(d)!=expected:raise ValueError('Draft changed. Review the current exact version.')
    if i['status']!='awaiting_approval':raise ValueError('This internal request is no longer editable or awaiting approval')
    _active(_account(con,oid))
    g,_=_unrequested(con,oid,_group(store,settings,oid,i['group_id']))
    if _request_key(oid,g)!=i['request_key'] or d['evidence_hash']!=context_hash(con,oid):
        raise ValueError('The account or its tasks changed. Review the current action and prepare the request again.')
    r=con.execute('SELECT recipient,evidence FROM internal_recipients WHERE opportunity_id=? AND group_id=?',(oid,g['id'])).fetchone()
    if not r or (r['recipient'],r['evidence'])!=(d['recipient'],d['verification_evidence']):raise ValueError('Internal routing changed; prepare and review a current draft')
    if con.execute('SELECT 1 FROM contact_authorizations WHERE lower(recipient)=? AND authorized=1',(d['recipient'],)).fetchone():
        raise ValueError('This address is a customer purchasing recipient; verify a different internal recipient')
    return i,d


def edit(store,settings,oid,iid,snapshot_hash,subject,body):
    subject=_required(subject,'a subject',300);body=_required(body,'the message',12000)
    with store.connect(write=True) as con:
        i,d=_ready(con,store,settings,oid,iid,snapshot_hash)
        if (subject,body)!=(d['subject'],d['body']):
            v=i['version']+1
            con.execute('INSERT INTO internal_draft_versions VALUES(?,?,?,?,?,?,?,?)',(iid,v,d['recipient'],d['verification_evidence'],subject,body,d['evidence_hash'],utcnow()))
            con.execute('UPDATE internal_inquiries SET version=? WHERE id=?',(v,iid))
            store.event('internal_request_edited',{'inquiry_id':iid,'version':v},opportunity_id=oid,con=con)
        return _details(con,store,_load(con,oid,iid))


def _check_message_scope(scope, body):
    """An edited request can only be recorded as sent for the records it still covers."""
    if scope['role_key'] not in {'fulfillment', 'billing'}:
        return
    orders = {}
    for line in scope['lines']:
        orders.setdefault(line['order_id'], []).append(line['sku'])
    passages = {order: [] for order in orders}
    order_context = None
    for passage in re.split(r'\n+|(?<=[.!?])\s+', body):
        named = [oid for oid in orders if _mentions(passage, oid)]
        if named:
            order_context = named[0] if len(named) == 1 else None
        if order_context:
            passages[order_context].append(passage)
    for order, skus in orders.items():
        if not _mentions(body, order):
            raise ValueError(f'The email no longer includes {order}. Include each requested order before approval.')
        if len(skus) == 1:
            continue
        # Other orders often carry the very same SKUs. Their lines cannot supply
        # the missing line for this order after the salesperson edits the email.
        local = ' '.join(passages[order])
        all_words = 'all|every|each|both' if len(skus) == 2 else 'all|every|each'
        if re.search(rf'\b(?:{all_words}) (?:of )?(?:(?:the|its) )?(?:\d+ )?(?:(?:open|credit|recorded) )?(?:lines?|items?)\b', local, re.I):
            continue
        for sku, count in Counter(skus).items():
            if len(re.findall(r'(?<![\w-])' + re.escape(sku) + r'(?![\w-])', local, re.I)) < count:
                raise ValueError(f'The email must cover every requested line of {order}. Include its product codes alongside the order ID or request all lines of that order.')


def approve(store,settings,oid,iid,snapshot_hash):
    with store.connect(write=True) as con:
        i=_load(con,oid,iid)
        approval=con.execute('SELECT * FROM internal_approvals WHERE inquiry_id=?',(iid,)).fetchone()
        if approval and snapshot_hash==approval['snapshot_hash']:return _details(con,store,i)
        i,d=_ready(con,store,settings,oid,iid,snapshot_hash)
        _check_message_scope(json.loads(i['scope']),d['body'])
        con.execute('INSERT INTO internal_approvals VALUES(?,?,?,?)',(iid,d['version'],snapshot_hash,utcnow()))
        SimulatedProvider(store).send_internal(con,d,{'snapshot_hash':snapshot_hash})
        con.execute("UPDATE internal_inquiries SET status='sent_simulated' WHERE id=?",(iid,))
        store.event('internal_request_approved_and_simulated',{'inquiry_id':iid,'version':d['version'],'snapshot_hash':snapshot_hash,'real_email_sent':False},opportunity_id=oid,con=con)
        return _details(con,store,_load(con,oid,iid))


def record_reply(store,oid,iid,body):
    body=_required(body,'the simulated internal response',12000)
    with store.connect(write=True) as con:
        i=_load(con,oid,iid)
        if i['status']=='awaiting_approval':raise ValueError('Only a simulated sent request can receive a reply')
        if not con.execute('SELECT 1 FROM internal_replies WHERE inquiry_id=? AND body=?',(iid,body)).fetchone():
            if i['status']=='verified':raise ValueError('This internal request has already been resolved')
            group=json.loads(i['scope'])
            ids={rid for t in group['tasks'] for rid in t['record_ids']}
            refs=sorted(rid for rid in ids if _mentions(body,rid))
            rid=uuid4().hex
            con.execute('INSERT INTO internal_replies VALUES(?,?,?,?,?)',(rid,iid,body,json.dumps(refs),utcnow()))
            con.execute("UPDATE internal_inquiries SET status='reply_recorded' WHERE id=?",(iid,))
            store.event('internal_reply_claim_recorded',{'inquiry_id':iid,'reply_id':rid,'matched_record_ids':refs,'verified':False},opportunity_id=oid,con=con)
        return _details(con,store,_load(con,oid,iid))


def validate_record_coverage(group, task, finding):
    """A single checked line cannot resolve a wider order or credit investigation."""
    if group.get('role_key') not in ('fulfillment', 'billing'):
        return
    for order_id in task['record_ids']:
        if not _mentions(finding, order_id):
            raise ValueError('Record a verified finding for each referenced record before resolving this task. Leave partially answered tasks open.')
        scoped = [line for line in group['lines']
                  if line['ref'] in task['record_refs'] and line['order_id'] == order_id]
        if len(scoped) > 1:
            every_sku = all(line['sku'].casefold() in finding.casefold() for line in scoped)
            every_line = re.search(r'\b(?:all|both|every) (?:of (?:the |its ))?(?:(?:open|credit|recorded) )?(?:line[s]?|items?)\b', finding, re.I)
            if not every_sku and not every_line:
                raise ValueError('The order has multiple lines. Confirm each SKU or explicitly confirm that the finding covers all lines.')


def confirm(store,settings,oid,iid,reply_id,findings):
    from .commercial import verified_task_finding
    from .task_purpose import task_purpose
    if not findings or len(findings)>50 or len({f['task_id'] for f in findings})!=len(findings):raise ValueError('Select distinct tasks with verified findings')
    with store.connect(write=True) as con:
        i=_load(con,oid,iid)
        reply=con.execute('SELECT * FROM internal_replies WHERE id=? AND inquiry_id=?',(reply_id,iid)).fetchone()
        if not reply:raise ValueError('Choose a response to this specific internal request')
        group=json.loads(i['scope']);tasks={t['id']:t for t in group['tasks']}
        changes=[]
        for f in findings:
            tid=f['task_id'];finding=_required(f['finding'],'the verified finding',4000);source=_required(f['source'],'how it was independently checked',2000)
            if tid not in tasks:raise ValueError('The selected task is not part of this inquiry')
            done=con.execute('SELECT finding,source FROM internal_confirmations WHERE task_id=? AND reply_id=?',(tid,reply_id)).fetchone()
            if done:
                if (done['finding'],done['source'])!=(finding,source):raise ValueError('A different finding has already been recorded for this task')
                continue
            raw=con.execute("SELECT * FROM investigation_tasks WHERE id=? AND opportunity_id=? AND status='pending'",(tid,oid)).fetchone()
            if not raw:raise ValueError('The selected task is no longer pending')
            if task_purpose(raw)['contact_resolvable']:raise ValueError('Verify the purchasing recipient and route in Contact Clearance; an internal reply cannot authorize customer contact')
            validate_record_coverage(group,tasks[tid],finding)
            changes.append((tid,finding,source))
        if changes:
            opp=_account(con,oid);_active(opp)
            current=_group(store,settings,oid,i['group_id'])
            if any(tid not in current['task_ids'] for tid,_,_ in changes):raise ValueError('The assessment changed; review the current task before recording a finding')
            for tid,finding,source in changes:
                verified_task_finding(store,con,tid,f'{finding}\nVerification source: {source}\nInternal simulated reply: {reply_id}')
            jid=store._enqueue_analysis(con,opp,investigation=True)
            for tid,finding,source in changes:
                con.execute('INSERT INTO internal_confirmations VALUES(?,?,?,?,?,?)',(reply_id,tid,finding,source,jid,utcnow()))
            pending={r['id'] for r in con.execute("SELECT id FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,))}
            status='reply_recorded' if set(tasks)&pending else 'verified'
            con.execute('UPDATE internal_inquiries SET job_id=?,status=? WHERE id=?',(jid,status,iid))
            store.event('internal_findings_verified',{'inquiry_id':iid,'reply_id':reply_id,'task_ids':[r[0] for r in changes]},job_id=jid,opportunity_id=oid,con=con)
        return _details(con,store,_load(con,oid,iid))


def install_routes(app,store,settings):
    from pydantic import BaseModel,Field,ConfigDict
    class Command(BaseModel):
        model_config=ConfigDict(extra='forbid')
    class Prepare(Command):
        group_id:str=Field(min_length=1,max_length=250)
        recipient:str=Field(default='',max_length=320)
        verification_evidence:str=Field(default='',max_length=2000)
    class ExactVersion(Command):
        snapshot_hash:str=Field(min_length=64,max_length=64)
    class Edit(ExactVersion):
        subject:str=Field(min_length=1,max_length=300)
        body:str=Field(min_length=1,max_length=12000)
    class Reply(Command):
        body:str=Field(min_length=1,max_length=12000)
    class Finding(Command):
        task_id:str
        finding:str=Field(min_length=1,max_length=4000)
        source:str=Field(min_length=1,max_length=2000)
    class Confirm(Command):
        reply_id:str
        findings:list[Finding]=Field(min_length=1,max_length=50)
    path='/api/accounts/{oid}/internal-inquiries'
    @app.get(path)
    def read(oid:str):return list_inquiries(store,oid)
    @app.post(path)
    def create(oid:str,body:Prepare):return prepare(store,settings,oid,**body.model_dump())
    @app.post(path+'/{iid}/edit')
    def revise(oid:str,iid:str,body:Edit):return edit(store,settings,oid,iid,**body.model_dump())
    @app.post(path+'/{iid}/approve')
    def decision(oid:str,iid:str,body:ExactVersion):return approve(store,settings,oid,iid,body.snapshot_hash)
    @app.post(path+'/{iid}/reply')
    def reply(oid:str,iid:str,body:Reply):return record_reply(store,oid,iid,body.body)
    @app.post(path+'/{iid}/confirm')
    def verify(oid:str,iid:str,body:Confirm):return confirm(store,settings,oid,iid,**body.model_dump())
