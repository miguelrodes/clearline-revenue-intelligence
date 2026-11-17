import json

from clearline.evidence import EvidenceAccess
from clearline.agent import behavioral_issues


def test_verified_finding_covers_the_ledger_and_keeps_source_drilldown(store, opportunity, settings, monkeypatch):
    oid = opportunity['id']
    base = dict(order_id='routine', order_date='2026-01-05', status='invoiced',
                sku='swab', sales_channel='distributor', qty='2', line_total='8.75')
    rows = [dict(base, ref=f'orders:{i}', order_id=str(i)) for i in range(100)]
    rows.extend([
        dict(base, ref='orders:100', order_id='invoice-1'),
        dict(base, ref='orders:101', order_id='invoice-1-CR', status='credit_memo', qty='-1', line_total='-4.25'),
        dict(base, ref='orders:102', order_id='open-1', status='open'),
        dict(base, ref='orders:103', order_date=''),
        dict(base, ref='orders:104', order_id='open-1'),
    ])
    evidence = dict(opportunity['evidence'], source_rows=list(range(len(rows))))
    with store.connect(write=True) as con:
        con.execute('UPDATE opportunities SET evidence=? WHERE id=?', (json.dumps(evidence), oid))
    job = dict(id=None, opportunity_id=oid, kind='analyze')
    monkeypatch.setattr(EvidenceAccess, 'source', lambda self, name: rows if name=='orders' else [])
    unmodified = EvidenceAccess(store, job, settings)
    assert not unmodified.finding_review
    assert json.loads(unmodified.purchasing())['next_offset'] == 100
    with store.connect(write=True) as con:
        con.execute('INSERT INTO investigation_resolutions VALUES(?,?,?,?)', ('task', oid, 'Verified finding', '2026-11-01'))
    access = EvidenceAccess(store, job, settings)
    packet = access.finding_packet()
    assert access.finding_review
    summary = packet['purchases:all:0']
    assert summary['total'] == len(rows) and summary['next_offset'] is None
    assert sum(r[3] for r in summary['invoice_totals']) == 103
    assert sum(r[5] for r in summary['invoice_totals']) == 103 * 875
    assert sum(int(r[4]) for r in summary['invoice_totals']) == 103 * 2
    assert summary['january_october']['2026'] == {'purchase_dates':1,'open_value_cents':875,'credit_cents':-425}
    assert summary['january_october']['2025'] == {'purchase_dates':0,'open_value_cents':0,'credit_cents':0}
    assert {r['ref'] for r in summary['detail_rows']} == {r['ref'] for r in rows[100:]}
    assert packet['overview']['internal_resolutions'][0]['resolution']=='Verified finding'
    assert not behavioral_issues(dict(decision='hold', citations=[{'ref':'orders:102'}]), access)
    assert json.loads(access.purchasing(status='ref:orders:14'))['rows'] == [rows[14]]
    assert json.loads(access.purchasing(status='order:open-1'))['rows'] == [rows[102], rows[104]]
    assert json.loads(access.purchasing(100,'raw'))['rows'] == rows[100:]


def test_previous_decisions_can_be_summarized_without_losing_full_record(store, opportunity, settings):
    access = EvidenceAccess(store, dict(opportunity_id=opportunity['id'], id=None), settings)
    access.finding_review = True
    prior = dict(decision='hold', recommended_action='Confirm fulfillment', commercial_review={'evidence':'Detailed review'})
    store.event('agent_decision', prior, opportunity_id=opportunity['id'])
    short = json.loads(access.previous())['assessments'][0]
    full = json.loads(access.previous(full=True))['assessments'][0]
    assert short['ref']==full['ref']
    assert short['details']==dict(decision='hold', recommended_action='Confirm fulfillment')
    assert full['details']==prior
