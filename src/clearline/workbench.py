"""Read models and exact-version decisions for the two-section sales interface."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from .store import STOPPED_STATUSES, utcnow
from .reporting import opportunities, valid_draft, primary_opportunity

TITLES={'support':'Address training and product-support needs','order_status':'Clarify existing orders','channel_support':'Support customers through their current buying route','inactivity':'Follow up with inactive customers','purchasing_decline':'Discuss reduced purchasing',
        'product_decline':'Follow up on product declines','channel_review':'Confirm the purchasing route','other':'Reconnect with customers'}


def ready_messages(store):
    rows=[]
    revisions={}
    for j in store.rows("SELECT id,opportunity_id,status,error FROM jobs WHERE kind='revise_draft' ORDER BY created_at,rowid"):
        revisions[j['opportunity_id']]={k:j[k] for k in ('id','status','error')}
    for d in store.rows("SELECT d.* FROM drafts d WHERE d.status='awaiting_approval' AND d.version=(SELECT MAX(x.version) FROM drafts x WHERE x.opportunity_id=d.opportunity_id)"):
        from .draft_revision import manual_reviewable
        if not valid_draft(store,d) and not manual_reviewable(store,d):continue
        o=store.opportunity(d['opportunity_id'])
        if o['status']!='awaiting_approval':continue
        # A pending delivery or a delivered copy cannot become a second action.
        if store.rows('SELECT 1 FROM outbox WHERE draft_id=?',(d['id'],)):continue
        excluded=store.rows('SELECT exclusion FROM campaign_accounts WHERE opportunity_id=?',(o['id'],))
        if excluded and all(m['exclusion'] for m in excluded) and not json.loads(d['analysis']).get('engine_version'):continue
        a=json.loads(d['analysis']);signals=[s['type'] for s in o['evidence'].get('signals',[])]
        origin=a.get('outreach_kind') or ('followup' if store.rows('SELECT 1 FROM outbox WHERE opportunity_id=?',(o['id'],)) else 'initial')
        key=origin if origin!='initial' else primary_opportunity(signals)
        if origin=='initial' and a.get('engine_version') and a.get('action_scope') in ('support','order_status','channel_support'):key=a['action_scope']
        if o['workflow']=='prospecting':key='prospect_'+key
        rows.append({'id':o['id'],'account_key':o['account_key'],'name':o['name'],'state':o['state'],'workflow':o['workflow'],
                     'decline_cents':o['decline_cents'],'products':[p['sku'] for p in o['evidence'].get('products',[])],
                     'strategy':a.get('strategy','personalized outreach'),'recommended_action':a.get('recommended_action','Review the prepared email.'),
                     'group_key':key,'revision':revisions.get(o['id']),'revision_note':a.get('revision_note'),'draft':{**d,'analysis':a,'snapshot_hash':store.draft_hash(d),'can_review':True}})
    return rows


def work_groups(store,now=None,workflow=None):
    now=now or utcnow();groups=[];messages=[m for m in ready_messages(store) if workflow is None or m['workflow']==workflow]
    accounts=opportunities(store);real=opportunities(store,'prospecting') if workflow is None else [];all_accounts={a['id']:a for a in accounts+real}
    def add(key,title,kind,members,why,button,rank,status='ready',amount=True,**extra):
        if not members:return
        unique={m['id']:m for m in members if m.get('id')}
        value=sum(max(0,m.get('decline_cents',0)) for m in unique.values()) if amount and all(m.get('workflow','recovery')=='recovery' and not m.get('account_key','').startswith('DISTRIBUTOR|') for m in unique.values()) else None
        groups.append({'id':key,'title':title,'kind':kind,'members':members,'accounts':len(unique),
                       'tasks':len(members),'why':why,'button_label':button,'rank':rank,'status':status,
                       'historical_decline_cents':value,'financial_cents':value,'financial_label':'Comparable-period purchasing decline','href':'/actions?'+urlencode({'group':key}),**extra})
    for key in dict.fromkeys(m['group_key'] for m in messages):
        ms=[m for m in messages if m['group_key']==key];reply='reply' in key;follow='followup' in key
        title='Respond to customer replies' if reply else 'Send prepared follow-ups' if follow else TITLES.get(key,'Contact real SwabTek prospects' if key.startswith('prospect_') else 'Review prepared outreach')
        if key=='inactivity':title=f'Reconnect with {len(ms)} inactive customers'
        elif key=='purchasing_decline':title=f'Restore purchasing with {len(ms)} customers buying less'
        elif key=='product_decline':title=f'Explore product needs with {len(ms)} customers'
        why={'inactivity':'Identified purchases have stopped for these customers. Personalized check-ins are prepared to confirm their current needs and buying route.',
             'purchasing_decline':'These customers are buying less than before. Personalized emails are prepared to ask what changed and whether their current supply needs are being met.',
             'product_decline':'Purchases of specific products have fallen. Personalized emails are prepared to ask whether product needs or purchasing arrangements changed.',
             'other':'The saved account reviews identified a reason to reconnect. Personalized emails are prepared around each customer’s history and outstanding questions.',
             'reply':'Customers have responded. The agents have prepared replies addressing their recorded requests.',
             'followup':'The follow-up date has arrived without a recorded response. A short follow-up is prepared for review.'}.get(key,'The personalized emails are written. Review them together and choose which ones to approve.')
        add('messages:'+key,title,'messages',ms,why,'Review and approve emails',0 if reply else 1)
    from .briefing import operational_queue
    add('contacts','Find the right purchasing contacts','contacts',operational_queue(store,'contacts',accounts),
        'The agents have prepared recovery recommendations for these customers. Confirm who handles purchasing so outreach can move forward.','Review contacts',2,status='needs_information')
    from .review_checks import review_batches
    checks=review_batches(store,accounts)
    for g in checks['groups']:
        add('check:'+g['id'],g['title'],'check',g['members'],g['description'],'Review request',3+g['effort']/10,status='needs_information',amount=False,check_key=g['id'],team=g['team'],financial_cents=g['historical_decline_cents'],financial_label='Historical purchasing decline associated with these records; identity and channel checks remain open')
    pending=store.rows("SELECT j.*,o.name,o.workflow FROM jobs j LEFT JOIN opportunities o ON o.id=j.opportunity_id WHERE j.kind!='revenue_brief' AND j.status IN ('queued','running','failed','blocked_config') ORDER BY j.due_at,j.id")
    if workflow:pending=[j for j in pending if j['workflow'] in (None,workflow)]
    for key,ms in [('failed',[j for j in pending if j['status'] in ('failed','blocked_config')]),
                   ('followups',[j for j in pending if j['kind']=='followup' and j['opportunity_id'] in all_accounts and all_accounts[j['opportunity_id']]['status']=='awaiting_response'])]:
        members=[{'id':j['opportunity_id'] or j['id'],'name':j['name'] or 'Portfolio update','job_id':j['id'],'kind':j['kind'], 'status':j['status'],'due_at':j['due_at'],'error':j['error'],'workflow':j['workflow'] or 'system',
                  'decline_cents':all_accounts.get(j['opportunity_id'],{}).get('decline_cents',0)} for j in ms]
        due=any(m['due_at']<=now for m in members)
        add(key,'Restart checks that could not finish' if key=='failed' else 'Upcoming follow-ups','jobs',members,
            'Some work could not finish. Check the reason before retrying.' if key=='failed' else 'The agents will prepare these follow-ups when they are due. Each email will still need your approval.',
            'Review tasks',0 if key=='failed' or due else 4,status='needs_attention' if key=='failed' or due else 'scheduled',amount=False,due_now=due)
    unassessed=[a for a in operational_queue(store,'unassessed',accounts) if a['signals']]
    add('investigate','Review customers awaiting investigation','accounts',unassessed,'The agents still need to review these purchasing changes.','Review customers',3,status='needs_information')
    add('real_questions','Review real-prospect questions','accounts',[a for a in real if a['status']=='agent_held'],'The research or response review found a question that needs your decision.','Review prospect',2,status='needs_information',amount=False)
    tasks=store.rows("SELECT t.*,o.name,o.workflow FROM commercial_tasks t JOIN opportunities o ON o.id=t.opportunity_id WHERE t.status='pending' ORDER BY t.created_at")
    members=[{'id':t['opportunity_id'],'name':t['name'],'workflow':t['workflow'],'recommended_action':t['title'],'status':'needs_information','task_id':t['id']} for t in tasks if workflow is None or t['workflow']==workflow]
    add('conversation_tasks','Resolve customer requests','accounts',members,'These customers have replied. Review the suggested next step before continuing outreach.','Review customer requests',0,status='needs_information',amount=False)
    verification=store.rows("SELECT t.*,o.name,o.workflow,o.account_key,o.decline_cents FROM investigation_tasks t JOIN opportunities o ON o.id=t.opportunity_id WHERE t.status='pending' AND o.active=1 ORDER BY t.blocking DESC,o.decline_cents DESC")
    # Presentation groups use only existing pending work. Dormant prerequisites
    # stay on the account, but no-action/monitoring decisions are not a daily to-do.
    import re
    buckets={}
    for t in verification:
        if workflow is not None and t['workflow']!=workflow:continue
        account=all_accounts.get(t['opportunity_id'],{})
        current=bool(account.get('engine_version'))
        if current and account.get('status') in {'no_action','monitor','defer'}:continue
        title=t['title'].lower()
        key=('orders' if re.search(r'\b(order\w*|invoice\w*|fulfil\w*|ship\w*|credit\w*|refund\w*|cancel\w*)\b',title) else
             'contacts' if re.search(r'contact|recipient|authoriz|identity|match|mapping|route|relationship',title) else
             'needs' if re.search(r'train|product|need|interest|procure|budget',title) else 'records') if current else 'legacy'
        buckets.setdefault(key,[]).append({'id':t['opportunity_id'],'account_key':t['account_key'],'name':t['name'],'workflow':t['workflow'],'decline_cents':t['decline_cents'],
              'recommended_action':t['title']+' — '+t['reason'],'owner':t['owner'],'task_id':t['id'],'blocking':bool(t['blocking'])})
    definitions={
        'orders':('Check open orders and credits','The agents identified specific order or credit records to check. Ask the named internal owner for the missing status or explanation, then record the finding on the customer.','Review order and credit checks',1),
        'contacts':('Confirm purchasing contacts and buying routes','The agents found a potential commercial reason to act, but the contact or relationship is unverified. Confirm the existing purchasing contact and permitted route before outreach.','Review contact checks',2),
        'needs':('Confirm training and product needs','The records mention a possible training, product or purchasing need. Check the existing notes with the named owner and record whether it is still relevant.','Review customer needs',2),
        'records':('Complete the remaining account checks','The agents have identified specific missing facts. Review each saved question and record a supported answer; do not contact customers just to fill these gaps.','Review account checks',3),
        'legacy':('Provide the missing business information','The agents have checked the available records. These specific questions need a person’s confirmation; each customer includes the requested next step.','Review agent findings',2),
    }
    for key,members in buckets.items():
        title,why,button,rank=definitions[key]
        add('verification_tasks' if key=='legacy' else 'investigation:'+key,title,'accounts',members,why,button,rank,status='needs_information')
    # Replies without a finished draft remain visible, including held/real-prospect cases.
    replies=[a for a in accounts+real if a['status']=='replied']
    add('replies_pending','Customer replies being reviewed','accounts',replies,'A response was recorded. The agent is preparing a recommendation; review any unresolved questions here.','Review replies',0,status='preparing',amount=False)
    for g in groups:
        g['urgency']=('Earliest scheduled follow-up: '+min(m['due_at'] for m in g['members'] if m.get('due_at'))) if g['id']=='followups' else None
        if g['id']=='check:orders':
            g['title']='Clarify pending orders before restarting sales outreach'
            g['why']='Open orders may explain the purchasing gap. A single request with the order references is ready for your orders team.'
            g['button_label']='Review outstanding orders'
        elif g['id']=='check:channel':g['title']='Review existing purchasing relationships'
        elif g['id']=='check:identity':g['title']='Resolve customer matches so recovery outreach reaches the right buyer'
        elif g['id']=='check:dates':g['title']='Recover missing purchase dates to identify who needs a follow-up'
    confidence={'identity':.2,'channel':.4,'dates':.6,'orders':1.0}
    groups.sort(key=lambda g:(int(g['rank']),-(g['financial_cents'] or 0)*confidence.get(g.get('check_key'),1),g['rank'],g['id']))
    return {'groups':groups,'checks':{k:checks[k] for k in ('priority_records','background_records')},'counts':{'ready_messages':len(messages),'groups':len(groups)}}


def decide_messages(store,group_id,snapshots,approve):
    if not snapshots or len({s['draft_id'] for s in snapshots})!=len(snapshots):raise ValueError('Select distinct saved messages')
    with store.connect(write=True) as con:
        # The write lock prevents edits/approvals between validation and commit.
        eligible={m['draft']['id']:m for m in ready_messages(store) if 'messages:'+m['group_key']==group_id}
        for snap in snapshots:
            m=eligible.get(snap['draft_id'])
            if not m or m['draft']['snapshot_hash']!=snap['snapshot_hash']:raise ValueError('A selected email changed or is no longer eligible. Reload and review it again.')
        for snap in snapshots:store._decide(con,snap['draft_id'],approve)
        # Keep saved campaigns consistent after approving only a subset through a work group.
        for c in con.execute('SELECT id FROM campaigns').fetchall():
            states=con.execute("SELECT d.status FROM campaign_accounts ca JOIN drafts d ON d.opportunity_id=ca.opportunity_id WHERE ca.campaign_id=? AND ca.exclusion IS NULL AND d.version=(SELECT MAX(x.version) FROM drafts x WHERE x.opportunity_id=d.opportunity_id)",(c['id'],)).fetchall()
            if states and all(x['status'] in ('approved','simulated','rejected','cancelled') for x in states):
                con.execute('UPDATE campaigns SET status=? WHERE id=?',('rejected' if all(x['status']=='rejected' for x in states) else 'approved',c['id']))
        store.event('group_human_decision',{'group_id':group_id,'draft_ids':[s['draft_id'] for s in snapshots],'approve':approve},con=con)


def recovery_performance(store,workflow='recovery'):
    outbox=store.rows('SELECT b.*,o.name FROM outbox b JOIN opportunities o ON o.id=b.opportunity_id WHERE o.workflow=? ORDER BY b.created_at,b.id',(workflow,))
    outcomes=store.rows('SELECT x.*,o.name FROM outcomes x JOIN opportunities o ON o.id=x.opportunity_id WHERE o.workflow=? ORDER BY x.created_at,x.id',(workflow,))
    first={};by_id={b['id']:b for b in outbox}
    events=[];linked=[];unlinked=0;seen_refs=set()
    for b in outbox:
        if b['opportunity_id'] not in first:
            first[b['opportunity_id']]=b;events.append({'at':b['created_at'],'kind':'contact','id':b['opportunity_id'],'amount':0})
    links={x['outcome_id']:x['outbox_id'] for x in store.rows('SELECT * FROM outcome_outreach')}
    for o in outcomes:
        previous=[b for b in outbox if b['opportunity_id']==o['opportunity_id'] and b['created_at']<=o['created_at']]
        b=by_id.get(links[o['id']]) if o['id'] in links else (previous[-1] if previous else None)
        if not b or o['provenance']!='manual_demo_input':unlinked+=1;continue
        key=(o['opportunity_id'],o['kind'],o.get('reference'))
        if o['kind'] in ('order','credit') and key in seen_refs:continue
        seen_refs.add(key)
        amount=(o.get('amount_cents') or 0)*(-1 if o['kind']=='credit' else 1)
        linked.append({**o,'outbox_id':b['id'],'outreach_at':b['created_at'],'net_cents':amount if o['kind'] in ('order','credit') else None})
        events.append({'at':o['created_at'],'kind':o['kind'],'id':o['opportunity_id'],'amount':amount})
    contacted=set();responded=set();purchased=set();net=0;series={}
    for e in sorted(events,key=lambda e:e['at']):
        if e['kind']=='contact':contacted.add(e['id'])
        elif e['kind']=='reply':responded.add(e['id'])
        elif e['kind']=='order':purchased.add(e['id']);net+=e['amount']
        elif e['kind']=='credit':net+=e['amount']
        day=datetime.fromisoformat(e['at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        series[day]={'date':day,'contacted':len(contacted),'responded':len(responded),'purchased':len(purchased),'net_cents':net}
    return {'workflow':workflow,'simulated':{'contacted':len(contacted),'responded':len(responded),'purchased':len(purchased),'net_cents':net,'series':list(series.values())},
            'verified':None,'incremental_cents':None,'outcomes':linked,'unlinked_outcomes':unlinked,
            'contacted_accounts':[{'id':b['opportunity_id'],'name':b['name']} for b in first.values()],
            'method':'Distinct customers are counted after a recorded simulated send. Orders and credits must follow outreach; order amounts minus credits give observed net sales. All manual outcomes are simulated. Subsequent sales do not establish causation. No baseline or comparison group supports incremental recovery.'}


def refresh_portfolio(store):
    with store.connect(write=True) as con:
        existing=con.execute("SELECT id FROM jobs WHERE kind='scan' AND status IN ('queued','running') ORDER BY created_at LIMIT 1").fetchone()
        if existing:return existing['id']
        return store._enqueue(con,'scan',{'analysis_limit':-1,'policy':{'inactivity_days':90,'decline_fraction':.25}})
