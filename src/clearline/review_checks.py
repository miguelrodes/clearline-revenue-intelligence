"""Batch source-data questions by the team that can answer them. Read-only.

Never clear a hold from a model's opinion or from copying/exporting a request.
"""
import csv
import io
import json
from hashlib import sha256
import pandas as pd
from .data import digest

CHECKS = {
    'orders': {'title':'Confirm pending orders', 'team':'Orders team',
        'description':'Some orders are still marked as open. Ask your orders team whether they went through.',
        'question':'For each order, confirm whether it is still open, fulfilled or cancelled, and provide the relevant dates or reference numbers.',
        'codes':{'open_orders_require_review'},'effort':1},
    'dates': {'title':'Fill in missing purchase dates', 'team':'Finance or order operations',
        'description':'These purchases have no date, so we cannot tell when the customer last bought.',
        'question':'Please supply the correct date for each undated order, using the original invoice or credit note.',
        'codes':{'undated_history'},'effort':2},
    'channel': {'title':'Check purchases through distributors', 'team':'Distributor account manager',
        'description':'Purchasing may have moved through a distributor. Review the existing relationship and the agent’s proposed channel-safe next step.',
        'question':'Distributor end-customer data is unavailable. Use existing records to confirm any channel restrictions and evaluate a neutral support or purchasing-route clarification with an existing relationship contact. Do not request sell-through data or allocate unmatched sales.',
        'codes':{'known_distributor_channel'},'effort':3},
    'identity': {'title':'Match customer names and locations', 'team':'CRM or sales operations',
        'description':'Some names or locations do not match. Ask your CRM team which records belong to the same customer.',
        'question':'Confirm the correct customer name, state and location for these records. Match aliases only when supported by a source record, and keep different institutions separate.',
        'codes':{'identity_needs_review','possible_missing_state_alias','ambiguous_identity','multiple_shipping_cities','missing_purchase_history'},'effort':4},
    'other': {'title':'Check the remaining customer questions', 'team':'Sales operations',
        'description':'The agent found a question that needs an answer before contacting these customers.',
        'question':'Please review the attached customer questions and provide the source information needed to answer them.',
        'codes':set(),'effort':5},
}


def group_keys(account):
    keys={k for k,c in CHECKS.items() if set(account['holds']) & c['codes']}
    known=set().union(*(c['codes'] for c in CHECKS.values()))
    if not keys or set(account['holds'])-known:keys.add('other')
    return keys


def review_batches(store, accounts=None):
    from .briefing import operational_queue
    held=operational_queue(store,'held',accounts)
    from .evidence import ENGINE_VERSION
    relevant=[a for a in held if a['signals'] and not a['account_key'].startswith('DISTRIBUTOR|') and a.get('engine_version')!=ENGINE_VERSION]
    groups=[]
    for key,config in CHECKS.items():
        members=[a for a in relevant if key in group_keys(a)]
        if not members:continue
        members.sort(key=lambda a:(len(group_keys(a))!=1,-a['decline_cents'],a['id']))
        view=[]
        for a in members:
            view.append({k:a[k] for k in ('id','name','state','owner','decline_cents','recommended_action','evidence_hash')} |
                        {'checks_left':[CHECKS[k]['title'] for k in CHECKS if k in group_keys(a) and k!=key],
                         'only_check':len(group_keys(a))==1})
        h=digest([{'id':a['id'],'hash':a['evidence_hash'],'holds':a['holds'],'status':a['status']} for a in members])
        groups.append({'id':key,'title':config['title'],'team':config['team'],'description':config['description'],
                       'accounts':len(members),'only_check_accounts':sum(a['only_check'] for a in view),
                       'members':view,'source_hash':h,'effort':config['effort'],
                       'historical_decline_cents':sum(max(0,a['decline_cents']) for a in members)})
    groups.sort(key=lambda g:(g['effort'],-g['only_check_accounts'],-g['historical_decline_cents']))
    return {'held_records':len(held),'priority_records':len(relevant),'background_records':len(held)-len(relevant),
            'groups':groups,'next_step':'Have the responsible team correct the source records, then run the recovery scan again. Copying a request does not clear any checks or approve outreach.'}


def batch_details(store,settings,key,signal=None,focus=None):
    groups=review_batches(store)['groups']
    group=next((g for g in groups if g['id']==key),None)
    if group is None:raise ValueError('No customers currently need this check')
    group={**group}
    if signal or focus:
        from .signal_views import members
        ids={a['id'] for a in members(store,signal)} if signal else None
        group['members']=[m for m in group['members'] if (ids is None or m['id'] in ids) and (not focus or m['id']==focus)]
        group['accounts']=len(group['members'])
        group['only_check_accounts']=sum(m['only_check'] for m in group['members'])
        if not group['members']:raise ValueError('No customers in this selection need this check')
    config=CHECKS[key]
    scans=store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
    summary=json.loads(scans[0]['summary']) if scans else {}
    source_error=None;orders=None
    try:
        from .reporting import _audited_orders
        hashes=summary['hashes']
        # Recheck even when the parsed source frame is cached.
        for name,expected in hashes.items():
            if sha256((settings.data_dir/f'{name}.csv').read_bytes()).hexdigest()!=expected:
                raise ValueError('Source files changed')
        orders=_audited_orders(str(settings.data_dir),hashes['orders'],hashes['products'])
    except (KeyError,OSError,ValueError):
        source_error='Source rows are unavailable or have changed. Run a new scan before relying on the order list.'
    records=[];members=[]
    fields=['source_row','order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','status']
    for member in group['members']:
        evidence=store.opportunity(member['id'])['evidence']
        source=[]
        if orders is not None:
            selected=orders[orders.source_row.isin(evidence.get('source_rows',[])) & (orders.date.isna() | orders.date.le(pd.Timestamp(summary['as_of'])))]
            if key=='orders':selected=selected[selected.status.eq('open')]
            if key=='dates':selected=selected[selected.date.isna()]
            source=selected[fields].to_dict(orient='records')
        order_ids=list(dict.fromkeys(str(x['order_id']) for x in source))
        aliases=evidence.get('aliases') or []
        members.append({**member,'order_ids':order_ids,'source_lines':len(source),'aliases':aliases})
        common={'account_id':member['id'],'customer':member['name'],'state':member['state'],'account_owner':member['owner'],
                'question':config['question'],'aliases':' | '.join(aliases),
                'other_checks':' | '.join(member['checks_left']),'response':'','supporting_reference':''}
        for line in source or [{}]:records.append({**common,**line})
    as_of=summary.get('as_of',settings.as_of)
    subject=f"{config['title']} — {group['accounts']} customer records"
    body=(f"Hi {config['team'].lower()},\n\n{config['question']}\n\n"
          f"The list comes from our saved export as of {as_of}; it may not reflect what happened afterwards. "
          "Please fill in the response and supporting-reference columns in the attached file and update the source records.\n\n"
          + f"There are {group['accounts']} customer records in the attached list. Order references and any other outstanding questions are included."
          + "\n\nWe will check the updated records before deciding whether to contact these customers. Thank you.")
    return {**group,'members':members,'subject':subject,'request_body':body,'records':records,'source_error':source_error,
            'source_as_of':as_of,'delivery_status':'Not sent'}


def batch_csv(detail):
    if detail['source_error']:raise ValueError(detail['source_error'])
    fields=['account_id','customer','state','account_owner','question','aliases','other_checks',
            'source_row','order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state',
            'sales_channel','sku','qty','status','response','supporting_reference']
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=fields)
    writer.writeheader()
    for record in detail['records']:
        # Shared CSVs must not turn source names or notes into spreadsheet formulas.
        row={k:("'"+str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in record.items()}
        writer.writerow(row)
    return out.getvalue()
