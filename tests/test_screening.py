import csv,json,asyncio
from pathlib import Path
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from clearline.config import Settings
from clearline.store import Store
from clearline.screening import screen,summary,listing,detail,queue,save_result
from clearline.screening_agent import Access,issues,passes,Decision
from clearline.api import create_app
from clearline.worker import execute_job

@pytest.fixture
def env(tmp_path):
    data=tmp_path/'data';data.mkdir()
    tables={
      'public_agencies':[dict(agency_name='Example County Detention Center',agency_type='county_jail',state='KS',county='Example',city='Example City',population_served='10000',jail_beds='300',in_hidta_region='yes',fy_end='06-30')],
      'products':[dict(sku='CL-MAIL50',name='Mailroom screening kit, 50 tests',tests_per_pack='50',list_price_until_2025_06_30='140',list_price_from_2025_07_01='154')],
      'orders':[dict(order_id='SO-1',order_date='2026-10-01',bill_to_account='Other County Jail',end_customer='',ship_to_state='KS',ship_to_city='Other City',sales_channel='direct',sku='CL-MAIL50',qty='4',unit_price='154',line_total='616',status='invoiced')],
      'crm_accounts':[dict(crm_id='CRM-1',account_name='Other County Jail',state='KS',owner='Sales',notes='',last_contacted='2026-10-01')],
    }
    def write():
        for name,rows in tables.items():
            with (data/(name+'.csv')).open('w') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    write();settings=Settings(tmp_path/'state.sqlite3',data,screening_enabled=True);store=Store(settings.db_path)
    return settings,store,tables,write

def first(env):
    settings,store,_,_=env;screen(store,settings);return detail(store,listing(store)['items'][0]['id'])

def plan(outcome='qualified'):
    return dict(outcome=outcome,summary='Internal discovery priority',rationale='Potential mail screening application',product_fit=[dict(sku='CL-MAIL50',application_hypothesis='Mail screening may fit',limitation='Need unverified')],reasons_against=['Unknown need'],missing_information=['No authorized contact'],next_task='Check internal segment knowledge before any contact',task_owner='Sales operations',alternative='Defer',change_conditions='Verified operational use',evidence_refs=['public_agencies:2','products:2'])

def test_complete_persistent_repeatable_and_no_outreach(env):
    settings,store,tables,_=env;r=first(env)
    assert r['classification']=='unverified_prospect' and r['priority']==1
    assert r['evidence']['segment_patterns']['product_buyers']['CL-MAIL50']==1
    before=store.rows('SELECT * FROM agency_screenings');screen(store,settings)
    assert Store(settings.db_path).rows('SELECT * FROM agency_screenings')==before
    assert summary(store)['source_records']==1
    for table in ('drafts','approvals','outbox','opportunities'):assert store.rows('SELECT * FROM '+table)==[]

@pytest.mark.parametrize('change,category',[
 ('exact_direct','verified_existing'),('channel','possible_existing_channel'),('alias','possible_existing_channel'),('crm_only','possible_existing_channel'),('missing_state','possible_existing_channel'),('city_conflict','ambiguous_identity'),('missing_city','ambiguous_identity'),('type_conflict','ambiguous_identity'),('unknown_type','unsuitable'),('future_order','unverified_prospect'),('open_order','possible_existing_channel'),('credit_only','possible_existing_channel')])
def test_identity_and_channel_boundaries(env,change,category):
    settings,store,t,w=env;a=t['public_agencies'][0];o=t['orders'][0]
    o.update(bill_to_account=a['agency_name'],ship_to_city=a['city'])
    if change=='channel':o.update(sales_channel='distributor',bill_to_account='Distributor',end_customer=a['agency_name'])
    if change=='alias':o['bill_to_account']='EXAMPLE CO JAIL'
    if change=='crm_only':o['bill_to_account']='Other Jail';t['crm_accounts'][0]['account_name']=a['agency_name']
    if change=='missing_state':o['ship_to_state']=''
    if change=='city_conflict':o['ship_to_city']='Different city'
    if change=='missing_city':a['city']=''
    if change=='type_conflict':a['agency_type']='police_dept'
    if change=='unknown_type':a.update(agency_name='Example Florist',agency_type='retail');o['bill_to_account']='Other Jail'
    if change=='future_order':o['order_date']='2026-11-02'
    if change=='open_order':o['status']='open'
    if change=='credit_only':o.update(status='credit_memo',qty='-4')
    w();assert first(env)['classification']==category


def test_dedupe_and_ambiguity_keep_all_source_rows(env):
    s,store,t,w=env;t['public_agencies'].append(dict(t['public_agencies'][0]));w();r=first(env)
    assert len(r['evidence']['agency'])==2 and summary(store)['exact_duplicate_rows']==1
    t['public_agencies'][1]['city']='Different';w();screen(store,s)
    assert summary(store)['source_records']==2 and summary(store)['unique_records']==2
    assert all(x['classification']=='ambiguous_identity' for x in listing(store)['items'])


def test_current_hash_queue_dedupe_and_source_change(env):
    s,store,t,w=env;r=first(env);a=queue(store,s,r['id'],r['evidence_hash']);assert queue(store,s,r['id'],r['evidence_hash'])==a
    j=store.claim(['agency_qualify']);t['orders'][0]['qty']='7';w();screen(store,s)
    with pytest.raises(ValueError):save_result(store,j,{'decision':plan()})
    with pytest.raises(ValueError):queue(store,s,r['id'],r['evidence_hash'])
    assert not store.rows('SELECT * FROM agency_qualifications')


def test_evidence_tools_and_rejection_guards(env):
    s,store,t,w=env;r=first(env);queue(store,s,r['id'],r['evidence_hash']);j=store.claim(['agency_qualify']);access=Access(store,j)
    assert issues(plan(),access)
    for section in ('agency','relationships','products','patterns'):access.get(section)
    assert issues(plan(),access)==[]
    for category in ('verified_existing','unsuitable','ambiguous_identity','possible_existing_channel'):
        access.e['classification']=category;assert issues(plan(),access)
    access.e['classification']='unverified_prospect';bad=plan();bad['evidence_refs']=['invented'];assert issues(bad,access)
    bad=plan();bad['product_fit'][0]['sku']='INVENTED';assert issues(bad,access)
    with pytest.raises(ValueError):Decision.model_validate({**plan(),'outcome':'send_email'})


def test_review_cannot_accept_critical_findings():
    r=dict(accepted=True,evidence_quality=True,product_suitability=True,identity_channel=True,commercial_relevance=True,prerequisites=True,worthwhile_next_step=True,no_fabrication=True,critical_findings=[],explanation='test')
    assert passes(r);r['critical_findings']=['Unauthorized approach'];assert not passes(r)
    r['critical_findings']=[];r['product_suitability']=False;assert not passes(r)


def test_paged_relationships_all_required(env):
    s,store,t,w=env
    o=t['orders'][0];o.update(bill_to_account=t['public_agencies'][0]['agency_name'],ship_to_city='Example City')
    t['orders']=[dict(o,order_id=str(i)) for i in range(55)];w();r=first(env);queue(store,s,r['id'],r['evidence_hash']);a=Access(store,store.claim(['agency_qualify']))
    for section in ('agency','relationships','products','patterns'):a.get(section)
    assert 'Read every relationship evidence page' in issues(plan('reject'),a)
    assert a.get('relationships',50)['next_offset'] is None
    assert issues(plan('reject'),a)==[]


def test_api_feature_flag_search_sort_queue_restart(env):
    s,store,t,w=env;r=first(env)
    disabled=TestClient(create_app(replace(s,screening_enabled=False)))
    assert disabled.get('/api/features').json()['prospect_screening'] is False
    assert disabled.get('/api/screening').status_code==404
    assert disabled.post('/api/screening/scan',headers={'X-Clearline-Client':'web'}).status_code==404
    api=TestClient(create_app(s),headers={'X-Clearline-Client':'web'})
    assert api.get('/api/screening').json()['source_records']==1
    assert api.get('/api/screening/agencies',params={'q':"' OR 1=1"}).json()['total']==0
    assert api.get('/api/screening/agencies',params={'classification':'unverified_prospect','sort':'state'}).json()['total']==1
    assert api.get('/api/screening/agencies',params={'sort':'injected'}).status_code==409
    response=api.post('/api/screening/agencies/'+r['id']+'/qualify',json={'evidence_hash':r['evidence_hash']});assert response.status_code==202
    assert TestClient(create_app(s)).get('/api/screening/agencies/'+r['id']).json()['jobs'][0]['id']==response.json()['job_id']
    assert not store.rows('SELECT * FROM drafts')


def test_shared_worker_save_and_cancel(env,monkeypatch):
    s,store,t,w=env;r=first(env);queue(store,s,r['id'],r['evidence_hash']);job=store.claim(['agency_qualify'])
    async def fake(*args):return {'decision':plan(),'review_passed':True,'outreach_eligible':False}
    monkeypatch.setattr('clearline.screening_agent.qualify',fake)
    asyncio.run(execute_job(store,s,job));assert detail(Store(s.db_path),r['id'])['qualification']['decision']['outcome']=='qualified'
    assert store.rows('SELECT status FROM jobs')[0]['status']=='completed'
    assert not store.rows('SELECT * FROM approvals') and not store.rows('SELECT * FROM outbox')
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job['id'],))
    with pytest.raises(ValueError):save_result(store,job,{'decision':plan()})


def test_mcp_flag_and_shared_data(env,monkeypatch):
    from test_mcp import TOKEN,call,data
    monkeypatch.setenv('CLEARLINE_MCP_TOKEN',TOKEN)
    s,store,t,w=env;r=first(env)
    for enabled in (False,True):
        with TestClient(create_app(replace(s,screening_enabled=enabled))) as api:
            response=api.post('/mcp',headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
            names=[x['name'] for x in response.json()['result']['tools']]
            assert ('get_prospect_screening' in names)==enabled
            if enabled:
                assert data(call(api,'get_prospect_screening'))['source_records']==1
                assert data(call(api,'get_screened_agency',{'agency_id':r['id']}))['name']==r['name']
                job=data(call(api,'qualify_screened_agency',{'agency_id':r['id'],'evidence_hash':r['evidence_hash']}))
                assert store.rows('SELECT id FROM jobs')[0]['id']==job['job_id']
                assert call(api,'get_account',{'account_id':r['id']})['isError']


def test_bounded_shortlist_skips_processed_and_deduplicates(env):
    from clearline.screening import queue_shortlist
    s,store,t,w=env
    for i in range(14):t['public_agencies'].append(dict(t['public_agencies'][0],agency_name=f'New {i} County Jail'))
    w();screen(store,s)
    first=queue_shortlist(store,s);assert len(first['job_ids'])==10
    second=queue_shortlist(store,s);assert len(second['job_ids'])==5
    assert not set(first['job_ids'])&set(second['job_ids'])
    assert queue_shortlist(store,s)['job_ids']==[]
    with pytest.raises(ValueError):queue_shortlist(store,s,11)


def test_rejected_and_unsupported_count_does_not_overlap(env):
    s,store,t,w=env;t['public_agencies'][0].update(agency_name='Florist',agency_type='retail');w();r=first(env)
    queue(store,s,r['id'],r['evidence_hash']);j=store.claim(['agency_qualify']);save_result(store,j,{'decision':plan('reject'),'review_passed':True})
    assert summary(store)['excluded_records']==1


def test_parallel_screening_pool_leaves_recovery_jobs_untouched(env,monkeypatch):
    from clearline.worker import run_pool
    s,store,t,w=env
    t['public_agencies'].append(dict(t['public_agencies'][0],agency_name='Second County Jail'));w();screen(store,s)
    for r in listing(store)['items']:queue(store,s,r['id'],r['evidence_hash'])
    recovery=store.enqueue('scan',{'analysis_limit':0})
    active=0;peak=0
    async def fake(*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active);await asyncio.sleep(.03);active-=1
        return {'decision':plan(),'review_passed':True,'outreach_eligible':False}
    monkeypatch.setattr('clearline.screening_agent.qualify',fake)
    asyncio.run(run_pool(store,replace(s,concurrency=2,max_concurrency=2),drain=True,auto_brief=False,kinds=['agency_scan','agency_qualify']))
    assert peak==2 and summary(store)['assessed']==2
    assert store.rows('SELECT status FROM jobs WHERE id=?',(recovery,))[0]['status']=='queued'
    assert not store.rows('SELECT * FROM drafts')
