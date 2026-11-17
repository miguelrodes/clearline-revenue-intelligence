"""Prospect overview projections read the same qualifications and gates as detail pages."""
from fastapi.testclient import TestClient

from clearline.api import create_app
from clearline.prospect_overview import overview, SHORTLIST_SIZE
from clearline.screening import screen, detail, queue, save_result
from clearline.screening_workflow import record_decision, record_information
from test_screening import env, first, plan
from test_screening_integration import qualify, INFO, draft
from test_prospecting import bundle, research, report, prospect


def groups(store):
    return {g['id']:g for g in overview(store, True)['groups']}


def test_bounded_ranked_shortlist_is_read_only_and_deduplicated(env):
    settings, store, tables, write = env
    for i in range(SHORTLIST_SIZE + 2):
        tables['public_agencies'].append(dict(tables['public_agencies'][0], agency_name=f'Fixture {i} County Jail', jail_beds=str(i+3)))
    write()
    screen(store, settings)
    api=TestClient(create_app(settings))
    before=store.rows('SELECT id FROM jobs')
    response=api.get('/api/overview/prospects')
    assert response.status_code==200
    g=response.json()['groups'][0]
    assert response.json()['coverage']['unique_records']==SHORTLIST_SIZE+3
    assert g['id']=='shortlist' and g['count']==len(g['members'])==SHORTLIST_SIZE
    expected=store.rows('SELECT a.id FROM agency_screenings a JOIN agency_rankings r ON a.id=r.agency_id ORDER BY r.score DESC,a.name,a.id LIMIT ?', (SHORTLIST_SIZE,))
    assert [m['id'] for m in g['members']]==[r['id'] for r in expected]
    assert all(m['href']=='/screening?agency='+m['id'] and m['status']=='Screened only' for m in g['members'])
    assert api.get('/api/overview/prospects').json()==response.json()
    assert before==store.rows('SELECT id FROM jobs')


def test_decisions_and_stale_evidence_move_only_the_relevant_prospect(env):
    _,store,*_=env
    r=first(env)
    qualify(env,r['id'])
    assert set(groups(store))=={'decision'}
    record_decision(store,r['id'],'accepted','Review the specific screening application')
    member=groups(store)['prerequisites']['members'][0]
    assert 'Verify the intended recipient' in member['next_step']
    r=detail(store,r['id'])
    record_information(store,r['id'],INFO,r['context_hash'])
    assert set(groups(store))=={'reassess'}
    qualify(env,r['id'])
    assert set(groups(store))=={'prepare'}
    record_decision(store,r['id'],'held','Pause this review')
    assert not groups(store)
    record_decision(store,r['id'],'rejected','No supported need')
    assert not groups(store)


def test_only_current_fictional_draft_enters_review_group(env):
    _,store,*_=env
    _,did=draft(env)
    assert set(groups(store))=={'agency_email'}
    store.decide(did,True)
    assert not groups(store)


def test_identity_conflict_is_verification_only_and_existing_buyer_stays_out(env):
    settings,store,tables,write=env
    a=tables['public_agencies'][0]
    tables['orders'][0]['bill_to_account']=a['agency_name']
    write()
    screen(store,settings)
    row=store.rows('SELECT * FROM agency_screenings')[0]
    assert row['classification']=='ambiguous_identity'
    queue(store,settings,row['id'],row['evidence_hash'])
    job=store.claim(['agency_qualify'])
    save_result(store,job,{'decision':plan('human_verification'),'review_passed':True})
    store.finish(job['id'])
    result=groups(store)
    assert set(result)=={'relationship'} and '$' not in result['relationship']['description']
    tables['orders'][0]['ship_to_city']=a['city']
    write()
    screen(store,settings)
    assert not groups(store)


def test_real_research_and_exact_approval_live_separately(store,prospect,research,report):
    store.queue_prospect(prospect)
    store.save_prospect_research(store.claim(),research)
    store.save_analysis(store.claim(),report)
    output=overview(store,False)
    g,=output['groups']
    assert g['source']=='phase4' and g['id']=='real_email' and g['count']==1
    assert 'Pennsylvania' in g['members'][0]['name'] and 'Paper screening' in g['members'][0]['commercial_context']
    assert g['members'][0]['href'].endswith('#prospect-outreach')
    assert any('Massachusetts' in b['text'] and 'preliminary evidence only' in b['text'] for b in output['brief'])
    assert '$' not in g['description']
    store.decide(store.rows('SELECT id FROM drafts')[0]['id'],True)
    assert not overview(store,False)['groups']


def test_accepted_unassessed_candidate_has_own_work_and_does_not_expand_ranked_window(env):
    settings,store,tables,write=env
    for i in range(SHORTLIST_SIZE + 1):
        tables['public_agencies'].append(dict(tables['public_agencies'][0], agency_name=f'Fixture {i} Sheriff', agency_type='sheriff'))
    write()
    screen(store,settings)
    aid=store.rows("SELECT id FROM agency_screenings WHERE agency_type='sheriff' LIMIT 1")[0]['id']
    record_decision(store,aid,'accepted','Sales confirms a reason for internal product-fit investigation')
    result=groups(store)
    assert result['accepted_qualification']['members'][0]['id']==aid
    assert aid not in {r['id'] for r in result['shortlist']['members']}
    assert result['shortlist']['count']<=SHORTLIST_SIZE
    assert any('accepted candidates' in b['text'] for b in overview(store,True)['brief'])
