"""Fictional peer spending is limited to a matching dated, direct-invoice cohort."""
import json

import pytest

from clearline.prospect_comparables import comparable_purchases


HASHES = {'orders': 'orders-test', 'products': 'products-test', 'public_agencies': 'agencies-test'}


def install_buyer(store, index, value, *, classification='verified_existing', extra=(), source_hashes=HASHES):
    name = f'County {index} Detention Center'
    row = dict(source='order', sales_channel='direct', status='invoiced', sku='CL-MAIL50', qty='1',
               order_date='2026-01-01', bill_to_account=name, order_id=f'order-{index}', unit_price=str(value),
               line_total=str(value), ship_to_city='Example', ship_to_state='KS')
    evidence = dict(provenance='fictional_agency_dataset',source_hashes=source_hashes,as_of='2026-11-01',
                    agency=[dict(agency_name=name, city='Example', state='KS')], identity_conflicts=[],
                    fit_hypothesis_skus=['CL-MAIL50'], products=[dict(sku='CL-MAIL50',name='Mailroom screening kit, 50 tests')],
                    relationship_records=[row,*(dict(row,**overrides) for overrides in extra)])
    with store.connect(write=True) as con:
        con.execute("""INSERT INTO agency_screenings(id,name,state,agency_type,classification,priority,evidence_hash,evidence,updated_at)
                       VALUES(?,?,'KS','county_jail',?,1,'test',?,'test')""",
                    (str(index), name, classification, json.dumps(evidence)))


@pytest.fixture
def scanned(store):
    store.save_scan({'as_of': '2026-11-01', 'hashes': HASHES}, [])
    return store


def test_net_basket_median_is_limited_to_verified_direct_purchases(scanned):
    for index, amount in enumerate([10,20,40,50]):
        install_buyer(scanned,index,amount)
    install_buyer(scanned,4,100,extra=[
        dict(order_id='credit',order_date='2026-10-31',status='credit_memo',qty='-1',line_total='-70.25'),
        dict(sales_channel='distributor',line_total='400'),
        dict(status='open',line_total='300'),dict(sku='training',line_total='200'),
        dict(order_date='2025-12-31',line_total='200'),dict(order_date='2026-11-01',line_total='200')])
    for index, category in enumerate(['ambiguous_identity','possible_existing_channel','unverified_prospect'],5):
        install_buyer(scanned,index,300,classification=category)
    install_buyer(scanned,9,110,source_hashes={**HASHES,'orders':'old-snapshot'})
    install_buyer(scanned,10,1000,extra=[dict(order_date='')])
    install_buyer(scanned,11,1000,extra=[dict(bill_to_account='Alternate name')])
    install_buyer(scanned,12,1000,extra=[dict(ship_to_state='OH')])
    install_buyer(scanned,13,1000,extra=[{}])  # indistinguishable repeated invoice line
    rows = scanned.rows('SELECT id,evidence_hash FROM agency_screenings ORDER BY id')
    text = comparable_purchases(scanned)['county_jail']
    assert 'Across 5 county detention facilities' in text
    assert '$29.75 per buyer' in text and 'Jan 1–Oct 31, 2026' in text and 'invoices less credits' in text
    assert scanned.rows('SELECT id,evidence_hash FROM agency_screenings ORDER BY id') == rows
    assert not scanned.rows('SELECT * FROM jobs')


def test_sparse_and_unmatched_segments_have_only_supported_qualitative_evidence(scanned):
    install_buyer(scanned,1,500)
    result = comparable_purchases(scanned)
    assert 'bought the mailroom screening kit directly' in result['county_jail']
    assert 'Fewer than five' in result['county_jail'] and '$' not in result['county_jail']
    assert 'does not establish' in result['sheriff']
    assert 'no established product fit' in result['drug_court']


def test_no_financial_model_without_a_matching_accounting_snapshot(store):
    install_buyer(store,1,1000)
    assert 'does not establish' in comparable_purchases(store)['county_jail']
