"""No paid calls: exercise pre-dispatch guard against an in-memory HTTP transport."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

try:
    import httpx2 as httpx
except ImportError:
    import httpx
import pytest

from clearline.screening_budget import BudgetLimit
from clearline.store import Store

spec = importlib.util.spec_from_file_location('phase12_acceptance_worker', Path(__file__).parents[1] / 'scripts/phase12_acceptance_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@pytest.fixture
def ledger(tmp_path):
    result = worker.Ledger(tmp_path / 'budget.sqlite3')
    result.initialize(tmp_path / 'acceptance.sqlite3', ['one', 'two'], ['inherited'])
    return result


def job(jid='j1', account='one', kind='analyze'):
    return {'id': jid, 'kind': kind, 'opportunity_id': account, 'payload': {}}


def body(**updates):
    return {'model': 'gpt-6.1-sol', 'max_output_tokens': 6000, 'input': 'Test evidence',
            'service_tier': 'default', **updates}



def reserve(ledger, selected, model, request_id, payload, stage, count=1000):
    ledger.start_preflight(selected, model, request_id, payload)
    ledger.finish_preflight(request_id, {'object': 'response.input_tokens', 'input_tokens': count}, 200)
    ledger.reserve(selected, model, request_id, payload, stage)

def test_global_budget_retains_unknown_and_rejects_before_next_dispatch(ledger):
    expensive = body(input='x' * 180000, prompt_cache_options={'ttl': '12h'})
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', expensive, 'investigation', count=175000)
    ledger.settle('r1', {'error': 'gateway'}, 502)
    reserve(ledger, job('j2', 'two'), 'gpt-6.1-sol', 'r2', expensive, 'investigation', count=175000)
    before = ledger.summary()
    with pytest.raises(BudgetLimit, match=r'\$2 cap'):
        reserve(ledger, job(), 'gpt-6.1-sol', 'r3', expensive, 'investigation', count=175000)
    assert ledger.summary()['requests'] == before['requests']
    assert ledger.summary()['retained_reservations_usd'] == before['retained_reservations_usd']
    assert before['requests'] == 2
    assert before['estimated_usd'] == 0
    assert 1 < before['retained_reservations_usd'] < 2


def test_large_text_uses_exact_count_and_not_serialized_bytes(ledger):
    # Large JSON/tool history is accepted based on the provider's exact count.
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(input='x' * 350000), 'investigation', count=20000)
    assert ledger.summary()['retained_reservations_usd'] == pytest.approx(.11064)
    with pytest.raises(BudgetLimit, match='272000-token tier'):
        reserve(ledger, job(), 'gpt-6.1-sol', 'r2', body(), 'investigation', count=272000)
    assert ledger.summary()['requests'] == 1


def test_output_guard_reports_safe_size_metadata(ledger):
    with pytest.raises(BudgetLimit, match=r'request_bytes=.+max_output_tokens=6001'):
        reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(max_output_tokens=6001), 'investigation')


def test_known_usage_releases_only_unused_reservation(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    ledger.settle('r1', {'model': 'gpt-6.1-sol-2026-11-01', 'service_tier': 'default',
                        'usage': {'input_tokens': 1000, 'output_tokens': 200,
                                  'input_tokens_details': {'cached_tokens': 100, 'cache_write_tokens': 0}}}, 200)
    result = ledger.summary()
    assert result['estimated_usd'] == pytest.approx(.00381)
    assert result['retained_reservations_usd'] == 0
    assert result['stages']['investigation']['input_tokens'] == 1000


@pytest.mark.parametrize('response', [
    {'model': 'gpt-6.1-sol', 'usage': {'input_tokens': 1, 'output_tokens': 1}},
    {'model': 'different-model', 'service_tier': 'default', 'usage': {'input_tokens': 1, 'output_tokens': 1}},
    {'model': 'gpt-6.1-sol', 'service_tier': 'priority', 'usage': {'input_tokens': 1, 'output_tokens': 1}},
])
def test_unknown_tier_or_model_keeps_full_reservation(ledger, response):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    before = ledger.summary()['retained_reservations_usd']
    ledger.settle('r1', response, 200)
    assert ledger.summary()['retained_reservations_usd'] == before


@pytest.mark.parametrize('updates', [
    {'tools': [{'type': 'web_search'}]},
    {'tools': [{'type': 'function', 'name': 'send_email'}]},
    {'service_tier': 'priority'}, {'model': 'unpriced'}, {'stream': True},
    {'previous_response_id': 'resp_id'}, {'input': [{'type': 'input_image'}]},
    {'input': [{'encrypted_content': 'opaque'}]}, {'max_output_tokens': 6001},
    {'prompt_cache_retention': '24h'}, {'unknown_context_field': 'unsupported'},
    {'prompt_cache_options': {'prewarm': True}},
])
def test_unsupported_request_blocked_without_reservation(ledger, updates):
    with pytest.raises(BudgetLimit):
        reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(**updates), 'investigation')
    assert ledger.summary()['requests'] == 0


def test_job_allowlist_and_total_admission_caps(ledger):
    for item in [job('inherited'), job(account='third'), job(kind='prospect_research')]:
        with pytest.raises(BudgetLimit):
            ledger.admit(item)
    ledger.admit(job())
    ledger.admit(job())  # same job may make several bounded requests
    with pytest.raises(BudgetLimit, match='One targeted'):
        ledger.admit(job('duplicate'))
    ledger.admit(job('b1', None, 'revenue_brief'))
    ledger.admit(job('b2', None, 'revenue_brief'))
    with pytest.raises(BudgetLimit, match='two manually'):
        ledger.admit(job('b3', None, 'revenue_brief'))


def test_request_cap_persists_when_ledger_reopened(ledger, monkeypatch):
    monkeypatch.setattr(worker, 'REQUESTS_PER_JOB', 1)
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    restarted = worker.Ledger(ledger.path)
    with pytest.raises(BudgetLimit, match='request cap'):
        reserve(restarted, job(), 'gpt-6.1-sol', 'r2', body(), 'investigation')


def test_explicit_restart_preserves_cost_and_is_limited_to_same_guard_blocked_job(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    ledger.settle('r1', {'model': 'gpt-6.1-sol', 'service_tier': 'default',
                        'usage': {'input_tokens': 1000, 'output_tokens': 200}}, 200)
    before = ledger.summary()
    blocked = {**job(), 'status': 'blocked_config', 'attempts': 1,
               'error': 'Request exceeds the bounded text/output envelope'}
    for changed in [{'status': 'failed'}, {'attempts': 2}, {'error': 'API billing issue'}]:
        with pytest.raises(BudgetLimit, match='first legacy'):
            ledger.authorize_restart({**blocked, **changed})
    ledger.authorize_restart(blocked)
    after = ledger.summary()
    assert after['explicit_job_restarts'] == 1
    assert after['requests'] == before['requests']
    assert after['estimated_usd'] == before['estimated_usd']
    assert after['remaining_usd'] == before['remaining_usd']
    with pytest.raises(BudgetLimit, match='already used'):
        ledger.authorize_restart(blocked)


def test_restart_with_unknown_prior_usage_is_refused(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    blocked = {**job(), 'status': 'blocked_config', 'attempts': 1,
               'error': 'Request exceeds the bounded text/output envelope'}
    with pytest.raises(BudgetLimit, match='known settled usage'):
        ledger.authorize_restart(blocked)
    assert ledger.summary()['explicit_job_restarts'] == 0


def test_bound_violation_blocks_all_further_requests(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    ledger.settle('r1', {'model': 'gpt-6.1-sol', 'service_tier': 'default',
                        'usage': {'input_tokens': 100, 'output_tokens': 6001}}, 200)
    with pytest.raises(BudgetLimit, match='usage bound was exceeded'):
        reserve(ledger, job('j2', 'two'), 'gpt-6.1-sol', 'r2', body(), 'investigation')


def test_transport_reserves_before_network_and_forces_standard_tier(ledger, monkeypatch):
    import clearline.telemetry as telemetry
    sent = []
    async def response(request):
        if request.url.path.endswith('/input_tokens'):
            assert ledger.summary()['requests'] == 0
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        assert ledger.summary()['requests'] == 1
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'service_tier': 'default',
                                        'usage': {'input_tokens': 100, 'output_tokens': 50}})
    @asynccontextmanager
    async def original(store, selected, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            yield SimpleNamespace(_client=http)
    monkeypatch.setattr(telemetry, 'client_for', original)
    store = SimpleNamespace(rows=lambda *_: [{'status': 'running'}])
    settings = SimpleNamespace(model='gpt-6.1-sol')
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(store, job(), settings) as client:
                payload = body()
                payload.pop('service_tier')
                result = await client._client.post('https://api.openai.com/v1/responses', json=payload)
                assert result.status_code == 200
    asyncio.run(invoke())
    assert sent[0]['service_tier'] == 'default'
    assert ledger.summary()['estimated_usd'] == pytest.approx(.00075)
    assert telemetry.client_for is original


def test_transport_rejection_never_reaches_network(ledger, monkeypatch):
    import clearline.telemetry as telemetry
    async def response(request):
        pytest.fail('Rejected hosted-tool request reached the network')
    @asynccontextmanager
    async def original(store, selected, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            yield SimpleNamespace(_client=http)
    monkeypatch.setattr(telemetry, 'client_for', original)
    store = SimpleNamespace(rows=lambda *_: [{'status': 'running'}])
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(store, job(), SimpleNamespace(model='gpt-6.1-sol')) as client:
                with pytest.raises(BudgetLimit, match='no web'):
                    await client._client.post('https://api.openai.com/v1/responses', json=body(tools=[{'type': 'web_search'}]))
    asyncio.run(invoke())
    assert ledger.summary()['requests'] == 0


def test_real_sdk_hook_rejection_preserves_budget_failure_without_retry(ledger, monkeypatch):
    import openai
    import clearline.telemetry as telemetry
    original_http = openai.DefaultAsyncHttpxClient
    calls = []
    async def response(request):
        calls.append(request)
        pytest.fail('Rejected request reached mocked network transport')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-offline-test-key')
    monkeypatch.setattr(openai, 'DefaultAsyncHttpxClient',
                        lambda **kwargs: original_http(transport=httpx.MockTransport(response), trust_env=False, **kwargs))
    store = SimpleNamespace(rows=lambda *_: [{'status': 'running'}], event=lambda *args, **kwargs: None)
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(store, job(), SimpleNamespace(model='gpt-6.1-sol', timeout_seconds=5)) as client:
                with pytest.raises((openai.APIConnectionError, BudgetLimit)) as error:
                    await client.responses.create(model='gpt-6.1-sol', input='Synthetic test', max_output_tokens=100,
                                                  tools=[{'type': 'web_search'}])
                cause = error.value
                while cause is not None and not isinstance(cause, BudgetLimit):
                    cause = cause.__cause__
                assert isinstance(cause, BudgetLimit)
    asyncio.run(invoke())
    assert calls == []
    assert ledger.summary()['requests'] == 0


def test_real_sdk_network_failure_keeps_reservation(ledger, monkeypatch):
    import openai
    import clearline.telemetry as telemetry
    original_http = openai.DefaultAsyncHttpxClient
    calls = []
    async def response(request):
        calls.append(request)
        if request.url.path.endswith('/input_tokens'):
            assert ledger.summary()['requests'] == 0
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        assert ledger.summary()['requests'] == 1
        raise httpx.ConnectError('Synthetic offline failure', request=request)
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-offline-test-key')
    monkeypatch.setattr(openai, 'DefaultAsyncHttpxClient',
                        lambda **kwargs: original_http(transport=httpx.MockTransport(response), trust_env=False, **kwargs))
    store = SimpleNamespace(rows=lambda *_: [{'status': 'running'}], event=lambda *args, **kwargs: None)
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(store, job(), SimpleNamespace(model='gpt-6.1-sol', timeout_seconds=5)) as client:
                with pytest.raises(openai.APIConnectionError):
                    await client.responses.create(model='gpt-6.1-sol', input='Synthetic test', max_output_tokens=100)
    asyncio.run(invoke())
    assert len(calls) == 2  # One count + one generation, never an SDK retry.
    assert ledger.summary()['input_count_requests'] == 1
    assert ledger.summary()['estimated_usd'] == 0
    assert ledger.summary()['retained_reservations_usd'] > 0


def test_claim_leaves_unselected_queue_jobs_unchanged(tmp_path, ledger):
    store = Store(tmp_path / 'acceptance.sqlite3')
    # Briefs avoid adding unrelated account fixtures to exercise queue isolation.
    other = store.enqueue('revenue_brief', {'source_hash': 'other'}, key='other')
    selected = store.enqueue('revenue_brief', {'source_hash': 'selected'}, key='selected')
    runner = worker.AcceptanceStore(store.path, [selected], ledger)
    result = runner.claim(worker.KINDS)
    assert result['id'] == selected
    assert runner.claim(worker.KINDS) is None
    assert store.rows('SELECT status,attempts FROM jobs WHERE id=?', (other,)) == [{'status': 'queued', 'attempts': 0}]


def test_production_and_preview_paths_rejected():
    for path in [worker.ROOT / 'runtime/phase3/screening.sqlite3', '/tmp/arbitrary.sqlite3']:
        with pytest.raises(ValueError, match='phase12-acceptance'):
            worker.isolated_path(path)


def test_one_dollar_limit_is_persisted_and_cannot_be_reset(tmp_path):
    ledger = worker.Ledger(tmp_path / 'one-dollar.sqlite3')
    ledger.initialize(tmp_path / 'session.sqlite3', ['one'], [], budget_usd=1)
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(prompt_cache_options={'ttl': '12h'}), 'investigation', count=175000)
    reopened = worker.Ledger(ledger.path)
    assert reopened.summary()['limit_usd'] == 1
    assert reopened.summary()['remaining_usd'] == pytest.approx(.06372)
    with pytest.raises(BudgetLimit, match=r'\$1 cap'):
        reserve(reopened, job(), 'gpt-6.1-sol', 'r2', body(), 'commercial_review', count=2000)
    with pytest.raises(ValueError, match='already exists'):
        reopened.initialize(tmp_path / 'session.sqlite3', ['one'], [], budget_usd=2)
    assert reopened.metadata()['limit_micro'] == '1000000'
    assert reopened.summary()['requests'] == 1


def test_counted_request_cannot_be_changed_before_reservation(ledger):
    payload = body()
    ledger.start_preflight(job(), 'gpt-6.1-sol', 'r1', payload)
    ledger.finish_preflight('r1', {'object': 'response.input_tokens', 'input_tokens': 1000}, 200)
    with pytest.raises(BudgetLimit, match='unchanged request'):
        ledger.reserve(job(), 'gpt-6.1-sol', 'r1', {**payload, 'input': 'different'}, 'investigation')
    assert ledger.summary()['requests'] == 0


@pytest.mark.parametrize('details,expected', [
    ({'cached_tokens': 100, 'cache_write_tokens': 600,
      'cache_write_tokens_details': {'ttl_30m_tokens': 400, 'ttl_12h_tokens': 200}}, .00461),
    ({'cached_tokens': 100, 'cache_write_tokens': 600}, .00561),
    ({'cached_tokens': 100}, .00651),
])
def test_cache_write_settlement_uses_breakdown_or_safe_ttl_fallback(ledger, details, expected):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(prompt_cache_options={'ttl': '12h'}), 'investigation')
    ledger.settle('r1', {'model': 'gpt-6.1-sol', 'service_tier': 'default',
                        'usage': {'input_tokens': 1000, 'output_tokens': 200, 'input_tokens_details': details}}, 200)
    assert ledger.summary()['estimated_usd'] == pytest.approx(expected)
    assert ledger.summary()['retained_reservations_usd'] == 0


def test_nested_cache_breakpoint_reserves_highest_ttl(ledger):
    payload = body(input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': 'evidence',
                          'prompt_cache_breakpoint': {'mode': 'explicit', 'ttl': '12h'}}]}])
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', payload, 'investigation')
    assert ledger.summary()['retained_reservations_usd'] == pytest.approx(.06628)


def test_invalid_cache_write_totals_retain_full_reservation(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    before = ledger.summary()['retained_reservations_usd']
    ledger.settle('r1', {'model': 'gpt-6.1-sol', 'service_tier': 'default',
                        'usage': {'input_tokens': 1000, 'output_tokens': 200,
                                  'input_tokens_details': {'cached_tokens': 200, 'cache_write_tokens': 900}}}, 200)
    assert ledger.summary()['retained_reservations_usd'] == before
    assert ledger.summary()['estimated_usd'] == 0


def test_encrypted_reasoning_and_all_context_reach_count_and_generation_unchanged(ledger, monkeypatch):
    import clearline.telemetry as telemetry
    requests = []
    payload = body(
        input=[{'type': 'reasoning', 'id': 'rs_test', 'encrypted_content': 'opaque-provider-state', 'summary': []},
               {'role': 'user', 'content': 'evidence'}],
        instructions='Be factual', reasoning={'effort': 'high'}, parallel_tool_calls=True,
        text={'format': {'type': 'json_schema', 'name': 'report', 'schema': {'type': 'object', 'properties': {}}}},
        tools=[{'type': 'function', 'name': 'get_account_overview', 'parameters': {'type': 'object'}}],
        tool_choice='auto', truncation='disabled', store=False, include=['reasoning.encrypted_content'])
    async def response(request):
        sent = json.loads(request.content)
        requests.append((request.url.path, sent))
        if request.url.path.endswith('/input_tokens'):
            assert ledger.summary()['requests'] == 0
            assert sent == {k: v for k, v in payload.items() if k in worker.COUNT_FIELDS}
            assert 'idempotency-key' not in request.headers
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 987})
        assert ledger.summary()['requests'] == 1
        assert sent == payload
        return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'service_tier': 'default',
                                        'usage': {'input_tokens': 987, 'output_tokens': 80}})
    @asynccontextmanager
    async def original(store, selected, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            yield SimpleNamespace(_client=http)
    monkeypatch.setattr(telemetry, 'client_for', original)
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(SimpleNamespace(rows=lambda *_: [{'status': 'running'}]), job(),
                                            SimpleNamespace(model='gpt-6.1-sol')) as client:
                await client._client.post('https://api.openai.com/v1/responses', json=payload,
                                         headers={'Idempotency-Key': 'generation-only'})
    asyncio.run(invoke())
    assert [p for p, _ in requests] == ['/v1/responses/input_tokens', '/v1/responses']
    assert ledger.summary()['input_count_requests'] == 1


@pytest.mark.parametrize('failure', ['unsupported', 'invalid_count', 'boolean_count', 'network', 'invalid_json'])
def test_count_failure_never_dispatches_generation(ledger, monkeypatch, failure):
    import clearline.telemetry as telemetry
    paths = []
    async def response(request):
        paths.append(request.url.path)
        assert request.url.path.endswith('/input_tokens')
        if failure == 'network':
            raise httpx.ConnectError('Synthetic count failure', request=request)
        if failure == 'invalid_json':
            return httpx.Response(200, content=b'not json')
        if failure == 'unsupported':
            return httpx.Response(400, json={'error': {'message': 'unsupported'}})
        return httpx.Response(200, json={'object': 'response.input_tokens',
                                        'input_tokens': True if failure == 'boolean_count' else -1})
    @asynccontextmanager
    async def original(store, selected, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            yield SimpleNamespace(_client=http)
    monkeypatch.setattr(telemetry, 'client_for', original)
    async def invoke():
        with worker.bounded_clients(ledger):
            async with telemetry.client_for(SimpleNamespace(rows=lambda *_: [{'status': 'running'}]), job(),
                                            SimpleNamespace(model='gpt-6.1-sol')) as client:
                with pytest.raises(BudgetLimit, match='generation was not dispatched'):
                    await client._client.post('https://api.openai.com/v1/responses', json=body())
    asyncio.run(invoke())
    assert paths == ['/v1/responses/input_tokens']
    assert ledger.summary()['input_count_states'] == {'failed': 1}
    assert ledger.summary()['requests'] == 0


def test_old_ledger_summary_preserves_recorded_limit_and_usage(ledger):
    reserve(ledger, job(), 'gpt-6.1-sol', 'r1', body(), 'investigation')
    before = ledger.summary()
    # Historical ledgers predate count telemetry. Merely reading must not migrate
    # or rewrite their recorded usage/limit; they remain compatible.
    with ledger.connect() as con:
        con.execute('DROP TABLE preflights')
    after = worker.Ledger(ledger.path).summary()
    for key in ('limit_usd', 'requests', 'estimated_usd', 'remaining_usd', 'retained_reservations_usd'):
        assert after[key] == before[key]
    assert after['input_count_requests'] == 0
