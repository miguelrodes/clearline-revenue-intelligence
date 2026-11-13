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


def test_manual_soft_edit_is_visible_debounced_and_approval_waits_for_fresh_qa(store,opportunity,decision):
    from test_intelligence import assessed
    from clearline.action_policy import proposal_fingerprint
    from clearline.draft_revision import current_draft
    from clearline.workbench import ready_messages
    from clearline.reporting import valid_draft
    j,a=assessed(store,opportunity,decision,['known_distributor_channel'],'channel_support');save_reviewed_fixture(store,j,a)
    old=store.rows('SELECT * FROM drafts')[0]
    first=store.revise_draft(old['id'],old['recipient'],old['subject'],'Would a short refresher be useful?')
    second=store.revise_draft(first,old['recipient'],old['subject'],'Would a short refresher on screening procedures help your team?')
    jobs=store.rows("SELECT * FROM jobs WHERE kind='revise_draft' ORDER BY created_at,rowid")
    assert [j['status'] for j in jobs]==['cancelled','queued']
    assert jobs[1]['due_at']>jobs[1]['created_at']
    d=store.rows('SELECT * FROM drafts WHERE id=?',(second,))[0]
    assert not valid_draft(store,d)
    assert [m['draft']['id'] for m in ready_messages(store)]==[second]
    with pytest.raises(ValueError):store.decide(second,True)
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET due_at='2000-01-01' WHERE id=?",(jobs[1]['id'],))
    job=store.claim(kinds=['revise_draft']);assert current_draft(store,job)['id']==second
    fresh={**a,'subject':d['subject'],'body':d['body']};fresh['quality']={'passed':True,'proposal_hash':proposal_fingerprint(fresh)}
    save_revision(store,job,RevisedEmail(subject=d['subject'],body=d['body'],review_note='Verified exact edit.',engine_version=a['engine_version'],context_hash=a['context_hash'],evidence_hash=a['evidence_hash'],quality=fresh['quality']))
    newest=store.rows('SELECT * FROM drafts ORDER BY version DESC LIMIT 1')[0]
    assert newest['body']==d['body'] and valid_draft(store,newest)
    assert not store.rows('SELECT * FROM approvals')
    with pytest.raises(ValueError):store.decide(second,True)
    store.decide(newest['id'],True)
    assert len(store.rows('SELECT * FROM approvals'))==1


def test_manual_review_cannot_rewrite_or_use_empty_quality_result(store,opportunity,decision):
    from test_intelligence import assessed
    j,a=assessed(store,opportunity,decision,['open_orders_require_review'],'order_status');save_reviewed_fixture(store,j,a)
    old=store.rows('SELECT * FROM drafts')[0]
    edited=store.revise_draft(old['id'],old['recipient'],old['subject'],'Could you confirm the status of the existing order?')
    with store.connect(write=True) as c:c.execute("UPDATE jobs SET due_at='2000-01-01' WHERE kind='revise_draft'")
    job=store.claim(kinds=['revise_draft'])
    with pytest.raises(ValueError,match='exact saved human edit'):save_revision(store,job,result())
    d=store.rows('SELECT * FROM drafts WHERE id=?',(edited,))[0]
    with pytest.raises(ValueError,match='successful quality review'):
        save_revision(store,job,RevisedEmail(subject=d['subject'],body=d['body'],review_note='Claimed fine'))
    assert not store.rows('SELECT * FROM approvals')
    assert len(store.rows('SELECT * FROM drafts'))==2


def test_failed_manual_review_can_be_reworked_with_human_guidance(store,opportunity,decision):
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


def test_account_detail_keeps_edited_draft_visible_without_approval(store,settings,opportunity,decision):
    from test_intelligence import assessed
    j,a=assessed(store,opportunity,decision,['open_orders_require_review'],'order_status');save_reviewed_fixture(store,j,a)
    d=store.rows('SELECT * FROM drafts')[0]
    edited=store.revise_draft(d['id'],d['recipient'],d['subject'],'Can you confirm the current order status?')
    api=TestClient(create_app(settings))
    saved=api.get('/api/accounts/example').json()['drafts'][0]
    assert saved['id']==edited and saved['can_edit'] and not saved['can_review'] and saved['review_status']=='queued'
