"""Commercial policy regressions; expected results fixed independently of model output."""
import json
from dataclasses import replace
from datetime import date,timedelta
import pytest
from clearline.commercial import detect,associations,CommercialPolicy,CATEGORIES,execution_issues
from clearline.commercial_agent import review_passes
from clearline.action_policy import permitted,proposal_fingerprint
from clearline.evidence import context_hash,ENGINE_VERSION


def evidence(**kw):return dict(account_key='MA|buyer|example',as_of='2026-11-01',signals=[],products=[],holds=[],prior_cents=1000000,current_cents=500000,decline_cents=500000,**kw)
def order(day,status='invoiced',sku='A',qty='10',value='100'):
    return dict(order_id='SO-'+day,order_date=day,status=status,sku=sku,qty=qty,line_total=value,ref='orders:'+day,sales_channel='direct')

@pytest.mark.parametrize('age',[0,1,7,29,30,31,60,120])
def test_open_age_review_threshold_not_sla(age):
    d=(date(2026,11,1)-timedelta(days=age)).isoformat();s=detect(evidence(),[order(d,'open')])
    assert any(x['category']=='aging_open_order' for x in s)==(age>=30)
    assert not any(x['category']=='inactive_recovery' for x in s)

@pytest.mark.parametrize('dates,expected',[
 (['2026-01-01'],False),(['2026-01-01','2026-02-01','2026-03-01'],False),
 (['2026-01-01','2026-02-01','2026-03-01','2026-04-01'],True),
 (['2026-07-01','2026-08-01','2026-09-01','2026-10-31'],False),
 (['2025-01-01','2026-01-01','2026-01-02','2026-10-01'],False)])
def test_cadence(dates,expected):
    s=detect(evidence(),[order(d) for d in dates]);assert any(x['category']=='missed_replenishment' for x in s)==expected

def test_recent_open_order_is_explicit_replenishment_counterevidence():
    s=detect(evidence(),[order(d) for d in ['2026-01-01','2026-02-01','2026-03-01','2026-04-01']]+[order('2026-10-31','open')])
    replen=next(x for x in s if x['category']=='missed_replenishment');assert replen['evidence']['recent_open_orders']==['SO-2026-10-31']

@pytest.mark.parametrize('fraction,expected',[(0,True),(.5,True),(.749,True),(.75,False),(.9,False),(1.2,False)])
def test_distributor_own_decline(fraction,expected):
    e=evidence();e.update(account_key='DISTRIBUTOR|buyer|D',current_cents=int(1000000*fraction))
    assert any(x['category']=='distributor_recovery' for x in detect(e,[]))==expected

@pytest.mark.parametrize('note,expected',[("Wants training for night shift",True),('Captain retired - new contact TBD',True),('Complained about color read in low light',True),('Asked about grant funding',True),('Prefers email',False),('',False)])
def test_documented_obstacle(note,expected):assert any(s['category']=='purchasing_obstacle' for s in detect(evidence(crm_notes=note),[]))==expected

@pytest.mark.parametrize('owned,interest,expected',[(False,True,True),(True,True,False),(False,False,False),(True,False,False)])
def test_explicit_cross_sell(owned,interest,expected):
    e=evidence(crm_notes='Interested in mailroom kit' if interest else '')
    if owned:e['products']=[dict(sku='CL-MAIL50',prior_packs_or_sessions=1)]
    assert any(s['category']=='cross_sell' for s in detect(e,[]))==expected

@pytest.mark.parametrize('credit,complaint,expected',[(True,False,True),(False,True,True),(True,True,True),(False,False,False)])
def test_churn_is_investigation_not_diagnosis(credit,complaint,expected):
    rows=[order('2026-06-01','credit_memo',qty='-10',value='-100')] if credit else []
    s=detect(evidence(crm_notes='Complained about color read in low light' if complaint else ''),rows)
    assert any(x['category']=='churn_prevention' for x in s)==expected

@pytest.mark.parametrize('kind,category',[('inactivity','inactive_recovery'),('reduced_purchasing','purchasing_decline'),('product_decline','sku_deterioration')])
def test_all_existing_signals_preserved(kind,category):
    e=evidence();e['signals']=[dict(type=kind,sku='A')];assert category in {s['category'] for s in detect(e,[])}

def test_overlap_has_distinct_persistent_ids_and_no_total_claim():
    e=evidence();e['signals']=[{'type':'inactivity'},{'type':'reduced_purchasing'},{'type':'product_decline','sku':'A'}]
    rows=detect(e,[]);assert len(rows)==len({r['id'] for r in rows})==3

def basket(i,skus):return dict(account_key=f'MA|buyer|{i}',holds=[],products=[dict(sku=s,current_packs_or_sessions=1) for s in skus])

def test_association_positive_and_small_sample_negative():
    population=[basket(i,['A','B']) for i in range(30)]+[basket(i,['C']) for i in range(30,100)]
    ab=next(r for r in associations(population) if r['antecedent']=='A' and r['consequent']=='B')
    assert ab['reliable'] and ab['pair_accounts']==30 and ab['confidence']==1 and ab['lift']>3
    assert not any(r['reliable'] for r in associations(population[:5]))

def test_ubiquitous_products_not_cross_sell_evidence():assert not any(r['reliable'] for r in associations([basket(i,['A','B']) for i in range(100)]))

def good_review():return {'verdict':'approve',**{k:{'passed':True,'explanation':'Fixture verified'} for k in ('revenue_objective','evidence','timing','intervention','recipient_channel','prerequisites','commercial_value')},'explanation':'Fixture'}
@pytest.mark.parametrize('criterion',['revenue_objective','evidence','timing','intervention','recipient_channel','prerequisites','commercial_value'])
def test_critical_failure_cannot_pass(criterion):
    r=good_review();r[criterion]['passed']=False;assert not review_passes(r)

def certified(store,oid,value):
    o=store.opportunity(oid)
    route='distributor' if 'known_distributor_channel' in o['holds'] or value.get('action_scope')=='channel_support' else 'direct'
    with store.connect(write=True) as c:
        c.execute('INSERT OR REPLACE INTO contact_authorizations VALUES(?,?,?,?,?,?,?)',(oid,'buyer@example.org','Purchasing',route,'Explicit fictional test authorization',1,'2026-11-13'))
        version=context_hash(c,oid)
    plan=dict(signal_decisions=[],outcome='contact',recipient='buyer@example.org',route=route,objective='Restore documented purchasing',timing='Overdue cadence',intervention='Discuss supply requirements')
    a={**value,'engine_version':ENGINE_VERSION,'context_hash':version,'evidence_hash':o['evidence_hash'],'recipient':'buyer@example.org','commercial_plan':plan,'commercial_review':good_review(),'verification_tasks':[],'action_scope':value.get('action_scope','recovery'),'quality':{'passed':True}}
    a['quality']['proposal_hash']=proposal_fingerprint(a);return a

def test_ordinary_account_no_quality_bypass(store,opportunity,decision):
    legacy={k:v for k,v in decision.items() if k not in ('quality','engine_version','commercial_plan','commercial_review')}
    assert not permitted(store.opportunity('example'),legacy)
    a=certified(store,'example',decision);assert permitted(store.opportunity('example'),a)
    a['body']='Changed';assert not permitted(store.opportunity('example'),a)

def test_blocking_prerequisite_prevents_individual_and_simulated_delivery(store,opportunity,decision):
    a=certified(store,'example',decision);store.queue_analysis('example');j=store.claim();store.save_analysis(j,a);d=store.rows('select * from drafts')[0]
    with store.connect(write=True) as c:c.execute('INSERT INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)',('blocking','example','ctx','Verify','Owner','Missing fact','[]',1,'pending','now'))
    with pytest.raises(ValueError):store.decide(d['id'],True)
    assert not store.rows('select * from approvals')
    with store.connect(write=True) as c:c.execute("UPDATE investigation_tasks SET status='resolved'")
    store.decide(d['id'],True);delivery=store.claim()
    with store.connect(write=True) as c:c.execute("UPDATE contact_authorizations SET authorized=0")
    with pytest.raises(ValueError):store.deliver(delivery)
    assert not store.rows('select * from outbox')


@pytest.mark.parametrize('day',['2024-03-03','2025-11-13',''])
def test_cross_sell_does_not_mistake_outside_window_purchase_for_missing_product(day):
    e=evidence(crm_notes='Interested in mailroom kit')
    signals=detect(e,[order(day,sku='CL-MAIL50')])
    assert not any(s['category']=='cross_sell' for s in signals)
