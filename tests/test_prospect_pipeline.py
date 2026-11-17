"""Exercise saved registry, screening and stage projections using disposable SQLite only."""
import json

import pytest

from clearline.data import digest
from clearline.prospect_pipeline import candidate_decision, candidate_detail, pipeline, save_discoveries
from clearline.store import Store, utcnow
from test_prospecting import bundle, prospect, research, report
from test_screening import env, first


def entry(name='Example County Detention Center',state='KS',**attrs):
    return {'name':name,'state':state,'segment':'county_jail','official_url':'https://doc.ks.gov/directory',
            'identity_quote':'Official facility list includes '+name,'source_title':'State directory',
            'retrieved_at':'2026-11-16','jail_beds':250,**attrs}


def test_origins_rank_sources_and_restart(env):
    settings,store,*_=env
    synthetic=first(env)
    candidates=[entry(),entry('Another County Detention Center')]
    result=save_discoveries(store,candidates,settings.as_of,'run-1')
    assert result['created']==2
    real,other=result['candidate_ids']
    assert real!=synthetic['id'] and other!=real
    saved=store.rows('SELECT * FROM prospect_candidate_profiles ORDER BY opportunity_id')
    o=store.opportunity(real)
    assert save_discoveries(store,[dict(d,retrieved_at='2026-11-17') for d in candidates],settings.as_of,'run-2')['unchanged']==2
    assert saved==store.rows('SELECT * FROM prospect_candidate_profiles ORDER BY opportunity_id')
    assert store.opportunity(real)==o
    projection=pipeline(Store(settings.db_path))
    assert projection['metrics']['total']==3 and projection['metrics']['fictional_csv']==1
    assert projection['metrics']['awaiting_research']==2 and len(projection['brief'])>=1
    actions={a['id']:a['href'] for a in projection['actions']}
    assert actions['select_research']=='/screening?stage=awaiting_research#candidates'
    assert pipeline(store,origin='real',stage='awaiting_research')['total']==2
    assert pipeline(store,origin='fictional_csv',q='example')['total']==1
    candidate=candidate_detail(store,real)
    assert candidate['verified'] and candidate['stage']=='screened' and candidate['researchable']
    assert {f['key'] for f in candidate['factors']}=={'fit','scale','similarity','context'}
    assert candidate['score']==sum(f['points'] for f in candidate['factors'])
    assert 'Fictional Clearline comparison' in candidate['comparison']
    assert candidate['field_sources']['jail_beds']==entry()['official_url']
    assert candidate['sources'][0]['identity_quote']==entry()['identity_quote']
    assert 'in_hidta_region' in candidate['missing_fields']
    assert not candidate_detail(store,synthetic['id'])['researchable']
    assert store.rows('SELECT id FROM jobs')==[]
    changed=save_discoveries(store,[entry(jail_beds=12)],settings.as_of,'run-3')
    assert changed['updated']==1 and candidate_detail(store,real)['score']<candidate['score']
    assert store.opportunity(real)['evidence_hash']!=o['evidence_hash']
    assert candidate_detail(store,other)['score']==candidate['score']
    with pytest.raises(ValueError,match='domains'):
        save_discoveries(store,[entry(official_url='https://wrong.ks.gov/dir')],settings.as_of,'run-4')
    with pytest.raises(ValueError,match='name the institution'):
        save_discoveries(store,[entry(identity_quote='Unrelated navigation label')],settings.as_of,'run-4')


def test_decisions_and_running_job_never_enqueue_by_reading(store,settings):
    (oid,)=save_discoveries(store,[entry()],settings.as_of,'new')['candidate_ids']
    assert next(a['href'] for a in pipeline(store)['actions'] if a['id']=='select_research')=='/screening?candidate='+oid
    selected=candidate_decision(store,oid,'select_for_research')
    assert selected['stage']=='selected_for_research' and not store.rows('SELECT id FROM jobs')
    held=candidate_decision(store,oid,'hold','Identity is clear but operational need is unverified.')
    assert held['stage']=='hold' and not held['researchable']
    before=store.rows('SELECT * FROM prospect_candidate_decisions')
    events=store.rows("SELECT * FROM events WHERE kind='prospect_manual_decision'")
    assert candidate_decision(store,oid,'hold',' Identity is clear but operational need is unverified. ')['stage']=='hold'
    assert store.rows('SELECT * FROM prospect_candidate_decisions')==before
    assert store.rows("SELECT * FROM events WHERE kind='prospect_manual_decision'")==events
    candidate_decision(store,oid,'hold','Updated rationale')
    assert len(store.rows("SELECT id FROM events WHERE kind='prospect_manual_decision'"))==len(events)+1
    assert not pipeline(store,stage='awaiting_research')['total']
    assert candidate_decision(store,oid,'resume')['stage']=='screened'
    job_id=store.enqueue('pipeline_research',{'evidence_hash':store.opportunity(oid)['evidence_hash']},oid)
    assert candidate_detail(store,oid)['stage']=='selected_for_research' and not candidate_detail(store,oid)['researchable']
    assert store.claim(['pipeline_research'])['id']==job_id
    assert candidate_detail(store,oid)['stage']=='research_in_progress'
    with pytest.raises(ValueError):
        candidate_decision(store,oid,'reject','Do not proceed.')


def test_curated_research_never_rewritten_by_registry_and_synthetic_names_stay_separate(store,settings,prospect,research,report):
    store.queue_prospect(prospect)
    store.save_prospect_research(store.claim(),research)
    store.save_analysis(store.claim(),report)
    # Earlier saved qualifications carry the evidence hash on the job rather than the event.
    with store.connect(write=True) as con:
        con.execute("UPDATE events SET details=json_remove(details,'$.evidence_hash') WHERE opportunity_id=? AND kind='agent_decision'",(prospect,))
    before=store.opportunity(prospect)
    drafts=store.rows('SELECT * FROM drafts')
    detail=candidate_detail(store,prospect)
    assert detail['stage']=='awaiting_approval' and detail['origin']=='real_manual' and detail['researched']
    assert not detail['outreach_permission_required']
    assert pipeline(store,stage='researched')['total']==1
    actions={a['id']:a['href'] for a in pipeline(store)['actions']}
    assert actions['review_emails']==f'/accounts/{prospect}#prospect-outreach'
    assert candidate_detail(store,next(r['id'] for r in store.rows('SELECT id FROM opportunities') if r['id']!=prospect))['stage']=='needs_verification'
    pa=entry(before['name'],'PA',official_url=before['evidence']['profile']['official_url'],segment='corrections_department')
    assert save_discoveries(store,[pa],settings.as_of,'duplicate')['candidate_ids']==[prospect]
    assert store.opportunity(prospect)==before and drafts==store.rows('SELECT * FROM drafts')
    assert candidate_detail(store,prospect)['origin']=='real_manual'
    assert pipeline(store)['metrics']['awaiting_approval']==1


def test_recipient_authorization_is_version_and_route_specific(store,settings,research,report):
    (oid,)=save_discoveries(store,[entry()],settings.as_of,'new')['candidate_ids']
    evidence=store.opportunity(oid)['evidence']
    evidence['research']=research
    fingerprint=digest(evidence)
    analysis=report.model_dump()|{'evidence_hash':fingerprint,'recipient':'buyer@example.org'}
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET evidence=?,evidence_hash=?,status='awaiting_approval' WHERE id=?",(json.dumps(evidence),fingerprint,oid))
        store.event('agent_decision',analysis,opportunity_id=oid,con=con)
        con.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)',('d',oid,1,fingerprint,'simulation@example.invalid','Subject','Body','awaiting_approval',json.dumps(analysis),utcnow()))
    assert candidate_detail(store,oid)['outreach_permission_required']
    assert next(a['href'] for a in pipeline(store)['actions'] if a['id']=='verify_permissions')==f'/screening?candidate={oid}#prospect-permission'
    assert pipeline(store)['metrics']['awaiting_approval']==0
    with store.connect(write=True) as con:
        con.execute('INSERT INTO contact_authorizations VALUES(?,?,?,?,?,1,?)',(oid,'buyer@example.org','Purchasing','distributor','Explicitly synthetic permission',utcnow()))
    assert candidate_detail(store,oid)['stage']=='needs_verification'
    with store.connect(write=True) as con:con.execute("UPDATE contact_authorizations SET route='direct'")
    assert candidate_detail(store,oid)['stage']=='awaiting_approval'
    with store.connect(write=True) as con:con.execute("UPDATE contact_authorizations SET recipient='other@example.org'")
    assert candidate_detail(store,oid)['stage']=='needs_verification'
    assert not store.rows('SELECT * FROM outbox') and not store.rows('SELECT * FROM approvals')


def test_outreach_remains_discoverable_after_approval_delivery_and_reply(store,settings,prospect,research,report):
    from clearline.conversations import ingest_message
    from clearline.prospect_pipeline import prospect_progress

    store.queue_prospect(prospect)
    store.save_prospect_research(store.claim(),research)
    store.save_analysis(store.claim(),report)
    name=store.opportunity(prospect)['name']
    draft=store.rows('SELECT id,version FROM drafts WHERE opportunity_id=?',(prospect,))[0]

    def check(stage,group,latest):
        matches=pipeline(store,stage=group)
        assert matches['total']==matches['metrics'][group]==1
        assert matches['rows'][0]['id']==prospect
        search=pipeline(store,q=name.lower())
        assert [(r['id'],r['stage']) for r in search['rows']]==[(prospect,stage)]
        detail=candidate_detail(store,prospect)
        progress=prospect_progress(store,prospect)
        assert progress=={key:detail[key] for key in ('stage','next_action','latest_activity')}
        assert detail['draft']['version']==draft['version']
        assert progress['latest_activity']['label']==latest
        return matches['metrics']

    check('awaiting_approval','awaiting_approval','Assessment saved')
    # A manually recorded stage cannot stand in for a message or delivery receipt.
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='quoted' WHERE id=?",(prospect,))
    assert pipeline(store,stage='in_conversation')['total']==0
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='awaiting_response' WHERE id=?",(prospect,))
    assert pipeline(store,stage='awaiting_response')['total']==0
    with store.connect(write=True) as con:
        con.execute("UPDATE opportunities SET status='awaiting_approval' WHERE id=?",(prospect,))
    store.decide(draft['id'],True)
    counts=check('awaiting_delivery','awaiting_delivery','Email approved')
    assert counts['awaiting_approval']==counts['awaiting_response']==counts['in_conversation']==0
    assert pipeline(store,stage='outreach_draft_ready')['total']==1
    assert not store.rows('SELECT id FROM outbox')
    assert 'queued' in prospect_progress(store,prospect)['next_action']
    job=store.claim(['deliver'])
    assert 'in progress' in prospect_progress(store,prospect)['next_action']
    store.deliver(job)
    counts=check('awaiting_response','awaiting_response','Simulated delivery recorded')
    assert counts['awaiting_delivery']==counts['in_conversation']==0
    with store.connect(write=True) as con:
        con.execute("UPDATE jobs SET due_at='2000-01-01' WHERE opportunity_id=? AND kind='followup'",(prospect,))
    check('follow_up','awaiting_response','Simulated delivery recorded')
    parent=store.rows("SELECT id FROM messages WHERE direction='outbound'")[0]['id']
    ingest_message(store,prospect,parent,'test-reply','A fictional reply.')
    counts=check('in_conversation','in_conversation','Simulated reply recorded')
    assert counts['awaiting_response']==counts['awaiting_delivery']==counts['awaiting_approval']==0
