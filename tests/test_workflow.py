from datetime import datetime, timezone, timedelta
import json
import pytest
from clearline.store import Store
from clearline.worker import run_one, worker_lock


def test_edit_invalidates_approval_and_blocks_old_action(store,draft):
    store.decide(draft["id"],True)
    new_id = store.revise_draft(draft["id"],"changed@example.invalid","New subject","New content")
    assert store.claim() is None
    assert store.rows("SELECT status FROM jobs WHERE kind='deliver'")==[{"status":"cancelled"}]
    assert not store.rows("SELECT * FROM outbox")
    assert store.rows("SELECT status FROM drafts WHERE id=?",(new_id,))[0]["status"] == "awaiting_approval"


def test_rejection_never_sends(store,draft):
    store.decide(draft["id"],False)
    assert store.claim() is None
    assert not store.rows("SELECT * FROM outbox")


def test_simulated_delivery_retry_is_idempotent_and_reply_cancels_followup(store,draft):
    store.decide(draft["id"],True)
    job = store.claim()
    store.deliver(job)
    store.deliver(job)
    assert len(store.rows("SELECT * FROM outbox")) == 1
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]["status"] == "queued"
    store.record_outcome("example","reply","Manual test response")
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]["status"] == "cancelled"
    assert store.rows("SELECT provenance FROM outcomes")[0]["provenance"] == "manual_demo_input"


def test_reply_while_agent_running_prevents_new_draft(store,draft,decision):
    store.decide(draft['id'],True)
    delivery=store.claim()
    store.deliver(delivery)
    store.finish(delivery['id'])
    store.queue_analysis("example",followup_of=draft['id'],investigation=True)
    job = store.claim()
    store.record_outcome("example","reply","Stop follow-up")
    store.save_analysis(job,decision)
    assert not store.rows("SELECT * FROM drafts WHERE status='awaiting_approval'")
    assert store.rows("SELECT status FROM jobs WHERE id=?",(job['id'],))[0]["status"] == "cancelled"


def test_changed_scan_evidence_blocks_approval(store,draft,opportunity):
    opportunity["evidence_hash"] = "changed"
    store.save_scan({},[opportunity])
    with pytest.raises(ValueError,match="changed"):
        store.decide(draft["id"],True)


def test_approval_hash_detects_tampering(store,draft):
    store.decide(draft["id"],True)
    with store.connect(write=True) as con:
        con.execute("UPDATE drafts SET body='Changed after approval' WHERE id=?",(draft["id"],))
    with pytest.raises(ValueError,match="approval"):
        store.deliver(store.claim())


def test_restart_preserves_state_and_recovers_job(store,settings,opportunity):
    jid = store.queue_analysis("example")
    store.claim()
    restarted = Store(settings.db_path)
    restarted.recover_interrupted()
    assert restarted.claim()["id"] == jid
    assert restarted.opportunity("example")["name"] == opportunity["name"]


def test_schedule_persists_and_does_not_duplicate_occurrence(store,settings):
    store.schedule(10)
    due = store.rows("SELECT next_run FROM schedules")[0]["next_run"]
    restarted = Store(settings.db_path)
    restarted.tick(due)
    restarted.tick(due)
    assert len(restarted.rows("SELECT * FROM jobs")) == 1
    assert restarted.rows("SELECT next_run FROM schedules")[0]["next_run"] > due


def test_single_worker_lock(settings):
    with worker_lock(settings.db_path):
        with pytest.raises(RuntimeError,match="already"):
            with worker_lock(settings.db_path): pass


def test_missing_key_blocks_without_fake_draft(store,settings,opportunity,monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    store.queue_analysis("example")
    run_one(store,settings)
    assert store.rows("SELECT status FROM jobs")[0]["status"] == "blocked_config"
    assert not store.rows("SELECT * FROM drafts")


def test_worker_boundary_with_small_test_stub(store,settings,opportunity,decision):
    async def response_fixture(*args): return decision
    store.queue_analysis("example")
    run_one(store,settings,analyst=response_fixture)
    d = store.rows("SELECT * FROM drafts")[0]
    store.decide(d["id"],True)
    run_one(store,settings)
    assert store.rows("SELECT delivery_mode FROM outbox")[0]["delivery_mode"] == "simulated"


def test_cancelled_agent_cannot_publish_a_draft(store,opportunity,decision):
    jid=store.queue_analysis("example")
    job=store.claim()
    store.cancel_job(jid)
    store.save_analysis(job,decision)
    assert not store.rows("SELECT * FROM drafts")
    assert store.rows("SELECT status FROM jobs")[0]["status"]=="cancelled"


def test_cancelled_delivery_cannot_reach_outbox(store,draft):
    store.decide(draft["id"],True)
    job=store.claim()
    store.cancel_job(job["id"])
    with pytest.raises(ValueError,match="no longer running"):
        store.deliver(job)
    assert not store.rows("SELECT * FROM outbox")


def test_pause_keeps_jobs_queued(store,settings,opportunity):
    store.queue_analysis("example")
    store.set_paused(True)
    assert not run_one(store,settings)
    assert store.rows("SELECT status FROM jobs")[0]["status"]=="queued"


def test_order_outcome_is_labeled_deduplicated_and_stops_followup(store,draft):
    store.decide(draft["id"],True)
    store.deliver(store.claim())
    store.record_outcome("example","order","Synthetic acceptance outcome",12345,"TEST-001")
    with pytest.raises(ValueError,match="already"):
        store.record_outcome("example","order","Same order",12345,"TEST-001")
    outcomes=store.rows("SELECT * FROM outcomes")
    assert len(outcomes)==1 and outcomes[0]["provenance"]=="manual_demo_input"
    assert outcomes[0]["amount_cents"]==12345
    assert store.rows("SELECT status FROM jobs WHERE kind='followup'")[0]["status"]=="cancelled"
    with pytest.raises(ValueError): store.queue_analysis("example")


def test_schedule_retains_selected_policy_and_spend_limit(store):
    store.schedule(60,analysis_limit=0,policy={"inactivity_days":120})
    row=store.rows("SELECT * FROM schedules")[0]
    store.tick(row["next_run"])
    payload=json.loads(store.rows("SELECT payload FROM jobs")[0]["payload"])
    assert payload=={"analysis_limit":0,"policy":{"inactivity_days":120}}
