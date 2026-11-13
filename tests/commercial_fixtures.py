"""Explicit reviewed-model fixtures for transport/persistence tests, never production."""
import copy
from test_commercial import certified
from clearline.evidence import context_hash
from clearline.action_policy import proposal_fingerprint

def reviewed_fixture(store,job,decision):
    value=copy.deepcopy(decision.model_dump() if hasattr(decision,'model_dump') else decision)
    if value.get('decision')=='pursue':value=certified(store,job['opportunity_id'],value)
    else:
        value.pop('commercial_plan',None);value.pop('quality',None)
    with store.connect() as c:value['context_hash']=context_hash(c,job['opportunity_id'])
    if value.get('quality'):value['quality']['proposal_hash']=proposal_fingerprint(value)
    return value

def save_reviewed_fixture(store,job,decision):
    store.save_analysis(job,reviewed_fixture(store,job,decision))
