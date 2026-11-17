import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from clearline import prospect_budget as budget
from clearline import prospect_discovery as workflow
from clearline.prospect_sources import DIRECTORIES, PublicPage, valid_url
from clearline.screening_budget import BudgetLimit
from clearline.demo import CONVERSATION_SESSION


def enabled(settings,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only-sentinel')
    monkeypatch.delenv('OPENAI_BASE_URL',raising=False)
    return replace(settings,screening_enabled=True)


def test_budget_inflight_exact_scope_unknown_and_replay(settings):
    job={'id':'first','kind':'pipeline_discover'}
    budget.reserve(settings,job,8000,3000)
    assert budget.usage(settings)['reserved_usd']==.05
    with pytest.raises(BudgetLimit):
        budget.reserve(settings,job,8000,3000)
    response={'id':'resp_test','model':budget.MODEL,'service_tier':'default',
              'usage':{'input_tokens':100,'output_tokens':10,
                       'input_tokens_details':{'cached_tokens':20,'cache_write_tokens':10}}}
    budget.settle(settings,job,SimpleNamespace(model_dump=lambda **_:response))
    assert budget.usage(settings)['spent_usd']==.000267
    for i in range(10):
        budget.reserve(settings,{'id':str(i),'kind':'pipeline_research'},32000,1900)
    assert budget.usage(settings)['remaining_usd']==.009733
    with pytest.raises(BudgetLimit,match='cumulative'):
        budget.reserve(settings,{'id':'last','kind':'pipeline_research'},5000,1500)
    with pytest.raises(BudgetLimit,match='per-stage'):
        budget.reserve(settings,{'id':'huge','kind':'pipeline_discover'},100000,1200)
    with pytest.raises(BudgetLimit):
        budget.settle(settings,{'id':'1'},SimpleNamespace(model_dump=lambda **_:{'model':'unexpected'}))
    assert budget.usage(settings)['reserved_usd']==.99


def test_discovery_confirm_verify_dedup_and_no_automatic_research(store,settings,monkeypatch):
    settings=enabled(settings,monkeypatch)
    source=DIRECTORIES['WY']
    url='https://corrections.wyo.gov/real-institution'
    name='Verified Test Institution'
    root=PublicPage(source); root.feed(f'<title>Wyoming facilities</title><a href="{url}">{name}</a>')
    site=PublicPage(url);site.feed(f'<title>{name}</title><p>{name} is a state institution for assessment and custody.</p><p>Lusk, WY 82225</p>')
    pages={source:root.result(),url:site.result()}
    calls=[]
    async def retrieve(url,vendor=False):return pages[url]
    async def simulate(*args):
        calls.append(args[1]['kind'])
        return workflow.DirectoryResult(candidates=[
            workflow.Listing(name=name,url=url,segment='state_prison',identity_quote=name),
            workflow.Listing(name='Invented institution',url=url,segment='state_prison',identity_quote=name)])
    monkeypatch.setattr(workflow,'fetch_page',retrieve)
    monkeypatch.setattr(budget,'generate',simulate)
    assert workflow.discovery_scope(store,settings,'Wyoming','corrections')['eligible_count']==10
    assert workflow.discovery_scope(store,settings,'NY','police')['enabled'] is False
    with pytest.raises(ValueError,match='Confirm'):
        workflow.queue_discovery(store,settings,'WY','corrections')
    for _ in range(2):
        workflow.queue_discovery(store,settings,'WY','corrections',confirmed=True)
        job=store.claim(kinds=['pipeline_discover'])
        asyncio.run(workflow.execute(store,job,settings))
        store.finish(job['id'])
    events=[json.loads(r['details']) for r in store.rows("SELECT details FROM events WHERE kind='prospect_discovery_saved' ORDER BY id")]
    assert events[0]['created']==1 and events[1]['unchanged']==1 and calls==['pipeline_discover']
    assert events[0]['candidate_ids']==events[1]['candidate_ids']
    # Cancellation during directory retrieval also applies to reused, zero-cost results.
    workflow.queue_discovery(store,settings,'WY','corrections',confirmed=True)
    cancelled=store.claim(kinds=['pipeline_discover'])
    async def cancel_during_retrieval(url,vendor=False):
        store.cancel_job(cancelled['id'])
        return pages[url]
    monkeypatch.setattr(workflow,'fetch_page',cancel_during_retrieval)
    asyncio.run(workflow.execute(store,cancelled,settings))
    assert not store.rows("SELECT id FROM events WHERE kind='prospect_discovery_saved' AND job_id=?",(cancelled['id'],))
    assert not store.rows('SELECT * FROM prospect_discovery_members WHERE run_id=?',(cancelled['id'],))
    assert not store.rows("SELECT id FROM jobs WHERE kind IN ('pipeline_research','pipeline_qualify','prospect_research')")
    attrs=json.loads(store.rows('SELECT attributes FROM prospect_candidate_profiles')[0]['attributes'])
    assert attrs['city']=='Lusk' and attrs['operational_context'].startswith(name)
    assert 'jail_beds' not in attrs
    scope=workflow.research_scope(store,settings,events[0]['candidate_ids'])
    assert scope['eligible_count']==1 and scope['max_cost_usd']==.28
    assert budget.config_error(replace(settings,db_path=CONVERSATION_SESSION))
    assert budget.config_error(replace(settings,model='unknown'))
    for unsafe in ['http://wy.gov','https://wy.gov:8000','https://test.example/','https://wy.gov@example.com/']:
        with pytest.raises(ValueError):valid_url(unsafe)


def test_new_hold_blocks_confirmed_research_before_job_is_created(store,settings,monkeypatch):
    from clearline.prospect_pipeline import candidate_decision, save_discoveries
    from test_prospect_pipeline import entry
    settings=enabled(settings,monkeypatch)
    oid,=save_discoveries(store,[entry()],settings.as_of,'fixture')['candidate_ids']
    preview=workflow.research_scope
    def hold_after_preview(*args):
        scope=preview(*args)
        candidate_decision(store,oid,'hold','Verify purchasing route')
        return scope
    monkeypatch.setattr(workflow,'research_scope',hold_after_preview)
    with pytest.raises(ValueError,match='eligibility changed'):
        workflow.queue_research(store,settings,[oid],confirmed=True)
    assert not store.rows('SELECT * FROM jobs')
