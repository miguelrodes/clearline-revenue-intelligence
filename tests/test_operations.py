from commercial_fixtures import save_reviewed_fixture,reviewed_fixture
import asyncio
import copy
import json
from dataclasses import replace
import pytest
from clearline.data import digest
from clearline.store import Store
from clearline.worker import run_pool,run_one,execute_job,Capacity
from clearline.operations import start_batch,batches,create_campaign,campaign_view,decide_campaign,metrics


def population(store,item,n=15):
    items=[]
    for i in range(n):
        x=copy.deepcopy(item);x['id']=str(i);x['account_key']=str(i);x['name']=f'Account {i}';x['evidence']['name']=x['name'];x['evidence_hash']=digest(x['evidence']);items.append(x)
    store.save_scan({},items)
    return [x['id'] for x in items]


def test_six_parallel_and_same_account_serialized(store,settings,opportunity,decision):
    settings=replace(settings,concurrency=6,max_concurrency=6)
    ids=population(store,opportunity,12);start_batch(store,ids); active=0; peak=0
    async def analyst(*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active);await asyncio.sleep(.05);active-=1
        from clearline.evidence import ENGINE_VERSION,context_hash
        with store.connect() as con:revision=context_hash(con,args[1]['opportunity_id'])
        return reviewed_fixture(store,args[1],decision)
    asyncio.run(run_pool(store,settings,analyst,drain=True,auto_brief=False))
    assert peak==6
    assert len(store.rows("SELECT * FROM events WHERE kind='agent_decision'"))==12
    assert len(store.rows('SELECT * FROM drafts'))==12 # Reviewed current-engine results prepare simulated proposals.
    b=start_batch(store,ids)
    assert next(x for x in batches(store) if x['id']==b)['counts']=={'cached':12}
    store.enqueue('analyze',{'evidence_hash':store.opportunity('0')['evidence_hash']},'0','duplicate-a')
    store.enqueue('analyze',{'evidence_hash':store.opportunity('0')['evidence_hash']},'0','duplicate-b')
    assert store.claim()['opportunity_id']=='0';assert store.claim() is None


def test_held_can_be_investigated_but_never_drafted(store,opportunity,decision):
    opportunity['holds']=['open_orders_require_review'];opportunity['evidence']['holds']=opportunity['holds'];opportunity['evidence_hash']=digest(opportunity['evidence']);store.save_scan({},[opportunity])
    start_batch(store);job=store.claim()
    with pytest.raises(ValueError,match='execution boundaries'):save_reviewed_fixture(store,job,decision)
    save_reviewed_fixture(store,job,{**decision,'decision':'hold','subject':'','body':''})
    assert not store.rows('SELECT * FROM drafts')
    assert store.opportunity('example')['status']=='agent_held'
    assert json.loads(store.rows("SELECT details FROM events WHERE kind='agent_decision'")[0]['details'])['decision']=='hold'


def test_campaign_15_atomic_approval_and_no_duplicate_send(store,settings,opportunity,decision):
    ids=population(store,opportunity);cid=create_campaign(store,'Fifteen',ids,True)
    async def analyst(*args):return reviewed_fixture(store,args[1],decision)
    asyncio.run(run_pool(store,settings,analyst,drain=True,auto_brief=False))
    view=campaign_view(store,cid);assert view['ready']==15
    snapshots=[{'draft_id':m['draft']['id'],'snapshot_hash':m['draft']['snapshot_hash']} for m in view['members']]
    wrong=copy.deepcopy(snapshots);wrong[-1]['snapshot_hash']='stale'
    with pytest.raises(ValueError,match='changed'):decide_campaign(store,cid,wrong,True)
    assert not store.rows('SELECT * FROM approvals')
    decide_campaign(store,cid,snapshots,True)
    assert len(store.rows('SELECT * FROM approvals'))==15
    asyncio.run(run_pool(store,settings,analyst,drain=True,auto_brief=False))
    assert len(store.rows('SELECT * FROM outbox'))==15
    with pytest.raises(ValueError):decide_campaign(store,cid,snapshots,True)
    assert len(store.rows("SELECT * FROM jobs WHERE kind='followup'"))==15
    store.record_outcome('0','opt_out','Test opt-out')
    assert store.rows("SELECT status FROM jobs WHERE kind='followup' AND opportunity_id='0'")[0]['status']=='cancelled'
    second=create_campaign(store,'Already contacted',ids,True)
    assert all(m['exclusion'] for m in campaign_view(store,second)['members'])


def test_campaign_no_synthetic_contact_without_explicit_choice(store,opportunity):
    cid=create_campaign(store,'Needs contacts',['example'])
    assert campaign_view(store,cid)['members'][0]['exclusion']
    assert not store.rows('SELECT * FROM jobs')


def test_rate_limit_backoff_and_quota_block(store,settings,opportunity):
    class Limited(Exception):status_code=429;code='rate_limit_exceeded'
    async def limited(*args):raise Limited()
    jid=store.queue_analysis('example');job=store.claim();cap=Capacity(settings)
    asyncio.run(execute_job(store,settings,job,limited,cap))
    saved=store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
    assert saved['status']=='queued' and saved['due_at']>saved['started_at']
    assert cap.current==settings.concurrency//2
    class Quota(Exception):status_code=429;code='insufficient_quota'
    async def quota(*args):raise Quota()
    with store.connect(write=True) as con:con.execute("UPDATE jobs SET due_at='2000-01-01' WHERE id=?",(jid,))
    asyncio.run(execute_job(store,settings,store.claim(),quota,cap))
    assert store.rows('SELECT status FROM jobs')[0]['status']=='blocked_config'


def test_cancellation_and_restart_cannot_duplicate_campaign_drafts(store,settings,opportunity,decision):
    cid=create_campaign(store,'Cancel',['example'],True);job=store.claim();store.cancel_job(job['id']);save_reviewed_fixture(store,job,decision)
    assert not store.rows('SELECT * FROM drafts')
    restarted=Store(settings.db_path);restarted.recover_interrupted()
    assert not restarted.claim()


def test_different_version_invalidates_campaign_review(store,settings,opportunity,decision):
    cid=create_campaign(store,'Edit',['example'],True);job=store.claim();save_reviewed_fixture(store,job,decision)
    d=campaign_view(store,cid)['members'][0]['draft'];snap=[{'draft_id':d['id'],'snapshot_hash':d['snapshot_hash']}]
    store.revise_draft(d['id'],d['recipient'],'Edited subject',d['body'])
    with pytest.raises(ValueError):decide_campaign(store,cid,snap,True)
    assert not store.rows('SELECT * FROM approvals')


def test_low_headroom_does_not_raise_concurrency(settings):
    cap=Capacity(replace(settings,concurrency=6,max_concurrency=12))
    for _ in range(20):cap.completed(5)
    assert cap.current==6
    cap.headers={'x-ratelimit-remaining-requests':'1000','x-ratelimit-remaining-tokens':'1000000'}
    cap.completed(5);assert cap.current==7


def test_campaign_waits_for_all_preparation_and_requires_all_reviewed_versions(store,settings,opportunity,decision):
    ids=population(store,opportunity,2);cid=create_campaign(store,'Both',ids,True)
    first=store.claim();save_reviewed_fixture(store,first,decision)
    view=campaign_view(store,cid)
    snapshots=[{'draft_id':m['draft']['id'],'snapshot_hash':m['draft']['snapshot_hash']} for m in view['members'] if m['ready']]
    with pytest.raises(ValueError,match='still running'):decide_campaign(store,cid,snapshots,True)
    save_reviewed_fixture(store,store.claim(),decision)
    with pytest.raises(ValueError,match='Campaign changed'):decide_campaign(store,cid,snapshots,True)
    assert not store.rows('SELECT * FROM approvals')


def test_repeated_completion_does_not_cancel_job_or_duplicate_draft(store,opportunity,decision):
    create_campaign(store,'Once',['example'],True);job=store.claim()
    save_reviewed_fixture(store,job,decision);save_reviewed_fixture(store,job,decision)
    assert store.rows('SELECT status FROM jobs')[0]['status']=='completed'
    assert len(store.rows('SELECT * FROM drafts'))==1
    assert len(store.rows("SELECT * FROM events WHERE kind='agent_decision'"))==1


def test_defer_stops_outreach_but_does_not_claim_evidence_resolved(store,opportunity,decision):
    from clearline.operations import review_recommendation
    cid=create_campaign(store,'Deferred',['example'],True);job=store.claim()
    review_recommendation(store,'example','defer','Waiting for purchasing team identity confirmation')
    save_reviewed_fixture(store,job,decision)
    assert store.opportunity('example')['status']=='deferred'
    assert not store.rows('SELECT * FROM drafts')
    assert campaign_view(store,cid)['ready']==0
    with pytest.raises(ValueError):review_recommendation(store,'example','acknowledge','Done')


def test_stale_assessment_is_not_current_and_failed_batch_members_are_visible(store,opportunity,decision):
    from clearline.reporting import opportunities
    start_batch(store);job=store.claim();save_reviewed_fixture(store,job,decision)
    opportunity['evidence_hash']='changed';store.save_scan({},[opportunity])
    assert opportunities(store)[0]['assessment'] is None
    start_batch(store);job=store.claim();store.finish(job['id'],'failed','Explicit failure')
    assert batches(store)[0]['counts']=={'failed':1}


def test_portfolio_scan_keeps_crm_only_unresolved_and_stable_customers_without_double_count(tmp_path):
    import pandas as pd
    from clearline.data import scan
    columns=['order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','unit_price','line_total','status']
    rows=[['1','2025-01-01','Stable County Jail','','Town','MA','direct','SWAB','10','100','1000','invoiced'],
          ['2','2026-01-01','Stable County Jail','','Town','MA','direct','SWAB','10','100','1000','invoiced'],
          ['3','2026-01-01','Unresolved Jail','','Town','','direct','SWAB','1','100','100','invoiced'],
          ['4','2026-01-01','Distributor Inc','Named County Jail','Town','MA','distributor','SWAB','2','100','200','invoiced'],
          ['5','2026-01-01','Distributor Inc','','Town','MA','distributor','SWAB','3','100','300','invoiced']]
    pd.DataFrame(rows,columns=columns).to_csv(tmp_path/'orders.csv',index=False)
    pd.DataFrame([['SWAB','Surface swabs',10,100,100]],columns=['sku','name','tests_per_pack','list_price_until_2025_06_30','list_price_from_2025_07_01']).to_csv(tmp_path/'products.csv',index=False)
    pd.DataFrame([['crm1','CRM Only Jail','MA','Owner','Validate identity','2025-01-01']],columns=['crm_id','account_name','state','owner','notes','last_contacted']).to_csv(tmp_path/'crm_accounts.csv',index=False)
    pd.DataFrame([['Stable County Jail','MA','Town'],['Named County Jail','MA','Town']],columns=['agency_name','state','city']).to_csv(tmp_path/'public_agencies.csv',index=False)
    baseline,_=scan(tmp_path);summary,items=scan(tmp_path,include_all=True)
    assert summary['current_cents']==baseline['current_cents']==160000
    assert len(items)==5
    assert any(x['name']=='Stable County Jail' and not x['evidence']['signals'] for x in items)
    assert any('missing_purchase_history' in x['holds'] for x in items)
    assert any(x['account_key'].startswith('UNRESOLVED|') for x in items)
    assert not next(x for x in items if x['name']=='Distributor Inc')['evidence']['signals']


def test_no_action_assessment_is_persisted_without_outreach(store,opportunity,decision):
    start_batch(store);job=store.claim()
    save_reviewed_fixture(store,job,{**decision,'decision':'no_action','subject':'','body':''})
    assert store.opportunity('example')['status']=='no_action'
    assert not store.rows('SELECT * FROM drafts')
    assert batches(store)[0]['counts']=={'completed':1}


def test_bulk_rejection_prevents_pending_followup_and_any_delivery(store,opportunity,decision):
    cid=create_campaign(store,'Reject',['example'],True);save_reviewed_fixture(store,store.claim(),decision)
    c=campaign_view(store,cid);d=c['members'][0]['draft']
    assert c['status']=='awaiting_approval'
    store.enqueue('followup',{},'example','future',due='2099-01-01')
    decide_campaign(store,cid,[{'draft_id':d['id'],'snapshot_hash':d['snapshot_hash']}],False)
    assert store.opportunity('example')['status']=='rejected'
    assert not store.rows("SELECT * FROM jobs WHERE status='queued'")
    assert not store.rows('SELECT * FROM outbox')


@pytest.mark.parametrize('mode',['pool','once'])
def test_credit_exhaustion_stops_model_queue_but_not_local_work(store,settings,opportunity,decision,mode):
    settings=replace(settings,concurrency=1,max_concurrency=1)
    ids=population(store,opportunity,2);start_batch(store,ids)
    calls=[]
    class Exhausted(Exception):status_code=429;code='credit_balance_exhausted'
    async def blocked(*args):
        calls.append(args[1]['id']);raise Exhausted()
    asyncio.run(execute_job(store,settings,store.claim(),blocked))
    assert len(calls)==1 and metrics(store)['api_blocked']['code']=='credit_balance_exhausted'
    # This local follow-up is obsolete and can be cancelled even while API access is blocked.
    store.enqueue('followup',{'parent_draft_id':'old'},ids[1],'billing-test-local')
    if mode=='pool':asyncio.run(run_pool(store,settings,blocked,drain=True,auto_brief=False))
    else:
        assert run_one(store,settings,blocked)
        assert not run_one(store,settings,blocked)
    assert len(calls)==1
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]['status']=='cancelled'
    assert len(store.rows("SELECT 1 FROM jobs WHERE kind='analyze' AND status='queued'"))==1
    store.retry(calls[0])
    assert not metrics(store)['api_blocked']
    async def funded(*args):return reviewed_fixture(store,args[1],decision)
    asyncio.run(run_pool(store,settings,funded,drain=True,auto_brief=False))
    assert len(store.rows("SELECT 1 FROM jobs WHERE kind='analyze' AND status='completed'"))==2


def test_drain_exits_when_paused_without_consuming_queue(store,settings,opportunity):
    start_batch(store);store.set_paused(True)
    asyncio.run(asyncio.wait_for(run_pool(store,settings,drain=True,auto_brief=False),timeout=2))
    assert store.rows("SELECT status FROM jobs WHERE kind='analyze'")[0]['status']=='queued'


def test_isolated_provider_failure_retries_without_misclassifying_rate_limit(store,settings,opportunity):
    class Gateway(Exception):status_code=520;code=None
    async def fail(*args):raise Gateway()
    store.queue_analysis('example');job=store.claim();cap=Capacity(replace(settings,concurrency=12,max_concurrency=24))
    asyncio.run(execute_job(store,settings,job,fail,cap))
    assert cap.current==12
    row=store.rows('SELECT status,attempts,error FROM jobs WHERE id=?',(job['id'],))[0]
    assert row['status']=='queued' and row['attempts']==1 and '520' in row['error']
    assert not store.rows("SELECT * FROM controls WHERE name='api_blocked'")


def test_clustered_provider_failures_reduce_concurrency(settings):
    cap=Capacity(replace(settings,concurrency=12,max_concurrency=24))
    cap.transient_failure(5);cap.transient_failure(5)
    assert cap.current==12
    cap.transient_failure(5)
    assert cap.current==6 and cap.cooldown>0
