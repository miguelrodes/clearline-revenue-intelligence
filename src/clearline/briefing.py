"""Trusted operational facts and executable destinations, separate from AI prioritization.

The model selects and orders factual summary clauses, actions and supported reasons.
It cannot author metrics, URLs, forecasts, customer responses or executable code.
"""
import json
from collections import Counter
from urllib.parse import urlencode
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated
from .data import digest
from .store import STOPPED_STATUSES, utcnow

VERSION = 2
INVESTIGATIONS = ('analyze', 'prepare', 'prospect_research', 'prospect_qualify')


def operational_queue(store, queue, accounts=None):
    from .reporting import opportunities, valid_draft
    accounts = opportunities(store) if accounts is None else accounts
    contacted = {r['opportunity_id'] for r in store.rows('SELECT DISTINCT opportunity_id FROM outbox UNION SELECT opportunity_id FROM outcomes')}
    busy = {r['opportunity_id'] for r in store.rows("SELECT opportunity_id FROM jobs WHERE status IN ('queued','running') AND kind IN ('analyze','prepare')")}
    eligible = [a for a in accounts if a['status'] not in STOPPED_STATUSES | {'approved','awaiting_response'} and a['id'] not in contacted]
    if queue == 'contacts':
        result = [a for a in eligible if a['status']=='needs_contact' and a['assessment']=='pursue' and not a['holds']]
    elif queue == 'unassessed':
        result = [a for a in eligible if not a['assessment'] and a['id'] not in busy]
    elif queue == 'held':
        result = [a for a in eligible if a['holds'] or a['status']=='agent_held']
    elif queue == 'approvals':
        valid = {d['opportunity_id'] for d in store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'") if valid_draft(store,d)}
        result = [a for a in eligible if a['status']=='awaiting_approval' and a['id'] in valid]
    else:
        raise ValueError('Unknown operational queue')
    return sorted(result, key=lambda a: (bool(a['holds']), -a['decline_cents'], a['id']))


def snapshot(store):
    from .workbench import work_groups
    work=work_groups(store,workflow="recovery")
    actions=[];facts={}
    # Read-only context: reuse saved amounts and correspondence, never infer a sale.
    sent={}
    for row in store.rows('SELECT opportunity_id,subject,created_at FROM outbox ORDER BY created_at,id'):
        sent[row['opportunity_id']]=row
    from .review_checks import CHECKS
    for g in work['groups']:
        # Future scheduled work is secondary, unless nothing currently needs a decision.
        actions.append({k:g[k] for k in ('id','title','href','accounts','historical_decline_cents','button_label','rank','status','financial_cents','financial_label','urgency')} |
                       {'account_ids':[m['id'] for m in g['members']],
                        'scope_label':f"{g['tasks']} {('email' if g['tasks']==1 else 'emails') if g['kind']=='messages' else 'customer records' if g['kind']=='check' else 'tasks'}",
                        'reasons':{'next':g['why']},'members_state':[{'id':m['id'],'draft':m.get('draft',{}).get('snapshot_hash'),'status':m.get('status'),'due_at':m.get('due_at'),'evidence_hash':m.get('evidence_hash'),'recommendation':m.get('recommended_action')} for m in g['members']]})
        members=[]
        for m in g['members']:
            previous=sent.get(m['id'],{})
            task=('Review the prepared email and choose whether to approve it.' if g['kind']=='messages' else
                  CHECKS[g['check_key']]['question'] if g.get('check_key') in CHECKS else
                  'Review the scheduled follow-up to the previous email; a draft will need approval when ready.' if g['id']=='followups' else
                  m.get('recommended_action') or g['why'])
            members.append({'id':m['id'],'name':m['name'],
                            'href':'/activity?status=errors' if m.get('workflow')=='system' else '/accounts/'+m['id']+'?tab=outreach',
                            'task':task,'historical_decline_cents':m.get('decline_cents'),
                            'due_at':m.get('due_at') if g['id']=='followups' else None,
                            'subject':previous.get('subject') if g['id']=='followups' else m.get('draft',{}).get('subject'),
                            'last_sent_at':previous.get('created_at') if g['id']=='followups' else None,
                            'commercial_context':{k:v for k,v in m.get('draft',{}).get('analysis',{}).items() if k in ('intent','facts','products','recommended_action','personalized_context')}})
        actions[-1]['members']=members
        actions[-1]['team']=g.get('team')
        actions[-1]['workflow_instructions']=(
            'Open Review request, copy the prepared request or download its customer CSV, and share it with the named team outside this application. This request has no approval or sending control. After source records are corrected, refresh portfolio intelligence; copying does not resolve the checks.' if g['kind']=='check' else
            'Open the email group, review or edit saved drafts, select messages, and approve simulated sending. These are ready for that review; do not add new verification requirements.' if g['kind']=='messages' else
            'Review the saved schedule and prior email topic. Agents prepare follow-ups when due; drafts require approval before simulated sending.' if g['id']=='followups' else g['why'])
        if g['id']=='followups':
            names=list(dict.fromkeys(m['name'] for m in members))
            actions[-1]['title']='Follow up with '+(', '.join(names) if len(names)<=2 else names[0]+f' and {len(names)-1} other customers')
            actions[-1]['button_label']='Review follow-ups'
            actions[-1]['reasons']['next']='These customers have no recorded response to their previous outreach. Review the saved email topics and scheduled dates below; each follow-up will need approval once drafted.'

    ranked=actions
    for position,a in enumerate(ranked):
        a['recommended_order']=position
        dates=[m['due_at'] for m in a['members_state'] if m.get('due_at')] if a['id']=='followups' else []
        a['earliest_due_at']=min(dates) if dates else None
        a['time_priority']=(0 if a['earliest_due_at'] and a['earliest_due_at']<=utcnow() or a['id'].startswith('messages:followup') else 1 if a['rank']==0 else 2 if dates else 3)
    if work['counts']['ready_messages']:facts['ready']=f"You have {work['counts']['ready_messages']} prepared {'email' if work['counts']['ready_messages']==1 else 'emails'} to review."
    if any(g['id']=='replies_pending' for g in work['groups']):facts['responses']='The agents are reviewing recorded customer replies.'
    if any(g['id']=='contacts' for g in work['groups']):facts['contacts']='Some promising customers still need a purchasing contact.'
    if work['checks']['priority_records']:facts['checks']='Requests for missing customer information are prepared for your team.'
    if not facts:facts['clear']='No decisions are waiting. Scheduled work will continue while the agents are running.'
    jobs=store.rows("SELECT id,kind,opportunity_id,status,due_at FROM jobs WHERE status IN ('queued','running','failed','blocked_config') AND kind!='revenue_brief' ORDER BY id")
    from .signal_views import signal_context
    return {'version':10,'signals':signal_context(store),'actions':ranked,'facts':facts,'record_checks':work['checks'],'execution':jobs,
            'limitations':['Historical decline is not a recovery forecast. No incremental-revenue estimate is supported.',
                           'Clearline identities are fictional. Real SwabTek prospects and all simulated communications remain distinct.',
                           'Open order age does not establish overdue status; expected fulfillment dates are unavailable.']}


class Recommendation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str
    reason_id: str
    description: str | None = Field(default=None,max_length=650)


class SignalAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    advice: str = Field(max_length=500)


class PriorityPoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str
    title: str | None = Field(default=None,min_length=1,max_length=40)
    text: str = Field(min_length=1,max_length=600)


def priority_points(points, catalog):
    """Bind AI-written priority explanations to exact action counts and amounts."""
    import re
    from decimal import Decimal, ROUND_HALF_UP
    ids=[p.action_id for p in points]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(catalog):
        raise ValueError('Priority bullets must cite distinct available actions')
    if not min(3,len(catalog))<=len(points)<=5:
        raise ValueError('Use three to five priorities, or fewer when fewer actions exist')
    rendered=[]
    for point in points:
        action=catalog[point.action_id]
        values={'customers':str(action['accounts'])}
        if action['accounts']==1 and action.get('members'):
            values['customer']=action['members'][0]['name']
        cents=action.get('financial_cents')
        if cents is None:cents=action.get('historical_decline_cents')
        if cents is not None and cents>0:
            dollars=(Decimal(cents)/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
            values['historical_decline']=f'${dollars:,}'
        tokens=re.findall(r'\{([^{}]+)\}',point.text)
        prose=re.sub(r'\{[^{}]+\}','',point.text)
        if not set(tokens)<=set(values) or '{' in prose or '}' in prose:
            raise ValueError('Priority bullet references an unavailable fact')
        if not any(t in tokens for t in ('customers','customer')):
            raise ValueError('Priority bullet must identify its customer or group count')
        # Legacy saved briefs remain readable; compact constraints apply to titled briefs.
        if point.title and (len(point.title.split())>4 or re.search(r'[0-9$€£{}\n]|https?://',point.title)):
            raise ValueError('Priority titles must be short labels without invented metrics')
        if re.search(r'[0-9$€£]|https?://|guarantee|definitely|overdue order',prose,re.I) or len(point.text.split())>(16 if point.title else 65):
            raise ValueError('Priority bullets must fit one concise line, use bound facts, and avoid unsupported urgency or promises')
        if 'historical_decline' in tokens and 'historical' not in prose.lower():
            raise ValueError('Historical decline must not be presented as forecast revenue or order value')
        rendered.append(re.sub(r'\{([^{}]+)\}',lambda m:values[m.group(1)],point.text))
    return rendered


class OperationalBrief(BaseModel):
    model_config = ConfigDict(extra='forbid')
    signal_advice: list[SignalAdvice] = Field(default_factory=list,max_length=4)
    priorities: list[PriorityPoint] = Field(default_factory=list,max_length=5)
    summary: str | None = Field(default=None,max_length=650)
    summary_points: list[Annotated[str, Field(min_length=1,max_length=500)]] = Field(default_factory=list,max_length=4)
    summary_fact_ids: list[str] = Field(min_length=1,max_length=3)
    recommendations: list[Recommendation]


def render_brief(output, state):
    output = OperationalBrief.model_validate(output)
    catalog = {a['id']:a for a in state['actions']}
    ids = [r.action_id for r in output.recommendations]
    if len(ids)!=len(set(ids)) or len(output.summary_fact_ids)!=len(set(output.summary_fact_ids)):
        raise ValueError('Brief repeats a fact or action')
    if ids!=list(catalog):
        raise ValueError('Brief must preserve the deterministic priority order')
    if not set(output.summary_fact_ids)<=set(state['facts']):
        raise ValueError('Brief cites an unsupported fact')
    advice_keys=[a.key for a in output.signal_advice]
    if advice_keys and (len(advice_keys)!=len(set(advice_keys)) or set(advice_keys)!={s['key'] for s in state.get('signals',[])}):
        raise ValueError('Signal advice must cover exactly the supplied signals')
    import re
    if any(re.search(r'[0-9$€£]|https?://|guarantee|definitely|overdue',a.advice,re.I) for a in output.signal_advice):
        raise ValueError('Signal advice cannot invent quantities or certainty')
    if output.summary:
        sentences=[part for part in re.split(r'[.!?]+(?:\s|$)',output.summary.strip()) if part.strip()]
        if not 2<=len(sentences)<=3 or re.search(r'[0-9$€£]|https?://|guarantee|definitely|overdue order',output.summary,re.I):
            raise ValueError('Summary must contain two or three grounded sentences without metrics or promises')
    if output.summary_points:
        if len(output.summary_points)<2 or any(re.search(r'[0-9$€£]|https?://|guarantee|definitely|overdue order',p,re.I) or len(p.split())>85 for p in output.summary_points):
            raise ValueError('Briefing bullets must be grounded without invented quantities or promises')
    actions = []
    for r in output.recommendations:
        if r.action_id not in catalog or r.reason_id not in catalog[r.action_id]['reasons']:
            raise ValueError('Brief recommends an unsupported action or reason')
        a = catalog[r.action_id]
        wording=r.description or a['reasons'][r.reason_id]
        import re
        if r.description and (re.search(r'[0-9$€£]|https?://|guarantee|definitely|overdue order',wording,re.I) or len(wording.split())>100):
            raise ValueError('Brief prose must not add quantities, promises, URLs or unsupported urgency')
        actions.append({k:a[k] for k in ('id','title','href','accounts','historical_decline_cents')} | {'why':wording,'button_label':a.get('button_label','Open'),'scope_label':a.get('scope_label'),'financial_cents':a.get('financial_cents'),'financial_label':a.get('financial_label'),'urgency':a.get('urgency'),'recommended_order':a.get('recommended_order',len(actions)),'earliest_due_at':a.get('earliest_due_at'),'time_priority':a.get('time_priority',3),'members':a.get('members',[]),'team':a.get('team')})
    points=priority_points(output.priorities,catalog) if output.priorities else output.summary_points
    priority_items=[{'action_id':p.action_id,'title':p.title or catalog[p.action_id]['title'],'text':text} for p,text in zip(output.priorities,points)]
    return {'summary':' '.join(points) or output.summary or ' '.join(state['facts'][f] for f in output.summary_fact_ids),'summary_points':points or ([output.summary] if output.summary else [state['facts'][f] for f in output.summary_fact_ids]),'priority_items':priority_items,'actions':actions,'signal_advice':[a.model_dump() for a in output.signal_advice]}


def current_brief(store, state=None):
    state = snapshot(store) if state is None else state
    source_hash = digest(state)
    saved = store.rows('SELECT * FROM operational_briefs WHERE source_hash=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(source_hash,))
    jobs = store.rows("SELECT id,status,error FROM jobs WHERE kind='revenue_brief' AND json_extract(payload,'$.source_hash')=? ORDER BY created_at DESC,rowid DESC LIMIT 1",(source_hash,))
    previous = store.rows('SELECT created_at FROM operational_briefs ORDER BY created_at DESC,rowid DESC LIMIT 1')
    result = {'brief':None,'stale':bool(previous and not saved),'last_generated_at':previous[0]['created_at'] if previous else None,'job':jobs[0] if jobs else None}
    if saved:
        result['brief'] = {**render_brief(json.loads(saved[0]['body']),state),'created_at':saved[0]['created_at'],'source_hash':source_hash}
    return result
