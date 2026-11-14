"""Shared, fail-closed execution boundaries; simulation never grants contact eligibility."""
import json
from .data import digest
SOFT_HOLDS={'known_distributor_channel','open_orders_require_review','undated_history','possible_missing_state_alias'}
SAFE_SCOPES={'clarification','support','order_status','channel_support'}

def decode(x):return json.loads(x) if isinstance(x,str) else x

def proposal_fingerprint(a):
    return digest({k:a.get(k) for k in ('subject','body','action_scope','context_hash','evidence_hash','commercial_plan','commercial_review','recipient')})

def permitted(opp,analysis,policy='normal',draft=None):
    o=dict(opp);a=decode(analysis) or {};holds=set(decode(o['holds']))
    if o.get('account_key','').startswith('DISTRIBUTOR|'):holds.discard('known_distributor_channel')
    if policy=='stop' or holds-SOFT_HOLDS:return False
    # Later-phase implementation is preserved, never exposed as recovery eligibility.
    if o.get('workflow')=='prospecting':return not holds and policy=='normal'
    if o.get('workflow')=='agency_screening':
        from .screening_agent import passes
        return (not holds and policy=='normal' and a.get('agency_engine_version')=='agency-outreach-1'
            and bool(a.get('review')) and passes(a['review'])
            and a.get('proposal_hash')==digest([a.get('subject'),a.get('body'),'simulation@example.invalid',a.get('context_hash')])
            and (not draft or all(dict(draft)[k]==a.get(k) for k in ('subject','body','recipient')))
            and a.get('recipient')=='simulation@example.invalid')
    from .evidence import ENGINE_VERSION
    if a.get('engine_version')!=ENGINE_VERSION:return False
    quality=a.get('quality') or {};plan=a.get('commercial_plan') or {}
    from .commercial_agent import review_passes
    if not a.get('commercial_review') or not review_passes(a['commercial_review']):return False
    if plan.get('outcome')!='contact' or not a.get('recipient') or plan.get('recipient')!=a['recipient']:return False
    if any(t.get('blocking') for t in a.get('verification_tasks',[])):return False
    if not quality.get('passed') or quality.get('proposal_hash')!=proposal_fingerprint(a):return False
    if draft and (any(dict(draft)[k]!=a.get(k) for k in ('subject','body')) or dict(draft)['recipient']!='simulation@example.invalid'):return False
    if holds and a.get('action_scope') not in SAFE_SCOPES:return False
    if ('known_distributor_channel' in holds or policy=='channel_review') and plan.get('route')!='distributor':return False
    return True
