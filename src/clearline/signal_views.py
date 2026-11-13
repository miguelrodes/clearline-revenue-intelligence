"""Signal-scoped evidence and existing actions; opening a view never creates work."""
from collections import Counter
import json
from urllib.parse import urlencode
from .reporting import opportunities
from .operations import financial_segments

KEYS=('inactivity','partial','product_decline','direct_gap_channel_review')

def disposition(a):
    if not a['assessment']:return 'unassessed'
    if a['status']=='awaiting_approval':return 'human_decision'
    if a['status'] in ('agent_held','needs_contact'):return 'verification'
    if a['assessment'] in ('no_action','reject') or a['status'] in ('no_action','rejected','opted_out','closed','lost','deferred'):return 'no_action'
    return 'actionable'


def coverage(store):
    rows=opportunities(store);counts=Counter(disposition(a) for a in rows)
    latest={}
    for j in store.rows("SELECT opportunity_id,status FROM jobs WHERE kind IN ('analyze','prepare') ORDER BY created_at,rowid"):
        latest[j['opportunity_id']]=j['status']
    failures=[a['id'] for a in rows if not a['assessment'] and latest.get(a['id']) in ('failed','blocked_config')]
    return {'total':len(rows),'assessed':sum(bool(a['assessment']) for a in rows),
            'counts':{k:counts[k] for k in ('actionable','human_decision','verification','no_action','unassessed')},
            'failed':len(failures),'failed_ids':failures,
            'identity_caveat':'Counts refer to distinct account records after current matching, including unresolved identities.'}


def members(store,key,accounts=None):
    if key not in KEYS:raise ValueError('Unknown signal')
    return [a for a in (accounts if accounts is not None else opportunities(store)) if (a['partial_decline'] if key=='partial' else key in a['signals'])]


def signal_context(store):
    rows=opportunities(store);segments=financial_segments(store)
    return [{**s,'dispositions':dict(Counter(disposition(a) for a in members(store,s['key'],rows))),
             'recommendations':list(dict.fromkeys(a['recommended_action'] for a in members(store,s['key'],rows) if a['recommended_action']))[:5]}
            for s in segments]


def signal_detail(store,key):
    from .workbench import work_groups
    from .briefing import current_brief
    rows=members(store,key);groups=work_groups(store,workflow='recovery')['groups']
    segment=next(s for s in financial_segments(store) if s['key']==key)
    chart=[];actions=[];products={}
    for a in rows:
        e=store.opportunity(a['id'])['evidence'];skus={s.get('sku') for s in e.get('signals',[]) if s['type']=='product_decline'}
        amount=a['decline_cents']
        if key=='product_decline':
            amount=0
            for p in e.get('products',[]):
                if p['sku'] not in skus:continue
                amount+=max(0,p['prior_cents']-p['current_cents'])
                dest=products.setdefault(p['sku'],{'name':p['name'],'sku':p['sku'],'prior_cents':0,'current_cents':0,'prior_tests':0,'current_tests':0,'decline_cents':0})
                for col in ('prior_cents','current_cents','prior_tests','current_tests'):dest[col]+=p.get(col,0)
                dest['decline_cents']+=max(0,p['prior_cents']-p['current_cents'])
        else:
            gap=next((s.get('days_since_purchase') for s in e.get('signals',[]) if s['type'] in ('inactivity','direct_gap_channel_review')),None)
            channel=next((s for s in e.get('signals',[]) if s['type']=='direct_gap_channel_review'),{})
            chart.append({k:a[k] for k in ('id','name','prior_cents','current_cents','last_purchase')} | {'days_since_purchase':gap,'decline_cents':amount,
                'direct_gap_days':channel.get('days_since_direct_purchase'),'identified_gap_days':channel.get('days_since_identified_purchase'),
                'channel_evidence':('Named distributor purchases are present. Unidentified end-customer sales are not allocated to this account. ' if 'known_distributor_channel' in e.get('holds',[]) else 'Distributor purchasing is not confirmed. ')+(('CRM note: '+e['crm_notes']) if e.get('crm_notes') else '')})
        links=[]
        for g in groups:
            if any(m['id']==a['id'] for m in g['members']):links.append({'group_id':g['id'],'kind':g['kind'],'title':g['button_label'],'href':'/actions?'+urlencode({'group':g['id'],'focus':a['id'],'signal':key})})
        actions.append({'id':a['id'],'name':a['name'],'decline_cents':amount,'status':a['status'],
                        'disposition':disposition(a),'recommendation':a['recommended_action'] or 'No current assessment is available.',
                        'next_step':a['next_action'],'links':links,'account_href':'/accounts/'+a['id']})
    brief=current_brief(store)['brief'];ai=next((s['advice'] for s in (brief or {}).get('signal_advice',[]) if s['key']==key),None)
    amount=f"${segment['decline_cents']/100:,.0f}"
    noun='qualifying product-level revenue reduction' if key=='product_decline' else 'historical purchasing decline'
    return {'key':key,'segment':segment,'fact_summary':f"{segment['accounts']} account records show this signal, associated with {amount} in {noun} across January–October 2025 and 2026.",
            'ai_advice':ai,'chart':list(products.values()) if key=='product_decline' else sorted(chart,key=lambda x:-x['decline_cents']),
            'actions':actions,'groups':[{'id':g['id'],'title':g['title'],'kind':g['kind'],'accounts':sum(m['id'] in {a['id'] for a in rows} for m in g['members']),
                                      'href':'/actions?'+urlencode({'group':g['id'],'signal':key})} for g in groups if any(m['id'] in {a['id'] for a in rows} for m in g['members'])],
            'limits':'These categories overlap. Historical declines are not forecast recovery. Causes remain hypotheses until confirmed with the customer or source records.'}
