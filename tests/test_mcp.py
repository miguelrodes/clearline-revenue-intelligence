import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.services import ApplicationService
from clearline.contracts import CampaignInput,BatchInput,DraftInput

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
    assert data(call(client,'get_brief'))==s.operational_brief()
    assert data(call(client,'query_accounts',{'limit':1}))['items'][0]['id']=='example'
    assert data(call(client,'get_account',{'account_id':'example','section':'evidence'}))['evidence']==s.account('example')['evidence']
    assert data(call(client,'get_draft',{'draft_id':draft['id']}))['body']==draft['body']
    assert data(call(client,'list_actions'))['counts']==s.work()['counts']
    assert call(client,'query_accounts',{'limit':101})['isError']
    assert call(client,'get_account',{'account_id':'missing'})['isError']

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
    store.save_analysis(job,decision)
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
    j=store.claim(['reply']);store.save_analysis(j,reply_decision)
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
    j=store.claim(['reply']);store.save_analysis(j,reply_decision)
    old=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")[0]
    r=s.regenerate_draft(old['id'],old['version'],uuid4());j=store.claim(['reply']);assert j['id']==r['job_id']
    store.save_analysis(j,{**reply_decision,'body':'Which team would benefit from training?'})
    ds=store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")
    assert len(ds)==1 and ds[0]['version']==old['version']+1
    assert len(store.rows('SELECT * FROM approvals'))==1
    assert len(store.rows('SELECT * FROM reply_interpretations'))==1
    assert len(store.rows('SELECT * FROM commercial_tasks'))==1

def test_mcp_edits_immediately_visible_in_http(client,draft):
    edited=data(call(client,'edit_draft',{'draft_id':draft['id'],'draft':{'version':draft['version'],'recipient':draft['recipient'],'subject':'MCP edit','body':draft['body']}}))
    current=client.get('/api/accounts/example').json()['drafts'][0]
    assert current['id']==edited['draft_id'] and current['subject']=='MCP edit' and current['status']=='awaiting_approval'
