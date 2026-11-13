"""Behavioral boundaries for evidence-aware recovery, using isolated state only."""
import json
import pytest
from clearline.action_policy import proposal_fingerprint
from clearline.evidence import ENGINE_VERSION,context_hash,current_assessment
from clearline.reporting import valid_draft
from clearline.data import digest

def assessed(store,opportunity,decision,holds=(),scope='support'):
    e={**opportunity['evidence'],'holds':list(holds)}
    with store.connect(write=True) as c:
        c.execute('UPDATE opportunities SET holds=?,evidence=?,evidence_hash=? WHERE id=?',(json.dumps(list(holds)),json.dumps(e),digest(e),opportunity['id']))
    store.queue_analysis(opportunity['id'],investigation=True);j=store.claim()
    with store.connect() as c:revision=context_hash(c,opportunity['id'])
    a={**decision,'subject':'Discuss support','body':'Would a short call to scope training for your night shift be useful?',
       'engine_version':ENGINE_VERSION,'context_hash':revision,'evidence_hash':digest(e),'action_scope':scope,
       'quality':{'passed':True},'verification_tasks':[]}
    a['quality']['proposal_hash']=proposal_fingerprint(a)
    return j,a

@pytest.mark.parametrize('hold,scope',[('known_distributor_channel','channel_support'),('open_orders_require_review','order_status'),('undated_history','clarification'),('possible_missing_state_alias','support')])
def test_reviewed_safe_action_preserves_warning_and_requires_exact_approval(store,opportunity,decision,hold,scope):
    j,a=assessed(store,opportunity,decision,[hold],scope);store.save_analysis(j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    assert store.opportunity('example')['holds']==[hold] and valid_draft(store,d)
    assert not store.rows('SELECT * FROM outbox')
    store.decide(d['id'],True);delivery=store.claim();store.deliver(delivery)
    assert len(store.rows('SELECT * FROM outbox'))==1
    store.deliver(delivery)
    assert len(store.rows('SELECT * FROM outbox'))==1

@pytest.mark.parametrize('hold,scope',[('ambiguous_identity','support'),('known_distributor_channel','recovery'),('open_orders_require_review','recovery')])
def test_unsafe_action_not_saved_even_with_positive_model_review(store,opportunity,decision,hold,scope):
    j,a=assessed(store,opportunity,decision,[hold],scope)
    with pytest.raises(ValueError):store.save_analysis(j,a)
    assert not store.rows('SELECT * FROM drafts')


def test_context_change_blocks_stale_save_and_cache(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision)
    with store.connect(write=True) as c:c.execute("INSERT INTO customer_context VALUES('example',NULL,NULL,'channel_review','now')")
    store.save_analysis(j,a)
    assert not store.rows('SELECT * FROM drafts')
    assert store.rows('SELECT status FROM jobs WHERE id=?',(j['id'],))[0]['status']=='cancelled'
    with store.connect() as c:assert not current_assessment(c,'example',a)


def test_contact_change_after_approval_blocks_delivery(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision);store.save_analysis(j,a);d=store.rows('SELECT * FROM drafts')[0];store.decide(d['id'],True)
    with store.connect(write=True) as c:c.execute("INSERT INTO customer_context VALUES('example','changed contact',NULL,'normal','now')")
    assert not valid_draft(store,d)
    with pytest.raises(ValueError):store.deliver(store.claim())
    assert not store.rows('SELECT * FROM outbox')


def test_edit_cannot_reuse_soft_hold_review(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision,['known_distributor_channel'],'channel_support');store.save_analysis(j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    new=store.revise_draft(d['id'],d['recipient'],'Bypass channel','Order directly instead.')
    with pytest.raises(ValueError):store.decide(new,True)
    assert not store.rows('SELECT * FROM approvals')


def test_engine_and_outcomes_invalidate_cache_without_generated_task_loops(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision);a['verification_tasks']=[{'title':'Confirm delivery event','owner':'Orders team','reason':'No shipment event supplied','evidence_refs':['account'],'blocking':False}]
    store.save_analysis(j,a)
    with store.connect() as c:assert current_assessment(c,'example',a)
    store.record_outcome('example','qualified','Customer supplied new information')
    with store.connect() as c:assert not current_assessment(c,'example',a)
    assert store.rows('SELECT * FROM investigation_tasks')[0]['status']=='pending'


def test_old_engine_draft_cannot_ignore_changed_context(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision);store.save_analysis(j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    saved=json.loads(d['analysis']);saved['engine_version']='recovery-previous'
    with store.connect(write=True) as c:
        c.execute('UPDATE drafts SET analysis=? WHERE id=?',(json.dumps(saved),d['id']))
        c.execute("INSERT INTO customer_context VALUES('example',NULL,NULL,'channel_review','now')")
    d=store.rows('SELECT * FROM drafts')[0]
    assert not valid_draft(store,d)
    with pytest.raises(ValueError):store.decide(d['id'],True)


def test_missing_state_warning_does_not_override_a_real_identity_conflict(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision,['possible_missing_state_alias','ambiguous_identity'],'support')
    with pytest.raises(ValueError):store.save_analysis(j,a)
    assert not store.rows('SELECT * FROM drafts')


def test_missing_state_policy_change_invalidates_only_affected_accounts(store,opportunity,decision):
    j,a=assessed(store,opportunity,decision,['possible_missing_state_alias'],'support')
    a['context_hash']='previous-policy-context'
    store.save_analysis(j,a)
    assert store.rows('SELECT status FROM jobs WHERE id=?',(j['id'],))[0]['status']=='cancelled'
    assert not store.rows('SELECT * FROM drafts')


def test_current_assessment_resolves_obsolete_initial_failure_but_preserves_followup_failure(store,opportunity,decision):
    old=store.enqueue('analyze',{'context_hash':'old','engine_version':'previous'},'example')
    follow=store.enqueue('analyze',{'context_hash':'old','engine_version':'previous','followup_of':'sent-draft'},'example')
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET status='failed',error='Historical failure' WHERE id IN (?,?)",(old,follow))
    j,a=assessed(store,opportunity,decision);store.save_analysis(j,a)
    assert store.rows('SELECT status,error FROM jobs WHERE id=?',(old,))[0]=={'status':'cancelled','error':'Historical failure'}
    assert store.rows('SELECT status FROM jobs WHERE id=?',(follow,))[0]['status']=='failed'
    assert store.rows("SELECT * FROM events WHERE kind='investigation_failure_superseded'")
