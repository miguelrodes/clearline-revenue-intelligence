import pandas as pd
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.data import scan


def test_account_transactions_are_read_only_scoped_and_paginated(settings,store):
    rows=[['one','2026-01-15','Example County Jail','','Town','MA','direct','CL-FEN','10','10','100','invoiced'],
          ['two','2026-02-01','Example County Jail','','Town','MA','direct','CL-FEN','20','10','200','open'],
          ['unknown-date','','Example County Jail','','Town','MA','direct','CL-FEN','3','10','30','invoiced'],
          ['other','2026-02-02','Other County Jail','','City','NY','direct','CL-FEN','20','10','200','invoiced']]
    pd.DataFrame(rows,columns=['order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','unit_price','line_total','status']).to_csv(settings.data_dir/'orders.csv',index=False)
    pd.DataFrame([['CL-FEN','Fentanyl swabs',10,10,12]],columns=['sku','name','tests_per_pack','list_price_until_2025_06_30','list_price_from_2025_07_01']).to_csv(settings.data_dir/'products.csv',index=False)
    pd.DataFrame([['c','Example County Jail','MA','Owner','','']],columns=['crm_id','account_name','state','owner','notes','last_contacted']).to_csv(settings.data_dir/'crm_accounts.csv',index=False)
    pd.DataFrame([['Example County Jail','MA','Town']],columns=['agency_name','state','city']).to_csv(settings.data_dir/'public_agencies.csv',index=False)
    summary,items=scan(settings.data_dir,include_all=True);store.save_scan(summary,items)
    account=next(i for i in items if i['state']=='MA' and i['evidence'].get('source_rows'))
    api=TestClient(create_app(settings))
    tables=['opportunities','jobs','drafts','events','approvals','outbox']
    before={t:store.rows(f'SELECT * FROM {t}') for t in tables}
    url=f"/api/accounts/{account['id']}/orders"
    first=api.get(url,params={'limit':1}).json()
    assert first['account_id']==account['id']
    assert first['items'][0]['order_id']=='two'
    assert first['items'][0]['status']=='open'
    assert first['next_offset']==1
    all_rows=api.get(url,params={'limit':100}).json()['items']
    assert 'other' not in {r['order_id'] for r in all_rows}
    assert {r['source_row'] for r in all_rows}==set(account['evidence']['source_rows'])
    last=api.get(url,params={'offset':1,'limit':100}).json()
    assert last['next_offset'] is None
    assert api.get(url,params={'offset':-1}).status_code==422
    assert api.get(url,params={'limit':101}).status_code==422
    assert api.get('/api/accounts/missing/orders').status_code==404
    assert before=={t:store.rows(f'SELECT * FROM {t}') for t in tables}
