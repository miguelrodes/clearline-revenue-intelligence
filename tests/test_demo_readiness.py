from commercial_fixtures import save_reviewed_fixture,reviewed_fixture
import asyncio,copy,json,sqlite3
from dataclasses import replace
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.demo import initialize,reset,capture,paths,use_guard
from clearline.store import Store
from clearline.signal_views import coverage,signal_detail
from clearline.operations import start_batch,latest_assessment,queue_brief
from clearline.briefing import snapshot
from clearline.workbench import work_groups,decide_messages
from clearline.worker import run_pool
from test_workbench import prepared,snaps


def test_signal_reuses_campaign_actions_and_only_matching_financial_pairs(store,opportunity,decision,settings):
    cid,g=prepared(store,opportunity,decision,3)
    with store.connect(write=True) as con:
        o=store.opportunity('1');e=o['evidence'];e['signals']=[{'type':'product_decline','sku':'A'}];e['products']=[{'sku':'A','name':'Swabs','prior_cents':40000,'current_cents':10000,'prior_tests':100,'current_tests':10},{'sku':'B','name':'Growing product','prior_cents':10000,'current_cents':90000,'prior_tests':10,'current_tests':90}]
        con.execute('UPDATE opportunities SET evidence=? WHERE id=?',(json.dumps(e),'1'))
    before={t:len(store.rows('SELECT * FROM '+t)) for t in ('jobs','campaigns','drafts','approvals')}
    d=signal_detail(store,'inactivity')
    assert {a['id'] for a in d['actions']}=={'0','2'}
    assert d['segment']['decline_cents']==20000
    assert all(a['links'][0]['group_id']=='messages:inactivity' for a in d['actions'])
    assert 'signal=inactivity' in d['groups'][0]['href']
    for group in d['groups']:
        assert group['why'] and group['button_label'] and isinstance(group['rank'],(int,float))
        relevant=[a for a in d['actions'] if any(link['group_id']==group['id'] for link in a['links'])]
        assert group['accounts']==len(relevant)
        assert group['financial_cents']==sum(max(0,a['decline_cents']) for a in relevant)
    sku=signal_detail(store,'product_decline')
    assert sku['segment']['decline_cents']==sku['actions'][0]['decline_cents']==30000
    assert len(sku['chart'])==1 and sku['chart'][0]['prior_tests']==100
    for group in sku['groups']:
        assert group['financial_label'].startswith('Qualifying product decline')
        relevant=[a for a in sku['actions'] if any(link['group_id']==group['id'] for link in a['links'])]
        assert group['financial_cents']==sum(max(0,a['decline_cents']) for a in relevant)
    assert before=={t:len(store.rows('SELECT * FROM '+t)) for t in before}


def test_entire_portfolio_finishes_with_distinct_dispositions_and_reuses_results(store,settings,opportunity,decision):
    from test_operations import population
    population(store,opportunity,6);start_batch(store)
    async def analyst(s,j,c):
        from clearline.evidence import ENGINE_VERSION,context_hash
        with s.connect() as con:revision=context_hash(con,j['opportunity_id'])
        return reviewed_fixture(s,j,{**decision,'decision':'hold' if j['opportunity_id']=='1' else 'no_action' if j['opportunity_id']=='2' else 'pursue'})
    asyncio.run(run_pool(store,settings,analyst,drain=True,auto_brief=False))
    d=coverage(store);assert d['assessed']==d['total']==6 and d['counts']['unassessed']==d['failed']==0
    assert d['counts']['verification']==1 and d['counts']['no_action']==1 and len(store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'"))==4
    before=len(store.rows("SELECT * FROM events WHERE kind='agent_decision'"));start_batch(store)
    assert not store.rows("SELECT * FROM jobs WHERE kind='analyze' AND status='queued'")
    assert len(store.rows("SELECT * FROM events WHERE kind='agent_decision'"))==before
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET evidence_hash='new' WHERE id='0'")
    start_batch(store)
    assert [j['opportunity_id'] for j in store.rows("SELECT * FROM jobs WHERE kind='analyze' AND status='queued'")]==['0']


def test_phase_one_brief_cannot_be_crowded_out_by_prospect_actions(store,opportunity,decision):
    _,g=prepared(store,opportunity,decision,1)
    with store.connect(write=True) as con:con.execute("UPDATE opportunities SET workflow='prospecting' WHERE id='0'")
    assert not any(a['id'].startswith('messages:prospect_') for a in snapshot(store)['actions'])


def test_reset_restores_exact_pending_versions_and_retains_original_history(store,settings,opportunity,decision,tmp_path):
    _,g=prepared(store,opportunity,decision,2);decide_messages(store,g['id'],snaps(g),True)
    asyncio.run(run_pool(store,settings,drain=True,auto_brief=False))
    original=store.rows('SELECT * FROM outbox');source_events=store.rows('SELECT * FROM events')
    folder=tmp_path/'demo';result=initialize(store.path,folder);baseline,session,marker=paths(folder);demo=Store(session)
    assert result['restored_campaign_accounts']==2
    g=next(g for g in work_groups(demo)['groups'] if g['kind']=='messages');before=snaps(g)
    decide_messages(demo,g['id'],before[:1],True)
    asyncio.run(run_pool(demo,replace(settings,db_path=session),drain=True,auto_brief=False))
    assert len(demo.rows('SELECT * FROM outbox'))==1
    demo.record_outcome(g['members'][0]['id'],'reply','Simulated request for training')
    reset(folder);demo=Store(session)
    restored=next(g for g in work_groups(demo)['groups'] if g['kind']=='messages')
    assert snaps(restored)==before and not demo.rows('SELECT * FROM outbox') and not demo.rows('SELECT * FROM outcomes')
    assert store.rows('SELECT * FROM outbox')==original and store.rows('SELECT * FROM events')==source_events
    assert len(demo.rows("SELECT * FROM events WHERE kind='agent_decision'"))==2
    assert list((folder/'history').glob('*.sqlite3'))
    api=TestClient(create_app(replace(settings,db_path=session)))
    with api:
        assert api.get('/api/work').status_code==api.get('/api/signals/inactivity').status_code==200
        with pytest.raises(ValueError,match='Stop demo serve'):reset(folder)
    reset(folder)


def test_reset_refuses_unknown_or_original_paths_and_changed_baseline(store,opportunity,tmp_path):
    with pytest.raises(FileNotFoundError):reset(tmp_path)
    folder=tmp_path/'demo';initialize(store.path,folder);b,s,m=paths(folder)
    data=json.loads(m.read_text());data['session']=str(store.path);m.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='registered'):reset(folder)
    data['session']=str(s);m.write_text(json.dumps(data));b.write_bytes(b.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='Baseline changed'):reset(folder)


def test_direct_gap_chart_uses_saved_channel_gaps_not_all_channel_revenue(store,opportunity):
    with store.connect(write=True) as con:
        e=copy.deepcopy(opportunity['evidence']);e['signals']=[{'type':'direct_gap_channel_review','days_since_direct_purchase':507,'days_since_identified_purchase':124}];e['holds']=['known_distributor_channel']
        con.execute('UPDATE opportunities SET evidence=? WHERE id=?',(json.dumps(e),opportunity['id']))
    d=signal_detail(store,'direct_gap_channel_review');row=d['chart'][0]
    assert row['direct_gap_days']==507 and row['identified_gap_days']==124
    assert 'Named distributor purchases are present' in row['channel_evidence']
    assert all(group['href'].endswith('signal=direct_gap_channel_review') and group['why'] for group in d['groups'])


def test_reset_refuses_to_signal_a_reused_or_unrelated_pid(store,opportunity,tmp_path,monkeypatch):
    from clearline.demo import stop_serving
    folder=tmp_path/'demo';initialize(store.path,folder)
    (folder/'server.json').write_text(json.dumps({'pid':99999,'identity':'expected process'}))
    class Process:stdout='unrelated process'
    monkeypatch.setattr('clearline.demo.subprocess.run',lambda *a,**k:Process())
    signalled=[];monkeypatch.setattr('clearline.demo.os.kill',lambda *a:signalled.append(a))
    with pytest.raises(ValueError,match='unrelated process'):stop_serving(folder)
    assert not signalled
