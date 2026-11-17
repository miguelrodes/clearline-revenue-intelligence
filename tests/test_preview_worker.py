"""Combined launcher boundaries; all databases and model responses are fixtures."""
import importlib.util
from pathlib import Path

import pytest

from commercial_fixtures import reviewed_fixture
from test_screening import env, first, plan


spec = importlib.util.spec_from_file_location(
    'screening_dev', Path(__file__).resolve().parents[1] / 'scripts/screening_dev.py'
)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_database_selection_stays_inside_integration_runtime(settings, tmp_path, monkeypatch):
    root = tmp_path / 'integration'
    monkeypatch.setattr(preview, 'ROOT', root)
    monkeypatch.setattr(preview.Settings, 'load', lambda: settings)
    default = preview.configuration(None, True)
    assert default.db_path == root / 'runtime/phase3/screening.sqlite3'
    assert default.screening_budget_path == default.db_path
    isolated = preview.configuration(None, True, Path('runtime/acceptance/test.sqlite3'))
    assert isolated.db_path == root / 'runtime/acceptance/test.sqlite3'
    assert isolated.screening_budget_path == isolated.db_path
    for path in (settings.db_path, root / 'runtime/../../stable.sqlite3'):
        with pytest.raises(ValueError, match='inside this checkout'):
            preview.configuration(None, True, path)
    (root / 'runtime').mkdir(parents=True)
    (root / 'runtime/escape').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='inside this checkout'):
        preview.configuration(None, True, Path('runtime/escape/stable.sqlite3'))


def test_startup_does_not_create_jobs_or_change_saved_business_work(
    store, settings, draft, monkeypatch
):
    store.schedule(1)
    with store.connect(write=True) as con:
        con.execute("UPDATE schedules SET next_run='2000-01-01'")
    tables = ('jobs', 'opportunities', 'drafts', 'approvals', 'outbox', 'schedules')
    before = {table: store.rows('SELECT * FROM ' + table) for table in tables}
    decisions = store.rows("SELECT * FROM events WHERE kind='agent_decision'")

    def forbidden(*args, **kwargs):
        pytest.fail('Automatic work or a model call must not run on preview startup')

    monkeypatch.setattr(store, 'tick', forbidden)
    monkeypatch.setattr('clearline.operations.start_batch', forbidden)
    monkeypatch.setattr('clearline.operations.queue_brief', forbidden)
    monkeypatch.setattr('clearline.worker.scan', forbidden)
    monkeypatch.setattr('clearline.worker.execute_job', forbidden)
    preview.run_preview_worker(store, settings, drain=True)
    assert {table: store.rows('SELECT * FROM ' + table) for table in tables} == before
    assert store.rows("SELECT * FROM events WHERE kind='agent_decision'") == decisions


def test_allowed_jobs_are_consumed_but_portfolio_and_phase4_are_not(
    store, settings, monkeypatch
):
    expected = {
        'analyze', 'prepare', 'reply', 'revise_draft', 'review_sent', 'followup', 'deliver',
        'revenue_brief', 'agency_scan', 'agency_qualify', 'agency_outreach',
        'agency_deliver', 'pipeline_discover', 'pipeline_research', 'pipeline_qualify',
    }
    assert set(preview.PREVIEW_JOB_KINDS) == expected
    ids = {kind: store.enqueue(kind, {}) for kind in expected}
    excluded = {
        kind: store.enqueue(kind, {})
        for kind in ('scan', 'prospect_qualify', 'prospect_research')
    }
    observed = []

    async def execute(st, config, job, *args):
        observed.append(job['kind'])
        st.finish(job['id'])

    monkeypatch.setattr('clearline.worker.execute_job', execute)
    preview.run_preview_worker(store, settings, drain=True)
    assert set(observed) == expected and len(observed) == len(expected)
    for kind, jid in ids.items():
        assert store.rows('SELECT status FROM jobs WHERE id=?', (jid,))[0]['status'] == 'completed'
    for jid in excluded.values():
        assert store.rows('SELECT status,attempts FROM jobs WHERE id=?', (jid,))[0] == {
            'status': 'queued', 'attempts': 0,
        }


def test_interrupted_allowed_work_resumes_without_creating_replacements(
    store, settings, monkeypatch
):
    allowed = store.enqueue('analyze', {})
    excluded = store.enqueue('prospect_research', {})
    with store.connect(write=True) as con:
        con.execute("UPDATE jobs SET status='running'")

    async def execute(st, config, job, *args):
        st.finish(job['id'])

    monkeypatch.setattr('clearline.worker.execute_job', execute)
    preview.run_preview_worker(store, settings, drain=True)
    assert len(store.rows('SELECT * FROM jobs')) == 2
    assert store.rows('SELECT status FROM jobs WHERE id=?', (allowed,))[0]['status'] == 'completed'
    assert store.rows('SELECT status,attempts FROM jobs WHERE id=?', (excluded,))[0] == {
        'status': 'running', 'attempts': 0,
    }


def test_existing_customer_and_agency_dispatch_with_manual_brief(
    env, opportunity, decision, monkeypatch
):
    from clearline import worker
    from clearline.screening import queue, summary
    from clearline.evidence import current_assessment
    from clearline.operations import latest_assessment

    settings, store, *_ = env
    agency = first(env)
    queue(store, settings, agency['id'], agency['evidence_hash'])
    store.queue_analysis(opportunity['id'])
    store.enqueue('revenue_brief', {})
    real_execute = worker.execute_job
    manual_briefs = []

    async def customer_analyst(st, job, config):
        return reviewed_fixture(st, job, decision)

    async def agency_analyst(*args):
        return {'decision': plan(), 'review_passed': True, 'outreach_eligible': False}

    async def manual_brief(st, job, config):
        manual_briefs.append(job['id'])

    async def execute(st, config, job, analyst, capacity):
        await real_execute(st, config, job, customer_analyst, capacity)

    monkeypatch.setattr(worker, 'execute_job', execute)
    monkeypatch.setattr('clearline.screening_agent.qualify', agency_analyst)
    monkeypatch.setattr('clearline.brief.generate', manual_brief)
    preview.run_preview_worker(store, settings, drain=True)
    jobs = store.rows('SELECT kind,status FROM jobs')
    assert len(jobs) == 3 and all(job['status'] == 'completed' for job in jobs)
    assert summary(store)['assessed'] == 1 and len(manual_briefs) == 1
    assessment = latest_assessment(store, opportunity['id'])
    with store.connect() as con:
        assert current_assessment(con, opportunity['id'], assessment)
    assert len(store.rows('SELECT * FROM drafts')) == 1
    assert not store.rows('SELECT * FROM approvals')
    assert not store.rows('SELECT * FROM outbox')


def test_paused_delivery_only_uses_exact_approval_and_leaves_other_work_queued(store, settings, draft):
    with pytest.raises(ValueError, match='Pause'):
        store.set_delivery_only(True)
    store.set_paused(True)
    store.decide(draft['id'], True)
    other_ids = [store.enqueue(kind, {}) for kind in ('analyze', 'reply', 'review_sent', 'pipeline_research', 'followup')]
    store.schedule(1)
    with store.connect(write=True) as con:
        con.execute("UPDATE schedules SET next_run='2000-01-01'")
        con.execute("INSERT INTO controls VALUES('api_blocked','fixture')")
    schedule = store.rows('SELECT * FROM schedules')
    preview.run_preview_worker(store, settings, drain=True)
    assert not store.rows('SELECT * FROM outbox')
    assert store.rows("SELECT status FROM jobs WHERE kind='deliver'") == [{'status': 'queued'}]
    store.set_delivery_only(True)
    with pytest.raises(ValueError, match='Turn off'):
        store.set_paused(False)
    assert store.claim(preview_mode='general') is None
    preview.run_preview_worker(store, settings, drain=True)
    preview.run_preview_worker(store, settings, drain=True)
    assert store.rows('SELECT draft_id,delivery_mode FROM outbox') == [{'draft_id': draft['id'], 'delivery_mode': 'simulated'}]
    assert store.rows("SELECT status,attempts FROM jobs WHERE kind='deliver'") == [{'status':'completed','attempts':1}]
    for jid in other_ids:
        assert store.rows('SELECT status,attempts FROM jobs WHERE id=?', (jid,)) == [{'status':'queued','attempts':0}]
    assert store.rows('SELECT * FROM schedules') == schedule
    store.set_delivery_only(False)
    assert store.paused() and store.claim(preview_mode='delivery') is None


def test_reclaimed_job_reports_persisted_attempt_state(store):
    jid = store.enqueue('analyze', {})
    with store.connect(write=True) as con:
        con.execute("UPDATE jobs SET finished_at='old time',error='old failure' WHERE id=?", (jid,))
    job = store.claim(['analyze'], preview_mode='general')
    saved = store.rows('SELECT status,started_at,finished_at,attempts,error FROM jobs WHERE id=?', (jid,))[0]
    assert saved == {key: job[key] for key in saved}
    assert saved['status'] == 'running' and saved['attempts'] == 1 and saved['finished_at'] is None


def test_explicit_worker_can_deliver_during_a_model_block(store, settings, draft):
    store.decide(draft['id'], True)
    jid=store.enqueue('analyze', {})
    with store.connect(write=True) as con:
        con.execute("INSERT INTO controls VALUES('api_blocked','fixture')")
    preview.run_preview_worker(store, settings, drain=True)
    assert store.rows('SELECT draft_id FROM outbox') == [{'draft_id': draft['id']}]
    assert store.rows('SELECT status,attempts FROM jobs WHERE id=?',(jid,)) == [{'status':'queued','attempts':0}]
