"""Verified, offline read model: actions can explain facts without generating work."""
import csv
import json
from hashlib import sha256

import pytest

from clearline.data import digest
from clearline.evidence import ENGINE_VERSION, context_hash
from clearline.practical_actions import practical_actions
from clearline.store import utcnow
from clearline.task_purpose import agent_managed_task


@pytest.fixture
def case(store, settings):
    rowdata=[
        ('SO-100001','2026-10-20','CL-PAT25','59','9665.00','open'),
        ('SO-100001','2026-10-20','CL-MP10','3','300.00','open'),
        ('SO-100002','2026-09-29','CL-FS10','10','450.00','open'),
        ('SO-100003-CR','2025-09-25','CL-MAIL50','-2','-300.00','credit_memo'),
        ('SO-100002','2026-09-29','CL-FS10','2','90.00','invoiced'),
        ('SO-200001','2026-10-02','CL-FS10','4','180.00','open'), # different account
    ]
    path=settings.data_dir/'orders.csv'
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(('order_id','order_date','sku','qty','line_total','status'));w.writerows(rowdata)
    e={'name':'Sample buyer','source_rows':[2,3,4,5,6],'as_of':'2026-11-01','crm_id':'CRM-123','crm_notes':'Asked about night-shift training'}
    store.save_scan({'as_of':e['as_of'],'hashes':{'orders':sha256(path.read_bytes()).hexdigest()}},[
        {'id':'a','account_key':'AZ|county_jail|sample','name':e['name'],'state':'AZ','evidence':e,'evidence_hash':digest(e),'decline_cents':0,'holds':[]}])
    def task(tid,title,reason,refs,owner='Saved records owner',blocking=True):
        with store.connect(write=True) as con:
            con.execute('INSERT INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (tid,'a','prior',title,owner,reason,json.dumps(refs),int(blocking),'pending',utcnow()))
    def certify(decision='hold',status='internal_investigation'):
        with store.connect(write=True) as con:
            con.execute('UPDATE opportunities SET status=? WHERE id=?',(status,'a'))
            store.event('agent_decision',{'decision':decision,'review_failed':False,'engine_version':ENGINE_VERSION,
                'context_hash':context_hash(con,'a'),'evidence_hash':digest(e)},opportunity_id='a',con=con)
    certify()
    return task,certify,lambda:practical_actions(store,settings,'a')


def test_scoped_open_lines_consolidate_by_account_owner_and_purpose(case):
    task,_,actions=case
    task('one','Confirm status of open order SO-100001','Check actual shipment or invoice status.', ['orders:2','orders:3','orders:7'],'Order operations')
    task('two','Extend operational review to the other open order','Is SO-100002 still open?', ['orders:4','orders:6'],'Order operations')
    task('three','Explain the credit memo SO-100003-CR','Confirm the original invoice and reason for the credit.',['orders:5','orders:6'],'Billing')
    task('four','Reassess recovery need after the operational findings','Decide whether to keep monitoring.', ['purchasing'])
    groups=actions(); assert len(groups)==2
    fulfillment,billing=groups
    assert fulfillment['role_key']=='fulfillment' and 'responsible for processing' in fulfillment['role']
    assert fulfillment['task_ids']==['one','two'] and fulfillment['can_prepare_internal']
    assert [(r['order_id'],r['sku']) for r in fulfillment['lines']]==[('SO-100002','CL-FS10'),('SO-100001','CL-PAT25'),('SO-100001','CL-MP10')]
    assert {r['ref'] for r in fulfillment['lines']}=={'orders:2','orders:3','orders:4'}
    assert '$10,415.00' in fulfillment['found'] and '12–33 days' in fulfillment['found'] and 'does not establish a delay' in fulfillment['found']
    assert billing['role_key']=='billing' and billing['task_ids']==['three']
    assert billing['tasks'][0]['record_refs']==['orders:5'] and '$300.00' in billing['found']
    task('other','Check status of open order SO-100001','Check only this specific line.', ['orders:2'],'Other verified task assignment')
    assert len([g for g in actions() if g['role_key']=='fulfillment'])==2


def test_bad_source_never_becomes_a_verified_order_line(case,settings):
    task,_,actions=case
    task('one','Confirm status of open order SO-100001','Check fulfillment status.', ['orders:2'])
    assert actions()[0]['can_prepare_internal']
    (settings.data_dir/'orders.csv').write_text('modified source')
    g=actions()[0];assert not g['can_prepare_internal'] and not g['lines'] and '$' not in g['found']


def test_partial_order_evidence_cannot_generate_an_inquiry_for_the_entire_task(case):
    task, _, actions = case
    task('missing', 'Check the status of two open orders',
         'Check SO-100001 and SO-999999.', ['orders:2'])
    group = actions()[0]
    assert group['tasks'][0]['record_ids'] == ['SO-100001']
    assert not group['can_prepare_internal']
    assert 'Some requested order references could not be verified' in group['next_step']


def test_contact_training_identity_and_human_decision_controls(case,store):
    task,_,actions=case
    task('contact','Verify authorized purchasing recipient and route','Check permission for current supplies.', ['account','relationship'],'Dana K.')
    task('training','Check existing night-shift training interest','Find out whether the recorded night-shift training request was addressed.', ['crm_accounts:1'],'Dana K.')
    task('grant','Check existing evidence behind the funding inquiry','Check whether the recorded grant enquiry has a current deadline.', ['crm_accounts:1'],'Account owner')
    task('identity','Verify conflicting buyer identities and email route','Confirm which account owns the order and note; do not infer a match.', ['identity'],'Marcus T.')
    task('decision','Decide whether a commercial next step remains useful','Record the reason for deferral.', ['previous_work'])
    # A partial save is not contact authorization or a reason to reassess.
    with store.connect(write=True) as con:
        con.execute("INSERT INTO contact_clearance_notes(opportunity_id,role,route,verification_evidence,status,updated_at) VALUES('a','Buyer','direct','Synthetic verification record','partial',?)",(utcnow(),))
    groups={g['task_ids'][0]:g for g in actions()}
    g=groups['contact'];assert g['control']=='contact' and g['missing_contact_fields']==['recipient']
    assert 'Verify the purchasing email address' in g['next_step'] and not g['can_prepare_internal'] and g['assigned_owner']=='Dana K.'
    assert groups['training']['category']=='needs' and 'night-shift training' in groups['training']['found']
    assert groups['grant']['role_key']=='planning' and 'purchasing plans' in groups['grant']['role']
    assert 'does not establish a current need' in groups['training']['found'] and groups['training']['can_prepare_internal']
    assert groups['identity']['control']=='finding' and groups['identity']['role_key']=='records' and 'which organization' in groups['identity']['found']
    assert not groups['decision']['can_prepare_internal']
    assert store.rows('SELECT * FROM jobs')==[]


def test_stale_or_inactive_or_no_action_never_exposes_an_internal_request(case,store):
    task,certify,actions=case
    task('f','Check order SO-100001 fulfillment','Check verified status.',['orders:2'])
    assert len(actions())==1
    with store.connect(write=True) as con:
        con.execute("INSERT INTO investigation_resolutions VALUES('other','a','Verified new information',?)",(utcnow(),))
    assert not actions()
    for decision,status in [('no_action','no_action'),('no_action','monitor'),('hold','deferred'),('hold','opted_out')]:
        certify(decision,status); assert not actions()
    certify()
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET active=0 WHERE id='a'")
    assert not actions()


@pytest.mark.parametrize('title,agent_owned',[
    ('Reassess the training opportunity after the verified response',True),
    ('Requalify the expansion opportunity using verified actions',True),
    ('Reassess recovery need after the operational findings',True),
    ('Reconcile verified order disposition with the decline assessment',True),
    ('Reassess purchasing decline and verify the invoice status',False),
    ('Establish the reason for the decline, then reassess product interest',False),
    ('Verify recipient authorization before reconsidering the account',False),
    ('Reassess eligibility and identity for this account',False),
])
def test_agent_chores_are_not_human_checks(title,agent_owned):
    assert agent_managed_task({'title':title}) is agent_owned
