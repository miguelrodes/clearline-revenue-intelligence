from commercial_fixtures import save_reviewed_fixture
import asyncio,copy,json
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.conversations import conversation
from clearline.transport import SimulatedProvider
from clearline.reply_agent import validate_reply
from clearline.worker import execute_job
from clearline.demo import initialize,reset,paths
from clearline.store import Store
from clearline.workbench import work_groups

@pytest.fixture
def sent(store,draft):
    store.decide(draft['id'],True);job=store.claim();store.deliver(job);store.finish(job['id'])
    return conversation(store,draft['opportunity_id'])['messages'][0]

def inject(store,sent,body='Can we arrange training?',key='message-1'):
    return SimulatedProvider(store).ingest(sent['opportunity_id'],sent['id'],key,body)

@pytest.mark.parametrize('intent,status,verdict,expected',[
 ('reorder','reorder_interest','pursue','awaiting_approval'),('training','support_needed','pursue','awaiting_approval'),
 ('support','support_needed','pursue','awaiting_approval'),('purchasing_contact','contact_updated','pursue','awaiting_approval'),
 ('distributor','channel_review','hold','agent_held'),('not_interested','not_interested','reject','lost'),('opt_out','opted_out','reject','opted_out')])
def test_reply_transitions_and_linked_history(store,sent,reply_decision,intent,status,verdict,expected):
    text='20 packs of swabs. Jordan Lee, jordan@example.invalid, now handles purchases. We buy through Bluewater.'
    result=inject(store,sent,text);job=store.claim();d={**reply_decision,'intent':intent,'opportunity_status':status,'decision':verdict,'facts':[{'fact':'Customer reported purchasing details.','quote':text}]}
    if verdict!='pursue':d.update(subject='',body='')
    if intent=='reorder':d['products']=[{'description':'swabs','sku':None,'quantity':20,'unit':'packs','quote':'20 packs of swabs.'}]
    if intent=='purchasing_contact':d['contact']={'name':'Jordan Lee','email':'jordan@example.invalid','phone':None,'quote':'Jordan Lee, jordan@example.invalid, now handles purchases.'}
    if intent=='distributor':d['channel']={'route':'distributor','distributor':'Bluewater','quote':'We buy through Bluewater.'}
    save_reviewed_fixture(store,job,d);thread=conversation(store,sent['opportunity_id'])
    assert store.opportunity(sent['opportunity_id'])['status']==expected
    assert thread['messages'][1]['reply_to']==sent['id'] and thread['messages'][1]['interpretation']['intent']==intent
    assert not store.rows("SELECT * FROM jobs WHERE kind='followup' AND status='queued'")
    assert len(thread['tasks'])==1 and len(store.rows('SELECT * FROM outbox'))==1
    if intent=='purchasing_contact':assert thread['context']['contact']['email']=='jordan@example.invalid' and not thread['context']['contact']['verified']
    if intent=='distributor':
        assert thread['context']['outreach_policy']=='channel_review'
        event=json.loads(store.rows("SELECT details FROM events WHERE kind='agent_decision' ORDER BY id DESC LIMIT 1")[0]['details'])
        assert event['channel']=='distributor'
        assert any(g['id']=='conversation_tasks' for g in work_groups(store)['groups'])
    if verdict=='pursue':
        draft=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")[0]
        # Forged delivery before human approval cannot succeed.
        jid=store.enqueue('deliver',{'draft_id':draft['id']},sent['opportunity_id']);bad=store.claim()
        with pytest.raises(ValueError,match='approval'):store.deliver(bad)
        store.finish(jid,'cancelled');store.decide(draft['id'],True);delivery=store.claim();store.deliver(delivery);store.finish(delivery['id'])
        thread=conversation(store,sent['opportunity_id']);assert len(thread['messages'])==3
        assert thread['messages'][2]['reply_to']==result['message_id']
        assert thread['tasks'][0]['status']=='completed'
    else:assert not store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")

def test_deduplication_conflict_and_parent_validation(store,sent):
    first=inject(store,sent);assert not first['duplicate']
    assert inject(store,sent)['duplicate']
    assert inject(store,sent,key='different-delivery-id')['duplicate']
    assert len(store.rows("SELECT * FROM jobs WHERE kind='reply'"))==1
    with pytest.raises(ValueError,match='different content'):inject(store,sent,'Changed message')
    with pytest.raises(ValueError,match='delivered'):SimulatedProvider(store).ingest('wrong-account',sent['id'],'x','Hello')
    assert len(store.rows('SELECT * FROM outcomes'))==1
    inject(store,sent,'Another reply',key='message-2')
    with pytest.raises(ValueError,match='different content'):inject(store,sent,'Another reply',key='message-1')

def test_validation_is_atomic(store,sent,reply_decision):
    inject(store,sent);job=store.claim();bad={**reply_decision,'contact':{'name':'Invented Person','email':None,'phone':None,'quote':'Can we arrange training?'}}
    with pytest.raises(ValueError,match='Contact'):store.save_analysis(job,bad)
    assert not store.rows('SELECT * FROM reply_interpretations') and not store.rows('SELECT * FROM commercial_tasks')
    assert len(store.rows('SELECT * FROM drafts'))==1
    for body in ('We will charge $50.','The price is 25 dollars.'):
        with pytest.raises(ValueError,match='pricing'):validate_reply({**reply_decision,'body':body},'Hello',{})
    with pytest.raises(ValueError):validate_reply({**reply_decision,'opportunity_status':'opted_out'},'Hello',{})

def test_late_optout_overrides_new_reply_and_future_recovery(store,sent,reply_decision,decision):
    inject(store,sent,'Do not contact us.');old=store.claim()
    inject(store,sent,'Can you arrange training?',key='new')
    stop={**reply_decision,'intent':'opt_out','opportunity_status':'opted_out','decision':'reject','subject':'','body':''}
    store.save_analysis(old,stop)
    newer=store.claim();store.save_analysis(newer,reply_decision)
    thread=conversation(store,sent['opportunity_id'])
    assert thread['context']['outreach_policy']=='stop'
    assert store.opportunity(sent['opportunity_id'])['status']=='opted_out'
    assert not store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")
    store.queue_analysis(sent['opportunity_id'],investigation=True,allow_simulation=True);j=store.claim();store.save_analysis(j,decision)
    assert store.opportunity(sent['opportunity_id'])['status']=='opted_out'
    assert not store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")

def test_manual_optout_blocks_inflight_result(store,sent,reply_decision):
    inject(store,sent);job=store.claim();store.record_outcome(sent['opportunity_id'],'opt_out','Stop')
    store.save_analysis(job,reply_decision)
    assert store.opportunity(sent['opportunity_id'])['status']=='opted_out'
    assert not store.rows('SELECT * FROM reply_interpretations')

def test_distributor_restriction_survives_portfolio_reanalysis(store,sent,reply_decision,decision):
    inject(store,sent);job=store.claim();store.save_analysis(job,{**reply_decision,'intent':'distributor','opportunity_status':'channel_review','decision':'hold','subject':'','body':''})
    store.queue_analysis(sent['opportunity_id'],investigation=True,allow_simulation=True);store.save_analysis(store.claim(),decision)
    assert store.opportunity(sent['opportunity_id'])['status']=='agent_held'
    assert not store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")

def test_api_inbound_is_linked_simulated_and_deduplicated(store,settings,sent):
    api=TestClient(create_app(settings));url=f"/api/accounts/{sent['opportunity_id']}/conversation"
    body={'reply_to':sent['id'],'message_id':'api-1','body':'Can we arrange training?'}
    headers={'X-Clearline-Client':'web','Origin':'http://127.0.0.1:3000'}
    assert api.post(url+'/replies',json=body).status_code==403
    assert api.post(url+'/replies',json=body,headers=headers).json()['duplicate'] is False
    assert api.post(url+'/replies',json=body,headers=headers).json()['duplicate'] is True
    assert api.get(url).json()['provider']=='simulated'
    assert len(api.get(url).json()['messages'])==2

def test_reset_run_reply_reset_run_no_duplicate_history(store,settings,draft,reply_decision,tmp_path):
    folder=tmp_path/'demo';initialize(store.path,folder);_,path,_=paths(folder)
    for cycle in range(2):
        s=Store(path);s.decide(draft['id'],True);job=s.claim();s.deliver(job);s.finish(job['id'])
        sent=conversation(s,draft['opportunity_id'])['messages'][0];inject(s,sent);save_reviewed_fixture(s,s.claim(),reply_decision)
        d=s.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")[0];s.decide(d['id'],True);j=s.claim();s.deliver(j);s.finish(j['id'])
        assert len(conversation(s,draft['opportunity_id'])['messages'])==3
        reset(folder);clean=Store(path)
        assert not clean.rows('SELECT * FROM messages') and not clean.rows('SELECT * FROM reply_interpretations')
        assert clean.rows('SELECT status FROM drafts')[0]['status']=='awaiting_approval'
    assert not store.rows('SELECT * FROM outbox')


@pytest.mark.parametrize('intent',['training','support'])
def test_distributor_training_reply_keeps_channel_and_separate_approval(store,sent,reply_decision,intent):
    from clearline.evidence import context_hash,ENGINE_VERSION
    from clearline.action_policy import proposal_fingerprint
    body='We buy through Range Line Distributors. Our night shift needs training.'
    inject(store,sent,body);job=store.claim()
    with store.connect() as c:version=context_hash(c,sent['opportunity_id'])
    result={**reply_decision,'intent':intent,'opportunity_status':'channel_review',
            'channel':{'route':'distributor','distributor':'Range Line Distributors','quote':'We buy through Range Line Distributors.'},
            'engine_version':ENGINE_VERSION,'context_hash':version,'evidence_hash':job['payload']['evidence_hash'],
            'body':'Would a discussion of night-shift training needs be useful while you continue buying through Range Line Distributors?',
            'action_scope':'channel_support','quality':{'passed':True}}
    result['quality']['proposal_hash']=proposal_fingerprint(result)
    save_reviewed_fixture(store,job,result)
    thread=conversation(store,sent['opportunity_id'])
    assert thread['context']['outreach_policy']=='channel_review'
    assert store.opportunity(sent['opportunity_id'])['status']=='awaiting_approval'
    assert len(store.rows('SELECT * FROM outbox'))==1
    draft=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")[0]
    store.decide(draft['id'],True);store.deliver(store.claim())
    assert len(store.rows('SELECT * FROM outbox'))==2
    assert conversation(store,sent['opportunity_id'])['context']['outreach_policy']=='channel_review'


def test_stale_reply_cannot_overwrite_new_account_context(store,sent,reply_decision):
    from clearline.evidence import context_hash,ENGINE_VERSION
    inject(store,sent);job=store.claim()
    with store.connect() as c:version=context_hash(c,sent['opportunity_id'])
    store.record_outcome(sent['opportunity_id'],'qualified','Updated delivery needs after the investigation began')
    store.save_analysis(job,{**reply_decision,'engine_version':ENGINE_VERSION,'context_hash':version})
    assert not store.rows('SELECT * FROM reply_interpretations')
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='cancelled'
