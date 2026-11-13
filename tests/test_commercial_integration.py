import copy,json
from dataclasses import replace
from datetime import datetime,timezone
import pytest
from clearline.commercial import CATEGORIES,detect,persist_investigation,refresh_message_signals,resolved_category
from clearline.commercial_agent import strategy_accepted
from clearline.evidence import EvidenceAccess,context_hash,ENGINE_VERSION
from clearline.agent import behavioral_issues
from clearline.operations import start_batch,batches
from clearline.services import ApplicationService
from clearline.reporting import valid_draft
from test_commercial import good_review,certified
from test_data import data_dir,write_csv,order
from clearline.data import scan,ScanPolicy,digest

@pytest.mark.parametrize('category',CATEGORIES)
def test_each_supported_signal_is_persisted_not_silently_dropped(store,opportunity,category):
    opportunity['evidence']['commercial_signals']=[dict(id='signal',category=category,trigger_key='source',evidence={'calculation':'fixture'},amount_cents=100)]
    store.save_scan({},[opportunity]);assert store.rows('SELECT * FROM commercial_signals')[0]['investigation_status']=='pending'
    a={'context_hash':'ctx','commercial_plan':{'signal_decisions':[dict(signal_id='signal',disposition='no_action',reason='Explicit assessment') ]}}
    with store.connect(write=True) as c:persist_investigation(c,'example',a,'now')
    r=store.rows('SELECT * FROM commercial_signals')[0];assert r['disposition']=='no_action' and r['next_action']=='Explicit assessment'
    opportunity['evidence']['commercial_signals']=[];store.save_scan({},[opportunity]);assert not store.rows('SELECT * FROM commercial_signals')[0]['active']

@pytest.mark.parametrize('fraction,flagged',[(1,False),(.9,False),(.75,False),(.749,True),(.5,True),(0,True)])
def test_decline_and_sku_thresholds_from_source_rows(data_dir,fraction,flagged):
    write_csv(data_dir,'orders',[order('2025-10-01',10000,1000),order('2026-10-25',10000*fraction,int(1000*fraction) or 1)])
    _,items=scan(data_dir,include_all=True);signals={s['category'] for s in items[0]['evidence']['commercial_signals']}
    assert ('purchasing_decline' in signals)==flagged
    assert ('sku_deterioration' in signals)==flagged

@pytest.mark.parametrize('gap,flagged',[(89,False),(90,False),(91,True),(120,True)])
def test_inactivity_boundary_from_source_rows(data_dir,gap,flagged):
    from datetime import date,timedelta
    last=date(2026,11,1)-timedelta(days=gap)
    write_csv(data_dir,'orders',[order((last-timedelta(days=i*30)).isoformat(),1000,100) for i in (0,1,2,3)])
    _,items=scan(data_dir,include_all=True)
    assert ('inactive_recovery' in {s['category'] for s in items[0]['evidence']['commercial_signals']})==flagged

@pytest.mark.parametrize('outcome',['internal_investigation','human_verification','defer','no_action'])
def test_supervisor_can_agree_with_noncontact_outcome(outcome):
    r=good_review();r['verdict']=outcome
    assert strategy_accepted(r,{'outcome':outcome})
    r['timing']['passed']=False;assert not strategy_accepted(r,{'outcome':outcome})

def test_all_material_pages_and_identity_are_mandatory(store,opportunity,settings):
    access=EvidenceAccess(store,{'id':None,'opportunity_id':'example'},settings)
    access.accessed={'overview','catalogue','identity','purchases:all:0','relationships:0'}
    access.outputs={'purchases:all:0':{'next_offset':100},'relationships:0':{'next_offset':100}}
    assert len(behavioral_issues({'decision':'hold'},access))==2
    access.accessed|={'purchases:all:100','relationships:100'}
    assert not behavioral_issues({'decision':'hold'},access)
    access.accessed.remove('identity');assert behavioral_issues({'decision':'hold'},access)

def test_raw_order_currency_unit_is_declared(store,opportunity,settings,monkeypatch):
    access=EvidenceAccess(store,{'id':None,'opportunity_id':'example'},settings)
    monkeypatch.setattr(access,'orders',lambda:[])
    value=json.loads(access.purchasing());assert value['units']['line_total']=='USD dollars'

def test_simulator_or_wrong_channel_never_grants_permission(store,opportunity,settings):
    svc=ApplicationService(settings)
    with pytest.raises(ValueError):svc.authorize_contact('example','simulation@example.invalid','Buyer','direct','Synthetic address only',True)
    with store.connect(write=True) as c:c.execute("UPDATE opportunities SET holds='[\"known_distributor_channel\"]' WHERE id='example'")
    with pytest.raises(ValueError):svc.authorize_contact('example','buyer@example.org','Buyer','direct','Downstream contact',True)
    assert not store.rows('SELECT * FROM contact_authorizations')

def test_blocking_task_resolution_queues_evidence_aware_reassessment(store,opportunity,decision,settings):
    with store.connect(write=True) as c:
        persist_investigation(c,'example',{'context_hash':decision['context_hash'],'verification_tasks':[dict(title='Reconcile credit',owner='Finance',reason='Unknown reason',evidence_refs=['orders:2'],blocking=True)]},'now')
        before=context_hash(c,'example')
    task=store.rows('SELECT * FROM investigation_tasks')[0]
    response=ApplicationService(settings).resolve_investigation(task['id'],'Finance found a duplicate invoice and applied credit. Reference F-1.')
    with store.connect() as c:assert context_hash(c,'example')!=before
    assert response['requires_reassessment'] and store.rows('SELECT status FROM investigation_tasks')[0]['status']=='resolved'
    assert len(store.rows('SELECT * FROM jobs'))==1

def test_no_duplicate_unresolved_task_on_same_evidence(store,opportunity):
    a={'context_hash':'first','verification_tasks':[dict(title='Check order',owner='Orders',reason='Need disposition',evidence_refs=['orders:2'],blocking=True)]}
    with store.connect(write=True) as c:
        persist_investigation(c,'example',a,'one');a['context_hash']='second';persist_investigation(c,'example',a,'two')
    assert len(store.rows('SELECT * FROM investigation_tasks'))==1

def test_resolution_of_unrelated_order_does_not_unlock_current_order(store,opportunity):
    with store.connect(write=True) as c:
        c.execute("INSERT INTO commercial_signals VALUES('sig','example','aging_open_order','old',?,100,1,'pending',NULL,NULL,NULL,'now')",(json.dumps({'rows':['orders:2','orders:3']}),))
        c.execute("INSERT INTO investigation_tasks VALUES('t','example','ctx','Check','Ops','Reason',?,1,'resolved','now')",(json.dumps(['orders:2']),))
        c.execute("INSERT INTO investigation_resolutions VALUES('t','example','Verified other line','now')")
        assert not resolved_category(c,'example','aging_open_order')
        c.execute("UPDATE investigation_tasks SET evidence_refs=?",(json.dumps(['orders:2','orders:3']),))
        assert resolved_category(c,'example','aging_open_order')

def test_elapsed_time_generates_new_cached_context_once(store,opportunity,decision):
    value=certified(store,'example',decision);value['reassess_at']='2026-01-01T00:00:00+00:00'
    store.queue_analysis('example');job=store.claim();store.save_analysis(job,value)
    jid=store.queue_analysis('example',investigation=True)
    assert jid!=job['id'] and store.queue_analysis('example',investigation=True)==jid


def test_distributor_own_account_is_not_downstream_contact(store,opportunity,decision):
    from clearline.action_policy import permitted,proposal_fingerprint
    o=store.opportunity('example');o.update(account_key='DISTRIBUTOR|buyer|supplier',holds=['known_distributor_channel'])
    a=copy.deepcopy(decision);a['commercial_plan']['route']='direct';a['quality']['proposal_hash']=proposal_fingerprint(a)
    assert permitted(o,a)
    o['account_key']='MA|buyer|institution';assert not permitted(o,a)

def test_source_aging_threshold_is_configurable_through_existing_service(store,opportunity,settings):
    from clearline.contracts import ScanInput
    result=ApplicationService(settings).run_scan(ScanInput(open_order_review_days=60))
    row=store.rows("SELECT payload FROM jobs WHERE kind='scan'")[0]
    assert json.loads(row['payload'])['policy']['open_order_review_days']==60


def test_simulated_request_creates_separate_cited_signal_and_rescan_keeps_it(store,draft,opportunity):
    from clearline.transport import SimulatedProvider
    store.decide(draft['id'],True);job=store.claim();store.deliver(job);store.finish(job['id'])
    parent=store.rows("SELECT * FROM messages WHERE direction='outbound'")[0]
    result=SimulatedProvider(store).ingest('example',parent['id'],'request-fixture','We need training for the night shift. We are interested in mailroom kits.')
    rows=store.rows('SELECT * FROM commercial_signals WHERE active=1');assert {r['category'] for r in rows}=={'purchasing_obstacle','cross_sell'}
    assert all(json.loads(r['evidence'])['message_ref']=='message:'+result['message_id'] for r in rows)
    store.save_scan({},[opportunity]);assert len(store.rows('SELECT * FROM commercial_signals WHERE active=1'))==2
    assert not store.rows("SELECT * FROM approvals WHERE draft_id!=?",(draft['id'],))

def test_reassessment_invalidates_old_approval_but_preserves_history(store,opportunity,decision,draft):
    store.decide(draft['id'],True)
    with store.connect(write=True) as c:c.execute("UPDATE contact_authorizations SET evidence='New authorization evidence' WHERE opportunity_id='example'")
    store.queue_analysis('example',investigation=True);j=store.claim(['analyze'])
    a=copy.deepcopy(decision)
    with store.connect() as c:a['context_hash']=context_hash(c,'example')
    a.update(decision='hold',subject='',body='',quality=None,commercial_plan=None)
    store.save_analysis(j,a)
    assert store.rows('SELECT status FROM drafts')[0]['status']=='superseded'
    assert store.rows("SELECT status FROM jobs WHERE kind='deliver'")[0]['status']=='cancelled'
    assert len(store.rows('SELECT * FROM approvals'))==1
    assert not store.rows('SELECT * FROM outbox')


def test_distinct_task_purposes_with_same_owner_and_evidence_are_preserved(store,opportunity):
    tasks=[dict(title=t,owner='Sales',reason='Distinct purpose',evidence_refs=['account'],blocking=True) for t in ['Confirm recipient','Clarify training need']]
    with store.connect(write=True) as c:persist_investigation(c,'example',{'context_hash':'ctx','verification_tasks':tasks},'now')
    assert len(store.rows('SELECT * FROM investigation_tasks'))==2


def test_current_internal_decision_stops_unsent_followup_preserving_delivery(store,opportunity,decision,draft):
    store.decide(draft['id'],True);send=store.claim();store.deliver(send);store.finish(send['id'])
    a=copy.deepcopy(decision)
    with store.connect() as c:a['context_hash']=context_hash(c,'example')
    a.update(decision='hold',subject='',body='',quality=None,commercial_plan={'outcome':'internal_investigation','signal_decisions':[]})
    store.queue_analysis('example',investigation=True);job=store.claim(['analyze']);store.save_analysis(job,a)
    assert store.opportunity('example')['status']=='internal_investigation'
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]['status']=='cancelled'
    assert len(store.rows('SELECT * FROM outbox'))==1 and len(store.rows('SELECT * FROM approvals'))==1


def test_message_interest_uses_all_history_ownership(store,draft,opportunity):
    from clearline.transport import SimulatedProvider
    opportunity['owned_product_skus']=['CL-MAIL50']
    store.save_scan({},[opportunity]);store.decide(draft['id'],True)
    job=store.claim();store.deliver(job);store.finish(job['id'])
    parent=store.rows("SELECT * FROM messages WHERE direction='outbound'")[0]
    SimulatedProvider(store).ingest('example',parent['id'],'ownership-fixture','We are interested in mailroom kits.')
    assert not store.rows("SELECT * FROM commercial_signals WHERE active=1 AND category='cross_sell'")


@pytest.mark.parametrize('title,duplicate',[
 ('Obtain separate human approval of the exact proposed communication',True),
 ('Review the pending support draft only after authorization is established',True),
 ('Keep the existing support draft unreleased pending authorization review',True),
 ('Verify the facility behind SO-103454 and establish its approved contact',False),
 ('Record explicit recipient authorization and disposition the pending draft',False),
 ('Review the historical support concern and gate the pending draft',False),
 ('Hold the existing draft and conditionally complete the existing Oregon-recipient task',False),
])
def test_execution_controls_are_distinct_from_missing_business_facts(title,duplicate):
    from clearline.commercial import workflow_control_task
    assert workflow_control_task({'title':title})==duplicate


def test_approval_bookkeeping_is_not_a_business_blocker_but_approval_is_required(store,draft):
    with store.connect(write=True) as c:c.execute("INSERT INTO investigation_tasks VALUES('control','example','ctx','Obtain separate human approval of the exact communication','Sales','Handled by approval screen','[]',1,'pending','now')")
    assert valid_draft(store,draft)
    assert not store.rows('SELECT * FROM approvals') and not store.rows('SELECT * FROM outbox')
    store.decide(draft['id'],True)
    assert len(store.rows('SELECT * FROM approvals'))==1 and not store.rows('SELECT * FROM outbox')
    job=store.claim();store.deliver(job)
    assert len(store.rows('SELECT * FROM outbox'))==1


def test_existing_task_reference_prevents_reworded_duplicates_and_scope_changes(store,opportunity):
    task=dict(title='Confirm order disposition',owner='Orders',reason='No fulfillment record',evidence_refs=['orders:2'],blocking=True)
    with store.connect(write=True) as c:persist_investigation(c,'example',{'context_hash':'one','verification_tasks':[task]},'now')
    existing=store.rows('SELECT * FROM investigation_tasks')[0]
    replacement={**task,'title':'Complete the existing order status investigation','existing_task_id':existing['id']}
    with store.connect(write=True) as c:persist_investigation(c,'example',{'context_hash':'two','verification_tasks':[replacement]},'later')
    assert len(store.rows('SELECT * FROM investigation_tasks'))==1
    replacement['evidence_refs']=['orders:3']
    with pytest.raises(ValueError):
        with store.connect(write=True) as c:persist_investigation(c,'example',{'context_hash':'three','verification_tasks':[replacement]},'later')
