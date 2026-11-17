from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.conversations import conversation, policy
from clearline.outreach_controls import change, restriction
from clearline.reporting import valid_draft
from clearline.store import Store
from clearline.transport import SimulatedProvider


def send_fixture(store, draft):
    store.decide(draft['id'],True)
    job=store.claim()
    store.deliver(job)
    store.finish(job['id'])
    return conversation(store,draft['opportunity_id'])['messages'][0]


@pytest.mark.parametrize('action,scope',[('pause','account'),('do_not_contact','account'),('do_not_contact','recipient')])
def test_restriction_after_approval_survives_restart_and_blocks_delivery(store,draft,action,scope):
    oid=draft['opportunity_id']
    store.decide(draft['id'],True)
    job=store.claim()
    args={'reason':'Fictional permission record','scope':scope}
    if scope=='recipient':args['recipient']='buyer@example.org'
    if action=='pause':args['reconsider_on']='2026-11-01'
    change(store,oid,action,**args)
    reopened=Store(store.path)
    controls=conversation(reopened,oid)['restrictions']
    assert len(controls)==1 and controls[0]['source']=='manual_salesperson'
    assert not valid_draft(reopened,draft)
    with pytest.raises(ValueError):reopened.deliver(job)
    assert not reopened.rows('SELECT * FROM outbox')
    # Replaying a claimed delivery cannot evade the permission check even if
    # another process still has the old approved draft and running job state.
    with reopened.connect(write=True) as con:
        con.execute("UPDATE drafts SET status='approved' WHERE id=?",(draft['id'],))
        con.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
    with pytest.raises(ValueError,match='prerequisites'):reopened.deliver(job)
    with reopened.connect(write=True) as con:
        con.execute("UPDATE drafts SET status='cancelled' WHERE id=?",(draft['id'],))
        con.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job['id'],))
    assert reopened.rows('SELECT decision FROM approvals')==[{'decision':'approved'}]
    assert reopened.rows('SELECT evidence_hash FROM opportunities WHERE id=?',(oid,))[0]['evidence_hash']==draft['evidence_hash']
    if action=='pause':
        assert reopened.opportunity(oid)['status']=='outreach_paused'
        change(reopened,oid,'resume')
        assert not conversation(reopened,oid)['restrictions']
        assert reopened.rows('SELECT status FROM drafts')[0]['status']=='cancelled'
    else:
        with pytest.raises(ValueError):change(reopened,oid,'resume')


def test_recipient_request_is_bound_to_intended_person_and_immediately_suspends_reminder(store,draft,reply_decision):
    sent=send_fixture(store,draft)
    text='Please stop emailing me personally.'
    store.record_outcome('example','reply',text)
    with store.connect() as c:
        assert c.execute("SELECT status FROM jobs WHERE kind='followup'").fetchone()[0]=='cancelled'
    job=store.claim()
    assert job['kind']=='reply'
    store.save_analysis(job,{**reply_decision,'decision':'reject','intent':'opt_out','opt_out_scope':'recipient',
        'opt_out_quote':text,'subject':'','body':'','opportunity_status':'opted_out'})
    with store.connect() as c:
        blocked=restriction(c,'example','BUYER@example.org')
        assert blocked['reason']==text and blocked['message_id'] and blocked['source']=='simulated_customer_reply'
        assert not restriction(c,'example','other@example.org')
        assert policy(c,'example')=='normal'
    assert store.rows('SELECT count(*) n FROM outbox')[0]['n']==1
    assert conversation(store,'example')['messages'][1]['reply_to']==sent['id']


def test_pause_during_reply_survives_ai_and_new_evidence(store,draft,reply_decision,opportunity):
    send_fixture(store,draft)
    store.record_outcome('example','reply','Interested in training')
    job=store.claim();change(store,'example','pause',reason='The account owner requested a review')
    store.save_analysis(job,reply_decision)
    item=dict(opportunity,evidence_hash='changed')
    store.save_scan({'test_fixture':True},[item])
    assert store.opportunity('example')['status']=='outreach_paused'
    assert not store.rows("SELECT 1 FROM drafts WHERE status='awaiting_approval'")
    assert conversation(store,'example')['restrictions'][0]['kind']=='pause'
    change(store,'example','resume')
    with store.connect() as c:assert policy(c,'example')=='normal'


def test_unknown_optout_scope_needs_verified_clarification(store,draft,reply_decision):
    send_fixture(store,draft)
    store.record_outcome('example','reply','Stop sending those.')
    store.save_analysis(store.claim(),{**reply_decision,'decision':'reject','intent':'opt_out','opt_out_scope':'unclear',
        'opt_out_quote':'Stop sending those.','subject':'','body':'','opportunity_status':'opted_out'})
    ambiguous=conversation(store,'example')['restrictions'][0]
    assert ambiguous['scope']=='thread'
    change(store,'example','do_not_contact',scope='recipient',recipient='buyer@example.org',
           reason='Fictional confirmation from the individual',clarify_id=ambiguous['id'])
    with store.connect() as c:
        assert restriction(c,'example','buyer@example.org')['scope']=='recipient'
        assert not restriction(c,'example','another@example.org')


def test_request_for_named_recipient_never_suppresses_the_sender(store,draft,reply_decision):
    send_fixture(store,draft)
    text='Please stop emailing jane@example.org. I am still the buyer.'
    store.record_outcome('example','reply',text)
    store.save_analysis(store.claim(),{**reply_decision,'decision':'reject','intent':'opt_out','opt_out_scope':'recipient',
        'opt_out_recipient':'jane@example.org','opt_out_quote':text,'subject':'','body':'','opportunity_status':'opted_out'})
    with store.connect() as c:
        assert restriction(c,'example','jane@example.org')
        assert not restriction(c,'example','buyer@example.org')
        assert not restriction(c,'example','different@example.org')


def test_no_action_channel_reply_closes_task_and_prevents_direct_recovery(store,draft,reply_decision):
    send_fixture(store,draft)
    text='We order through a regional distributor.'
    store.record_outcome('example','reply',text)
    store.save_analysis(store.claim(),{**reply_decision,'decision':'hold','intent':'distributor','opportunity_status':'channel_review',
        'channel':{'route':'distributor','distributor':None,'quote':text},'subject':'','body':'','commercial_plan':{'outcome':'no_action','signal_decisions':[],'verification_tasks':[]}})
    t=conversation(store,'example')
    assert t['context']['channel']['verified'] is False and t['tasks'][0]['status']=='completed'
    assert store.opportunity('example')['status']=='no_action'
    assert not store.rows("SELECT id FROM drafts WHERE status='awaiting_approval'")


def test_no_reply_without_own_delivered_email(store,settings,opportunity,draft):
    client=TestClient(create_app(replace(settings,db_path=store.path)))
    headers={'x-clearline-client':'web'}
    oid=opportunity['id']
    with pytest.raises(ValueError,match='prior delivered'):store.record_outcome(oid,'reply','Hello')
    result=client.post(f'/api/accounts/{oid}/conversation/replies',headers=headers,
                       json={'reply_to':draft['id'],'message_id':'wrong','body':'Hello'})
    assert result.status_code==409
    assert not store.rows("SELECT id FROM jobs WHERE kind='reply'")
    sent=send_fixture(store,draft)
    with pytest.raises(ValueError,match='this account'):
        SimulatedProvider(store).ingest('different-account',sent['id'],'wrong-account','Hello')
