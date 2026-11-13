from commercial_fixtures import save_reviewed_fixture,reviewed_fixture
import asyncio
import json
from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.data import digest
from clearline.store import utcnow
from clearline.operations import create_campaign, campaign_view, decide_campaign, queue_brief
from clearline.briefing import snapshot, operational_queue, render_brief, current_brief
from clearline.worker import run_pool, execute_job, Capacity
from test_operations import population


def choose(state):
    return {'summary_fact_ids':list(state['facts'])[:2],
            'recommendations':[{'action_id':a['id'],'reason_id':next(iter(a['reasons']))} for a in state['actions']]}


def save_brief(store,state):
    with store.connect(write=True) as con:
        con.execute('INSERT INTO operational_briefs VALUES(?,?,?,?,?)',
                    (uuid4().hex,digest(state),json.dumps(state),json.dumps(choose(state)),utcnow()))


def test_actions_are_grounded_filtered_and_read_only(store,settings,opportunity,decision):
    ids=population(store,opportunity,3)
    cid=create_campaign(store,'Review',['0'],True);save_reviewed_fixture(store,store.claim(),decision)
    jid=store.queue_analysis('1',investigation=True);save_reviewed_fixture(store,store.claim(),decision)
    state=snapshot(store);save_brief(store,state)
    rendered=current_brief(store)['brief']
    assert rendered and len(rendered['actions'])==2
    assert not any(a['id']=='contacts' for a in rendered['actions']) # already authorized fixtures
    campaign=next(a for a in rendered['actions'] if a['id'].startswith('messages:'))
    assert campaign['href']=='/actions?group=messages%3Ainactivity'
    assert campaign['historical_decline_cents']==20000
    api=TestClient(create_app(settings))
    before=len(store.rows('SELECT * FROM jobs'))
    assert not api.get('/api/opportunities?queue=contacts').json()
    assert [a['id'] for a in api.get('/api/opportunities?queue=unassessed').json()]==['2']
    assert api.get('/api/brief').json()['brief']['summary']==rendered['summary']
    assert len(store.rows('SELECT * FROM jobs'))==before
    assert api.get('/api/opportunities?queue=invented').status_code==422


def test_stale_brief_is_hidden_after_approval_and_outcome(store,settings,opportunity,decision):
    cid=create_campaign(store,'Review',['example'],True);save_reviewed_fixture(store,store.claim(),decision)
    state=snapshot(store);save_brief(store,state)
    assert current_brief(store)['brief']
    d=campaign_view(store,cid)['members'][0]['draft']
    decide_campaign(store,cid,[{'draft_id':d['id'],'snapshot_hash':d['snapshot_hash']}],True)
    assert current_brief(store)['brief'] is None and current_brief(store)['stale']
    assert not any(a['id'].startswith('messages:') for a in snapshot(store)['actions'])
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    assert any(a['id']=='followups' for a in snapshot(store)['actions'])
    store.record_outcome('example','reply','Explicit test response')
    state=snapshot(store)
    assert not any(a['id']=='followups' for a in state['actions'])
    assert not any(a['id']=='followups' for a in state['actions'])
    assert not operational_queue(store,'contacts')


def test_unknown_action_reason_fact_metrics_and_urls_are_rejected(store,opportunity):
    state=snapshot(store);valid=choose(state)
    for bad in [
        {**valid,'summary_fact_ids':['invented_sales']},
        {**valid,'expected_revenue':100000},
        {**valid,'recommendations':[{'action_id':'https://external.test','reason_id':'ready'}]},
        {**valid,'recommendations':[{'action_id':state['actions'][0]['id'],'reason_id':'guaranteed_recovery'}]},
        {**valid,'recommendations':[{'action_id':state['actions'][0]['id'],'reason_id':'missing_assessment','url':'/send'}]},
    ]:
        with pytest.raises(ValueError):render_brief(bad,state)


def test_cache_coalesces_without_self_triggered_api_loop(store,opportunity,decision):
    first=queue_brief(store)
    assert first==queue_brief(store)
    store.event('api_response',{'requests':1,'cost_usd':1.23})
    store.heartbeat('running')
    assert first==queue_brief(store)
    store.queue_analysis('example',investigation=True)
    # Queue status is a material operational change, so the old queued brief is obsolete.
    second=queue_brief(store)
    assert first!=second
    assert store.rows('SELECT status FROM jobs WHERE id=?',(first,))[0]['status']=='cancelled'
    assert second==queue_brief(store,True) # repeated regenerate clicks cannot duplicate in-flight work


def test_contacts_exclude_prior_outreach_stopped_held_and_stale(store,settings,opportunity,decision):
    population(store,opportunity,4)
    for oid in ('0','1','2','3'):
        store.queue_analysis(oid,investigation=True);save_reviewed_fixture(store,store.claim(),decision)
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='deferred' WHERE id='1'")
        con.execute("UPDATE opportunities SET holds=? WHERE id='2'",(json.dumps(["open_orders_require_review"]),))
        con.execute("UPDATE opportunities SET evidence_hash='changed' WHERE id='3'")
    assert not operational_queue(store,'contacts')
    from clearline.workbench import ready_messages
    assert [a['id'] for a in ready_messages(store)]==['0']


def test_fifteen_parallel_independent_results_and_persistence(store,settings,opportunity,decision):
    from clearline.operations import start_batch,metrics
    from clearline.store import Store
    population(store,opportunity,30);start_batch(store);active=0;peak=0
    async def analyst(*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.05)
        active-=1;return reviewed_fixture(store,args[1],decision)
    asyncio.run(run_pool(store,replace(settings,concurrency=15,max_concurrency=15),analyst,drain=True,auto_brief=False))
    assert peak==15
    reopened=Store(settings.db_path)
    assert len(reopened.rows("SELECT * FROM events WHERE kind='agent_decision'"))==30
    assert len(reopened.rows('SELECT * FROM drafts'))==30 # each fixture is expressly authorized
    assert metrics(reopened)['capacity']['peak_investigations']==15
    assert not metrics(reopened)['active_investigations']


def test_retry_after_and_max_attempts_are_respected(store,settings,opportunity):
    class Response:headers={'retry-after':'300'}
    class Limited(Exception):status_code=429;code='rate_limit_exceeded';response=Response()
    async def analyst(*args):raise Limited()
    store.queue_analysis('example');job=store.claim();cap=Capacity(settings)
    asyncio.run(execute_job(store,settings,job,analyst,cap))
    from datetime import datetime
    row=store.rows('SELECT * FROM jobs')[0]
    assert (datetime.fromisoformat(row['due_at'])-datetime.fromisoformat(row['started_at'])).total_seconds()>=300
    with store.connect(write=True) as con:con.execute("UPDATE jobs SET attempts=?,due_at='2000-01-01'",(settings.max_attempts-1,))
    asyncio.run(execute_job(store,settings,store.claim(),analyst,cap))
    assert store.rows('SELECT status FROM jobs')[0]['status']=='failed'


def test_metrics_distinguish_inflight_queued_and_backoff(store,opportunity):
    from clearline.operations import metrics
    store.queue_analysis('example');job=store.claim()
    store.event('model_request_started',{'request_id':'request'},job['id'])
    m=metrics(store);assert m['model_requests_inflight']==1 and len(m['active_investigations'])==1
    store.event('model_request_finished',{'request_id':'request'},job['id'])
    assert metrics(store)['model_requests_inflight']==0
    with store.connect(write=True) as con:con.execute("UPDATE jobs SET status='queued',due_at='2099-01-01'")
    m=metrics(store);assert m['retry_wait']==1 and m['queue_ready']==0 and not m['active_investigations']


def test_superseded_result_can_regenerate_but_failed_brief_does_not_loop(store,opportunity):
    first=queue_brief(store);job=store.claim();store.finish(job['id'])
    second=queue_brief(store)
    assert second!=first
    assert queue_brief(store)==second
    store.finish(store.claim()['id'],'failed','Rejected output')
    # Stable failed state stays blocked until explicit regeneration.
    before=len(store.rows('SELECT * FROM jobs'))
    queue_brief(store)
    assert len(store.rows('SELECT * FROM jobs'))==before


def test_brief_includes_more_than_five_actions_and_natural_summary(store,opportunity,monkeypatch):
    from clearline import workbench
    original=workbench.work_groups
    def expanded(*args,**kwargs):
        work=original(*args,**kwargs)
        seed=work['groups'][0]
        work['groups']=[dict(seed,id=f'action:{i}') for i in range(8)]
        return work
    monkeypatch.setattr(workbench,'work_groups',expanded)
    state=snapshot(store)
    assert len(state['actions'])==8
    output=choose(state)
    output['summary']='Customer reviews are waiting for your attention. The agents have prepared the next steps for you to review.'
    rendered=render_brief(output,state)
    assert len(rendered['actions'])==8
    assert rendered['summary']==output['summary']
    assert [a['recommended_order'] for a in rendered['actions']]==list(range(8))
    for bad in ['A generic single sentence.', 'You will recover $500. Send everything now.']:
        with pytest.raises(ValueError):render_brief({**output,'summary':bad},state)


def test_followup_context_uses_saved_correspondence_and_does_not_change_records(store,settings,opportunity,decision):
    cid=create_campaign(store,'Review',['example'],True)
    save_reviewed_fixture(store,store.claim(),decision)
    draft=campaign_view(store,cid)['members'][0]['draft']
    decide_campaign(store,cid,[{'draft_id':draft['id'],'snapshot_hash':draft['snapshot_hash']}],True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    before=store.rows('SELECT * FROM outbox')
    state=snapshot(store)
    action=next(a for a in render_brief(choose(state),state)['actions'] if a['id']=='followups')
    member=action['members'][0]
    assert member['subject']==before[0]['subject']
    assert member['last_sent_at']==before[0]['created_at']
    assert member['due_at']==store.rows("SELECT due_at FROM jobs WHERE kind='followup'")[0]['due_at']
    assert member['name'] in action['title']
    assert member['historical_decline_cents']==store.opportunity('example')['decline_cents']
    assert action['financial_cents'] is None  # do not invent a follow-up revenue total
    assert store.rows('SELECT * FROM outbox')==before


def test_structured_briefing_points_and_descriptive_actions(store,opportunity):
    state=snapshot(store);output=choose(state)
    points=['Review the prepared customer work and choose the next step for each account. Historical purchasing declines are context, not promised sales.', 'Ask the responsible team to confirm missing information before starting outreach.']
    output['summary_points']=points
    output['recommendations'][0]['description']='Review the saved customer history to understand the purchasing change and the questions that remain unanswered. Open the customer group to inspect the records and determine what information is needed before preparing outreach. Use the historical decline to guide your review, without assuming the customer has stopped buying or that lost purchases can be recovered.'
    result=render_brief(output,state)
    assert result['summary_points']==points
    assert result['summary']==' '.join(points)
    assert result['actions'][0]['why']==output['recommendations'][0]['description']
    with pytest.raises(ValueError):render_brief({**output,'summary_points':['Recover $100 today.',points[1]]},state)


def test_priority_bullets_bind_counts_and_money_to_their_own_action():
    from clearline.briefing import PriorityPoint,priority_points
    catalog={
        'reduced':{'accounts':27,'financial_cents':11612600,'members':[]},
        'inactive':{'accounts':14,'financial_cents':17691800,'members':[]},
        'reply':{'accounts':1,'financial_cents':None,'historical_decline_cents':None,'members':[{'name':'Lone Tree'}]},
    }
    points=[PriorityPoint(action_id='reduced',text='{customers} customers are buying less, with {historical_decline} in historical purchasing decline. Review their prepared emails to clarify supply needs.'),
            PriorityPoint(action_id='inactive',text='{customers} customers have stopped identified purchasing. Review the prepared check-ins to confirm whether they still need supplies.'),
            PriorityPoint(action_id='reply',text='{customer} has requested a quote. Review the prepared response to clarify delivery requirements and advance the purchase.')]
    result=priority_points(points,catalog)
    assert result[0].startswith('27 customers are buying less, with $116,126 in historical purchasing decline.')
    assert result[2].startswith('Lone Tree has requested a quote.')
    for text in ['99 customers are buying less.', '{customers} customers could recover $116,126.',
                 '{customers} customers have {invented_amount} in orders.',
                 '{customers} customers have {historical_decline} in open orders.',
                 'Review the prepared emails.']:
        with pytest.raises(ValueError):priority_points([points[0].model_copy(update={'text':text}),*points[1:]],catalog)
    with pytest.raises(ValueError):priority_points([*points[:2],points[2].model_copy(update={'text':'{customer} has {historical_decline} in historical decline.'})],catalog)
    with pytest.raises(ValueError):priority_points([points[0],points[0],points[2]],catalog)


def test_priority_bullets_render_through_existing_brief_contract(store,opportunity):
    state=snapshot(store);output=choose(state);action=state['actions'][0]
    output['priorities']=[{'action_id':action['id'],'text':'{customers} customers need investigation. Review their purchasing changes to decide which recovery actions are justified.'}]
    rendered=render_brief(output,state)
    assert rendered['summary_points'][0].startswith(str(action['accounts'])+' customers need investigation.')
    assert rendered['summary']==' '.join(rendered['summary_points'])
    assert len(rendered['actions'])==len(state['actions'])


def test_investigation_brief_cannot_invent_legacy_export_controls():
    from clearline.briefing import render_brief
    state={'actions':[{'id':'investigation:orders','title':'Check orders','href':'/actions?group=investigation:orders','accounts':1,'historical_decline_cents':None,'reasons':{'next':'Record the missing status.'}}],'facts':{'verification':'Check missing facts.'}}
    output={'summary_fact_ids':['verification'],'recommendations':[{'action_id':'investigation:orders','reason_id':'next','description':'Download and share externally with the orders team.'}]}
    import pytest
    with pytest.raises(ValueError,match='actual customer-task controls'):render_brief(output,state)
    output['recommendations'][0]['description']='Ask the order owner for the missing status and record the finding on the customer.'
    assert render_brief(output,state)['actions'][0]['why']==output['recommendations'][0]['description']
