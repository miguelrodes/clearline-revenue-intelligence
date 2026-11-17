from commercial_fixtures import save_reviewed_fixture
import json
from fastapi.testclient import TestClient

from clearline.api import create_app
from clearline.worker import run_one


def client(settings):
    return TestClient(create_app(settings), headers={"X-Clearline-Client":"web"})


def payload(d):
    return {k:d[k] for k in ("version","recipient","subject","body")}


def test_reads_do_not_mutate_sales_records_and_missing_accounts_are_404(settings,store,draft):
    api=client(settings)
    counts={t:len(store.rows(f"SELECT * FROM {t}")) for t in ("jobs","drafts","approvals","events","outbox")}
    for route in ("/overview","/opportunities","/accounts/example","/activity","/actions","/health"):
        r=api.get('/api'+route)
        assert r.status_code==200, r.text
    assert api.get('/api/accounts/missing').status_code==404
    assert counts=={t:len(store.rows(f"SELECT * FROM {t}")) for t in counts}


def test_edit_approve_simulate_and_reply_survive_api_restart(settings,store,draft):
    api=client(settings)
    unsaved={**payload(draft),"subject":"Edited purchasing check-in"}
    assert api.post(f"/api/drafts/{draft['id']}/decision",json={**unsaved,"approve":True}).status_code==409
    assert not store.rows("SELECT * FROM approvals")
    r=api.patch(f"/api/drafts/{draft['id']}",json=unsaved)
    assert r.status_code==200, r.text
    new=store.rows("SELECT * FROM drafts WHERE id=?",(r.json()['draft_id'],))[0]
    assert new['version']==2
    assert api.post(f"/api/drafts/{draft['id']}/decision",json={**payload(draft),"approve":True}).status_code==409
    assert not store.rows("SELECT id FROM jobs WHERE kind IN ('review_sent','revise_draft')")
    decision={**payload(new),"approve":True}
    assert api.post(f"/api/drafts/{new['id']}/decision",json=decision).status_code==200
    assert api.post(f"/api/drafts/{new['id']}/decision",json=decision).status_code==409
    run_one(store,settings)
    restarted=client(settings)
    detail=restarted.get('/api/accounts/example').json()
    assert detail['status']=='awaiting_response'
    assert len(detail['outbox'])==1
    assert detail['outbox'][0]['delivery_mode']=='simulated'
    assert len([j for j in detail['jobs'] if j['kind']=='followup' and j['status']=='queued'])==1
    assert restarted.post('/api/accounts/example/outcomes',json={"kind":"reply","note":"Synthetic integration reply"}).status_code==200
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]['status']=='cancelled'
    assert store.rows("SELECT provenance FROM outcomes")[0]['provenance']=='manual_demo_input'


def test_stale_evidence_and_held_accounts_cannot_be_approved(settings,store,draft,opportunity):
    api=client(settings)
    opportunity['evidence_hash']='changed'
    store.save_scan({},[opportunity])
    assert api.get('/api/accounts/example').json()['drafts'][0]['can_review'] is False
    assert api.post(f"/api/drafts/{draft['id']}/decision",json={**payload(draft),"approve":True}).status_code==409
    opportunity['holds']=['ambiguous_identity']
    store.save_scan({},[opportunity])
    assert api.post('/api/accounts/example/assess',json={'evidence_hash':'changed'}).status_code==202
    assert not store.rows("SELECT * FROM approvals")


def test_foreign_origin_and_plain_form_requests_cannot_mutate(settings):
    api=TestClient(create_app(settings))
    assert api.post('/api/scan',json={}).status_code==403
    assert api.post('/api/scan',json={},headers={'X-Clearline-Client':'web','Origin':'https://example.com'}).status_code==403
    assert not api.app.state.store.rows("SELECT * FROM jobs")


def test_manual_assessment_and_retry_are_bounded_and_worker_owned(settings,store,opportunity,decision):
    api=client(settings)
    body={'evidence_hash':opportunity['evidence_hash']}
    first=api.post('/api/accounts/example/assess',json=body)
    assert first.status_code==202
    assert api.post('/api/accounts/example/assess',json=body).json()==first.json()
    assert not store.rows("SELECT * FROM drafts")
    async def boundary(*args): return decision
    run_one(store,settings,analyst=boundary)
    assert api.get('/api/accounts/example').json()['status']=='awaiting_approval'
    assert len(api.get('/api/accounts/example').json()['drafts'])==1 # explicit fixture authorization
    assert api.post('/api/accounts/example/assess',json={**body,'rerun':True}).status_code==409
    body.update(rerun=True,request_id='00000000-0000-4000-8000-000000000001')
    rerun=api.post('/api/accounts/example/assess',json=body)
    assert rerun.status_code==202
    assert api.post('/api/accounts/example/assess',json=body).json()==rerun.json()
    assert len(store.rows("SELECT * FROM jobs"))==2


def test_real_prospect_is_not_in_recovery_kpis(settings,store,opportunity):
    from clearline.prospects import seed_prospects
    seed_prospects(store,settings.as_of)
    api=client(settings)
    assert len(api.get('/api/opportunities').json())==1
    assert len(api.get('/api/opportunities?workflow=prospecting').json())==2
    assert api.get('/api/overview').json()['counts']['accounts']==1
    assert api.get('/api/health').json()['alive'] is False


def test_monthly_reporting_matches_authoritative_scan(settings,tmp_path):
    from clearline.data import scan
    from clearline.reporting import monthly_trends
    from clearline.store import Store
    # This test's fixture is built explicitly below; comparisons verify independent aggregation.
    orders=[['1','2025-01-15','Example County Jail','','Town','MA','direct','CL-FEN','10','10','100','invoiced'],
            ['2','2026-01-15','Example County Jail','','Town','MA','direct','CL-FEN','-2','10','-20','credit_memo'],
            ['3','2026-02-01','Example County Jail','','Town','MA','direct','CL-FEN','20','10','200','open'],
            ['4','2026-11-01','Example County Jail','','Town','MA','direct','CL-FEN','30','10','300','invoiced'],
            ['5','','Example County Jail','','Town','MA','direct','CL-FEN','3','10','30','invoiced']]
    import pandas as pd
    pd.DataFrame(orders,columns=['order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','unit_price','line_total','status']).to_csv(tmp_path/'orders.csv',index=False)
    pd.DataFrame([['CL-FEN','Fentanyl swabs',10,10,12]],columns=['sku','name','tests_per_pack','list_price_until_2025_06_30','list_price_from_2025_07_01']).to_csv(tmp_path/'products.csv',index=False)
    pd.DataFrame([['c','Example County Jail','MA','Owner','','']],columns=['crm_id','account_name','state','owner','notes','last_contacted']).to_csv(tmp_path/'crm_accounts.csv',index=False)
    pd.DataFrame([['Example County Jail','MA','Town']],columns=['agency_name','state','city']).to_csv(tmp_path/'public_agencies.csv',index=False)
    summary,items=scan(tmp_path)
    store=Store(settings.db_path);store.save_scan(summary,items)
    trends=monthly_trends(store,settings)['rows']
    for period in ('prior','current'):
        assert sum(r[period+'_cents'] for r in trends)==summary[period+'_cents']
        assert sum(r[period+'_tests'] for r in trends)==summary[period+'_tests']
    api=client(settings)
    for year,period in [(2025,'prior'),(2026,'current')]:
        ledger=api.get(f'/api/transactions?year={year}')
        assert ledger.status_code==200, ledger.text
        assert ledger.json()['net_cents']==summary[period+'_cents']
        assert ledger.json()['tests']==summary[period+'_tests']
    assert api.get('/api/transactions?year=2027').status_code==422
    assert api.get('/api/transactions?offset=-1').status_code==422
