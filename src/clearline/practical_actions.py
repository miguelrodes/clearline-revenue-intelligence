"""Turn saved human checks into executable account actions; no new commercial decisions."""
import json
import re
from datetime import date
from decimal import Decimal
from hashlib import sha256

from .commercial import workflow_control_task
from .data import cents, digest
from .evidence import current_assessment, source_records
from .operations import latest_assessment
from .store import STOPPED_STATUSES
from .task_purpose import task_purpose


ROLES = {
    'fulfillment': 'Person responsible for processing and fulfilling customer orders',
    'billing': 'Person responsible for billing and credit adjustments',
    'relationship': 'Person responsible for the customer relationship',
    'distributor': 'Person responsible for the distributor relationship',
    'support': 'Person responsible for customer training or product support',
    'planning': 'Person responsible for the customer relationship and purchasing plans',
    'records': 'Person responsible for the relevant customer records',
}
FIELDS = {'recipient': 'purchasing email address', 'role': 'purchasing role',
          'route': 'permitted purchasing route', 'verification_evidence': 'source of authorization'}
WHY = {
    'fulfillment': 'If a shipment or invoice has stalled, fixing it could protect the order and avoid asking the customer to buy the same supplies again.',
    'billing': 'Knowing why a credit was issued and whether it was settled can reveal a billing problem worth fixing before trying to sell again.',
    'contact': 'The right buyer and permitted route make it possible to reconnect about a genuine purchasing need without sidestepping a distributor or contacting the wrong person.',
    'identity': 'Checking which buyer the records belong to keeps salespeople from acting on a decline or request that belongs to someone else.',
    'needs': 'A confirmed need could justify support, training or a suitable purchase. If it was already addressed, another sales approach may be unnecessary.',
    'records': 'A verified answer helps separate a purchasing obstacle the team can fix from an incomplete or misleading record.',
}
AFTER = 'Once you record a material verified finding, Clearline reassesses this account. It may recommend support, outreach, monitoring or no action. You still decide whether to approve any email.'
ORDER_ID = re.compile(r'\bSO-\d+(?:-CR)?\b', re.I)
IDENTITY = re.compile(r'\b(?:identit\w*|jurisdiction|alias\w*|attribut\w*|linkage|mapping|legal entity)\b')
NEED = re.compile(r'\b(?:train\w*|support|product|funding|grant|budget|complaint|concern|interpretation|color.reading|night.shift|patrol|interest|need|service records|procurement)\b')
PURCHASING_PLANS = re.compile(r'\b(?:funding|grant|budget|procurement|purchasing plan\w*)\b', re.I)
CREDIT = re.compile(r'\b(?:credit\w*|refund\w*|billing|adjustment\w*)\b')
FULFILL = re.compile(r'\b(?:open|fulfill?\w*|ship\w*|cancel\w*|aged|operational review|disposition|order.status)\b')
ORDER_RECORD = re.compile(r'\b(?:orders?|lines?|invoice\w*|fulfill?\w*|ship\w*|operational review)\b')
REAL_NAME = re.compile(r'\b[A-Z][a-zA-Z’\'-]+ [A-Z]\.')


def _dollars(c):
    return f'${Decimal(c)/100:,.2f}'


def _orders(store, settings, account):
    # Reuse the saved source-row identity and hash. No investigation tools,
    # scan, rematch or evidence-retrieval events are necessary for display.
    refs = {f'orders:{r}' for r in account['evidence'].get('source_rows', [])}
    if not refs:
        return {}
    scans = store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
    expected = json.loads(scans[0]['summary']).get('hashes', {}).get('orders') if scans else None
    if not expected:
        return {}
    try:
        path = settings.data_dir / 'orders.csv'
        if sha256(path.read_bytes()).hexdigest() != expected:
            return {}
        rows = source_records(str(path), expected)
    except (OSError, ValueError):
        return {}
    return {r['ref']: r for r in rows if r['ref'] in refs}


def _line(r, asof):
    try:
        age = (date.fromisoformat(asof) - date.fromisoformat(r['order_date'])).days
    except (TypeError, ValueError):
        age = None
    return dict(ref=r['ref'], order_id=r['order_id'], sku=r['sku'], qty=r['qty'],
                date=r['order_date'], status=r['status'], amount_cents=cents(r['line_total']), age_days=age)


def _kind(t, account, records):
    title = t['title'].lower()
    purpose = task_purpose(t)
    if purpose['identity_check'] or IDENTITY.search(title):
        return 'identity'
    if purpose['contact_resolvable']:
        return 'contact'
    if CREDIT.search(title):
        return 'billing'
    if FULFILL.search(title) and (ORDER_RECORD.search(title) or any(r['status']=='open' for r in records)):
        return 'fulfillment'
    if NEED.search(title):
        return 'needs'
    return 'records'


def _tidy(text):
    """Translate a saved request without inventing a cause, contact or action."""
    text = re.sub(r'^(?:(?:complete|continue|update|extend) (?:the )?(?:existing|pending) (?:task|check|review)\s*[:—-]\s*)', '', text, flags=re.I)
    for pattern, replacement in [(r'\bestablish (?:the )?(?:current )?disposition\b', 'confirm the current status'),
                                 (r'\bdisposition\b', 'status'), (r'\breconcile\b', 'check'),
                                 (r'\bsell-through\b', 'downstream purchasing'),(r'\bthe commercial hypothesis\b','the reason for the change')]:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text[:1].upper() + text[1:]


def _request(t):
    # Retain the concrete missing fact from the saved task. Suppress process
    # instructions about the reviewer/AI/draft; the UI already explains those.
    reason = re.sub(r'\s+', ' ', t['reason']).strip()
    candidates = re.split(r'(?<=[.!?])\s+(?=[A-Z])', reason)
    good = [s for s in candidates if not re.match(
        r'^(?:Update the (?:existing|pending) task|Continue the existing (?:pending )?task|Do not duplicate|Keep the existing draft|Reassess |Only if |After (?:verification|reconciliation), reassess|Do not (?:draft|contact|request|seek)|No outreach|Do not merge|Retain the (?:source|identity) hold|Do not assume)',s)]
    return _tidy(' '.join(good[:2]) or t['title']).rstrip('.') + '.'


def _group(account, kind, role_key, items, asof, missing, role_owner, assigned):
    tasks = [t for t,_ in items]; lines = list({r['ref']:r for _,rs in items for r in rs}.values())
    lines.sort(key=lambda r:(r['date'],r['order_id'],r['ref']))
    ids = list(dict.fromkeys(r['order_id'] for r in lines))
    member_tasks=[]
    for task, task_lines in items:
        member_tasks.append({'id':task['id'], 'title':task['title'], 'blocking':bool(task['blocking']),
                             'question':_request(task),'record_refs':[r['ref'] for r in task_lines] if kind in {'fulfillment','billing'} else json.loads(task['evidence_refs']),
                             'record_ids':list(dict.fromkeys(r['order_id'] for r in task_lines)) if kind in {'fulfillment','billing'} else list(dict.fromkeys(ORDER_ID.findall(task['reason'].upper()+' '+task['title'].upper())))})
    n=len(ids)
    needs_contact=kind=='contact'
    found = _tidy(tasks[0]['title']).rstrip('.') + '.'
    next_step = member_tasks[0]['question']
    title = _tidy(tasks[0]['title']).rstrip('.')
    allow_inquiry=True
    if kind=='fulfillment' and n:
        title = f'Confirm the status of order {ids[0]}' if n==1 else f'Confirm the status of {n} open orders'
        ages=[r['age_days'] for r in lines if r['age_days'] is not None and r['age_days']>=0]
        when = (f' The recorded order date was {ages[0]} days before the cutoff.' if ages and len(ages)==len(lines) and len(set(ages))==1 else
                f' Their order dates were {min(ages)}–{max(ages)} days before the cutoff.' if ages and len(ages)==len(lines) else '')
        found=(f"{ids[0]} has " if n==1 else f'{n} orders have ')+f'{len(lines)} open '+('line' if len(lines)==1 else 'lines')+f' totaling {_dollars(sum(r["amount_cents"] for r in lines))} at {asof}.'+when+' Open status alone does not establish a delay.'
        next_step='Confirm for each listed line whether it shipped, was invoiced, was canceled or is still open. Record the supporting reference and, if anything is blocked, the reason and who can fix it.'
    elif kind=='billing' and n:
        title= f'Check the reason and outcome of credit {ids[0]}' if n==1 else f'Check the reason and outcome of {n} credit memos'
        found='The records include '+(', '.join(ids))+f' with {_dollars(sum(abs(r["amount_cents"]) for r in lines))} in historical credits. A credit does not mean there is a current problem.'
        next_step='Confirm the reason and outcome of each listed credit, with the original invoice and any adjustment, replacement or closure record.'
    elif kind=='billing' or kind=='fulfillment':
        # Never draft a record-specific request without independently scoped rows.
        allow_inquiry=False
        next_step=member_tasks[0]['question']+' Check the original records; the referenced lines could not be verified against the saved order snapshot.'
    elif needs_contact:
        title='Confirm the purchasing contact and permitted route'
        found=f"The saved review requires purchasing permission specific to {account['name']}. An old email or an invoice alone does not establish it."
        if missing:
            labels=[FIELDS[k] for k in missing]
            what=labels[0] if len(labels)==1 else ', '.join(labels[:-1])+' and '+labels[-1]
            next_step='Verify the '+what+' using approved internal records. Save partial details if other facts are still unknown.'
        else:
            next_step='Confirm whether the saved authorization covers the specific scope requested in this task.'
        if missing==['recipient']:
            allow_inquiry=False
    elif kind=='needs':
        note=account['evidence'].get('crm_notes','').strip()
        if note and account['evidence'].get('crm_id') and any(str(ref).startswith('crm_accounts:') for t in tasks for ref in json.loads(t['evidence_refs'])):
            found=f'The saved CRM note says “{note}”. It does not establish a current need.'
    elif kind=='identity':
        title='Verify which customer the records belong to'
        found=f"The review could not verify which organization the cited records belong to for {account['name']}."
    # Conditional tasks stay on the account; an alternative channel or an address
    # does not make an internal inquiry justified when the saved question is a
    # choice to hold, or a later step contingent on another verification.
    if re.match(r'^(?:decide |defer |hold |monitor |choose |after |once |if |conditionally |approve |reject )', tasks[0]['title'], re.I):
        allow_inquiry=False
    if kind in {'fulfillment', 'billing'} and n:
        for task, task_lines in items:
            mentioned = set(ORDER_ID.findall(task['title'].upper() + ' ' + task['reason'].upper()))
            matched = {line['order_id'] for line in task_lines}
            if not matched or not mentioned.issubset(matched):
                allow_inquiry = False
                next_step += ' Check the original records first. Some requested order references could not be verified.'
                break
    category={'contact':'contacts','identity':'records','fulfillment':'orders','billing':'orders','needs':'needs','records':'records'}[kind]
    return dict(id=f'{role_key}:'+digest([kind,role_owner] if kind in {'fulfillment','billing'} else [kind,tasks[0]['id']])[:16],
                category=category, role_key=role_key, role=ROLES[role_key], assigned_owner=assigned,
                title=title, found=found, why=WHY[kind], next_step=next_step, afterward=AFTER, as_of=asof,
                control='contact' if needs_contact else 'finding', can_prepare_internal=allow_inquiry,
                task_ids=[t['id'] for t in tasks], tasks=member_tasks, lines=lines,
                missing_contact_fields=missing if needs_contact else [])


def practical_actions(store, settings, oid):
    """Account-scoped, read-only projection of existing pending, justified human work."""
    account=store.opportunity(oid)
    if account['workflow']!='recovery' or not account['active'] or account['status'] in STOPPED_STATUSES|{'no_action','monitor','defer','approved','awaiting_response','awaiting_approval'}:
        return []
    assessment=latest_assessment(store,oid)
    if not assessment or assessment.get('review_failed') or assessment.get('decision') in {'no_action','monitor','defer'} or assessment.get('evidence_hash')!=account['evidence_hash']:
        return []
    with store.connect() as con:
        if not current_assessment(con,oid,assessment): return []
    tasks=store.rows("SELECT * FROM investigation_tasks WHERE opportunity_id=? AND status='pending' ORDER BY blocking DESC,created_at,rowid",(oid,))
    tasks=[t for t in tasks if not workflow_control_task(t)]
    if not tasks:return []
    rows=_orders(store,settings,account) if any('orders:' in t['evidence_refs'] for t in tasks) else {}
    asof=account['evidence'].get('as_of','')
    saved=store.rows('SELECT * FROM contact_clearance_notes WHERE opportunity_id=?',(oid,))
    auth=store.rows('SELECT * FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(oid,))
    recorded=(dict(auth[0],verification_evidence=auth[0]['evidence']) if auth else {}) | (saved[0] if saved else {})
    missing=[k for k in FIELDS if not (recorded.get(k) or '').strip()]
    groups={}
    for t in tasks:
        refs=json.loads(t['evidence_refs']);records=[rows[r] for r in refs if r in rows];kind=_kind(t,account,records)
        role_key={'fulfillment':'fulfillment','billing':'billing','contact':'distributor' if account['account_key'].startswith('DISTRIBUTOR|') or 'channel' in t['owner'].lower() else 'relationship',
                  'identity':'records','records':'records','needs':'planning' if PURCHASING_PLANS.search(t['title']) else 'support'}[kind]
        # Do not combine requests for different saved owners, account identities,
        # or different functions. Non-order business questions each retain scope.
        key=t['owner'].strip().casefold() if kind in {'fulfillment','billing'} else t['id']
        targeted=[]
        if kind in ('fulfillment','billing'):
            status='open' if kind=='fulfillment' else 'credit_memo'
            target_ids=set(ORDER_ID.findall(t['title'].upper()+' '+t['reason'].upper()))
            targeted=[_line(r,asof) for r in records if r['status']==status and (not target_ids or r['order_id'] in target_ids)]
        groups.setdefault((kind,role_key,key),[]).append((t,targeted))
    actions=[]
    for (kind,role_key,owner),items in groups.items():
        # A saved owner/assignment is not permission to email that person.
        raw=items[0][0]['owner'];names=list(dict.fromkeys(REAL_NAME.findall(raw)))
        assigned=', '.join(names) if names else None
        actions.append(_group(account,kind,role_key,items,asof,missing,owner,assigned))
    return sorted(actions,key=lambda g:(not any(t['blocking'] for t in g['tasks']),{'fulfillment':0,'records':1,'billing':2,'support':3,'planning':3,'relationship':4,'distributor':4}[g['role_key']]))
