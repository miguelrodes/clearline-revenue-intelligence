import json
import pytest
from fastapi.testclient import TestClient
from clearline import internal_inquiries as inquiries
from clearline.api import create_app
from clearline.evidence import context_hash
from clearline.store import Store

SYNTHETIC_ROUTE={'recipient':'fulfillment@example.invalid','verification_evidence':'Synthetic acceptance: verified internal mailbox and responsibility against the test directory.'}


@pytest.fixture
def internal(store,settings,opportunity,monkeypatch,request):
    items=getattr(request,'param',[('SO-1','CL-MAIL50'),('SO-1','CL-FS10'),('SO-2','CL-FS10'),('SO-3','CL-MAIL50')])
    lines=[dict(ref=f'orders:{n}',order_id=o,sku=sku,qty=str(n),date='2026-10-01',status='open',amount_cents=n*100,age_days=31)
           for n,(o,sku) in enumerate(items,1)]
    focus=items[0][0]
    others=[line for line in lines if line['order_id']!=focus]
    tasks=[
        {'id':'one','title':f'Check order {focus}','question':f'Confirm the two open lines of {focus}.','blocking':True,
         'record_ids':[focus],'record_refs':[line['ref'] for line in lines if line['order_id']==focus]},
        {'id':'two','title':'Check the remaining open orders','question':'Confirm current status for all attached order references.','blocking':True,
         'record_ids':[line['order_id'] for line in others],'record_refs':[line['ref'] for line in others]},
        {'id':'credit','title':'Explain credit reason','question':'Confirm whether the historical credit is resolved.','blocking':False,'record_ids':[],'record_refs':[]},
        {'id':'contact','title':'Verify purchasing recipient','question':'Confirm existing purchasing recipient, route and permission.','blocking':True,'record_ids':[],'record_refs':[]},
    ]
    with store.connect(write=True) as con:
        for t in tasks:con.execute('INSERT INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)',(t['id'],'example','saved',t['title'],'Synthetic responsible owner',t['question'],json.dumps(t['record_refs']),int(t['blocking']),'pending','now'))
    def groups(store,settings,oid):
        pending={r['id'] for r in store.rows("SELECT id FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,))}
        groups=[]
        for key,ts in [('fulfillment',tasks[:2]),('billing',tasks[2:3]),('relationship',tasks[3:])]:
            ts=[t for t in ts if t['id'] in pending]
            if ts:groups.append(dict(id=key,role_key=key,role='Person responsible for '+key,task_ids=[t['id'] for t in ts],tasks=ts,
                               lines=[l for l in lines if any(l['ref'] in t['record_refs'] for t in ts)],can_prepare_internal=True))
        return groups
    monkeypatch.setattr('clearline.practical_actions.practical_actions',groups)
    return TestClient(create_app(settings),headers={'X-Clearline-Client':'web'})

PATH='/api/accounts/example/internal-inquiries'
def ok(resp):
    assert resp.status_code==200,resp.text
    return resp.json()

def test_internal_lifecycle_is_exact_scoped_persistent_and_never_customer_outreach(internal,store,settings):
    api=internal
    with store.connect() as con:before=context_hash(con,'example')
    assert ok(api.get(PATH))=={'recipients':[],'inquiries':[]}
    assert api.post(PATH,json={'group_id':'fulfillment','recipient':SYNTHETIC_ROUTE['recipient']}).status_code==409
    d=ok(api.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    p=PATH+'/'+d['id']
    assert d['status']=='awaiting_approval' and len(d['lines'])==4 and len(d['tasks'])==2
    assert all(x in d['body'] for x in ['SO-1','SO-2','SO-3','CL-MAIL50','CL-FS10'])
    assert 'credit reason' not in d['body'] and not store.rows('SELECT * FROM internal_deliveries')
    assert api.post(PATH,json={'group_id':'billing'}).status_code==409  # not same scope
    assert ok(api.post(PATH,json={'group_id':'fulfillment'}))['id']==d['id']
    assert api.post(p+'/reply',json={'body':'Not yet sent'}).status_code==409
    edit=ok(api.post(p+'/edit',json={'snapshot_hash':d['snapshot_hash'],'subject':d['subject'],'body':d['body']+'\nPlease include the shipment reference.'}))
    assert edit['version']==2 and edit['snapshot_hash']!=d['snapshot_hash']
    assert [(v['version'],v['subject'],v['body'],v['recipient']) for v in edit['previous_versions']]==[(1,d['subject'],d['body'],d['recipient'])]
    assert api.post(p+'/approve',json={'snapshot_hash':d['snapshot_hash']}).status_code==409
    for _ in range(2):
        assert ok(api.post(p+'/approve',json={'snapshot_hash':edit['snapshot_hash']}))['status']=='sent_simulated'
    assert len(store.rows('SELECT * FROM internal_deliveries'))==len(store.rows('SELECT * FROM internal_approvals'))==1
    assert api.post(p+'/edit',json={'snapshot_hash':edit['snapshot_hash'],'subject':'Change','body':'Different'}).status_code==409
    body='Synthetic internal reply: SO-1 reportedly shipped; other orders have not yet been checked.'
    r=ok(api.post(p+'/reply',json={'body':body}))['replies'][0]
    assert r['record_refs']==['SO-1'] and not r['confirmed_task_ids']
    assert r['suggested_findings']=={'one':body}
    assert ok(api.post(p+'/reply',json={'body':body}))['replies']==[r]
    with store.connect() as con:assert context_hash(con,'example')==before
    assert not store.rows('SELECT * FROM jobs')
    source='Synthetic test: checked carrier receipt TR-44 and packing list.'
    payload=lambda task,finding:{'reply_id':r['id'],'findings':[{'task_id':task,'finding':finding,'source':source}]}
    assert api.post(p+'/confirm',json=payload('credit','A credit was recorded.')).status_code==409
    assert api.post(p+'/confirm',json=payload('two','SO-2 shipped.')).status_code==409
    assert api.post(p+'/confirm',json=payload('one','SO-1 shipped.')).status_code==409 # ambiguous line coverage
    finding='Synthetic test: SO-1 both open lines shipped; invoice status remains pending.'
    done=ok(api.post(p+'/confirm',json=payload('one',finding)))
    assert done['pending_task_ids']==['two'] and done['status']=='reply_recorded' and done['job_id']
    assert ok(api.post(p+'/confirm',json=payload('one',finding)))['job_id']==done['job_id']
    assert ok(api.post(PATH,json={'group_id':'fulfillment'}))['id']==d['id']  # no second draft for outstanding order questions
    jobs=store.rows('SELECT kind,opportunity_id,payload FROM jobs')
    assert [(j['kind'],j['opportunity_id']) for j in jobs]==[('analyze','example')]
    with store.connect() as con:assert json.loads(jobs[0]['payload'])['context_hash']==context_hash(con,'example')!=before
    assert len(store.rows('SELECT * FROM internal_draft_versions'))==2
    for t in ('drafts','approvals','outbox','outcomes','messages','contact_authorizations'):
        assert store.rows('SELECT * FROM '+t)==[]
    assert [r['id'] for r in store.rows("SELECT id FROM investigation_tasks WHERE status='resolved'")]==['one']
    assert inquiries.list_inquiries(Store(settings.db_path),'example')['inquiries'][0]==done


def pending_communications(store):
    with store.connect() as con:
        return inquiries.task_communication_states(con)


@pytest.mark.parametrize('internal',[[
    ('SO-105040','CL-MAIL50'),('SO-105040','CL-FS10'),('SO-101546','CL-MAIL50'),
    ('SO-100219','CL-MP10'),('SO-100762','CL-FS10'),('SO-103115','CL-MP10'),
    ('SO-105677','CL-MAIL50'),('SO-104185','CL-MP10'),
]],indirect=True)
def test_range_line_status_by_requested_order_persists_through_partial_reply(internal,store,settings):
    first=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    p=PATH+'/'+first['id']
    assert first['workflow_state']=='awaiting_approval' and first['sent_at'] is None
    assert pending_communications(store)=={'one':'draft','two':'draft'}
    sent=ok(internal.post(p+'/approve',json={'snapshot_hash':first['snapshot_hash']}))
    assert sent['workflow_state']=='awaiting_response' and sent['sent_at'] and sent['sent_version']==1
    assert sent['recipient']==SYNTHETIC_ROUTE['recipient'] and len(sent['record_states'])==7
    assert len({ref for row in sent['record_states'] for ref in row['line_refs']})==8
    assert {row['status'] for row in sent['record_states']}=={'status_requested'}
    assert pending_communications(store)=={'one':'status_requested','two':'status_requested'}
    reply=ok(internal.post(p+'/reply',json={'body':'Synthetic fulfillment response: SO-105040 shipped.'}))
    assert reply['workflow_state']=='response_recorded'
    assert [row['order_id'] for row in reply['record_states'] if row['status']=='response_recorded']==['SO-105040']
    assert pending_communications(store)=={'one':'response_recorded','two':'status_requested'}
    assert not store.rows('SELECT * FROM jobs')
    finding='Synthetic verification: SO-105040 both lines shipped. Invoicing remains on hold.'
    done=ok(internal.post(p+'/confirm',json={'reply_id':reply['replies'][0]['id'],'findings':[
        {'task_id':'one','finding':finding,'source':'Synthetic carrier receipts and invoice ledger.'}]}))
    assert done['workflow_state']=='partially_verified' and done['reassessment_status']=='queued'
    assert {r['order_id']:r['status'] for r in done['record_states']}=={
        r['order_id']:('verified' if r['order_id']=='SO-105040' else 'status_requested') for r in sent['record_states']}
    assert done['task_states'][0]=={'task_id':'one','status':'verified','finding':finding}
    assert done['task_states'][1]['status']=='status_requested'
    assert pending_communications(store)=={'two':'status_requested'}
    assert ok(internal.post(PATH,json={'group_id':'fulfillment'}))['id']==first['id']
    reopened=inquiries.list_inquiries(Store(settings.db_path),'example')['inquiries']
    assert reopened==[done]
    assert [r['id'] for r in store.rows("SELECT id FROM investigation_tasks WHERE status='pending' ORDER BY id")]==['contact','credit','two']
    assert len(store.rows('SELECT * FROM internal_deliveries'))==len(store.rows('SELECT * FROM jobs'))==1


def test_record_projection_respects_multiple_orders_and_manual_resolutions(internal,store):
    draft=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    p=PATH+'/'+draft['id']
    ok(internal.post(p+'/approve',json={'snapshot_hash':draft['snapshot_hash']}))
    reply=ok(internal.post(p+'/reply',json={'body':'I can check tomorrow.'}))
    assert reply['workflow_state']=='response_recorded' and {r['status'] for r in reply['record_states']}=={'status_requested'}
    partial=ok(internal.post(p+'/reply',json={'body':'SO-2 appears to be on hold.'}))
    assert {r['order_id']:r['status'] for r in partial['record_states']}=={'SO-1':'status_requested','SO-2':'response_recorded','SO-3':'status_requested'}
    assert pending_communications(store)=={'one':'status_requested','two':'response_recorded'}
    finding='SO-1 both open lines remain on hold, verified against the synthetic ledger.'
    ok(internal.post('/api/investigations/one/resolve',json={'resolution':finding}))
    projection=ok(internal.get(PATH))['inquiries'][0]
    assert projection['task_states'][0]=={'task_id':'one','finding':finding,'status':'verified'}
    with store.connect(write=True) as con:
        con.execute("UPDATE investigation_tasks SET status='superseded' WHERE id='two'")
    closed=ok(internal.get(PATH))['inquiries'][0]
    assert closed['workflow_state']=='closed' and pending_communications(store)=={}
    assert {r['order_id']:r['status'] for r in closed['record_states']}=={'SO-1':'verified','SO-2':'closed','SO-3':'closed'}

def test_internal_draft_cannot_ship_after_evidence_or_account_changes(internal,store):
    a=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}));p=PATH+'/'+a['id']+'/approve'
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET evidence_hash='changed' WHERE id='example'")
    assert internal.post(p,json={'snapshot_hash':a['snapshot_hash']}).status_code==409
    b=ok(internal.post(PATH,json={'group_id':'fulfillment'}))
    assert b['id']==a['id'] and b['version']==2
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET status='no_action' WHERE id='example'")
    assert internal.post(p,json={'snapshot_hash':b['snapshot_hash']}).status_code==409
    assert internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}).status_code==409
    assert not store.rows('SELECT * FROM internal_approvals')

def test_internal_reply_does_not_grant_customer_permission(internal,store):
    d=ok(internal.post(PATH,json={'group_id':'relationship',**SYNTHETIC_ROUTE}));p=PATH+'/'+d['id']
    ok(internal.post(p+'/approve',json={'snapshot_hash':d['snapshot_hash']}))
    reply=ok(internal.post(p+'/reply',json={'body':'The current purchasing contact could be the procurement team.'}))
    result=internal.post(p+'/confirm',json={'reply_id':reply['replies'][0]['id'],'findings':[{'task_id':'contact','finding':'They have a buyer.','source':'Synthetic internal contact.'}]})
    assert result.status_code==409 and 'Contact Clearance' in result.text
    assert store.rows('SELECT * FROM contact_authorizations')==[]
    assert store.rows('SELECT status FROM investigation_tasks WHERE id="contact"')[0]['status']=='pending'
    assert not store.rows('SELECT * FROM jobs')

def test_batch_confirmation_rolls_back_all_findings_if_queue_cannot_commit(internal,store,monkeypatch):
    d=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}));p=PATH+'/'+d['id']
    ok(internal.post(p+'/approve',json={'snapshot_hash':d['snapshot_hash']}))
    rr=ok(internal.post(p+'/reply',json={'body':'Synthetic dispatch confirmation for SO-1, SO-2, SO-3.'}))['replies'][0]
    def fail(*args,**kw):raise ValueError('Queue unavailable')
    monkeypatch.setattr(Store,'_enqueue_analysis',fail)
    resp=internal.post(p+'/confirm',json={'reply_id':rr['id'],'findings':[{'task_id':'one','finding':'SO-1 both lines shipped.','source':'Synthetic manifest A'}, {'task_id':'two','finding':'SO-2, SO-3 shipped.','source':'Synthetic manifest B'}]})
    assert resp.status_code==409 and 'Queue unavailable' in resp.text
    assert not store.rows('SELECT * FROM investigation_resolutions') and not store.rows("SELECT id FROM investigation_tasks WHERE status='resolved'")

def test_direct_finding_also_requires_full_order_scope(internal,store):
    p='/api/investigations/one/resolve'
    for partial in ('Somebody said it shipped.', 'SO-1 has a shipped item.'):
        assert internal.post(p,json={'resolution':partial}).status_code==409
    assert internal.post('/api/investigations/two/resolve',json={'resolution':'SO-2 shipped per test dispatch log.'}).status_code==409
    assert not store.rows('SELECT * FROM jobs')
    assert ok(internal.post(p,json={'resolution':'SO-1: both open lines shipped per synthetic dispatch manifest.'}))['requires_reassessment']
    assert not store.rows('SELECT * FROM contact_authorizations')
    assert len(store.rows('SELECT * FROM jobs'))==1


def test_mixed_identity_finding_never_grants_contact_permission(internal,store):
    with store.connect(write=True) as con:
        con.execute("UPDATE investigation_tasks SET title='Verify identity and purchasing contact' WHERE id='contact'")
    result=internal.post('/api/investigations/contact/resolve',json={'resolution':'Synthetic purchasing ledger verified these aliases belong to the same institution. Contact permission remains unknown.'})
    assert ok(result)['requires_reassessment']
    assert store.rows('SELECT * FROM contact_authorizations')==[]
    assert store.rows('SELECT * FROM drafts')==[]

def test_reprepare_after_scope_change_reuses_draft_and_keeps_history(internal,store):
    first=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    with store.connect(write=True) as con:
        con.execute("UPDATE investigation_tasks SET status='superseded' WHERE id='two'")
    url=PATH+'/'+first['id']+'/approve'
    assert internal.post(url,json={'snapshot_hash':first['snapshot_hash']}).status_code==409
    current=ok(internal.post(PATH,json={'group_id':'fulfillment'}))
    assert (current['id'], current['version'], current['task_ids'])==(first['id'],2,['one'])
    assert 'SO-2' not in current['body']
    assert len(ok(internal.get(PATH))['inquiries'])==1
    assert internal.post(url,json={'snapshot_hash':first['snapshot_hash']}).status_code==409
    assert internal.post('/api/accounts/other/internal-inquiries/'+first['id']+'/approve',json={'snapshot_hash':current['snapshot_hash']}).status_code==409
    assert ok(internal.post(url,json={'snapshot_hash':current['snapshot_hash']}))['status']=='sent_simulated'


def test_email_cannot_ship_if_internal_recipient_is_now_a_customer(internal,store):
    first=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    with store.connect(write=True) as con:
        con.execute('INSERT INTO contact_authorizations VALUES(?,?,?,?,?,?,?)',('other',first['recipient'],'Buyer','direct','Synthetic confirmed buyer',1,'now'))
    assert internal.post(PATH+'/'+first['id']+'/approve',json={'snapshot_hash':first['snapshot_hash']}).status_code==409
    assert not store.rows('SELECT * FROM internal_deliveries')


def test_edited_email_cannot_claim_unrequested_orders_or_lines(internal,store):
    current=ok(internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}))
    p=PATH+'/'+current['id']
    original=current['body']
    for removed,order in [('• SO-2 |','SO-2'),('1 × CL-MAIL50','SO-1')]:
        body='\n'.join(line for line in original.splitlines() if removed not in line)
        current=ok(internal.post(p+'/edit',json={'snapshot_hash':current['snapshot_hash'],'subject':'Order update','body':body}))
        blocked=internal.post(p+'/approve',json={'snapshot_hash':current['snapshot_hash']})
        assert blocked.status_code==409 and order in blocked.text
        assert current['workflow_state']=='awaiting_approval' and current['sent_at'] is None
        assert not store.rows('SELECT * FROM internal_approvals') and not store.rows('SELECT * FROM internal_deliveries')
    body='Please check both open lines of SO-1. Please also confirm SO-2 and SO-3 using our test ledger. Thank you.'
    current=ok(internal.post(p+'/edit',json={'snapshot_hash':current['snapshot_hash'],'subject':'Order update','body':body}))
    sent=ok(internal.post(p+'/approve',json={'snapshot_hash':current['snapshot_hash']}))
    assert sent['workflow_state']=='awaiting_response' and sent['sent_version']==4
    assert len(sent['record_states'])==3 and len(sent['lines'])==4
