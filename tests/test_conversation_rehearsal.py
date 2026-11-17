"""MCP contact clearance and the isolated rehearsal budget, entirely offline."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clearline import demo, telemetry
from clearline.screening_budget import BudgetLimit
from test_contact_clearance import add_task
from test_mcp import TOKEN, call, client, data
from test_phase12_acceptance_worker import body, job, reserve


@pytest.fixture
def rehearsal(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    import conversation_demo
    return conversation_demo


def test_contact_verification_through_mcp_shares_dashboard_state(client, store, opportunity):
    add_task(store, "example", "contact-check", "Verify current purchasing contact and route", "Buyer changed.")
    add_task(store, "example", "credit-check", "Resolve credit memo", "Verify the adjustment.")
    base = {"account_id": "example", "recipient": "buyer@example.org"}
    assert call(client, "record_contact_authorization", base)["isError"]
    details = dict(base, authorized=True, route="direct", role="Purchasing coordinator", evidence="")
    assert call(client, "record_contact_authorization", details)["isError"]
    assert not store.rows("SELECT * FROM contact_authorizations")
    assert not store.rows("SELECT * FROM jobs")
    account = data(call(client, "get_account", {"account_id": "example"}))
    assert [row["id"] for row in account["pending_contact_checks"]] == ["contact-check"]
    details["evidence"] = "Synthetic test record confirms this buyer is authorized to discuss direct purchasing."
    assert call(client, "record_contact_authorization", dict(details, task_id="credit-check"))["isError"]
    verified = data(call(client, "record_contact_authorization", details))
    assert verified["task_status"] == "resolved" and verified["requires_reassessment"]
    repeated = data(call(client, "record_contact_authorization", details))
    assert not repeated["requires_reassessment"]
    assert store.rows("SELECT kind,opportunity_id FROM jobs") == [{"kind": "analyze", "opportunity_id": "example"}]
    assert not data(call(client, "get_account", {"account_id": "example"}))["pending_contact_checks"]
    work = client.get("/api/accounts/example/commercial-work").json()
    assert [t["id"] for t in work["tasks"]] == ["credit-check"]
    assert store.rows("SELECT recipient,route,authorized FROM contact_authorizations") == [
        {"recipient": "buyer@example.org", "route": "direct", "authorized": 1}]
    assert not store.rows("SELECT * FROM approvals") and not store.rows("SELECT * FROM outbox")


def test_contact_schema_and_repeat_with_internal_handoff_review(client, store, opportunity):
    response=client.post('/mcp', headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/json, text/event-stream'},
                         json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
    schema=next(t['inputSchema'] for t in response.json()['result']['tools'] if t['name']=='record_contact_authorization')
    assert schema['properties']['task_id']['type']=='string' and 'task_id' not in schema['required']
    add_task(store,'example','route','Record explicit recipient/route authorization','Verify who buys directly.')
    add_task(store,'example','crm','Review available contact-handoff context and update the CRM hypothesis','Review prior contact notes.')
    choices=data(call(client,'get_account',{'account_id':'example'}))['pending_contact_checks']
    assert [t['id'] for t in choices]==['route'] and choices[0]['reason']
    args=dict(account_id='example',recipient='buyer@example.org',role='Buyer',route='direct',
              evidence='Synthetic directory and explicit permission.',authorized=True)
    assert call(client,'record_contact_authorization',dict(args,task_id='crm'))['isError']
    initial=data(call(client,'record_contact_authorization',args))
    assert initial['requires_reassessment']
    for override in ({},{'task_id':'route'}):
        repeat=data(call(client,'record_contact_authorization',dict(args,**override)))
        assert not repeat['requires_reassessment'] and repeat['task_status']=='resolved'
    assert store.rows("SELECT id FROM investigation_tasks WHERE status='pending'")==[{'id':'crm'}]
    assert [r['id'] for r in store.rows('SELECT id FROM jobs')]==[initial['job_id']]


def test_multiple_contact_checks_require_explicit_id(client, store, opportunity):
    for tid in ("route", "contact"):
        add_task(store, "example", tid, "Verify purchasing " + tid, "Role or buying route is missing.")
    args = dict(account_id="example", recipient="buyer@example.org", authorized=True, route="direct",
                role="Purchasing coordinator", evidence="The fictional directory confirms the role and permission.")
    assert call(client, "record_contact_authorization", args)["isError"]
    assert not store.rows("SELECT * FROM contact_authorizations")
    assert data(call(client, "record_contact_authorization", dict(args, task_id="route")))["task_status"] == "resolved"
    assert store.rows("SELECT id FROM investigation_tasks WHERE status='pending'") == [{"id": "contact"}]


def test_reset_and_restart_preserve_charges_and_pending_reservations(rehearsal, tmp_path, store, opportunity, monkeypatch):
    folder = tmp_path / "interactive"
    folder.mkdir()
    baseline, session, marker = demo.paths(folder)
    sent = folder / "approved-outbound.sqlite3"
    money = folder / "interactive-budget.sqlite3"
    for key, value in dict(FOLDER=folder, BASELINE=baseline, SESSION=session, MARKER=marker, SENT=sent,
                           CONVERSATION_BUDGET=money, LONE_TREE="example").items():
        monkeypatch.setattr(rehearsal, key, value)
    for key, value in dict(CONVERSATION_DIR=folder, CONVERSATION_SESSION=session, CONVERSATION_BUDGET=money).items():
        monkeypatch.setattr(demo, key, value)
    for checkpoint in (baseline, session, sent):
        demo.backup(store.path, checkpoint)
    marker.write_text(json.dumps(dict(kind="clearline-disposable-demo-v1", source=str(store.path),
        baseline=str(baseline), session=str(session), baseline_sha256=rehearsal.checksum(baseline),
        approved_outbound_sha256=rehearsal.checksum(sent))))
    ledger = rehearsal.interactive_budget(create=True)
    selected = job("scoped", "example", "reply")
    reserve(ledger, selected, "gpt-6.1-sol", "r1", body(), "reply")
    ledger.settle("r1", {"model": "gpt-6.1-sol", "service_tier": "default", "usage": {
        "input_tokens": 1000, "output_tokens": 200, "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 0}}}, 200)
    reserve(ledger, selected, "gpt-6.1-sol", "r2", body(), "reply")
    usage = demo.conversation_spending(session)
    assert usage["charged_usd"] == pytest.approx(0.00381) and usage["reserved_usd"] > 0
    assert usage["remaining_usd"] == pytest.approx(2 - usage["charged_usd"] - usage["reserved_usd"])
    for checkpoint in (True, False):
        rehearsal.restore(sent=checkpoint)
        reopened = rehearsal.interactive_budget(create=True)
        assert demo.conversation_spending(session) == usage
        with pytest.raises(BudgetLimit, match="unsettled"):
            reopened.admit(job("new", "example", "reply"))
    ledger.settle("r2", {}, 502)
    with pytest.raises(BudgetLimit, match="unsettled"):
        rehearsal.interactive_budget().admit(job("new", "example", "analyze"))
    money.unlink()  # Only this disposable pytest fixture.
    with pytest.raises(ValueError, match="unavailable"):
        rehearsal.interactive_budget(create=True)


def test_only_affordable_targeted_jobs_can_be_claimed(rehearsal, store, opportunity, tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "LONE_TREE", "example")
    ledger = rehearsal.ConversationBudget(tmp_path / "small-budget.sqlite3")
    ledger.initialize(store.path, ["example"], [], budget_usd=.30)
    inherited = store.enqueue("analyze", {}, "example", "prior")
    skipped = store.enqueue("revenue_brief", {}, key="unrelated")
    expensive = store.enqueue("revise_draft", {}, "example", "edit")
    accepted = store.enqueue("analyze", {}, "example", "target")
    assert rehearsal.claim_interactive(store, ledger, {inherited})["id"] == accepted
    result = {r["id"]: r for r in store.rows("SELECT id,status,attempts,error FROM jobs")}
    assert result[expensive]["status"] == "blocked_config" and "projected" in result[expensive]["error"]
    assert result[expensive]["attempts"] == 0
    assert result[inherited]["status"] == result[skipped]["status"] == "queued"
    assert ledger.summary()["requests"] == ledger.summary()["input_count_requests"] == 0
    for refused in (job("another", "other"), job("scan", "example", "scan")):
        with pytest.raises(BudgetLimit):
            ledger.admit(refused)


def test_unguarded_model_client_cannot_open_for_rehearsal(settings):
    async def invoke():
        async with telemetry.client_for(SimpleNamespace(path=demo.CONVERSATION_SESSION), job(), settings):
            pytest.fail("An unguarded client must never open")
    with pytest.raises(BudgetLimit, match="persistent interactive spending guard"):
        asyncio.run(invoke())


def test_registered_worker_wraps_real_client_for_a_revision(rehearsal, store, settings, opportunity, tmp_path, monkeypatch):
    import openai
    from test_phase12_acceptance_worker import httpx

    jid = store.enqueue("revise_draft", {}, "example", "edit")
    selected = store.claim(["revise_draft"])
    money = tmp_path / "meter.sqlite3"
    monkeypatch.setattr(demo, "CONVERSATION_SESSION", store.path)
    monkeypatch.setattr(demo, "CONVERSATION_BUDGET", money)
    ledger = rehearsal.ConversationBudget(money)
    ledger.initialize(store.path, ["example"], [])
    calls = []
    async def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        assert ledger.summary()["retained_reservations_usd"] > 0
        return httpx.Response(200, json={"model": settings.model, "service_tier": "default",
                                         "usage": {"input_tokens": 100, "output_tokens": 50}})
    http_client = openai.DefaultAsyncHttpxClient
    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", lambda **options: http_client(
        transport=httpx.MockTransport(respond), trust_env=False, **options))
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture-only")
    async def invoke():
        with rehearsal.bounded_clients(ledger):
            async with telemetry.client_for(store, selected, settings) as sdk:
                result = await sdk.responses.create(model=settings.model, input="Offline guard test", max_output_tokens=100)
                assert result.usage.output_tokens == 50
    asyncio.run(invoke())
    assert selected["id"] == jid and calls == ["/v1/responses/input_tokens", "/v1/responses"]
    assert ledger.summary()["estimated_usd"] == pytest.approx(.00075)


def test_review_discloses_both_recipients_before_any_decision(client, store, draft):
    actual = data(call(client, "get_draft", {"draft_id": draft["id"]}))
    review = data(call(client, "review_outreach", {"draft_ids": [draft["id"]]}))
    snapshot, = review["drafts"]
    assert snapshot["intended_recipient"] == actual["analysis"]["recipient"] == "buyer@example.org"
    assert snapshot["delivery_destination"] == actual["recipient"] == "simulation@example.invalid"
    assert all(snapshot[k] == actual[k] for k in ("subject", "body", "snapshot_hash", "version"))
    assert snapshot["id"] == actual["id"] and not store.rows("SELECT * FROM approvals")
    assert not store.rows("SELECT * FROM outbox") and not store.rows("SELECT * FROM jobs WHERE kind='deliver'")


def test_mcp_retry_only_requeues_selected_job_and_clears_old_times(client, store, opportunity, monkeypatch):
    monkeypatch.setattr(demo, "CONVERSATION_SESSION", store.path)
    selected = store.enqueue("reply", {"message_id": "original"}, "example", "same-reply")
    other = store.enqueue("analyze", {}, "example", "other-block")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO controls VALUES ('api_blocked','{}')")
        db.execute("UPDATE jobs SET status='blocked_config',attempts=1,started_at='start',finished_at='end',error='prior failure'")
    assert data(call(client, "manage_job", {"job_id": selected, "action": "retry"})) == {"status": "queued"}
    assert store.rows("SELECT status,attempts,started_at,finished_at,error,payload FROM jobs WHERE id=?", (selected,)) == [
        dict(status="queued", attempts=1, started_at=None, finished_at=None, error=None, payload=json.dumps({"message_id": "original"}))]
    assert store.rows("SELECT status,finished_at FROM jobs WHERE id=?", (other,)) == [dict(status="blocked_config", finished_at="end")]
    assert not store.rows("SELECT 1 FROM controls WHERE name='api_blocked'")
    previous = store.rows("SELECT details FROM events WHERE kind='job_retry_requested' AND job_id=?", (selected,))
    assert json.loads(previous[0]["details"])["finished_at"] == "end"
    assert call(client, "manage_job", {"job_id": selected, "action": "retry"})["isError"]


@pytest.mark.parametrize("status,envelope,released", [
    (429, {"error": {"code": "credit_balance_exhausted"}}, True),
    (429, {"error": {"code": "rate_limit_exceeded"}}, False),
    (429, {"error": {"code": "credit_balance_exhausted"}, "usage": {"output_tokens": 1}}, False),
    (503, {"error": {"code": "credit_balance_exhausted"}}, False),
])
def test_only_explicit_generation_refusals_release_reservations(rehearsal, tmp_path, status, envelope, released):
    ledger = rehearsal.ConversationBudget(tmp_path / "meter.sqlite3")
    ledger.initialize(tmp_path / "test.sqlite3", ["one"], [])
    reserve(ledger, job(kind="reply"), "gpt-6.1-sol", "req", body(), "investigation")
    ledger.settle("req", envelope, status)
    assert (ledger.summary()["retained_reservations_usd"] == 0) == released
    with ledger.connect() as db:
        row = db.execute("SELECT * FROM requests WHERE id='req'").fetchone()
        assert row["reserved_micro"] > 0
        assert row["state"] == ("rejected_credit_balance" if released else "unknown")
        assert row["charged_micro"] == (0 if released else None)


@pytest.mark.parametrize("match", ["exact", "different request", "provider timeout", "unobserved usage", "reported tokens"])
def test_legacy_credit_reconciliation_requires_matching_request_and_terminal_evidence(rehearsal, store, opportunity, tmp_path, monkeypatch, match):
    monkeypatch.setattr(rehearsal, "LONE_TREE", "example")
    ledger = rehearsal.ConversationBudget(tmp_path / "meter.sqlite3")
    ledger.initialize(store.path, ["example"], [])
    other = store.enqueue("reply", {}, "example", "other-reply")
    jid = store.enqueue("reply", {"message_id": "original"}, "example", "saved-reply")
    reserve(ledger, job(jid, "example", "reply"), "gpt-6.1-sol", "failed-request", body(), "investigation")
    rehearsal.Ledger.settle(ledger, "failed-request", {}, 429)  # Existing format: preserved unknown reservation.
    with store.connect(write=True) as db:
        db.execute("UPDATE jobs SET attempts=1,started_at='old start',finished_at='old end' WHERE id=?", (jid,))
        for kind, details in (
            ("job_started", {"kind": "reply"}),
            ("model_request_started", {"request_id": "failed-request"}),
            ("model_request_finished", {"request_id": "different" if match == "different request" else "failed-request", "status": 429}),
            ("api_response", {"status": 429, "requests": 1, "input_tokens": 0, "output_tokens": int(match == "reported tokens"), "cached_tokens": 0,
                              "usage_available": match == "unobserved usage"}),
            ("job_blocked_config", {"error": "Timeout" if match == "provider timeout" else "RateLimitError (status=429, code=credit_balance_exhausted)"}),
        ):
            store.event(kind, details, jid, "example", con=db)
    claimed = rehearsal.claim_interactive(store, ledger, set(), reply_job_id=jid)
    assert store.rows("SELECT status,attempts FROM jobs WHERE id=?", (other,)) == [dict(status="queued", attempts=0)]
    if match == "exact":
        assert claimed["id"] == jid and claimed["attempts"] == 2 and claimed["payload"] == {"message_id": "original"}
        assert claimed["finished_at"] is None and claimed["started_at"] != "old start"
        assert ledger.summary()["retained_reservations_usd"] == 0
        assert rehearsal.claim_interactive(store, ledger, set(), reply_job_id=jid) is None
    else:
        assert claimed is None and ledger.summary()["retained_reservations_usd"] > 0
        assert store.rows("SELECT status FROM jobs WHERE id=?", (jid,)) == [dict(status="blocked_config")]


def test_retry_rechecks_remaining_budget_without_resetting_usage(rehearsal, store, opportunity, tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "LONE_TREE", "example")
    ledger = rehearsal.ConversationBudget(tmp_path / "meter.sqlite3")
    ledger.initialize(store.path, ["example"], [], budget_usd=.40)
    jid = store.enqueue("reply", {}, "example", "original")
    selected = rehearsal.claim_interactive(store, ledger, set())
    reserve(ledger, selected, "gpt-6.1-sol", "paid", body(), "investigation")
    ledger.settle("paid", {"model":"gpt-6.1-sol","service_tier":"default","usage":{"input_tokens":1000,"output_tokens":5000}}, 200)
    store.finish(jid, "failed", "Local failure after paid request")
    store.retry(jid)
    before = ledger.summary()
    assert rehearsal.claim_interactive(store, ledger, set(), reply_job_id=jid) is None
    assert ledger.summary() == before and 0 < before["remaining_usd"] < .363
    assert "projected" in store.rows("SELECT error FROM jobs WHERE id=?", (jid,))[0]["error"]


def test_one_reply_run_returns_to_pause_without_claiming_other_work(rehearsal, store, settings, opportunity, tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "SESSION", store.path)
    monkeypatch.setattr(rehearsal, "LONE_TREE", "example")
    ledger = rehearsal.ConversationBudget(tmp_path / "meter.sqlite3")
    ledger.initialize(store.path, ["example"], [])
    other = store.enqueue("analyze", {}, "example", "other")
    target = store.enqueue("reply", {}, "example", "target")
    store.set_paused(True)
    seen = []
    async def exercise():
        done = asyncio.Event()
        async def fixture_run(worker_store, config, selected):
            seen.append(selected["id"])
            worker_store.finish(selected["id"])
            done.set()
        monkeypatch.setattr(rehearsal, "execute_job", fixture_run)
        worker = asyncio.create_task(rehearsal.conversation_worker(settings, ledger, reply_job_id=target))
        try:
            await asyncio.wait_for(done.wait(), 3)
            for _ in range(20):
                if len(store.rows("SELECT id FROM events WHERE kind='worker_paused'")) == 2:break
                await asyncio.sleep(.01)
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
    asyncio.run(exercise())
    assert seen == [target] and store.paused()
    assert store.rows("SELECT status,attempts FROM jobs WHERE id=?", (other,)) == [dict(status="queued", attempts=0)]
    assert ledger.summary()["requests"] == 0


def test_dispatch_uses_registered_accounts_and_excludes_inherited_work(rehearsal, tmp_path, store, opportunity):
    from test_operations import population
    population(store,opportunity,3)
    outside=store.enqueue('analyze',{},'2','outside')
    inherited=store.enqueue('analyze',{},'1','inherited')
    target=store.enqueue('analyze',{},'1','verified-contact')
    ledger=rehearsal.ConversationBudget(tmp_path/'two-accounts.sqlite3')
    ledger.initialize(store.path,['0','1'],[inherited])
    picked=rehearsal.claim_interactive(store,ledger,{inherited})
    assert picked['id']==target and picked['opportunity_id']=='1'
    assert store.rows('SELECT status FROM jobs WHERE id IN (?,?)',(outside,inherited))==[{'status':'queued'}]*2
    assert ledger.summary()['requests']==0 and ledger.summary()['remaining_usd']==2


def test_reselect_secondary_account_and_claim_only_the_named_job(rehearsal, store, opportunity, tmp_path, monkeypatch):
    from test_operations import population
    population(store, opportunity, 3)
    ledger = rehearsal.ConversationBudget(tmp_path / 'budget.sqlite3')
    ledger.initialize(store.path, ['0', '1'], [])
    for key in ('SESSION', 'BASELINE', 'SENT'):
        monkeypatch.setattr(rehearsal, key, store.path)
    monkeypatch.setattr(rehearsal, 'LONE_TREE', '0')
    monkeypatch.setattr(rehearsal, 'interactive_budget', lambda: ledger)
    other = store.enqueue('revise_draft', {}, '0', 'unrelated')
    target = store.enqueue('analyze', {}, '2', 'verified-finding')
    store.set_paused(True)
    before = ledger.summary()
    assert rehearsal.claim_interactive(store, ledger, set(), job_id=target) is None
    rehearsal.select_account('2')
    assert json.loads(ledger.metadata()['accounts']) == ['0', '2']
    assert rehearsal.claim_interactive(store, ledger, set(), job_id=target)['id'] == target
    assert store.rows('SELECT status,attempts FROM jobs WHERE id=?', (other,)) == [{'status':'queued', 'attempts':0}]
    assert ledger.summary() == before and store.paused()
