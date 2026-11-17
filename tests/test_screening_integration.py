import asyncio,json
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from test_screening import env,first,plan
from clearline.store import Store
from clearline.screening import screen,listing,detail,queue,save_result,summary,queue_shortlist
from clearline.screening_workflow import record_decision,record_information,prerequisites,queue_outreach,save_outreach,record_activity
from clearline.screening_budget import reserve,settle,summary as usage,BudgetLimit
from clearline.api import create_app

REVIEW=dict(accepted=True,evidence_quality=True,product_suitability=True,identity_channel=True,commercial_relevance=True,prerequisites=True,worthwhile_next_step=True,no_fabrication=True,critical_findings=[],explanation='Verified synthetic fixture only')
INFO=dict(facts='SYNTHETIC: incoming mail is screened for surface contamination; buyer requests an application discussion.',evidence='SYNTHETIC fixture confirmation, 2026-11-01',recipient='buyer@example.invalid',role='Purchasing lead',route='direct',contact_verified=True,authorized=True,relationship_checked=True,synthetic=True)

def qualify(env,aid):
 s,st,*_=env;r=detail(st,aid);queue(st,s,aid,r['evidence_hash']);j=st.claim(['agency_qualify']);assert j
 save_result(st,j,dict(decision=plan(),review_passed=True,review=REVIEW));st.finish(j['id'])
 return detail(st,aid)

def cleared(env):
 s,st,*_=env;r=first(env);record_decision(st,r['id'],'accepted','Plausible internal discovery application')
 record_information(st,r['id'],INFO,r['context_hash']);return qualify(env,r['id'])

def draft(env):
 s,st,*_=env;r=cleared(env);queue_outreach(st,s,r['id'],r['context_hash']);j=st.claim(['agency_outreach'])
 did=save_outreach(st,j,dict(proposal=dict(subject='Mail-screening application discussion',body='Hello, would a discussion of the verified mailroom application be useful?',strategy='Scope an application discussion without claiming prior purchases'),review=REVIEW));st.finish(j['id'])
 return r,did

def test_ranking_cache_missing_values_and_outliers(env):
 s,st,t,w=env
 for n in range(20):t['public_agencies'].append(dict(t['public_agencies'][0],agency_name=f'Fixture {n} County Jail',jail_beds=str(n+1)))
 t['public_agencies'].append(dict(t['public_agencies'][0],agency_name='Missing County Jail',jail_beds=''))
 t['public_agencies'].append(dict(t['public_agencies'][0],agency_name='Outlier County Jail',jail_beds='1e100'))
 w();screen(st,s);before=st.rows('SELECT * FROM agency_rankings');hashes=st.rows('SELECT evidence_hash FROM agency_screenings')
 screen(st,s);assert before==st.rows('SELECT * FROM agency_rankings') and hashes==st.rows('SELECT evidence_hash FROM agency_screenings')
 rows=listing(st,limit=100)['items'];assert all(0<=r['score']<=100 for r in rows)
 missing=next(r for r in rows if r['name'].startswith('Missing'));assert next(f['points'] for f in missing['ranking']['factors'] if f['key']=='scale')==0
 outlier=next(r for r in rows if r['name'].startswith('Outlier'));assert next(f['points'] for f in outlier['ranking']['factors'] if f['key']=='scale')==25
 assert sum(f['maximum'] for f in outlier['ranking']['factors'])==100


def test_reuse_unchanged_and_target_only_new_information(env):
 s,st,*_=env;r=first(env);r=qualify(env,r['id']);jobs=len(st.rows('SELECT * FROM jobs'))
 assert queue(st,s,r['id'],r['evidence_hash'])['reused'];assert len(st.rows('SELECT * FROM jobs'))==jobs
 before=st.rows('SELECT * FROM agency_qualifications')
 assert record_information(st,r['id'],{'facts':'Partial verified note'},r['context_hash'])['ai_triggered'] is False
 r=detail(st,r['id']);assert not r['qualification_current'];assert prerequisites(r)
 assert len(st.rows('SELECT * FROM jobs'))==jobs and before==st.rows('SELECT * FROM agency_qualifications')
 with pytest.raises(ValueError):queue_outreach(st,s,r['id'],r['context_hash'])
 a=queue(st,s,r['id'],r['evidence_hash']);assert a==queue(st,s,r['id'],r['evidence_hash']);assert len(st.rows('SELECT * FROM jobs'))==jobs+1


def test_decisions_persist_no_rejected_or_held_shortlist(env):
 s,st,*_=env;r=first(env)
 record_decision(st,r['id'],'rejected','Wrong institutional workflow');screen(st,s)
 assert not listing(Store(s.db_path))['items']
 assert listing(st,outcome='rejected')['items'][0]['id']==r['id']
 assert not queue_shortlist(st,s)['job_ids']
 with pytest.raises(ValueError):queue(st,s,r['id'],r['evidence_hash'])
 record_decision(st,r['id'],'held','Need relationship confirmation')
 assert not queue_shortlist(st,s)['job_ids']
 record_decision(st,r['id'],'accepted','Relationship review can proceed');assert queue_shortlist(st,s)['job_ids']


def test_human_decision_during_investigation_prevents_result(env):
 s,st,*_=env;r=first(env);queue(st,s,r['id'],r['evidence_hash']);job=st.claim(['agency_qualify'])
 record_decision(st,r['id'],'rejected','Do not pursue')
 with pytest.raises(ValueError):save_result(st,job,dict(decision=plan(),review_passed=True))
 assert not st.rows('SELECT * FROM agency_qualifications')

def test_activity_replay_preserves_evidence_and_pending_reassessment(env):
 s,st,*_=env;r=cleared(env);aid=r['id']
 record_activity(st,aid,'response_received','Synthetic: please discuss training')
 after=detail(st,aid);queued=queue(st,s,aid,after['evidence_hash'])
 record_activity(st,aid,'response_received','Synthetic: please discuss training')
 assert detail(st,aid)['context_hash']==after['context_hash']
 assert st.rows('SELECT status FROM jobs WHERE id=?',(queued['job_id'],))[0]['status']=='queued'
 record_activity(st,aid,'response_received','Synthetic: purchasing has confirmed a new route')
 assert detail(st,aid)['context_hash']!=after['context_hash']


def test_mcp_search_by_state_name_city_and_rejection_source(env,monkeypatch):
 from test_mcp import TOKEN,call,data
 s,st,t,write=env
 original=t['public_agencies'][0]
 t['public_agencies']=[
     dict(original,agency_name='Crystal Lake Jail',city='Elsewhere',state='WY',jail_beds='2'),
     dict(original,agency_name='Harbor Jail',city='Crystal Lake',state='WY',jail_beds='900'),
     dict(original,agency_name='Wyatt Facility',city='Other',state='KS')]
 write();screen(st,s)
 ids={r['name']:r['id'] for r in st.rows('SELECT name,id FROM agency_screenings')}
 aid=ids['Crystal Lake Jail'];queue(st,s,aid,detail(st,aid)['evidence_hash']);job=st.claim(['agency_qualify'])
 save_result(st,job,dict(decision=plan('reject'),review_passed=True));st.finish(job['id'])
 monkeypatch.setenv('CLEARLINE_MCP_TOKEN',TOKEN)
 with TestClient(create_app(s)) as client:
  def search(**kwargs):return data(call(client,'query_screened_agencies',kwargs))['items']
  assert [r['id'] for r in search(q=' wyOMing ')]==[r['id'] for r in search(q='wy')]
  assert {r['state'] for r in search(q='WY')}=={'WY'}
  assert [r['matched_on'] for r in search(q='Crystal Lake')]==['name','city']
  record_decision(st,ids['Harbor Jail'],'rejected','Synthetic test decision')
  for word in ('reject','rejected'):
   assert {r['id'] for r in search(outcome=word)}=={aid,ids['Harbor Jail']}
  assert [r['id'] for r in search(outcome='human_rejected')]==[ids['Harbor Jail']]
  assert [r['id'] for r in search(outcome='qualification_reject')]==[aid]


@pytest.mark.parametrize('field,value',[('recipient',''),('role',''),('route',''),('facts',''),('evidence',''),('contact_verified',False),('authorized',False),('relationship_checked',False)])
def test_every_contact_prerequisite_blocks(env,field,value):
 s,st,*_=env;r=cleared(env)
 record_information(st,r['id'],{**INFO,field:value},r['context_hash']);r=qualify(env,r['id'])
 assert prerequisites(r)
 with pytest.raises(ValueError):queue_outreach(st,s,r['id'],r['context_hash'])


def test_exact_approval_and_idempotent_simulated_send_and_tracking(env):
 s,st,*_=env;r,did=draft(env)
 assert not st.rows('SELECT * FROM approvals') and not st.rows('SELECT * FROM outbox')
 d=st.rows('SELECT * FROM drafts WHERE id=?',(did,))[0]
 api=TestClient(create_app(s),headers={'X-Clearline-Client':'web'})
 snapshot={k:d[k] for k in ('version','recipient','subject','body')}
 assert api.post('/api/drafts/'+did+'/decision',json={**snapshot,'body':'Tampered','approve':True}).status_code==409
 assert api.post('/api/drafts/'+did+'/decision',json={**snapshot,'approve':True}).status_code==200
 job=st.claim(['agency_deliver']);assert job
 st.deliver(job);st.deliver(job);st.finish(job['id'])
 assert len(st.rows('SELECT * FROM outbox'))==1 and not st.rows("SELECT * FROM jobs WHERE kind='followup'")
 assert detail(st,r['id'])['workflow']['stage']=='contact_attempted'
 record_activity(st,r['id'],'response_received','SYNTHETIC customer reply: please scope an application discussion')
 assert detail(st,r['id'])['workflow']['stage']=='responded'
 record_activity(st,r['id'],'advanced','SYNTHETIC application discussion scheduled')
 assert detail(Store(s.db_path),r['id'])['workflow']['stage']=='advanced'
 assert not st.rows('SELECT * FROM outcomes') # not reported as real revenue


@pytest.mark.parametrize('when',['before_approval','before_delivery'])
def test_changed_verification_revokes_approval_and_delivery(env,when):
 s,st,*_=env;r,did=draft(env)
 if when=='before_delivery':st.decide(did,True);job=st.claim(['agency_deliver'])
 record_information(st,r['id'],{**INFO,'authorized':False},r['context_hash'])
 with pytest.raises(ValueError):
  if when=='before_approval':st.decide(did,True)
  else:st.deliver(job)
 assert not st.rows('SELECT * FROM outbox')


def test_bad_review_or_identity_blocks_outreach(env):
 s,st,*_=env;r=cleared(env);queue_outreach(st,s,r['id'],r['context_hash']);j=st.claim(['agency_outreach'])
 with pytest.raises(ValueError):save_outreach(st,j,{'review':{**REVIEW,'accepted':False}})
 assert not st.rows('SELECT * FROM drafts')
 with st.connect(write=True) as c:c.execute("UPDATE agency_screenings SET classification='possible_existing_channel' WHERE id=?",(r['id'],))
 assert prerequisites(detail(st,r['id']))


def request_body():return dict(model='gpt-6.1-sol',input='test',max_output_tokens=6000,service_tier='default')
def budget_job(aid='a',jid='j'):return dict(id=jid,payload={'agency_id':aid},usage_stage='investigation')


def test_budget_unknown_usage_keeps_reservation_and_known_usage_settles(env):
 s,st,*_=env;body=request_body();reserve(st,budget_job(),s,'one',body)
 reserved=usage(st)['reserved_usd'];assert reserved>0
 settle(st,'one',{},429);assert usage(st)['reserved_usd']==reserved
 reserve(st,budget_job(),s,'two',body);settle(st,'two',dict(model=s.model,usage=dict(input_tokens=100,output_tokens=50),service_tier='default'),200)
 result=usage(st);assert result['requests']==2 and result['estimated_usd']==.00075 and result['reserved_usd']==reserved
 assert result['stages']['investigation']['input_tokens']==100


def test_screening_cache_costs_are_reserved_then_settled_at_verified_rates(env):
 s,st,*_=env
 reserve(st,budget_job(),s,'cached',request_body())
 row=st.rows("SELECT * FROM agency_usage WHERE request_id='cached'")[0]
 assert row['reserved_micro']==row['input_bound']*2.5+row['output_bound']*10
 details={'cached_tokens':100,'cache_write_tokens':600,'cache_write_tokens_details':{'ttl_30m_tokens':600,'ttl_12h_tokens':0}}
 response=dict(model=s.model,usage=dict(input_tokens=1000,output_tokens=0,input_tokens_details=details),service_tier='default')
 settle(st,'cached',response,200)
 assert usage(st)['estimated_usd']==.00211
 reserve(st,budget_job(),s,'malformed',request_body())
 details['cache_write_tokens']=900
 settle(st,'malformed',response,200)
 assert st.rows("SELECT state,charged_micro FROM agency_usage WHERE request_id='malformed'")==[{'state':'unknown','charged_micro':None}]
 with pytest.raises(BudgetLimit,match='cache policy'):
  reserve(st,budget_job(),s,'long-cache',{**request_body(),'prompt_cache_options':{'ttl':'12h'}})


def test_budget_concurrent_limit_is_atomic(env):
 s,st,*_=env
 def attempt(n):
  try:reserve(st,budget_job(jid=str(n)),s,str(n),{**request_body(),'input':'X'*190000});return True
  except BudgetLimit:return False
 with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(20)))
 assert 0<sum(results)<20 and usage(st)['reserved_usd']<=5
 assert usage(st)['remaining_usd']>=0


def test_budget_agency_limit_and_unknown_pricing(env):
 s,st,*_=env
 for n in range(15):reserve(st,budget_job(str(n),str(n)),s,str(n),request_body())
 with pytest.raises(BudgetLimit):reserve(st,budget_job('sixteen'),s,'sixteen',request_body())
 with pytest.raises(BudgetLimit):reserve(st,budget_job(),s,'unknown',{**request_body(),'model':'unknown'})
 for change in ({'service_tier':'priority'},{'tools':[{'type':'web_search'}]},{'previous_response_id':'x'},{'input':[{'type':'input_image'}]},{'input':[{'type':'reasoning','encrypted_content':'opaque'}]},{'max_output_tokens':6001},{'stream':True}):
  with pytest.raises(BudgetLimit):reserve(st,budget_job(),s,'invalid',{**request_body(),**change})


def test_budget_violation_freezes_future_requests(env):
 s,st,*_=env;reserve(st,budget_job(),s,'one',request_body())
 settle(st,'one',dict(model=s.model,usage=dict(input_tokens=1000000,output_tokens=10)),200)
 with pytest.raises(BudgetLimit):reserve(st,budget_job(),s,'two',request_body())


def test_new_actions_feature_flag_and_mcp_shared_state(env,monkeypatch):
 from test_mcp import TOKEN,call,data
 monkeypatch.setenv('CLEARLINE_MCP_TOKEN',TOKEN)
 s,st,*_=env;r=first(env)
 disabled=TestClient(create_app(replace(s,screening_enabled=False)),headers={'X-Clearline-Client':'web'})
 assert disabled.post('/api/screening/agencies/'+r['id']+'/decision',json={'decision':'accepted','rationale':'Fit'}).status_code==404
 with TestClient(create_app(s),headers={'X-Clearline-Client':'web'}) as api:
  assert api.post('/mcp',headers={'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'}).status_code==401
  result=data(call(api,'decide_screened_agency',{'agency_id':r['id'],'decision':'held','rationale':'Need operational application evidence'}))
  assert result['decision']=='held'
  assert api.get('/api/screening/agencies/'+r['id']).json()['workflow']['decision']=='held'


def test_http_budget_hook_prevents_dispatch_and_shares_ledger(env,monkeypatch,tmp_path):
 import openai
 try:import httpx2 as httpx
 except ImportError:import httpx
 from clearline.telemetry import client_for
 from clearline.worker import execute_job
 s,st,*_=env;r=first(env);queue(st,s,r['id'],r['evidence_hash']);job=st.claim(['agency_qualify'])
 ledger=Store(tmp_path/'common-ledger.sqlite3');s=replace(s,screening_budget_path=ledger.path)
 monkeypatch.setenv('OPENAI_API_KEY','synthetic-test-key')
 calls=[]
 def handler(request):
  calls.append(request)
  assert usage(ledger)['reserved_usd']>0
  return httpx.Response(200,json={'id':'resp_fixture','object':'response','created_at':0,'model':s.model,'status':'completed','output':[],'service_tier':'default','usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}})
 monkeypatch.setattr(openai,'DefaultAsyncHttpxClient',lambda **kwargs:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kwargs))
 async def send():
  async with client_for(st,job,s) as client:await client.responses.create(model=s.model,input='Synthetic fixture',max_output_tokens=100,service_tier='default')
 asyncio.run(send());assert len(calls)==1 and usage(ledger)['requests']==1 and usage(st)['requests']==0
 with ledger.connect(write=True) as c:c.execute('UPDATE agency_usage SET charged_micro=5000000')
 async def blocked_qualifier(*args):await send()
 monkeypatch.setattr('clearline.screening_agent.qualify',blocked_qualifier)
 asyncio.run(execute_job(st,s,job))
 assert len(calls)==1
 result=st.rows('SELECT status,error FROM jobs WHERE id=?',(job['id'],))[0]
 assert result['status']=='blocked_config' and '$5 cap' in result['error']
 assert not st.rows("SELECT * FROM events WHERE kind='job_retry_scheduled'")


def test_reply_changes_only_affected_context_and_reassessment_reads_history(env):
 from clearline.screening_agent import Access
 s,st,t,w=env
 t['public_agencies'].append(dict(t['public_agencies'][0],agency_name='Independent County Jail'));w();screen(st,s)
 ids=[r['id'] for r in listing(st)['items']]
 for aid in ids:qualify(env,aid)
 aid,other=ids;before=detail(st,other);r=detail(st,aid)
 record_decision(st,aid,'accepted','Relevant application')
 record_activity(st,aid,'contact_attempted','SYNTHETIC: introduction attempted')
 assert detail(st,aid)['qualification_current'] # sending alone does not require another model call
 record_activity(st,aid,'response_received','SYNTHETIC buyer reply: we need people testing, not physical mail screening')
 changed=detail(st,aid);assert not changed['qualification_current']
 assert detail(st,other)['context_hash']==before['context_hash'] and detail(st,other)['qualification_current']
 result=queue(st,s,aid,r['evidence_hash']);assert result==queue(st,s,aid,r['evidence_hash'])
 job=st.claim(['agency_qualify']);assert job['payload']['agency_id']==aid
 evidence=Access(st,job).get('agency')
 assert any('people testing' in x['note'] for x in evidence['activity_history'])
 assert len(listing(st,outcome='needs_reassessment')['items'])==1
 assert summary(st)['assessed']==1
 save_result(st,job,{'decision':plan('reject'),'review_passed':True,'review':REVIEW});st.finish(job['id'])
 assert detail(st,aid)['qualification_current']
 assert queue(st,s,aid,r['evidence_hash'])['reused']
 # Adding our own qualification history must not create another stale-context loop.
 assert summary(st)['assessed']==2
