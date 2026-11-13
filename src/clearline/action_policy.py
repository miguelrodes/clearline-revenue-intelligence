"""Execution boundaries only. Commercial strategy remains the model's responsibility."""
import json
from .data import digest
SOFT_HOLDS={'known_distributor_channel','open_orders_require_review','undated_history','possible_missing_state_alias'}
SAFE_SCOPES={'clarification','support','order_status','channel_support'}

def decode(x):return json.loads(x) if isinstance(x,str) else x

def proposal_fingerprint(a):return digest({k:a.get(k) for k in ('subject','body','action_scope','context_hash','evidence_hash')})

def permitted(opp,analysis,policy='normal',draft=None):
    o=dict(opp);a=decode(analysis) or {};holds=set(decode(o['holds']))
    if policy=='stop':return False
    if holds-SOFT_HOLDS:return False
    if not holds and policy=='normal':return True
    # Warnings are never removed. Only a reviewed, narrow proposal can proceed with them.
    quality=a.get('quality') or {}
    if not quality.get('passed') or quality.get('proposal_hash')!=proposal_fingerprint(a):return False
    if draft and any(dict(draft)[k]!=a.get(k) for k in ('subject','body')):return False
    if a.get('action_scope') not in SAFE_SCOPES:return False
    if ('known_distributor_channel' in holds or policy=='channel_review') and a.get('action_scope') not in {'channel_support','support'}:return False
    return True
