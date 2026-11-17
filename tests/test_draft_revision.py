from commercial_fixtures import save_reviewed_fixture
import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from clearline.api import create_app
from clearline.draft_revision import queue_revisions, save_revision, RevisedEmail
from clearline.worker import execute_job
from clearline.workbench import work_groups, decide_messages
from test_workbench import prepared, snaps


def result():
    return RevisedEmail(subject='Screening supplies',body='Hello,\n\nWould it help to prepare a quote for your next replenishment?\n\nThank you.',review_note='Made the message more direct and offered a quote. No discount terms were invented.')


def test_revision_is_selected_idempotent_and_requires_new_approval(store,settings,opportunity,decision,monkeypatch):
    _,g=prepared(store,opportunity,decision);selected=snaps(g)[:1];old=g['members'][0]['draft']
    api=TestClient(create_app(settings),headers={"X-Clearline-Client":"web"})
    response=api.post('/api/work/'+g['id']+'/revise',json={'snapshots':selected,'instructions':'Make this more direct and offer a quote'})
    assert response.status_code==200
    queued=response.json()
    assert queued==queue_revisions(store,g['id'],selected,'Make this more direct and offer a quote')
    assert len(store.rows("SELECT * FROM jobs WHERE kind='revise_draft'"))==1
    with pytest.raises(ValueError,match='revising'):decide_messages(store,g['id'],selected,True)
    assert not store.rows('SELECT * FROM approvals')
    async def revised(*args):
        from clearline.evidence import ENGINE_VERSION,context_hash
        with store.connect() as c:version=context_hash(c,args[1]['opportunity_id'])
        return result().model_copy(update={'engine_version':ENGINE_VERSION,'context_hash':version,'evidence_hash':old['evidence_hash'],'quality':{'passed':True}})
    monkeypatch.setattr('clearline.draft_revision.rewrite',revised)
    job=store.claim(kinds=['revise_draft']);asyncio.run(execute_job(store,settings,job))
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='completed'
    drafts=store.rows('SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version',(old['opportunity_id'],))
    assert len(drafts)==2 and drafts[0]['body']==old['body'] and drafts[0]['status']=='superseded'
    assert drafts[-1]['status']=='awaiting_approval' and drafts[-1]['recipient']==old['recipient']
    assert json.loads(drafts[-1]['analysis'])['revision_note']==result().review_note
    assert not store.rows('SELECT * FROM outbox') and not store.rows('SELECT * FROM approvals')
    with pytest.raises(ValueError):decide_messages(store,g['id'],selected,True)
    # Persisting a retried completion cannot create a duplicate version.
    save_revision(store,job,result())
    assert len(store.rows('SELECT * FROM drafts'))==len(g['members'])+1


def test_revision_never_overwrites_newer_edit(store,opportunity,decision):
    _,g=prepared(store,opportunity,decision);d=g['members'][0]['draft']
    queue_revisions(store,g['id'],snaps(g)[:1],'Be direct')
    job=store.claim(kinds=['revise_draft'])
    edited=store.revise_draft(d['id'],d['recipient'],'Human subject','Human copy')
    save_revision(store,job,result())
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='cancelled'
    assert store.rows('SELECT body FROM drafts WHERE id=?',(edited,))[0]['body']=='Human copy'
    assert len(store.rows('SELECT * FROM drafts'))==len(g['members'])+1


def test_revision_cannot_bypass_changed_evidence_or_rejection(store,opportunity,decision):
    _,g=prepared(store,opportunity,decision);d=g['members'][0]['draft']
    queue_revisions(store,g['id'],snaps(g)[:1],'Offer a discount if appropriate')
    job=store.claim(kinds=['revise_draft'])
    store.decide(d['id'],False)
    save_revision(store,job,result())
    assert store.rows('SELECT status FROM drafts WHERE id=?',(d['id'],))[0]['status']=='rejected'
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='cancelled'


def test_revision_selection_validation_is_atomic(store,opportunity,decision):
    _,g=prepared(store,opportunity,decision);ss=snaps(g);ss[1]['snapshot_hash']='stale'
    with pytest.raises(ValueError):queue_revisions(store,g['id'],ss,'Be direct')
    assert not store.rows("SELECT * FROM jobs WHERE kind='revise_draft'")
    with pytest.raises(ValueError):queue_revisions(store,g['id'],snaps(g),'  ')
    with pytest.raises(ValueError):queue_revisions(store,'messages:other',snaps(g),'Be direct')


def test_failed_revision_keeps_original_draft_and_retry_path(store,settings,opportunity,decision,monkeypatch):
    _,g=prepared(store,opportunity,decision);old=g['members'][0]['draft']
    queue_revisions(store,g['id'],snaps(g)[:1],'Be direct')
    async def failure(*args):raise ValueError('Invalid model output')
    monkeypatch.setattr('clearline.draft_revision.rewrite',failure)
    job=store.claim(kinds=['revise_draft']);asyncio.run(execute_job(store,settings,job))
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='failed'
    assert store.rows('SELECT body,status FROM drafts WHERE id=?',(old['id'],))[0]=={'body':old['body'],'status':'awaiting_approval'}
    store.retry(job['id'])
    assert store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status']=='queued'


def test_human_edits_review_only_the_delivered_version(store,settings,opportunity,decision,monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from clearline.conversations import conversation
    from test_intelligence import assessed
    j,a=assessed(store,opportunity,decision,['open_orders_require_review'],'order_status')
    save_reviewed_fixture(store,j,a)
    original=store.rows('SELECT * FROM drafts')[0]
    first=store.revise_draft(original['id'],original['recipient'],'Changed subject','Intermediate copy')
    final=store.revise_draft(first,original['recipient'],'Final subject','Final human text')
    assert not store.rows("SELECT id FROM jobs WHERE kind IN ('review_sent','revise_draft')")
    with pytest.raises(ValueError):store.decide(first,True)
    store.decide(final,True)
    assert not store.rows("SELECT id FROM jobs WHERE kind='review_sent'")
    delivery=store.claim(['deliver'])
    store.deliver(delivery);store.deliver(delivery);store.finish(delivery['id'])
    assert store.rows('SELECT draft_id,subject,body FROM outbox')==[dict(draft_id=final,subject='Final subject',body='Final human text')]
    reviews=store.rows("SELECT id FROM jobs WHERE kind='review_sent'")
    assert len(reviews)==1
    calls=[]
    async def create(**kwargs):
        calls.append(json.loads(kwargs['input']))
        return SimpleNamespace(status='completed',output_text='The salesperson requested an order update.')
    @asynccontextmanager
    async def fake_client(*args):yield SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr('clearline.telemetry.client_for',fake_client)
    asyncio.run(execute_job(store,settings,store.claim(['review_sent'])))
    assert len(calls)==1 and calls[0]['sent_message']=='Final human text'
    assert conversation(store,'example')['messages'][0]['sent_review']=='The salesperson requested an order update.'
    assert store.claim(['review_sent']) is None and len(store.rows('SELECT * FROM approvals'))==1


def test_outstanding_legacy_edit_becomes_confirmable_without_model(store,settings,opportunity,decision):
    from test_intelligence import assessed
    from clearline.store import Store
    j,a=assessed(store,opportunity,decision,['open_orders_require_review'],'order_status')
    save_reviewed_fixture(store,j,a)
    old=store.rows('SELECT * FROM drafts')[0]
    edited=store.revise_draft(old['id'],old['recipient'],old['subject'],'Exact previously saved human edit.')
    with store.connect(write=True) as db:
        db.execute("UPDATE drafts SET analysis=json_remove(analysis,'$.human_edit_hash') WHERE id=?",(edited,))
    d=store.rows('SELECT * FROM drafts WHERE id=?',(edited,))[0]
    legacy=store.enqueue('revise_draft',{'review_only':True,'draft_id':edited,'snapshot_hash':store.draft_hash(d)},'example')
    Store(store.path)
    assert store.rows('SELECT status FROM jobs WHERE id=?',(legacy,))==[{'status':'cancelled'}]
    assert TestClient(create_app(settings)).get('/api/accounts/example').json()['drafts'][0]['can_review']
    with store.connect(write=True) as db:db.execute("UPDATE drafts SET body='tampered' WHERE id=?",(edited,))
    with pytest.raises(ValueError):store.decide(edited,True)
    assert not store.rows('SELECT * FROM approvals')


def test_person_can_still_request_an_agent_rewrite(store,opportunity,decision):
    from test_intelligence import assessed
    from clearline.draft_revision import current_draft
    j,a=assessed(store,opportunity,decision,['known_distributor_channel'],'channel_support');save_reviewed_fixture(store,j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    edited=store.revise_draft(d['id'],d['recipient'],d['subject'],'Please order directly from us.')
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET status='failed' WHERE kind='revise_draft'")
    group=next(g for g in work_groups(store)['groups'] if g['id']=='messages:channel_support')
    queued=queue_revisions(store,group['id'],snaps(group),'Keep distributor purchasing and offer training support instead.')
    job=store.claim(kinds=['revise_draft'])
    assert job['id']==queued['job_ids'][0] and current_draft(store,job)['id']==edited
    with pytest.raises(ValueError):store.decide(edited,True)


def test_account_detail_allows_human_confirmation_after_edit(store,settings,opportunity,decision):
    from test_intelligence import assessed
    j,a=assessed(store,opportunity,decision,['open_orders_require_review'],'order_status');save_reviewed_fixture(store,j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    edited=store.revise_draft(d['id'],d['recipient'],d['subject'],'Can you confirm the current order status?')
    api=TestClient(create_app(settings))
    saved=api.get('/api/accounts/example').json()['drafts'][0]
    assert saved['id']==edited and saved['can_edit'] and saved['can_review'] and saved['review_status'] is None
