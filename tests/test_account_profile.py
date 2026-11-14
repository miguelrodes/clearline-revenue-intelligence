import copy
import csv
import hashlib
import json
import pytest
from clearline.account_profile import describe_account, account_profiles


def account(key='ID|state_prison|lone tree', name='ID DOC - Lone Tree', **evidence):
    return {'id': 'sample', 'name': name, 'state': 'ID', 'account_key': key, 'holds': [],
            'evidence': {'as_of': '2026-11-01', 'source_rows': [2], **evidence}}


def order(**changes):
    return {'ref': 'orders:2', 'bill_to_account': 'ID DOC - Lone Tree', 'end_customer': '',
            'sales_channel': 'direct', 'status': 'invoiced', 'qty': '5', 'order_date': '2026-01-01', **changes}


def test_end_buyer_direct_and_deterministic_description():
    a=account(); before=copy.deepcopy(a)
    p=describe_account(a,[order()])
    assert (p['account_type'],p['purchasing_channel']) == ('End buyer','Direct')
    assert p['description']=='Correctional facility in Idaho with a history of purchasing directly from Clearline.'
    assert a==before


def test_distributor_inventory_is_direct_but_does_not_make_it_an_end_buyer():
    a=account('DISTRIBUTOR|buyer|range line distributors','Range Line Distributors');a['state']='MULTI'
    p=describe_account(a,[order(sales_channel='distributor',bill_to_account=a['name'],end_customer='')])
    assert (p['account_type'],p['purchasing_channel'])==('Distributor','Direct')
    assert p['description']=='Distributor with a history of purchasing directly from Clearline.'
    assert 'MULTI' not in p['description']


def test_documented_end_customer_and_both_routes():
    a=account(source_rows=[2,3])
    r=order(sales_channel='distributor',bill_to_account='Range Line Distributors',end_customer=a['name'])
    assert describe_account(a,[r])['purchasing_channel']=='Through distributor'
    assert describe_account(a,[r,order(ref='orders:3')])['purchasing_channel']=='Both'


def test_unattributed_distributor_inventory_is_not_end_buyer_evidence():
    a=account();a['holds']=['known_distributor_channel']
    p=describe_account(a,[order(sales_channel='distributor',bill_to_account='Range Line Distributors',end_customer='')])
    assert p['purchasing_channel']=='Unknown'


@pytest.mark.parametrize('note,expected',[('Switched to distributor','Through distributor'),('May have switched to distributor','Unknown'),('Not switched to distributor','Unknown')])
def test_explicit_crm_route_only(note,expected):
    assert describe_account(account(crm_id='C1',crm_notes=note))['purchasing_channel']==expected


def test_ambiguous_identity_and_conflicting_roles_stay_unknown():
    a=account();a['holds']=['ambiguous_identity']
    p=describe_account(a,[order()])
    assert p['account_type']==p['purchasing_channel']=='Unknown'
    assert 'need confirmation' in p['description']
    a['holds']=[]
    p=describe_account(a,[order(sales_channel='distributor')])
    assert p['account_type']==p['purchasing_channel']=='Unknown'


@pytest.mark.parametrize('changes',[{'status':'open'},{'status':'credit_memo','qty':'-5'},{'order_date':''},{'order_date':'2027-01-01'}])
def test_open_credits_unknown_dates_and_future_orders_do_not_prove_purchases(changes):
    assert describe_account(account(),[order(**changes)])['purchasing_channel']=='Unknown'


def test_missing_institution_and_location_readable():
    a=account('UNRESOLVED|unknown|example','Example');a['state']=''
    p=describe_account(a)
    assert p['account_type']==p['purchasing_channel']=='Unknown'
    assert 'UNRESOLVED' not in p['description'] and 'Idaho' not in p['description']
    a=account('ID|state_prison|lone tree',crm_id='C1');a['state']=''
    p=describe_account(a)
    assert p['description']=='Correctional facility recorded in Clearline’s CRM, with no confirmed purchasing route.'


def test_unlinked_rows_cannot_establish_a_route():
    assert describe_account(account(source_rows=[]),[order()])['purchasing_channel']=='Unknown'


def test_api_profile_reads_preserve_business_state_and_fail_closed_on_changed_source(settings,store,opportunity):
    from clearline.services import ApplicationService
    path=settings.data_dir/'orders.csv'
    row=order(bill_to_account=opportunity['name']);row.pop('ref')
    with path.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    opportunity['evidence'].update(source_rows=[2],as_of='2026-11-01')
    store.save_scan({'hashes':{'orders':hashlib.sha256(path.read_bytes()).hexdigest()}},[opportunity])
    service=ApplicationService(settings,store)
    tables=['opportunities','jobs','events','drafts','approvals','outbox']
    before={t:store.rows(f'SELECT * FROM {t}') for t in tables}
    detail=service.detail(opportunity['id']);listing=service.get_opportunities()
    assert detail['organization_profile']==listing[0]['organization_profile']
    assert detail['organization_profile']['purchasing_channel']=='Direct'
    assert before=={t:store.rows(f'SELECT * FROM {t}') for t in tables}
    path.write_text(path.read_text()+'\n')
    assert service.detail(opportunity['id'])['organization_profile']['purchasing_channel']=='Unknown'


def test_different_named_end_customer_does_not_prove_this_account_purchased():
    assert describe_account(account(),[order(sales_channel="distributor",bill_to_account="Range Line Distributors",end_customer="Different buyer")])["purchasing_channel"]=="Unknown"
