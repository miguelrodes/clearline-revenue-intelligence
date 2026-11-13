from commercial_fixtures import save_reviewed_fixture,reviewed_fixture
import asyncio,copy,json
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.store import Store
from clearline.operations import create_campaign,queue_brief
from clearline.briefing import snapshot,current_brief,render_brief
from clearline.workbench import work_groups,decide_messages,recovery_performance,refresh_portfolio
from clearline.worker import run_pool,execute_job
from test_operations import population
from test_briefing import save_brief


def prepared(store,opportunity,decision,n=3):
    ids=population(store,opportunity,n);cid=create_campaign(store,'Existing campaign',ids,True)
    for _ in ids:save_reviewed_fixture(store,store.claim(),copy.deepcopy(decision))
    group=next(g for g in work_groups(store)['groups'] if g['kind']=='messages')
    return cid,group


def snaps(group):return [{'draft_id':m['draft']['id'],'snapshot_hash':m['draft']['snapshot_hash']} for m in group['members']]


def test_subset_approval_keeps_other_messages_and_campaign_history(store,settings,opportunity,decision):
    cid,g=prepared(store,opportunity,decision)
    ss=snaps(g);decide_messages(store,g['id'],ss[:2],True)
    assert len(store.rows('SELECT * FROM approvals'))==2
    assert len(store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'"))==1
    assert store.rows('SELECT status FROM campaigns WHERE id=?',(cid,))[0]['status']!='approved'
    with pytest.raises(ValueError):decide_messages(store,g['id'],ss[:2],True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    assert len(store.rows('SELECT * FROM outbox'))==2
    remaining=next(g for g in work_groups(store)['groups'] if g['kind']=='messages')
    decide_messages(store,remaining['id'],snaps(remaining),True)
    assert store.rows('SELECT status FROM campaigns WHERE id=?',(cid,))[0]['status']=='approved'


def test_bulk_rejects_stale_edited_or_held_drafts_atomically(store,opportunity,decision):
    _,g=prepared(store,opportunity,decision);ss=snaps(g);d=g['members'][1]['draft']
    store.revise_draft(d['id'],d['recipient'],'Changed',d['body'])
    with pytest.raises(ValueError,match='changed'):decide_messages(store,g['id'],ss,True)
    assert not store.rows('SELECT * FROM approvals')
    g=next(g for g in work_groups(store)['groups'] if g['kind']=='messages');ss=snaps(g)
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET holds='[\"open_orders_require_review\"]' WHERE id=?",(g['members'][0]['id'],))
    with pytest.raises(ValueError):decide_messages(store,g['id'],ss,True)
    assert not store.rows('SELECT * FROM approvals')


def test_signal_categories_match_counts_and_revenue(settings,store,opportunity):
    api=TestClient(create_app(settings));segments=api.get('/api/overview').json()['segments']
    assert [s['key'] for s in segments]==['inactivity','partial','product_decline','direct_gap_channel_review']
    assert segments[0]['accounts']==1
    assert segments[1]['accounts']==segments[1]['decline_cents']==0


def test_unchanged_brief_does_not_expire_but_manual_refresh_can_renew(store,opportunity):
    state=snapshot(store);jid=queue_brief(store);job=store.claim();save_brief(store,state);store.finish(job['id'])
    assert queue_brief(store)==jid
    with store.connect(write=True) as con:con.execute('UPDATE operational_briefs SET created_at=?',((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),))
    assert queue_brief(store)==jid
    newer=queue_brief(store,True);assert newer!=jid and queue_brief(store)==newer


def test_brief_ranking_up_to_five_and_rejects_added_numbers(store,opportunity):
    state=snapshot(store)
    output={'summary_fact_ids':list(state['facts'])[:1],'recommendations':[{'action_id':a['id'],'reason_id':'next','description':'Review these customers and decide the next step.'} for a in state['actions']]}
    assert len(render_brief(output,state)['actions'])<=5
    output['recommendations'][0]['description']='Guaranteed recovery of $5000.'
    with pytest.raises(ValueError):render_brief(output,state)


def test_performance_excludes_unlinked_and_real_claims_and_nets_credits(store,settings,opportunity,decision):
    _,g=prepared(store,opportunity,decision,2)
    store.record_outcome('1','order','Before any outreach',10000,'early')
    eligible=[s for s in snaps(g) if s['draft_id']==g['members'][0]['draft']['id']]
    decide_messages(store,g['id'],eligible,True);asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    store.record_outcome('0','reply','Simulated reorder request')
    store.record_outcome('0','order','Simulated invoice',20000,'invoice-1')
    store.record_outcome('0','credit','Simulated credit note',5000,'credit-1')
    with pytest.raises(ValueError):store.record_outcome('0','order','Duplicate',20000,'invoice-1')
    p=recovery_performance(store)
    assert p['verified'] is None and p['incremental_cents'] is None
    assert p['simulated']['contacted']==p['simulated']['responded']==p['simulated']['purchased']==1
    assert p['simulated']['net_cents']==15000 and p['unlinked_outcomes']==1
    assert len(store.rows('SELECT * FROM outcome_outreach'))==3
    assert p['simulated']['series'][-1]['net_cents']==15000


def test_reply_preparation_requires_new_exact_approval_and_stops_old_sequence(store,settings,opportunity,decision,reply_decision,monkeypatch):
    _,g=prepared(store,opportunity,decision,1);decide_messages(store,g['id'],snaps(g),True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False));store.record_outcome('0','reply','Can you help with training?')
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]['status']=='cancelled'
    job=store.claim();assert job['kind']=='reply'
    async def reply(*args):return reviewed_fixture(store,args[1],reply_decision)
    monkeypatch.setattr('clearline.reply_agent.draft_reply',reply)
    asyncio.run(execute_job(store,settings,job))
    rg=next(g for g in work_groups(store)['groups'] if g['id']=='messages:reply')
    assert rg['rank']==0 and rg['accounts']==1
    assert len(store.rows('SELECT * FROM approvals'))==len(store.rows('SELECT * FROM outbox'))==1
    assert store.rows("SELECT status FROM drafts ORDER BY version DESC LIMIT 1")[0]['status']=='awaiting_approval'


def test_reply_result_cannot_override_new_optout_or_reply(store,settings,opportunity,decision,reply_decision,monkeypatch):
    _,g=prepared(store,opportunity,decision,1);decide_messages(store,g['id'],snaps(g),True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False));store.record_outcome('0','reply','First reply');job=store.claim()
    async def reply(*args):
        store.record_outcome('0','reply','Replacement reply')
        return reply_decision
    monkeypatch.setattr('clearline.reply_agent.draft_reply',reply)
    asyncio.run(execute_job(store,settings,job))
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='cancelled'
    assert len(store.rows('SELECT * FROM drafts'))==1
    store.record_outcome('0','opt_out','Stop contacting')
    assert not any(g['kind']=='messages' for g in work_groups(store)['groups'])


def test_combined_refresh_deduplicates_and_search_is_read_only(store,settings,opportunity):
    a=refresh_portfolio(store);assert refresh_portfolio(store)==a
    api=TestClient(create_app(settings))
    before={t:len(store.rows('SELECT * FROM '+t)) for t in ('opportunities','jobs','approvals','outbox')}
    assert api.get('/api/search?q=Example').json()[0]['id']=='example'
    assert api.get('/api/search?q=x').json()==[]
    assert api.get('/api/work').status_code==api.get('/api/performance').status_code==200
    assert before=={t:len(store.rows('SELECT * FROM '+t)) for t in before}


def test_due_followup_prepares_a_new_draft_but_requires_fresh_approval(store,settings,opportunity,decision):
    _,g=prepared(store,opportunity,decision,1);decide_messages(store,g['id'],snaps(g),True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    with store.connect(write=True) as con:con.execute("UPDATE jobs SET due_at='2000-01-01' WHERE kind='followup'")
    async def analyst(*args):return reviewed_fixture(store,args[1],{**decision,'subject':'Follow-up purchasing question'})
    asyncio.run(run_pool(store,settings,analyst,drain=True,auto_brief=False))
    g=next(g for g in work_groups(store)['groups'] if g['id']=='messages:followup')
    assert g['accounts']==1 and g['members'][0]['draft']['version']==2
    assert len(store.rows('SELECT * FROM approvals'))==len(store.rows('SELECT * FROM outbox'))==1
    decide_messages(store,g['id'],snaps(g),True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    assert len(store.rows('SELECT * FROM outbox'))==2
    assert not store.rows("SELECT 1 FROM jobs WHERE kind='followup' AND status='queued'")


def test_investigation_group_never_adds_distributor_and_agency_decline(store,opportunity):
    with store.connect(write=True) as c:
        c.execute("UPDATE opportunities SET account_key='DISTRIBUTOR|buyer|fixture' WHERE id='example'")
        c.execute("INSERT INTO investigation_tasks VALUES('t','example','ctx','Review order','Operations','Unclear status','[]',1,'pending','now')")
    group=next(g for g in work_groups(store)['groups'] if g['id']=='verification_tasks')
    assert group['historical_decline_cents'] is None and group['financial_cents'] is None


def test_current_tasks_group_by_business_purpose_without_activating_dormant_work(store,opportunity,monkeypatch):
    import clearline.workbench as workbench
    with store.connect(write=True) as c:
        for task,title in [('orders','Resolve the open order status'),('contacts','Verify purchasing recipient and relationship route'),('needs','Confirm night-shift training needs')]:
            c.execute("INSERT INTO investigation_tasks VALUES(?, 'example','ctx',?,'Account owner','Missing fact','[]',1,'pending','now')",(task,title))
    account={'id':'example','name':'Example','workflow':'recovery','engine_version':'commercial-5.3','status':'human_verification','holds':[],'signals':[],'assessment':'hold','decline_cents':10000}
    monkeypatch.setattr(workbench,'opportunities',lambda *args:[dict(account)])
    groups=workbench.work_groups(store,workflow='recovery')['groups']
    relevant=[g for g in groups if g['id'].startswith('investigation:')]
    assert {g['id'] for g in relevant}=={'investigation:orders','investigation:contacts','investigation:needs'}
    assert {m['task_id'] for g in relevant for m in g['members']}=={'orders','contacts','needs'}
    for status in ['no_action','monitor','defer']:
        account['status']=status
        assert not any(g['id'].startswith('investigation:') for g in workbench.work_groups(store,workflow='recovery')['groups'])
    assert len(store.rows("SELECT * FROM investigation_tasks WHERE status='pending'"))==3
