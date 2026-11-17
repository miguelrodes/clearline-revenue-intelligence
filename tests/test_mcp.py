from commercial_fixtures import save_reviewed_fixture
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.services import ApplicationService
from clearline.contracts import CampaignInput,BatchInput,DraftInput
from test_internal_inquiries import internal, SYNTHETIC_ROUTE, PATH
from test_prospecting import bundle, research, prospect, report

TOKEN='test-only-'+('x'*40)

@pytest.fixture
def client(settings,monkeypatch):
    monkeypatch.setenv('CLEARLINE_MCP_TOKEN',TOKEN)
    with TestClient(create_app(settings)) as client:yield client

def call(client,name,args=None,token=TOKEN):
    response=client.post('/mcp',headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args or {}}})
    assert response.status_code==200,response.text
    return response.json()['result']

def data(result):
    assert not result.get('isError'),result
    return result['structuredContent']['data']

def test_authentication_and_discovery(client):
    for path in ('/mcp','/mcp/'):
        assert client.post(path,json={}).status_code==401
        assert client.post(path,headers={'Authorization':'Bearer wrong'},json={}).status_code==401
    response=client.post('/mcp',headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
    assert response.status_code==200,response.text
    tools=response.json()['result']['tools']
    assert len(tools)>=30
    assert all(t.get('description') and t['inputSchema'] for t in tools)
    assert not any(any(bad in t['name'] for bad in ('sql','reset','delete_database')) for t in tools)
    assert client.post('/api/portfolio/refresh').status_code==403
    assert client.get('/api/health').status_code==200

def test_local_auth_fails_closed(client,monkeypatch):
    monkeypatch.delenv('CLEARLINE_MCP_TOKEN')
    assert client.post('/mcp',headers={'Authorization':'Bearer '+TOKEN},json={}).status_code==401

def test_tool_read_parity_and_pagination(client,settings,draft):
    s=ApplicationService(settings)
    assert data(call(client,'get_brief',{'view':'saved_brief'}))==s.operational_brief()
    assert data(call(client,'get_brief'))==s.daily_priorities()
    assert data(call(client,'query_accounts',{'limit':1}))['items'][0]['id']=='example'
    assert data(call(client,'get_account',{'account_id':'example','section':'evidence'}))['evidence']==s.account('example')['evidence']
    assert data(call(client,'get_draft',{'draft_id':draft['id']}))['body']==draft['body']
    assert data(call(client,'list_actions'))['counts']==s.work()['counts']
    assert call(client,'query_accounts',{'limit':101})['isError']
    assert call(client,'get_account',{'account_id':'missing'})['isError']

def test_daily_priorities_include_only_current_prospect_draft(client,store,prospect,research,report):
    store.queue_prospect(prospect)
    store.save_prospect_research(store.claim(),research)
    store.save_analysis(store.claim(),report)
    jobs=store.rows('SELECT id,status FROM jobs ORDER BY id')
    first,=data(call(client,'get_brief'))['priorities']
    assert first['id']==prospect and first['draft']['subject']==report.subject
    actions=data(call(client,'list_actions'))
    assert actions['priorities']==[first]
    detail=data(call(client,'list_actions',{'group_id':first['group_id'],'limit':1}))
    assert detail['members']['items'][0]['draft']==first['draft']
    assert store.rows('SELECT id,status FROM jobs ORDER BY id')==jobs
    store.decide(first['draft']['id'],False)
    assert not data(call(client,'get_brief'))['priorities']
    assert not data(call(client,'list_actions'))['groups']['items']

def test_internal_inquiry_moves_from_review_to_wait_to_partial_findings(client,internal):
    draft=internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}).json()
    path=PATH+'/'+draft['id']
    assert any(p['status']=='draft_prepared' for p in data(call(client,'get_brief'))['priorities'])
    assert internal.post(path+'/approve',json={'snapshot_hash':draft['snapshot_hash']}).status_code==200
    sent=data(call(client,'get_brief'))
    waiting,=sent['waiting']
    assert set(waiting['order_ids'])=={'SO-1','SO-2','SO-3'}
    assert draft['id'] not in {p.get('inquiry_id') for p in sent['priorities']}
    detail=data(call(client,'list_actions',{'group_id':'verification_tasks'}))
    assert {m['task_id'] for m in detail['members']['items']}=={'credit','contact'}
    assert internal.post(path+'/reply',json={'body':'Synthetic fulfillment response: SO-2 shipped.'}).status_code==200
    now=data(call(client,'list_actions'))
    first=now['priorities'][0]
    assert first['inquiry_id']==draft['id'] and first['status']=='response_recorded' and first['order_ids']==['SO-2']
    assert set(now['waiting'][0]['order_ids'])=={'SO-1','SO-3'}

def test_order_check_counts_follow_saved_inquiry_state_across_all_three_views(client, internal, store):
    from clearline.evidence import ENGINE_VERSION, context_hash

    # This is a temporary account with two fulfillment checks, one independent credit
    # check and one contact check. Its evidence and saved decision stay fixed.
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='internal_investigation' WHERE id='example'")
        evidence_hash = con.execute("SELECT evidence_hash FROM opportunities WHERE id='example'").fetchone()[0]
        store.event('agent_decision', {'decision':'hold','engine_version':ENGINE_VERSION,
                    'context_hash':context_hash(con,'example'),'evidence_hash':evidence_hash},
                    opportunity_id='example', con=con)

    # A separate customer's already-delivered message and future reminder must survive
    # every transition. These are saved records in the fixture, not a send request.
    from clearline.conversations import outbound_record
    with store.connect(write=True) as con:
        con.execute('''INSERT INTO opportunities
            (id,account_key,name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at,workflow)
            SELECT 'other','other','Other buyer',state,0,evidence,evidence_hash,'[]','awaiting_response',1,updated_at,workflow
            FROM opportunities WHERE id='example' ''')
        con.execute('''INSERT INTO drafts VALUES('prior','other',1,?,'simulation@example.invalid',
                    'Previous message','Previous message','simulated','{}','2026-11-01')''',(evidence_hash,))
        con.execute('''INSERT INTO outbox VALUES('delivery','prior','other','simulation@example.invalid',
                    'Previous message','Previous message','simulated','2026-11-01')''')
        outbound_record(con,con.execute("SELECT * FROM outbox WHERE id='delivery'").fetchone(),
                        con.execute("SELECT * FROM drafts WHERE id='prior'").fetchone(),backfill=True)
        reminder = store._enqueue(con,'followup',{'parent_draft_id':'prior'},'other','existing-reminder','2099-01-01')
    protected = {table:store.rows('SELECT * FROM '+table) for table in ('jobs','drafts','outbox','messages','approvals','outcomes')}

    orders, contacts, waiting, review = ('investigation:orders','investigation:contacts','internal:waiting','internal:review')

    def check_views(expected):
        # Repeated reads exercise regeneration from current saved workflow facts.
        for _ in range(2):
            overview = internal.get('/api/brief').json()['brief']
            action_rows = {g['id']:g for g in overview['actions']}
            waiting_rows = {g['id']:g for g in overview.get('waiting',[])}
            assert waiting not in action_rows and not action_rows.keys() & waiting_rows.keys()
            shown = {**action_rows, **waiting_rows}
            work = {g['id']:g for g in internal.get('/api/work').json()['groups']}
            queue = data(call(client,'list_actions'))
            mcp = {g['id']:g for g in queue['groups']['items']}
            assert [(m['job_id'],m['status']) for m in queue['upcoming']] == [(reminder,'queued')]
            assert 'followups' in work and 'followups' in mcp
            expected = {**expected, contacts:{'contact'}}
            all_ids = []
            for key in (orders,contacts,waiting,review):
                ids = expected.get(key,set())
                for view in (shown,work,mcp):
                    assert (key in view) == bool(ids)
                if not ids:
                    continue
                assert shown[key]['accounts'] == work[key]['accounts'] == mcp[key]['accounts'] == 1
                assert int(shown[key]['scope_label'].split()[0]) == work[key]['tasks'] == mcp[key]['tasks'] == len(ids)
                if key == waiting:
                    assert work[key]['status'] == mcp[key]['status'] == 'waiting'
                detail = data(call(client,'list_actions',{'group_id':key}))
                for members in (work[key]['members'], detail['members']['items']):
                    assert {m['task_id'] for m in members} == ids
                all_ids.extend(ids)
            assert len(all_ids) == len(set(all_ids))

    check_views({orders:{'one','two','credit'}})
    draft = internal.post(PATH,json={'group_id':'fulfillment',**SYNTHETIC_ROUTE}).json()
    check_views({orders:{'credit'}, review:{'one','two'}})

    # Insert a historical delivery fixture. Neither a send operation nor a worker runs.
    iid = draft['id']
    with store.connect(write=True) as con:
        con.execute("INSERT INTO internal_approvals VALUES(?,1,?,'2026-11-01')",(iid,draft['snapshot_hash']))
        con.execute("INSERT INTO internal_deliveries VALUES(?,1,'simulated','2026-11-01')",(iid,))
        con.execute("UPDATE internal_inquiries SET status='sent_simulated' WHERE id=?",(iid,))
    check_views({orders:{'credit'},waiting:{'one','two'}})

    # One order in the multi-order check receives a response. That check is
    # actionable exactly once even though its other order is still outstanding.
    with store.connect(write=True) as con:
        con.execute("INSERT INTO internal_replies VALUES('reply',?,?,?,?)",
                    (iid,'Synthetic status received for SO-2.',json.dumps(['SO-2']),'2026-11-02'))
    check_views({orders:{'credit'},waiting:{'one'},review:{'two'}})

    # Close and reopen the independent credit check and the fulfilled check.
    # State is manipulated in this fixture only, avoiding a real reassessment.
    with store.connect(write=True) as con:
        con.execute("UPDATE investigation_tasks SET status='resolved' WHERE id IN ('one','credit')")
    check_views({review:{'two'}})
    with store.connect(write=True) as con:
        con.execute("UPDATE investigation_tasks SET status='pending' WHERE id IN ('one','credit')")
    check_views({orders:{'credit'},waiting:{'one'},review:{'two'}})
    for table,original in protected.items():
        assert store.rows('SELECT * FROM '+table) == original
    assert len(store.rows('SELECT * FROM internal_deliveries')) == len(store.rows('SELECT * FROM internal_approvals')) == 1


def test_only_live_reminder_for_latest_conversation_is_upcoming(client,store,draft):
    store.decide(draft['id'],True)
    job=store.claim(['deliver']);store.deliver(job);store.finish(job['id'])
    due,=data(call(client,'get_brief'))['upcoming']
    assert due['id']=='example' and due['status']=='queued'
    store.cancel_job(due['job_id'])
    assert data(call(client,'get_brief'))['upcoming']==[]
    assert 'followups' not in {g['id'] for g in data(call(client,'list_actions'))['groups']['items']}
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='human_verification' WHERE id='example'")
        for tid,title in [('r','Check the existing queued follow-up'),('p','Verify purchasing contact')]:
            con.execute('INSERT INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (tid,'example','saved',title,'Sales','Synthetic check','[]',1,'pending','now'))
    actions=data(call(client,'list_actions'))
    groups=[g for g in actions['groups']['items'] if g['id'].startswith('investigation:') or g['id']=='verification_tasks']
    ids={m['task_id'] for g in groups for m in data(call(client,'list_actions',{'group_id':g['id']}))['members']['items']}
    assert 'p' in ids and 'r' not in ids

def test_older_reminder_cannot_outlive_newer_customer_reply(client,store,draft):
    store.decide(draft['id'],True)
    job=store.claim(['deliver']);store.deliver(job);store.finish(job['id'])
    reminder,=data(call(client,'get_brief'))['upcoming']
    outbound=data(call(client,'get_conversation',{'account_id':'example'}))['messages'][0]
    data(call(client,'simulate_customer_reply',{'account_id':'example','message':{
        'reply_to':outbound['id'],'message_id':'fixture-customer-reply','body':'We have a purchasing question.'}}))
    assert not data(call(client,'list_actions'))['upcoming']
    # A stale queued row on an otherwise waiting account must still lose to the thread.
    with store.connect(write=True) as con:
        con.execute("UPDATE jobs SET status='queued' WHERE id=?",(reminder['job_id'],))
        con.execute("UPDATE opportunities SET status='awaiting_response' WHERE id='example'")
    assert not data(call(client,'get_brief'))['upcoming']

def test_review_confirm_send_exact_once(client,store,draft):
    r=data(call(client,'review_outreach',{'draft_ids':[draft['id']]}))
    assert r['drafts'][0]['body']==draft['body']
    assert not store.rows('SELECT * FROM approvals')
    args={'review_id':r['review_id'],'approve':True,'confirmation':'yes'}
    assert call(client,'decide_outreach',args)['isError']
    args['confirmation']=r['required_confirmation']
    a=data(call(client,'decide_outreach',args))
    assert data(call(client,'decide_outreach',args))==a
    assert len(store.rows('SELECT * FROM approvals'))==1
    assert len(a['job_ids'])==1
    j=store.claim(['deliver']);store.deliver(j);store.finish(j['id'])
    assert data(call(client,'execute_approved_sends',{'draft_ids':[draft['id']]}))['items'][0]['sent']
    assert len(store.rows('SELECT * FROM outbox'))==1

def test_stale_review_fails_without_partial_approval(client,store,settings,draft):
    s=ApplicationService(settings);r=s.review_outreach([draft['id']])
    s.edit(draft['id'],DraftInput(version=draft['version'],recipient=draft['recipient'],subject='Updated subject',body=draft['body']))
    assert call(client,'decide_outreach',{'review_id':r['review_id'],'approve':True,'confirmation':r['required_confirmation']})['isError']
    assert not store.rows('SELECT * FROM approvals')

def test_evidence_hold_after_review_blocks_approval(client,store,draft):
    r=data(call(client,'review_outreach',{'draft_ids':[draft['id']]}))
    with store.connect(write=True) as c:c.execute("UPDATE opportunities SET holds='[\"open_orders\"]'")
    assert call(client,'decide_outreach',{'review_id':r['review_id'],'approve':True,'confirmation':r['required_confirmation']})['isError']
    assert not store.rows('SELECT * FROM approvals')

def test_bulk_atomic_rollback(settings,store,draft):
    from clearline.data import digest
    s=ApplicationService(settings)
    with store.connect(write=True) as c:
        c.execute("INSERT INTO opportunities SELECT 'second','second',name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at,workflow FROM opportunities WHERE id='example'")
        c.execute("INSERT INTO drafts SELECT 'second-draft','second',version,evidence_hash,recipient,subject,body,status,analysis,created_at FROM drafts WHERE id=?",(draft['id'],))
    from test_commercial import certified
    a=certified(store,'second',json.loads(draft['analysis']))
    with store.connect(write=True) as c:c.execute("UPDATE drafts SET analysis=? WHERE id='second-draft'",(json.dumps(a),))
    r=s.review_outreach([draft['id'],'second-draft'])
    with store.connect(write=True) as c:c.execute("UPDATE opportunities SET holds='[\"open_orders\"]' WHERE id='second'")
    with pytest.raises(ValueError):s.decide_review(r['review_id'],True,r['required_confirmation'])
    assert not store.rows('SELECT * FROM approvals')
    assert not store.rows("SELECT * FROM jobs WHERE kind='deliver'")

def test_idempotent_campaign_and_batch(settings,store,opportunity):
    s=ApplicationService(settings);key=uuid4()
    body=CampaignInput(name='Test',account_ids=['example'],simulated_contacts=True,request_id=key)
    assert s.campaign(body)==s.campaign(body)
    with pytest.raises(ValueError):s.campaign(body.model_copy(update={'name':'Different'}))
    assert len(store.rows('SELECT * FROM campaigns'))==1
    b=BatchInput(account_ids=['example'],request_id=uuid4());assert s.batch(b)==s.batch(b)

def test_regeneration_respects_racing_edit(settings,store,draft,decision):
    s=ApplicationService(settings);r=s.regenerate_draft(draft['id'],draft['version'],uuid4())
    job=store.claim(['analyze'])
    assert job['id']==r['job_id']
    store.revise_draft(draft['id'],draft['recipient'],'New subject',draft['body'])
    save_reviewed_fixture(store,job,decision)
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='cancelled'
    assert len(store.rows('SELECT * FROM drafts'))==2

def test_real_transport_reply_persistence(client,store,draft,reply_decision):
    r=data(call(client,'review_outreach',{'draft_ids':[draft['id']]}))
    data(call(client,'decide_outreach',{'review_id':r['review_id'],'approve':True,'confirmation':r['required_confirmation']}))
    j=store.claim(['deliver']);store.deliver(j);store.finish(j['id'])
    thread=data(call(client,'get_conversation',{'account_id':'example'}))
    parent=thread['messages'][0]['id']
    args={'account_id':'example','message':{'reply_to':parent,'message_id':'test-mcp-reply','body':'We need training.'}}
    result=data(call(client,'simulate_customer_reply',args))
    again=data(call(client,'simulate_customer_reply',args));assert again['job_id']==result['job_id']
    j=store.claim(['reply']);save_reviewed_fixture(store,j,reply_decision)
    thread=data(call(client,'get_conversation',{'account_id':'example'}))
    assert len(thread['messages'])==2
    assert store.rows('SELECT * FROM reply_interpretations')
    assert len(store.rows('SELECT * FROM approvals'))==1

def test_expired_and_rejected_review(client,store,draft):
    r=data(call(client,'review_outreach',{'draft_ids':[draft['id']]}))
    with store.connect(write=True) as c:c.execute("UPDATE approval_reviews SET expires_at='2000-01-01T00:00:00+00:00'")
    assert call(client,'decide_outreach',{'review_id':r['review_id'],'approve':True,'confirmation':r['required_confirmation']})['isError']
    r=data(call(client,'review_outreach',{'draft_ids':[draft['id']]}))
    data(call(client,'decide_outreach',{'review_id':r['review_id'],'approve':False,'confirmation':'REJECT '+r['review_id']}))
    assert not store.rows("SELECT * FROM jobs WHERE kind='deliver'")

def test_custom_scan_idempotency(client,store):
    args={'scan':{'analysis_limit':0,'inactivity_days':120},'request_id':str(uuid4())}
    result=data(call(client,'run_recovery_scan',args));assert data(call(client,'run_recovery_scan',args))==result
    args['scan']['inactivity_days']=60
    assert call(client,'run_recovery_scan',args)['isError']
    assert len(store.rows("SELECT * FROM jobs WHERE kind='scan'"))==1

def test_worker_schedule_job_and_status_tools(client,store,opportunity):
    assert data(call(client,'set_worker_state',{'action':'pause'}))['paused']
    assert not data(call(client,'set_worker_state',{'action':'resume'}))['paused']
    data(call(client,'set_scan_schedule',{'schedule':{'enabled':False,'analysis_limit':0}}))
    assert not data(call(client,'get_agent_status'))['health']['schedules'][0]['enabled']
    jid=store.enqueue('followup',{},'example')
    assert data(call(client,'list_jobs',{'kind':'followup'}))['total']==1
    data(call(client,'manage_job',{'job_id':jid,'action':'cancel'}))
    assert data(call(client,'get_job',{'job_id':jid}))['job']['status']=='cancelled'
    assert call(client,'manage_job',{'job_id':jid,'action':'retry'})['isError']
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET status='failed' WHERE id=?",(jid,))
    data(call(client,'manage_job',{'job_id':jid,'action':'retry'}))
    assert data(call(client,'get_job',{'job_id':jid}))['job']['status']=='queued'

def test_reply_regeneration_and_fresh_approval(settings,store,draft,reply_decision):
    from clearline.transport import SimulatedProvider
    s=ApplicationService(settings);store.decide(draft['id'],True)
    j=store.claim(['deliver']);store.deliver(j);store.finish(j['id'])
    parent=s.conversation('example')['messages'][0]['id']
    SimulatedProvider(store).ingest('example',parent,'first','We need training.')
    j=store.claim(['reply']);save_reviewed_fixture(store,j,reply_decision)
    old=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")[0]
    r=s.regenerate_draft(old['id'],old['version'],uuid4());j=store.claim(['reply']);assert j['id']==r['job_id']
    save_reviewed_fixture(store,j,{**reply_decision,'body':'Which team would benefit from training?'})
    ds=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")
    assert len(ds)==1 and ds[0]['version']==old['version']+1
    assert len(store.rows('SELECT * FROM approvals'))==1
    assert len(store.rows('SELECT * FROM reply_interpretations'))==1
    assert len(store.rows('SELECT * FROM commercial_tasks'))==1

def test_mcp_edits_immediately_visible_in_http(client,draft):
    edited=data(call(client,'edit_draft',{'draft_id':draft['id'],'draft':{'version':draft['version'],'recipient':draft['recipient'],'subject':'MCP edit','body':draft['body']}}))
    current=client.get('/api/accounts/example').json()['drafts'][0]
    assert current['id']==edited['draft_id'] and current['subject']=='MCP edit' and current['status']=='awaiting_approval'
