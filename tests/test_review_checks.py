import copy
import csv
import io
import json
from hashlib import sha256
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.data import digest
from clearline.briefing import snapshot
from clearline.review_checks import review_batches, batch_details, batch_csv


def item(base, oid, holds, signals=True, decline=10000, source_rows=None):
    x=copy.deepcopy(base)
    x.update(id=oid,account_key=oid,name=f'Customer {oid}',holds=holds,decline_cents=decline)
    x['evidence'].update(holds=holds,signals=[{'type':'inactivity'}] if signals else [],source_rows=source_rows or [])
    x['evidence_hash']=digest(x['evidence'])
    return x


def test_groups_only_recovery_signals_counts_overlap_and_preserves_holds(store,opportunity):
    xs=[item(opportunity,'one',['open_orders_require_review'],decline=100),
        item(opportunity,'both',['open_orders_require_review','known_distributor_channel'],decline=100000),
        item(opportunity,'background',['ambiguous_identity'],signals=False),
        item(opportunity,'identity',['ambiguous_identity','identity_needs_review']),
        item(opportunity,'DISTRIBUTOR|test',['known_distributor_channel']),
        item(opportunity,'stopped',['open_orders_require_review']),
        item(opportunity,'unknown',['new_hold'])]
    store.save_scan({},xs)
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET status='deferred' WHERE id='stopped'")
    before=store.rows('SELECT * FROM opportunities ORDER BY id')
    result=review_batches(store)
    assert (result['held_records'],result['priority_records'],result['background_records'])==(6,4,2)
    groups={g['id']:g for g in result['groups']}
    assert [m['id'] for m in groups['orders']['members']]==['one','both']
    assert groups['orders']['only_check_accounts']==1
    assert groups['identity']['only_check_accounts']==1
    assert sum(g['accounts'] for g in groups.values())==5 # four unique records, one in two lists
    assert groups['other']['accounts']==1
    state=snapshot(store)
    action=next(a for a in state['actions'] if a['id']=='check:orders')
    assert action['href']=='/actions?group=check%3Aorders' and action['historical_decline_cents'] is None
    assert action['scope_label']=='2 customer records'
    assert not any(a['id']=='holds' for a in state['actions'])
    assert store.rows('SELECT * FROM opportunities ORDER BY id')==before


def sources(settings,store,opportunity):
    fields=['order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','status','line_total']
    rows=[['OPEN','2026-10-01','Customer','', 'Town','MA','direct','TEST','3','open','30'],
          ['INVOICED','2026-10-01','Customer','', 'Town','MA','direct','TEST','1','invoiced','10'],
          ['UNDATED','','Customer','', 'Town','MA','direct','TEST','1','invoiced','10'],
          ['FUTURE','2026-12-01','Customer','', 'Town','MA','direct','TEST','1','open','10'],
          ['OTHER','2026-10-01','Different customer','', 'Town','MA','direct','TEST','1','open','10']]
    with (settings.data_dir/'orders.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(fields);w.writerows(rows)
    (settings.data_dir/'products.csv').write_text('sku,tests_per_pack\nTEST,10\n')
    hashes={name:sha256((settings.data_dir/f'{name}.csv').read_bytes()).hexdigest() for name in ('orders','products')}
    x=item(opportunity,'customer',['open_orders_require_review','undated_history'],source_rows=[2,3,4,5])
    store.save_scan({'as_of':'2026-11-01','hashes':hashes},[x])


def test_request_export_uses_actual_assigned_orders_and_is_read_only(settings,store,opportunity):
    sources(settings,store,opportunity)
    before={t:store.rows(f'SELECT * FROM {t}') for t in ('opportunities','scans','jobs','drafts','approvals','outbox','events')}
    api=TestClient(create_app(settings))
    assert api.get('/api/checks').json()['priority_records']==1
    detail=api.get('/api/checks/orders').json()
    assert detail['members'][0]['order_ids']==['OPEN']
    assert detail['delivery_status']=='Not sent'
    assert 'records' not in detail
    download=api.get('/api/checks/orders/export')
    assert download.status_code==200 and 'attachment;' in download.headers['content-disposition']
    rows=list(csv.DictReader(io.StringIO(download.text)))
    assert [x['order_id'] for x in rows]==['OPEN']
    assert rows[0]['response']==rows[0]['supporting_reference']==''
    dates=api.get('/api/checks/dates').json()
    assert dates['members'][0]['order_ids']==['UNDATED']
    assert api.get('/api/checks/invented/export').status_code==422
    assert before=={t:store.rows(f'SELECT * FROM {t}') for t in before}


def test_changed_source_is_rejected_even_after_cached_read(settings,store,opportunity):
    sources(settings,store,opportunity)
    detail=batch_details(store,settings,'orders');assert not detail['source_error']
    path=settings.data_dir/'orders.csv';path.write_text(path.read_text().replace('OPEN,','CHANGED,'))
    api=TestClient(create_app(settings))
    assert api.get('/api/checks/orders').json()['source_error']
    assert api.get('/api/checks/orders/export').status_code==409


def test_missing_sources_do_not_export_and_formula_cells_are_inert(settings,store,opportunity):
    store.save_scan({},[item(opportunity,'one',['open_orders_require_review'])])
    assert TestClient(create_app(settings)).get('/api/checks/orders/export').status_code==409
    csv_text=batch_csv({'source_error':None,'records':[{'customer':' =HYPERLINK("https://example.test")','account_owner':'+command','response':'normal'}]})
    row=next(csv.DictReader(io.StringIO(csv_text)))
    assert row['customer'].startswith("' =") and row['account_owner']=="'+command"
    assert row['response']=='normal'
