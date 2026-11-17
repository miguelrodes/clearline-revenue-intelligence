"""Test-only, explicit-job acceptance runner with a persistent, explicitly capped request budget.

Never use this for the preview worker. ``clone`` backs up the combined preview
read-only into runtime/phase12-acceptance/. Submit synthetic evidence through the
API pointing at that clone, then ``run --job-id ...`` processes only those jobs.
Existing agent, supervisor, persistence and telemetry code is reused unchanged.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from clearline.config import ROOT, Settings
from clearline.screening_budget import BudgetLimit
from clearline.store import Store, utcnow
from clearline.telemetry import PRICES

REQUESTS_PER_JOB = 32
KINDS = ('analyze', 'reply', 'revenue_brief')
INPUT_SAFETY_TOKENS = 256
CACHE_WRITE_MULTIPLIERS = {'30m': 1.25, '12h': 2.5}
# Accepted by the installed Responses input_tokens.count SDK, including all
# context-bearing schema, tools, reasoning and encrypted input items.
COUNT_FIELDS = {'conversation', 'input', 'instructions', 'model', 'parallel_tool_calls',
                'personality', 'previous_response_id', 'reasoning', 'text', 'tool_choice',
                'tools', 'truncation'}
GENERATION_FIELDS = {'max_output_tokens', 'service_tier', 'store', 'stream', 'background',
                     'include', 'metadata', 'safety_identifier', 'prompt_cache_key',
                     'prompt_cache_retention', 'prompt_cache_options', 'temperature', 'top_p',
                     'top_logprobs', 'max_tool_calls'}
FORBIDDEN_INPUT_TYPES = {'input_image', 'input_file', 'input_audio', 'computer_call',
                         'computer_call_output', 'compaction', 'item_reference',
                         'code_interpreter_call', 'file_search_call', 'web_search_call',
                         'image_generation_call', 'mcp_call', 'mcp_list_tools'}
PREFLIGHT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS preflights(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,model TEXT NOT NULL,request_hash TEXT NOT NULL,
 cache_multiplier REAL NOT NULL,state TEXT NOT NULL,input_tokens INTEGER,
 created_at TEXT NOT NULL,http_status INTEGER,detail TEXT NOT NULL);
'''
INTERNAL_TOOLS = {
    'get_account_overview', 'get_purchase_history', 'get_relationship_history',
    'investigate_identity', 'get_product_catalogue', 'get_previous_work',
    'get_product_associations',
}
SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE baseline_jobs(id TEXT PRIMARY KEY);
CREATE TABLE admitted_jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,account_id TEXT);
CREATE TABLE explicit_restarts(job_id TEXT PRIMARY KEY,previous_attempt INTEGER NOT NULL,
 previous_error TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE requests(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,stage TEXT NOT NULL,model TEXT NOT NULL,
 reserved_micro INTEGER NOT NULL,input_bound INTEGER NOT NULL,output_bound INTEGER NOT NULL,
 charged_micro INTEGER,input_tokens INTEGER,output_tokens INTEGER,state TEXT NOT NULL,created_at TEXT NOT NULL);
'''


def isolated_path(path):
    path = Path(path)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    if not path.is_relative_to((ROOT / 'runtime/phase12-acceptance').resolve()):
        raise ValueError('Acceptance database must be under runtime/phase12-acceptance/')
    return path


class Ledger:
    """Separate from both business databases and the Phase 3 budget ledger."""
    kinds = KINDS
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self, db_path, accounts, baseline_jobs, budget_usd=2):
        budget = Decimal(str(budget_usd))
        if not budget.is_finite() or budget <= 0 or budget > 2:
            raise ValueError("Acceptance budget must be positive and no greater than $2")
        limit_micro = int(budget * 1_000_000)
        if limit_micro < 1:
            raise ValueError("Acceptance budget must be at least one microdollar")
        if not 1 <= len(accounts) <= 2 or len(set(accounts)) != len(accounts):
            raise ValueError('Choose one or two distinct acceptance accounts')
        if self.path.exists():
            raise ValueError('Acceptance ledger already exists; never reset it to bypass the cap')
        with self.connect() as con:
            con.executescript(SCHEMA + PREFLIGHT_SCHEMA)
            con.executemany('INSERT INTO metadata VALUES(?,?)', [
                ('db_path', str(Path(db_path).resolve())), ('accounts', json.dumps(accounts)),
                ('limit_micro', str(limit_micro)), ('created_at', utcnow()),
            ])
            con.executemany('INSERT INTO baseline_jobs VALUES(?)', ((j,) for j in baseline_jobs))

    def metadata(self):
        with self.connect() as con:
            return dict(con.execute('SELECT key,value FROM metadata').fetchall())

    def admit(self, job):
        with self.connect() as con:
            meta = dict(con.execute('SELECT key,value FROM metadata').fetchall())
            kind, account = job['kind'], job.get('opportunity_id')
            if kind not in self.kinds or (kind != 'revenue_brief' and account not in json.loads(meta['accounts'])):
                raise BudgetLimit('Only selected customer reassessments and manual briefs are permitted')
            if kind == 'revenue_brief' and account is not None:
                raise BudgetLimit('Unexpected account-bound briefing job')
            if con.execute('SELECT 1 FROM baseline_jobs WHERE id=?', (job['id'],)).fetchone():
                raise BudgetLimit('Inherited baseline jobs cannot be processed by this test')
            old = con.execute('SELECT * FROM admitted_jobs WHERE id=?', (job['id'],)).fetchone()
            if old:
                if old['kind'] != kind or old['account_id'] != account:
                    raise BudgetLimit('Admitted job identity changed')
                return
            self.check_new_job(con,job)
            con.execute('INSERT INTO admitted_jobs VALUES(?,?,?)', (job['id'], kind, account))

    def check_new_job(self,con,job):
        kind, account = job['kind'],job.get('opportunity_id')
        if kind == 'analyze' and con.execute('SELECT 1 FROM admitted_jobs WHERE kind=? AND account_id=?', (kind, account)).fetchone():
            raise BudgetLimit('One targeted reassessment per selected account is permitted')
        if kind == 'reply' and con.execute("SELECT count(*) FROM admitted_jobs WHERE kind='reply'").fetchone()[0] >= 3:
            raise BudgetLimit('At most three selected reply scenarios are permitted')
        if kind == 'revenue_brief' and con.execute('SELECT COUNT(*) FROM admitted_jobs WHERE kind=?', (kind,)).fetchone()[0] >= 2:
            raise BudgetLimit('At most two manually selected briefing jobs are permitted')

    def authorize_restart(self, job):
        """One explicit restart after the obsolete input-size guard, never retry automatically.

        The job restarts its model stages. Prior usage and attempt records remain
        charged and visible; this is not a continuation of the interrupted model.
        """
        if (job['kind'] != 'analyze' or job['status'] != 'blocked_config'
                or job['attempts'] != 1
                or job.get('error') != 'Request exceeds the bounded text/output envelope'):
            raise BudgetLimit('Explicit restart is only permitted for the first legacy envelope-guard rejection')
        self.admit(job)
        with self.connect() as con:
            # Additive ledger-only migration for acceptance runs created before
            # this explicit restart option existed. Never reset the cost ledger.
            con.execute('''CREATE TABLE IF NOT EXISTS explicit_restarts(
                job_id TEXT PRIMARY KEY,previous_attempt INTEGER NOT NULL,
                previous_error TEXT NOT NULL,created_at TEXT NOT NULL)''')
            if con.execute('SELECT 1 FROM explicit_restarts WHERE job_id=?', (job['id'],)).fetchone():
                raise BudgetLimit('This acceptance job has already used its one explicit restart')
            calls = con.execute('SELECT state FROM requests WHERE job_id=?', (job['id'],)).fetchall()
            if not calls or any(r['state'] != 'settled' for r in calls):
                raise BudgetLimit('Restart requires known settled usage for every prior paid request')
            con.execute('INSERT INTO explicit_restarts VALUES(?,?,?,?)',
                        (job['id'], job['attempts'], job['error'], utcnow()))

    @staticmethod
    def validate_request(model, body):
        if model != 'gpt-6.1-sol' or body.get('model') != model or body.get('service_tier') != 'default':
            raise BudgetLimit('Use the priced gpt-6.1-sol cache policy and standard service tier')
        if set(body) - COUNT_FIELDS - GENERATION_FIELDS:
            raise BudgetLimit('Unsupported request fields cannot use the acceptance budget')
        if any(body.get(k) for k in ('previous_response_id', 'conversation', 'background', 'stream')):
            raise BudgetLimit('Stateful or streaming requests cannot be bounded by this test')
        if body.get('prompt_cache_retention') is not None:
            raise BudgetLimit('Legacy cache retention is outside the verified acceptance pricing policy')
        if body.get('truncation', 'disabled') != 'disabled':
            raise BudgetLimit('Automatic truncation is unsupported by this exact-count test')
        for tool in body.get('tools') or []:
            if not isinstance(tool, dict) or tool.get('type') != 'function' or tool.get('name') not in INTERNAL_TOOLS:
                raise BudgetLimit('Only existing internal evidence tools are allowed; no web or hosted tools')
        if any(item != 'reasoning.encrypted_content' for item in body.get('include') or []):
            raise BudgetLimit('Only encrypted reasoning inclusion is supported')
        options = body.get('prompt_cache_options') or {}
        if not isinstance(options, dict) or set(options) - {'mode', 'ttl'}:
            raise BudgetLimit('Cache prewarming or diagnostic requests are unsupported')
        ttl = options.get('ttl', '30m')
        if ttl not in ('30m', '12h') or options.get('mode', 'implicit') not in ('implicit', 'explicit'):
            raise BudgetLimit('Unsupported prompt cache policy')
        multipliers = [CACHE_WRITE_MULTIPLIERS[ttl]]
        def inspect(value):
            if isinstance(value, dict):
                if (value.get('type') in FORBIDDEN_INPUT_TYPES
                        or any(k in value for k in ('file_id', 'image_url', 'audio_url'))
                        or ('encrypted_content' in value and value.get('type') != 'reasoning')):
                    raise BudgetLimit('Only text and provider-counted encrypted reasoning can use the acceptance budget')
                breakpoint = value.get('prompt_cache_breakpoint')
                if breakpoint is not None:
                    if not isinstance(breakpoint, dict) or set(breakpoint) - {'mode', 'ttl'}:
                        raise BudgetLimit('Unsupported cache breakpoint')
                    breakpoint_ttl = breakpoint.get('ttl', ttl)
                    if breakpoint_ttl not in CACHE_WRITE_MULTIPLIERS or breakpoint.get('mode', 'explicit') != 'explicit':
                        raise BudgetLimit('Unsupported cache breakpoint TTL')
                    multipliers.append(CACHE_WRITE_MULTIPLIERS[breakpoint_ttl])
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(body)
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        output = body.get('max_output_tokens')
        if type(output) is not int or not 1 <= output <= 6000:
            raise BudgetLimit('Request exceeds bounded output envelope '
                              f'(request_bytes={len(raw)}, max_output_tokens={output}; allowed_output_tokens=1..6000)')
        return max(multipliers)

    @staticmethod
    def request_hash(body):
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _guard(con, job_id, model):
        if con.execute("SELECT 1 FROM requests WHERE state='violation'").fetchone():
            raise BudgetLimit('A usage bound was exceeded; all subsequent requests are blocked')
        models = {r[0] for r in con.execute('SELECT DISTINCT model FROM requests')}
        if models and models != {model}:
            raise BudgetLimit('Do not switch models inside an existing acceptance budget')
        if con.execute('SELECT COUNT(*) FROM requests WHERE job_id=?', (job_id,)).fetchone()[0] >= REQUESTS_PER_JOB:
            raise BudgetLimit('Per-job request cap reached, including quality revisions and retries')
        limit = int(con.execute("SELECT value FROM metadata WHERE key='limit_micro'").fetchone()[0])
        used = con.execute('SELECT COALESCE(SUM(COALESCE(charged_micro,reserved_micro)),0) FROM requests').fetchone()[0]
        return limit, used

    def start_preflight(self, job, model, request_id, body):
        """Validate before even the non-generative count call; do not guess counts."""
        self.admit(job)
        multiplier = self.validate_request(model, body)
        with self.connect() as con:
            con.execute(PREFLIGHT_SCHEMA)
            limit, used = self._guard(con, job['id'], model)
            if con.execute('SELECT COUNT(*) FROM preflights WHERE job_id=?', (job['id'],)).fetchone()[0] >= REQUESTS_PER_JOB:
                raise BudgetLimit('Per-job input-count request cap reached')
            if used + math.ceil(body['max_output_tokens'] * PRICES[model][1]) > limit:
                raise BudgetLimit('Acceptance cap cannot reserve even the maximum output; count request withheld')
            con.execute('INSERT INTO preflights VALUES(?,?,?,?,?,?,NULL,?,NULL,?)',
                        (request_id, job['id'], model, self.request_hash(body), multiplier,
                         'counting', utcnow(), 'not_started'))
        return {key: value for key, value in body.items() if key in COUNT_FIELDS}

    def finish_preflight(self, request_id, result=None, status=None, error=None):
        valid = (error is None and status == 200 and isinstance(result, dict)
                 and result.get('object') == 'response.input_tokens'
                 and type(result.get('input_tokens')) is int and result['input_tokens'] >= 0)
        with self.connect() as con:
            con.execute('UPDATE preflights SET state=?,input_tokens=?,http_status=?,detail=? WHERE id=?',
                        ('counted' if valid else 'failed', result['input_tokens'] if valid else None,
                         status, 'exact_provider_count' if valid else error or 'invalid_or_unsupported_count', request_id))
        if not valid:
            raise BudgetLimit('Exact input-token count failed or is unsupported; generation was not dispatched')

    def reserve(self, job, model, request_id, body, stage):
        self.admit(job)
        multiplier = self.validate_request(model, body)
        rates = PRICES[model]
        with self.connect() as con:
            count = con.execute('SELECT * FROM preflights WHERE id=?', (request_id,)).fetchone()
            if (not count or count['state'] != 'counted' or count['job_id'] != job['id']
                    or count['model'] != model or count['request_hash'] != self.request_hash(body)):
                raise BudgetLimit('A successful exact count of this unchanged request is required before dispatch')
            input_bound = count['input_tokens'] + INPUT_SAFETY_TOKENS
            output = body['max_output_tokens']
            if input_bound > 272_000:
                raise BudgetLimit(f'Acceptance input bound {input_bound} exceeds the standard-price 272000-token tier')
            reserved = math.ceil(input_bound * rates[0] * multiplier + output * rates[1])
            limit, used = self._guard(con, job['id'], model)
            if used + reserved > limit:
                raise BudgetLimit(f'Acceptance ${limit / 1e6:g} cap: insufficient unreserved budget before dispatch '
                                  f'(exact_input_tokens={count["input_tokens"]}, input_bound={input_bound}, output_bound={output}, '
                                  f'reservation_usd={reserved / 1e6:.6f}, remaining_usd={(limit - used) / 1e6:.6f})')
            con.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)',
                        (request_id, job['id'], stage, model, reserved, input_bound, output, 'reserved', utcnow()))
            con.execute("UPDATE preflights SET detail='generation_reserved' WHERE id=?", (request_id,))

    def settle(self, request_id, body, status):
        usage = body.get('usage') or {}
        it, ot = usage.get('input_tokens'), usage.get('output_tokens')
        with self.connect() as con:
            row = con.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if not row:
                raise BudgetLimit('No pre-dispatch reservation exists for this response')
            model = body.get('model') or ''
            known = (status == 200 and type(it) is int and type(ot) is int and it >= 0 and ot >= 0
                     and body.get('service_tier') in ('default', 'standard')
                     and isinstance(model, str)
                     and (model == row['model'] or model.startswith(row['model'] + '-')))
            if not known:
                con.execute("UPDATE requests SET state='unknown' WHERE id=?", (request_id,))
                return
            details = usage.get('input_tokens_details') or {}
            if not isinstance(details, dict):
                con.execute("UPDATE requests SET state='unknown' WHERE id=?", (request_id,))
                return
            cached = details.get('cached_tokens', 0)
            writes = details.get('cache_write_tokens')
            breakdown = details.get('cache_write_tokens_details')
            multiplier = con.execute('SELECT cache_multiplier FROM preflights WHERE id=?', (request_id,)).fetchone()[0]
            if (type(cached) is not int or not 0 <= cached <= it
                    or (writes is not None and (type(writes) is not int or writes < 0))):
                con.execute("UPDATE requests SET state='unknown' WHERE id=?", (request_id,))
                return
            write30 = write12 = 0
            if breakdown is not None:
                if not isinstance(breakdown, dict):
                    known = False
                else:
                    write30, write12 = breakdown.get('ttl_30m_tokens'), breakdown.get('ttl_12h_tokens')
                    if any(type(value) is not int or value < 0 for value in (write30, write12)):
                        known = False
                    elif (writes is not None and writes != write30 + write12) or write30 + write12 + cached > (it or 0):
                        known = False
                    else:
                        writes = write30 + write12
            elif writes is not None and (type(writes) is not int or writes < 0 or writes + cached > (it or 0)):
                known = False
            if not known:
                con.execute("UPDATE requests SET state='unknown' WHERE id=?", (request_id,))
                return
            rates = PRICES[row['model']]
            if breakdown is not None:
                input_cost = (it - cached - writes) * rates[0] + rates[0] * (write30 * 1.25 + write12 * 2.5)
            elif writes is not None:
                input_cost = (it - cached - writes) * rates[0] + writes * rates[0] * multiplier
            else:
                # Missing write counters do not justify ordinary-input pricing.
                input_cost = (it - cached) * rates[0] * multiplier
            charged = math.ceil(input_cost + ot * rates[1] + cached * rates[2])
            violation = it > row['input_bound'] or ot > row['output_bound'] or charged > row['reserved_micro']
            con.execute('UPDATE requests SET charged_micro=?,input_tokens=?,output_tokens=?,state=? WHERE id=?',
                        (charged, it, ot, 'violation' if violation else 'settled', request_id))

    def summary(self):
        with self.connect() as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM requests')]
            limit = int(con.execute("SELECT value FROM metadata WHERE key='limit_micro'").fetchone()[0])
            restarts = (con.execute('SELECT COUNT(*) FROM explicit_restarts').fetchone()[0]
                        if con.execute("SELECT 1 FROM sqlite_master WHERE name='explicit_restarts'").fetchone() else 0)
            counts = ([dict(r) for r in con.execute('SELECT state,COUNT(*) AS count FROM preflights GROUP BY state')]
                      if con.execute("SELECT 1 FROM sqlite_master WHERE name='preflights'").fetchone() else [])
        stages = {}
        for row in rows:
            stage = stages.setdefault(row['stage'], dict(requests=0, input_tokens=0, output_tokens=0, estimated_usd=0))
            stage['requests'] += 1
            stage['input_tokens'] += row['input_tokens'] or 0
            stage['output_tokens'] += row['output_tokens'] or 0
            stage['estimated_usd'] += (row['charged_micro'] or 0) / 1e6
        charged = sum(r['charged_micro'] or 0 for r in rows)
        reserved = sum(r['reserved_micro'] for r in rows if r['charged_micro'] is None)
        return dict(limit_usd=limit / 1e6, requests=len(rows), explicit_job_restarts=restarts, estimated_usd=charged / 1e6,
                    input_count_requests=sum(r['count'] for r in counts), input_count_states={r['state']: r['count'] for r in counts},
                    retained_reservations_usd=reserved / 1e6,
                    remaining_usd=max(0, (limit - charged - reserved) / 1e6), stages=stages,
                    models=sorted({r['model'] for r in rows}),
                    price_basis='Standard generation rates including cache writes; count preflights reported separately; estimated, not an OpenAI billing invoice')

def usage_stage(job, body):
    if job['kind']=='review_sent':return 'post_send_review'
    if job['kind'] == 'revenue_brief':
        return 'manual_briefing'
    from clearline.commercial_agent import STRATEGY, SUPERVISOR, COMMUNICATION, COMM_REVIEW
    stages = {STRATEGY: 'investigation', SUPERVISOR: 'commercial_review',
              COMMUNICATION: 'communication', COMM_REVIEW: 'communication_review'}
    return stages.get(body.get('instructions'), 'customer_other')


@contextmanager
def bounded_clients(ledger):
    """Attach a dispatch guard to the real HTTP client; retain original hooks.

    HTTPX chooses a transport after request hooks, including any proxy route.
    Wrapping that selector covers every route without touching production code
    or replacing agent behavior. The wrapper is scoped to this test process.
    """
    # The installed OpenAI SDK uses httpx2; retain compatibility with older
    # environments without introducing another dependency.
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    import clearline.telemetry as telemetry
    original = telemetry.client_for

    class GuardedTransport(httpx.AsyncBaseTransport):
        def __init__(self, transport, store, job, settings):
            self.transport, self.store, self.job, self.settings = transport, store, job, settings

        async def handle_async_request(self, request):
            if request.method != 'POST' or request.url.scheme != 'https' or request.url.host != 'api.openai.com' or request.url.path != '/v1/responses':
                raise BudgetLimit('Acceptance worker permits only bounded OpenAI Responses requests')
            current = self.store.rows('SELECT status FROM jobs WHERE id=?', (self.job['id'],))
            if not current or current[0]['status'] != 'running':
                raise BudgetLimit('The selected acceptance job is no longer running')
            body = json.loads(await request.aread())
            if body.get('service_tier') not in (None, 'default'):
                raise BudgetLimit('Acceptance requests must use the standard service tier')
            body['service_tier'] = 'default'
            rid = request.extensions.get('clearline_request_id') or uuid4().hex
            count_body = ledger.start_preflight(self.job, self.settings.model, rid, body)
            # Direct transport avoids SDK generation hooks/retries. Preserve the
            # authorization headers but do not reuse the generation idempotency key.
            count_raw = json.dumps(count_body, ensure_ascii=False).encode('utf-8')
            count_headers = dict(request.headers)
            count_headers.pop('idempotency-key', None)
            count_headers['content-length'] = str(len(count_raw))
            count_request = httpx.Request('POST', request.url.copy_with(path='/v1/responses/input_tokens'),
                                         headers=count_headers, content=count_raw, extensions=dict(request.extensions))
            try:
                count_response = await self.transport.handle_async_request(count_request)
                try:
                    await count_response.aread()
                    try:
                        counted = json.loads(count_response.content)
                    except (ValueError, TypeError):
                        counted = None
                    count_status = count_response.status_code
                finally:
                    await count_response.aclose()
            except Exception as exc:
                ledger.finish_preflight(rid, error=type(exc).__name__)
            ledger.finish_preflight(rid, counted, count_status)
            ledger.reserve(self.job, self.settings.model, rid, body, usage_stage(self.job, body))
            raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers = dict(request.headers)
            headers['content-length'] = str(len(raw))
            forwarded = httpx.Request(request.method, request.url, headers=headers, content=raw, extensions=request.extensions)
            # A connection error leaves the reservation intact. Only a fully
            # observed successful standard-tier response can release unused cost.
            response = await self.transport.handle_async_request(forwarded)
            await response.aread()
            try:
                result = json.loads(response.content)
            except (ValueError, TypeError):
                result = {}
            ledger.settle(rid, result, response.status_code)
            return response

    @asynccontextmanager
    async def wrapped(store, job, settings):
        ledger.admit(job)
        from clearline.demo import CONVERSATION_SESSION
        path = getattr(store,'path',None)
        options = {'_guarded_ledger':ledger.path.resolve()} if path and path.resolve()==CONVERSATION_SESSION else {}
        async with original(store, job, settings, **options) as client:
            http = client._client
            select = http._transport_for_url
            http._transport_for_url = lambda url: GuardedTransport(select(url), store, job, settings)
            try:
                yield client
            finally:
                http._transport_for_url = select

    # brief.py binds client_for at import time, unlike commercial_agent.py.
    import clearline.brief as brief
    import clearline.reply_agent as replies
    prior_brief_client = brief.client_for
    prior_reply_client = replies.client_for
    telemetry.client_for = wrapped
    brief.client_for = wrapped
    replies.client_for = wrapped
    try:
        yield
    finally:
        telemetry.client_for = original
        brief.client_for = prior_brief_client
        replies.client_for = prior_reply_client


class AcceptanceStore(Store):
    def __init__(self, path, selected_ids, ledger, restart_ids=()):
        super().__init__(path)
        self.selected_ids, self.ledger = tuple(selected_ids), ledger
        self.restart_ids = set(restart_ids)

    def claim(self, kinds=None):
        # Exact ID filter means inherited or concurrently queued unrelated work
        # is never claimed, changed, or sent to an agent by this acceptance worker.
        conditions = ' OR '.join('(j.id=? AND j.attempts=?)' for _ in self.selected_ids)
        params = tuple(value for jid in self.selected_ids for value in (jid, 1 if jid in self.restart_ids else 0))
        eligible_kinds = tuple(kind for kind in KINDS if kinds is None or kind in kinds)
        if not eligible_kinds or not self.selected_ids:
            return None
        placeholders = ','.join('?' for _ in eligible_kinds)
        with self.connect(write=True) as con:
            row = con.execute(f'''SELECT j.* FROM jobs j WHERE ({conditions})
                AND j.status='queued' AND j.kind IN ({placeholders}) AND j.due_at<=?
                AND NOT EXISTS (SELECT 1 FROM jobs a WHERE a.status='running'
                  AND (a.kind='scan' OR (j.opportunity_id IS NOT NULL AND a.opportunity_id=j.opportunity_id)))
                ORDER BY j.created_at,j.rowid LIMIT 1''', (*params, *eligible_kinds, utcnow())).fetchone()
            if row is None:
                return None
            job = dict(row)
            self.ledger.admit(job)
            started = utcnow()
            con.execute("UPDATE jobs SET status='running',started_at=?,finished_at=NULL,attempts=attempts+1,error=NULL WHERE id=?", (started, job['id']))
            job['payload'] = json.loads(job['payload'])
            job.update(status='running', started_at=started, finished_at=None, error=None, attempts=row['attempts']+1)
            return job


def clone(db_path, accounts, budget_usd=2):
    target = isolated_path(db_path)
    source = (ROOT / 'runtime/phase3/screening.sqlite3').resolve()
    ledger = Ledger(target.parent / 'acceptance-budget.sqlite3')
    if target.exists() or ledger.path.exists():
        raise ValueError('Use the existing acceptance clone/ledger; refusing to overwrite or reset either')
    if not 1 <= len(accounts) <= 2 or len(set(accounts)) != len(accounts):
        raise ValueError('Choose one or two distinct acceptance accounts')
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as read:
        for account in accounts:
            if not read.execute("SELECT 1 FROM opportunities WHERE id=? AND workflow='recovery' AND active=1", (account,)).fetchone():
                raise ValueError('Selected account is not an active existing customer')
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as copied:
            read.backup(copied)
            baseline = [r[0] for r in copied.execute('SELECT id FROM jobs')]
    ledger.initialize(target, accounts, baseline, budget_usd=budget_usd)
    return dict(db_path=str(target), ledger_path=str(ledger.path), accounts=accounts)


def run(db_path, job_ids, env_file=None, model=None, restart_blocked=False):
    target = isolated_path(db_path)
    ledger = Ledger(target.parent / 'acceptance-budget.sqlite3')
    if not target.is_file() or not ledger.path.is_file():
        raise ValueError('Create the isolated acceptance database and ledger with clone first')
    if ledger.metadata()['db_path'] != str(target):
        raise ValueError('Ledger is bound to a different database')
    if not 1 <= len(job_ids) <= 4 or len(set(job_ids)) != len(job_ids):
        raise ValueError('Explicitly select one to four distinct newly queued test jobs')
    if restart_blocked and len(job_ids) != 1:
        raise ValueError('Explicitly restart exactly one envelope-blocked job')
    if env_file:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    settings = Settings.load()
    settings = replace(settings, db_path=target, screening_budget_path=target, concurrency=1,
                       max_concurrency=1, max_attempts=1, model=model or settings.model)
    if settings.model != 'gpt-6.1-sol':
        raise ValueError('Acceptance cache-write pricing is verified only for gpt-6.1-sol; execution disabled')
    store = AcceptanceStore(target, job_ids, ledger, restart_ids=job_ids if restart_blocked else ())
    if store.paused() or store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):
        raise ValueError('Acceptance clone is paused or API-blocked; existing worker controls remain enforced')
    for jid in job_ids:
        rows = store.rows('SELECT * FROM jobs WHERE id=?', (jid,))
        if not rows:
            raise ValueError('Selected acceptance job does not exist')
        if restart_blocked:
            ledger.authorize_restart(rows[0])
            with store.connect(write=True) as con:
                con.execute("UPDATE jobs SET status='queued',error=NULL,finished_at=NULL WHERE id=? AND status='blocked_config' AND attempts=1", (jid,))
                store.event('acceptance_explicit_job_restart', {
                    'reason': 'Legacy fixed input-size guard replaced by conservative dollar reservation',
                    'previous_attempt': 1, 'previous_error': rows[0]['error'],
                    'paid_stages_restart': True, 'prior_cost_and_requests_retained': True,
                }, jid, rows[0]['opportunity_id'], con=con)
        elif rows[0]['status'] != 'queued' or rows[0]['attempts'] != 0:
            raise ValueError('Only new, queued, never-attempted jobs may run; no automatic retry')
        ledger.admit(rows[0])
    from clearline.worker import execute_job, worker_lock
    async def execute_selected():
        store.heartbeat('running')
        try:
            while (job := store.claim(KINDS)) is not None:
                await execute_job(store, settings, job)
        finally:
            store.heartbeat('stopped')
    with worker_lock(target), bounded_clients(ledger):
        # Directly reuse the real dispatcher, but never tick schedulers, recover
        # interrupted work, inspect portfolio coverage, or drain unrelated jobs.
        asyncio.run(execute_selected())
    return dict(usage=ledger.summary(), jobs=[store.rows('SELECT id,kind,status,attempts,error FROM jobs WHERE id=?', (jid,))[0] for jid in job_ids])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('clone', 'run', 'status'))
    parser.add_argument('--db-path', type=Path, required=True)
    parser.add_argument('--account-id', action='append', default=[])
    parser.add_argument('--job-id', action='append', default=[])
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--budget-usd', type=Decimal, help='New clone only: immutable incremental generation cap (default $2, maximum $2)')
    parser.add_argument('--restart-blocked', action='store_true',
                        help='Explicitly restart one legacy envelope-guard-blocked analyze job; retain every prior cost/attempt')
    args = parser.parse_args()
    if args.budget_usd is not None and args.command != 'clone':
        parser.error('--budget-usd is only allowed when creating a new clone; existing limits are immutable')
    if args.command == 'clone':
        result = clone(args.db_path, args.account_id, budget_usd=args.budget_usd if args.budget_usd is not None else 2)
    elif args.command == 'run':
        result = run(args.db_path, args.job_id, args.env_file, args.model, args.restart_blocked)
    else:
        result = Ledger(isolated_path(args.db_path).parent / 'acceptance-budget.sqlite3').summary()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
