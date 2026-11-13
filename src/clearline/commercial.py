"""Versioned commercial opportunities, deterministic triggers and execution prerequisites."""
import json, math, statistics
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date
from .data import digest, cents

CATEGORIES=('inactive_recovery','purchasing_decline','sku_deterioration','missed_replenishment',
 'distributor_recovery','aging_open_order','cross_sell','purchasing_obstacle','churn_prevention')
SCHEMA='''
CREATE TABLE IF NOT EXISTS commercial_signals(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, category TEXT NOT NULL, trigger_key TEXT NOT NULL,
 evidence TEXT NOT NULL, amount_cents INTEGER, active INTEGER NOT NULL, investigation_status TEXT NOT NULL,
 disposition TEXT, next_action TEXT, assessment_context TEXT, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS commercial_signals_account ON commercial_signals(opportunity_id,active);
CREATE TABLE IF NOT EXISTS contact_authorizations(
 opportunity_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, role TEXT NOT NULL, route TEXT NOT NULL,
 evidence TEXT NOT NULL, authorized INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contact_clearance_notes(
 opportunity_id TEXT PRIMARY KEY, task_id TEXT, contact_name TEXT NOT NULL DEFAULT '',
 recipient TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 route TEXT NOT NULL DEFAULT '', distributor TEXT NOT NULL DEFAULT '',
 verification_evidence TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'partial', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigation_resolutions(
 task_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, resolution TEXT NOT NULL, updated_at TEXT NOT NULL);
'''
@dataclass(frozen=True)
class CommercialPolicy:
    open_review_days:int=30
    cadence_min_dates:int=4
    cadence_multiplier:float=1.5
    cadence_max_cv:float=.5
    association_min_accounts:int=30
    association_min_pair:int=10
    association_min_confidence:float=.6
    association_min_lift:float=1.2
    recent_contact_days:int=14


def parse_date(s):
    try:return date.fromisoformat(str(s)[:10])
    except (ValueError,TypeError):return None


def purchased_skus(orders,asof):
    return {r['sku'] for r in orders if r['status']=='invoiced' and float(r['qty'])>0 and (not parse_date(r.get('order_date')) or parse_date(r.get('order_date'))<=asof)}


def associations(accounts,policy=CommercialPolicy()):
    """Unique, resolved institutional accounts; no distributor/agency double counting."""
    baskets=[]
    for e in accounts:
        if e.get('account_key','').startswith(('DISTRIBUTOR|','UNRESOLVED|','CRM_UNRESOLVED|')):continue
        if set(e.get('holds',[])) & {'ambiguous_identity','identity_needs_review','multiple_shipping_cities'}:continue
        basket={p['sku'] for p in e.get('products',[]) if p.get('current_packs_or_sessions',0)>0}
        if basket:baskets.append(basket)
    n=len(baskets);result=[]
    for a in sorted(set().union(*baskets) if baskets else []):
        for b in sorted(set().union(*baskets)-{a}):
            na=sum(a in x for x in baskets);nb=sum(b in x for x in baskets);pair=sum({a,b}<=x for x in baskets)
            confidence=pair/na;baseline=nb/n;lift=confidence/baseline
            z=1.96;lower=(confidence+z*z/(2*na)-z*math.sqrt(confidence*(1-confidence)/na+z*z/(4*na*na)))/(1+z*z/na)
            reliable=n>=policy.association_min_accounts and pair>=policy.association_min_pair and confidence>=policy.association_min_confidence and lift>=policy.association_min_lift and lower>baseline
            result.append(dict(antecedent=a,consequent=b,accounts=n,antecedent_accounts=na,consequent_accounts=nb,pair_accounts=pair,support=pair/n,confidence=confidence,lift=lift,confidence_lower_95=lower,reliable=reliable,limitation='Observational co-purchasing, not evidence of demand or causal conversion.'))
    return result


def detect(e,orders,association_rows=(),policy=CommercialPolicy()):
    result=[];asof=parse_date(e.get('as_of')) or date(2026,11,1)
    def add(category,key,evidence,amount=None):
        result.append(dict(id=digest([e.get('account_key'),category,key])[:28],category=category,trigger_key=key,evidence=evidence,amount_cents=amount))
    for s in e.get('signals',[]):
        category={'inactivity':'inactive_recovery','reduced_purchasing':'purchasing_decline','product_decline':'sku_deterioration'}.get(s['type'])
        if category:
            amount=e.get('decline_cents',0)
            if category=='sku_deterioration':amount=sum(max(0,p['prior_cents']-p['current_cents']) for p in e.get('products',[]) if p['sku']==s['sku'])
            add(category,s.get('sku','account'),s,amount)
    dated=[(r,parse_date(r.get('order_date'))) for r in orders]
    dated=[(r,d) for r,d in dated if d and d<=asof]
    invoice_dates=sorted({d for r,d in dated if r['status']=='invoiced' and float(r['qty'])>0 and r['sku']!='CL-TRN'})
    open_rows=[(r,d) for r,d in dated if r['status']=='open']
    if len(invoice_dates)>=policy.cadence_min_dates:
        gaps=[(b-a).days for a,b in zip(invoice_dates,invoice_dates[1:])];median=statistics.median(gaps)
        cv=statistics.pstdev(gaps)/statistics.mean(gaps) if statistics.mean(gaps)>0 else 99
        elapsed=(asof-invoice_dates[-1]).days
        if median>0 and cv<=policy.cadence_max_cv and elapsed>median*policy.cadence_multiplier:
            add('missed_replenishment','account',dict(days_since_purchase=elapsed,median_gap_days=median,coefficient_of_variation=cv,purchase_dates=len(invoice_dates),review_after_days=median*policy.cadence_multiplier,recent_open_orders=[r['order_id'] for r,d in open_rows if d>=invoice_dates[-1]],inventory_unknown=True))
    if e.get('account_key','').startswith('DISTRIBUTOR|') and e.get('prior_cents',0)>=100000 and e.get('current_cents',0)<e['prior_cents']*.75:
        add('distributor_recovery','own_purchases',dict(prior_cents=e['prior_cents'],current_cents=e['current_cents'],decline_fraction=(e['prior_cents']-e['current_cents'])/e['prior_cents'],scope='Distributor own purchases; overlaps attributed agency records'),e['decline_cents'])
    grouped=defaultdict(list)
    for r,d in open_rows:
        if (asof-d).days>=policy.open_review_days:grouped[r['order_id']].append((r,d))
    for oid,lines in grouped.items():
        add('aging_open_order',oid,dict(order_id=oid,age_days=max((asof-d).days for r,d in lines),threshold_days=policy.open_review_days,threshold_kind='Internal review threshold; not a fulfillment SLA',rows=[r.get('ref') for r,d in lines],fulfillment_unknown=True),sum(cents(r['line_total']) for r,d in lines))
    notes=e.get('crm_notes','').lower();owned={p['sku'] for p in e.get('products',[]) if p.get('current_packs_or_sessions',0)>0 or p.get('prior_packs_or_sessions',0)>0}
    # Product ownership uses every supplied invoice, including outside the two
    # comparable windows. A past purchase is not a new-product opportunity.
    owned.update(purchased_skus(orders,asof))
    if 'interested in mailroom' in notes and 'CL-MAIL50' not in owned:add('cross_sell','CL-MAIL50',dict(basis='Explicit undated CRM interest',sku='CL-MAIL50',current_need_unverified=True))
    for a in association_rows:
        if a['reliable'] and a['antecedent'] in owned and a['consequent'] not in owned:add('cross_sell',a['consequent'],dict(basis='Purchasing association',association=a,customer_need_unverified=True))
    obstacles=[x for x in ('training','low light','grant funding','retired','procurement','complained') if x in notes]
    if obstacles:add('purchasing_obstacle','crm',dict(note=e.get('crm_notes'),topics=obstacles,current_need_unverified=True,last_contacted=e.get('last_contacted')))
    credits=[r for r,d in dated if r['status']=='credit_memo']
    if credits or 'complained' in notes:
        add('churn_prevention','risk_review',dict(credit_rows=[r.get('ref') for r in credits],complaint_note=e.get('crm_notes') if 'complained' in notes else None,interpretation='Investigate reason/resolution; not confirmed dissatisfaction'),sum(abs(cents(r['line_total'])) for r in credits) or None)
    # Multiple bases for a product remain evidence on one persistent signal.
    unique={}
    for r in result:
        if r['id'] in unique:unique[r['id']]['evidence'].setdefault('additional_bases',[]).append(r['evidence'])
        else:unique[r['id']]=r
    return list(unique.values())


def eligibility(store,oid):
    rows=store.rows('SELECT * FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(oid,))
    if not rows:return {'eligible':False,'reason':'No authorized recipient and relationship route recorded','authorization':None}
    r=rows[0];return {'eligible':True,'reason':'Human-recorded relationship authorization','authorization':r}


def workflow_control_task(task):
    """Identify draft/approval bookkeeping, not missing customer business facts.

    These operations already have exact-version controls; making them business
    prerequisites would prevent a new proposal from ever reaching those controls.
    Mixed tasks verifying a recipient, identity or order remain business tasks.
    """
    import re
    title=task['title'].strip().casefold()
    patterns=(r'^(?:after authorization,\s*)?obtain separate .*approval',
              r'^review(?: and separately approve)? (?:the )?(?:existing|pending)\b.*\b(draft|proposal)\b',
              r'^reconcile (?:the )?(?:pending|awaiting-approval) draft\b',
              r'^(?:gate|keep|flag) (?:the )?(?:existing|pending|awaiting-approval)\b.*\bdraft\b',
              r'^resolve (?:the )?pending\b.*\bdraft',
              r'^hold (?:the )?pending draft\b')
    return any(re.search(pattern,title) for pattern in patterns)


def decision_issues(plan,access):
    """Hard safety/coverage conditions; commercial judgment remains independently reviewed."""
    issues=[];outcome=plan['outcome'];e=access.opp['evidence']
    expected={s['id'] for s in access.store.rows('SELECT id FROM commercial_signals WHERE opportunity_id=? AND active=1',(access.oid,))}
    assessed=[s['signal_id'] for s in plan['signal_decisions']]
    if set(assessed)!=expected or len(assessed)!=len(set(assessed)):issues.append('Assess every detected signal exactly once')
    if not plan['objective'].strip() or not plan['timing'].strip() or not plan['intervention'].strip() or not plan['alternatives']:issues.append('Objective, timing, intervention and alternatives are mandatory')
    for task in plan['verification_tasks']:
        if task.get('existing_task_id'):
            old=access.store.rows("SELECT evidence_refs FROM investigation_tasks WHERE id=? AND opportunity_id=? AND status='pending'",(task['existing_task_id'],access.oid))
            if not old or set(json.loads(old[0]['evidence_refs']))!=set(task['evidence_refs']):issues.append('Reuse only an existing pending task for this account with the exact same evidence scope')
    if any(workflow_control_task(t) for t in plan['verification_tasks']):issues.append('Remove draft-review, holding and approval-only tasks. Existing workflow controls perform those steps; investigation tasks must request missing business facts, never require approval before a new proposal can be prepared.')
    if outcome=='contact':
        auth=eligibility(access.store,access.oid)
        if not auth['eligible']:issues.append(auth['reason'])
        elif plan['recipient']!=auth['authorization']['recipient'] or plan['route']!=auth['authorization']['route']:issues.append('Recipient must be exactly '+auth['authorization']['recipient']+' with no name or explanation; route must be '+auth['authorization']['route'])
        if any(t['blocking'] for t in plan['verification_tasks']):issues.append('Resolve blocking prerequisites before external contact')
        if access.store.rows('SELECT 1 FROM controls WHERE name=?',('commercial_prerequisites:'+access.oid,)) and any(not workflow_control_task(t) for t in access.store.rows("SELECT title FROM investigation_tasks WHERE opportunity_id=? AND status='pending' AND blocking=1",(access.oid,))):issues.append('Previously recorded blocking prerequisites remain unresolved')
        from .action_policy import SOFT_HOLDS
        if set(access.opp['holds'])-SOFT_HOLDS:issues.append('Unresolved identity prohibits contact')
        if plan['capability']=='aging_open_order':
            with access.store.connect() as con:resolved=resolved_category(con,access.oid,'aging_open_order')
            if not resolved:issues.append('Order-status outreach requires a resolution linked to the relevant order evidence')
        if plan['capability']=='churn_prevention' and any('credit_rows' in json.loads(s['evidence']) and json.loads(s['evidence'])['credit_rows'] for s in access.store.rows('SELECT evidence FROM commercial_signals WHERE opportunity_id=? AND category=? AND active=1',(access.oid,'churn_prevention'))):
            with access.store.connect() as con:resolved=resolved_category(con,access.oid,'churn_prevention')
            if not resolved:issues.append('Investigate credit reason and resolution internally before credit-led contact')
    return issues

def execution_issues(con,oid,analysis):
    issues=[]
    if any(not workflow_control_task(t) for t in con.execute("SELECT title FROM investigation_tasks WHERE opportunity_id=? AND blocking=1 AND status='pending'",(oid,))):issues.append('Blocking investigation prerequisites remain unresolved')
    auth=con.execute('SELECT * FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(oid,)).fetchone()
    if not auth or auth['recipient']!=analysis.get('recipient') or auth['route']!=(analysis.get('commercial_plan') or {}).get('route'):issues.append('Recipient/channel authorization is missing or changed')
    return issues

def resolved_category(con,oid,category):
    signals=con.execute('SELECT evidence FROM commercial_signals WHERE opportunity_id=? AND category=? AND active=1',(oid,category)).fetchall()
    resolutions=con.execute('SELECT t.evidence_refs FROM investigation_resolutions r JOIN investigation_tasks t ON t.id=r.task_id WHERE r.opportunity_id=? AND length(trim(r.resolution))>0',(oid,)).fetchall()
    refs=set().union(*(set(json.loads(r['evidence_refs'])) for r in resolutions)) if resolutions else set()
    required=[set(json.loads(s['evidence']).get('credit_rows' if category=='churn_prevention' else 'rows',[])) for s in signals]
    return bool(required) and all(bool(r) and r.issubset(refs) for r in required)


def persist_investigation(con,oid,analysis,now):
    """Version signal decisions; reuse unresolved tasks with the same evidence/purpose."""
    from .data import digest
    from .evidence import ENGINE_VERSION
    marker='commercial_prerequisites:'+oid
    if not con.execute('SELECT 1 FROM controls WHERE name=?',(marker,)).fetchone():
        referenced={t.get('existing_task_id') for t in analysis.get('verification_tasks',[])}
        for old in con.execute("SELECT id FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,)).fetchall():
            if old['id'] not in referenced:con.execute("UPDATE investigation_tasks SET status='superseded' WHERE id=?",(old['id'],))
        con.execute('INSERT INTO controls VALUES(?,?)',(marker,ENGINE_VERSION))
    for old in con.execute("SELECT id,title FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,)).fetchall():
        if workflow_control_task(old):con.execute("UPDATE investigation_tasks SET status='handled_by_workflow_controls' WHERE id=?",(old['id'],))
    for t in analysis.get('verification_tasks', (analysis.get('commercial_plan') or {}).get('verification_tasks',[])):
        refs=sorted(set(t['evidence_refs']))
        if t.get('existing_task_id'):
            old=con.execute("SELECT evidence_refs FROM investigation_tasks WHERE id=? AND opportunity_id=? AND status='pending'",(t['existing_task_id'],oid)).fetchone()
            if not old or sorted(set(json.loads(old['evidence_refs'])))!=refs:raise ValueError('Referenced task changed or belongs to different evidence')
            if t['blocking']:con.execute('UPDATE investigation_tasks SET blocking=1 WHERE id=?',(t['existing_task_id'],))
            continue
        pending=con.execute("SELECT id,title,evidence_refs,owner,blocking FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,)).fetchall()
        existing=next((r for r in pending if sorted(set(json.loads(r['evidence_refs'])))==refs and r['owner']==t['owner'] and r['blocking']==int(t['blocking']) and r['title'].strip().casefold()==t['title'].strip().casefold()),None)
        if existing:continue
        tid=digest([oid,analysis.get('context_hash'),t])
        con.execute('INSERT OR IGNORE INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)',(tid,oid,analysis.get('context_hash',''),t['title'],t['owner'],t['reason'],json.dumps(refs),int(t['blocking']),'pending',now))
    for signal in (analysis.get('commercial_plan') or {}).get('signal_decisions',[]):
        state='review_failed' if analysis.get('review_failed') else 'assessed'
        con.execute('UPDATE commercial_signals SET investigation_status=?,disposition=?,next_action=?,assessment_context=?,updated_at=? WHERE id=? AND opportunity_id=?',(state,signal['disposition'],signal['reason'],analysis['context_hash'],now,signal['signal_id'],oid))


def refresh_message_signals(con,oid,now):
    """Reproducible mention/request candidates, never assertions of need or consent.

    Conversations are separate simulated evidence, dated by the message clock rather
    than backdated into the case-study CSV period. Resolutions are judged by the agent.
    """
    import re
    row=con.execute('SELECT evidence FROM opportunities WHERE id=?',(oid,)).fetchone()
    if not row:return
    e=json.loads(row['evidence']);owned={p['sku'] for p in e.get('products',[]) if p.get('current_packs_or_sessions',0)>0 or p.get('prior_packs_or_sessions',0)>0}
    saved=con.execute('SELECT value FROM controls WHERE name=?',('purchased_skus:'+oid,)).fetchone()
    if saved:owned.update(json.loads(saved['value']))
    con.execute("UPDATE commercial_signals SET active=0 WHERE opportunity_id=? AND trigger_key LIKE 'message:%'",(oid,))
    for m in con.execute("SELECT id,body,created_at FROM messages WHERE opportunity_id=? AND direction='inbound'",(oid,)):
        text=m['body'].lower();categories=[]
        if re.search(r'\b(training|train|procurement|retired|purchasing contact|low light|funding)\b',text):categories.append(('purchasing_obstacle','mention'))
        if re.search(r'\b(complaint|complained|return|refund|credit|cancel|damaged|not working|unhappy)\b',text):categories.append(('churn_prevention','mention'))
        if re.search(r'\b(interested|need|would like|tell me|can you|could you)\b',text):
            for word,sku in [('mailroom','CL-MAIL50'),('fentanyl','CL-FS10'),('multi-panel','CL-MP10')]:
                if word in text and sku not in owned:categories.append(('cross_sell',sku))
        for category,key in categories:
            trigger='message:'+m['id']+':'+key;sid=digest([oid,category,trigger])[:28]
            evidence=json.dumps({'basis':'Simulated customer statement candidate; verify meaning, current relevance and negation','message_ref':'message:'+m['id'],'quote':m['body'],'created_at':m['created_at'],'simulated':True,'sku':key if category=='cross_sell' else None},sort_keys=True)
            con.execute("""INSERT INTO commercial_signals VALUES(?,?,?,?,?,NULL,1,'pending',NULL,NULL,NULL,?)
             ON CONFLICT(id) DO UPDATE SET active=1,evidence=excluded.evidence,updated_at=excluded.updated_at""",(sid,oid,category,trigger,evidence,now))
