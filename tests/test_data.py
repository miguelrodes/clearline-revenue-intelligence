import csv
import pytest
from clearline.data import canonical, scan, ScanPolicy


def write_csv(folder,name,rows):
    with (folder / (name+".csv")).open("w",newline="") as f:
        w = csv.DictWriter(f,fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def order(date,value=100,qty=10,status="invoiced",sku="TEST10",channel="direct",state="MA"):
    return dict(order_id=f"{date}-{sku}-{status}",order_date=date,bill_to_account="Example County Jail" if channel=="direct" else "Example Distributor",
                end_customer="" if channel=="direct" else "Example Co Detention",ship_to_city="Sample City",ship_to_state=state,
                sales_channel=channel,sku=sku,qty=str(qty),unit_price=str(value/qty),line_total=str(value),status=status)


@pytest.fixture
def data_dir(tmp_path):
    write_csv(tmp_path,"products",[
        dict(sku="TEST10",name="Example test pack",tests_per_pack="10",list_price_until_2025_06_30="10",list_price_from_2025_07_01="12"),
        dict(sku="CL-TRN",name="Training",tests_per_pack="1",list_price_until_2025_06_30="50",list_price_from_2025_07_01="50")])
    write_csv(tmp_path,"crm_accounts",[dict(crm_id="test",account_name="Example County Jail",state="MA",owner="Test",notes="",last_contacted="2025-01-01")])
    write_csv(tmp_path,"public_agencies",[dict(agency_name="Example County Jail",state="MA",city="Sample City")])
    return tmp_path


PRIOR = [order("2025-01-01"),order("2025-02-01"),order("2025-03-01")]


def test_credits_open_services_price_and_volume(data_dir):
    write_csv(data_dir,"orders",PRIOR+[order("2026-01-01",120),order("2026-01-02",-12,-1,"credit_memo"),
        order("2026-01-03",50,1,sku="CL-TRN"),order("2026-02-01",200,20,"open")])
    summary,items = scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    assert summary["net_cents_whole_export"] == 45800
    assert summary["current_tests"] == 90
    product = next(x for x in items[0]["evidence"]["products"] if x["sku"]=="TEST10")
    assert product["constant_list_value_change_cents"] == -21000
    assert "open_orders_require_review" in items[0]["holds"]


def test_missing_dates_hold_and_duplicates_remain(data_dir):
    write_csv(data_dir,"orders",PRIOR+[PRIOR[0],order("")])
    summary,items=scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    assert summary["net_cents_whole_export"] == 50000
    assert summary["prior_cents"] == 40000
    assert summary["undated_lines"] == 1 and summary["duplicate_excess_retained"] == 1
    assert "undated_history" in items[0]["holds"]


def test_distributor_purchase_suppresses_false_inactivity(data_dir):
    write_csv(data_dir,"orders",PRIOR+[order("2026-10-30",channel="distributor")])
    _,items=scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    kinds=[s["type"] for s in items[0]["evidence"]["signals"]]
    assert "inactivity" not in kinds and "direct_gap_channel_review" in kinds
    assert "known_distributor_channel" in items[0]["holds"]


def test_as_of_purchase_suppresses_stale_alert_but_stays_out_of_ytd(data_dir):
    write_csv(data_dir,"orders",PRIOR+[order("2026-11-01")])
    summary,items=scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    assert summary["current_cents"]==0
    assert "inactivity" not in [s["type"] for s in items[0]["evidence"]["signals"]]


def test_partial_product_decline_can_exist_while_account_grows(data_dir):
    write_csv(data_dir,"orders",PRIOR+[order("2026-10-30",12,1),order("2026-10-30",1000,20,sku="CL-TRN")])
    _,items=scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    assert items[0]["decline_cents"]==0
    assert [s["type"] for s in items[0]["evidence"]["signals"]]==["product_decline"]


def test_missing_state_alias_requires_review(data_dir):
    write_csv(data_dir,"orders",PRIOR+[order("2026-10-30",state="")])
    _,items=scan(data_dir,ScanPolicy(minimum_prior_revenue=1))
    assert "possible_missing_state_alias" in items[0]["holds"]


def test_identity_never_merges_sheriff_and_jail_or_conflicting_state():
    assert canonical("Example County Jail","MA")[0] != canonical("Example County Sheriff","MA")[0]
    assert canonical("MA DOC - Example","CA")[0] == ""
    assert canonical("Example County Jail","")[0] == ""


def test_unattended_scan_runs_in_separate_worker_process(data_dir,tmp_path):
    import os
    import subprocess
    import sys
    import time
    from clearline.store import Store
    write_csv(data_dir,"orders",PRIOR)
    database=tmp_path/"scheduled.sqlite3"
    store=Store(database)
    store.schedule(1,analysis_limit=0)
    env={**os.environ,"CLEARLINE_DB_PATH":str(database),"CLEARLINE_DATA_DIR":str(data_dir),"OPENAI_API_KEY":""}
    process=subprocess.Popen([sys.executable,"-m","clearline.cli","worker"],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if store.rows("SELECT * FROM scans"): break
            if process.poll() is not None: raise AssertionError(process.stderr.read().decode())
            time.sleep(.1)
        assert store.rows("SELECT * FROM scans")
        assert not store.rows("SELECT * FROM jobs WHERE kind='analyze'")
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize('changed_source',['orders','crm_accounts','public_agencies','products'])
def test_relevant_source_details_invalidate_assessment_without_changing_finances(data_dir,changed_source):
    write_csv(data_dir,'orders',PRIOR)
    before,items=scan(data_dir,include_all=True)
    with (data_dir/(changed_source+'.csv')).open(newline='') as f:rows=list(csv.DictReader(f))
    field,value={'orders':('order_id','REVISED-REFERENCE'),'crm_accounts':('notes','Night shift asks for training'),
                 'public_agencies':('city','Corrected City'),'products':('name','Corrected product name')}[changed_source]
    rows[0][field]=value;write_csv(data_dir,changed_source,rows)
    after,updated=scan(data_dir,include_all=True)
    assert updated[0]['id']==items[0]['id']
    assert updated[0]['evidence_hash']!=items[0]['evidence_hash']
    for key in ('prior_cents','current_cents','prior_tests','current_tests','net_cents_whole_export','duplicate_excess_retained'):
        assert before[key]==after[key]


def test_evidence_tools_retrieve_all_ambiguous_crm_and_public_records(data_dir,settings,store):
    from dataclasses import replace
    import json
    from clearline.evidence import EvidenceAccess
    write_csv(data_dir,'orders',PRIOR)
    with (data_dir/'crm_accounts.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    rows.append({**rows[0],'crm_id':'second','notes':'Training question'})
    write_csv(data_dir,'crm_accounts',rows)
    summary,items=scan(data_dir,include_all=True);store.save_scan(summary,items)
    oid=items[0]['id'];store.queue_analysis(oid,investigation=True);job=store.claim()
    access=EvidenceAccess(store,job,replace(settings,data_dir=data_dir))
    relationships=json.loads(access.relationships());identity=json.loads(access.identity())
    assert {x['crm_id'] for x in relationships['crm']}=={'test','second'}
    assert identity['public_matches'][0]['agency_name']=='Example County Jail'
    assert 'ambiguous_identity' in store.opportunity(oid)['holds']
