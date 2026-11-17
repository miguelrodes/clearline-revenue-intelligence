"""One fixed, cumulative USD 1 meter for manually triggered prospect discovery and research."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3

from openai.lib._pydantic import to_strict_json_schema

from .config import ROOT
from .screening_budget import BudgetLimit
from .store import utcnow
from .telemetry import IMPLICIT_WRITE_PRICES, PRICES, implicit_cache_charge

MODEL = 'gpt-6.1-sol'
CAP = 1_000_000  # microdollars
# Per-stage maximum shown before confirmation, including reasoning and implicit cache writes.
STAGE_CAP = {'pipeline_discover': 120_000, 'pipeline_research': 160_000, 'pipeline_qualify': 120_000}
OUTPUT = {'pipeline_discover': 3400, 'pipeline_research': 3400, 'pipeline_qualify': 3200}
LEDGER = ROOT / 'runtime/prospect-pipeline-usage.sqlite3'
SCHEMA = '''CREATE TABLE IF NOT EXISTS calls(job_id TEXT PRIMARY KEY,kind TEXT,model TEXT,
 input_bound INTEGER,output_bound INTEGER,reserved INTEGER,charged INTEGER,state TEXT,
 input_tokens INTEGER,output_tokens INTEGER,created_at TEXT,provider_id TEXT)'''


def ledger_path(settings):
    # Production and all copies in this checkout share a non-restored meter. A separate
    # test-only root is permitted for fixtures outside the application's runtime tree.
    path = Path(settings.db_path).resolve()
    if path.is_relative_to((ROOT / 'runtime').resolve()):
        return LEDGER
    return (settings.screening_budget_path or path).parent / 'prospect-pipeline-usage.sqlite3'


@contextmanager
def transaction(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.row_factory = sqlite3.Row
        con.execute(SCHEMA)
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def usage(settings):
    path = ledger_path(settings)
    if not path.exists():
        return {'spent_usd': 0.0, 'reserved_usd': 0.0, 'remaining_usd': 1.0, 'requests': 0}
    con = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    try:
        spent, held, n = con.execute("""SELECT COALESCE(SUM(charged),0),
          COALESCE(SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END),0),COUNT(*) FROM calls""").fetchone()
    finally:
        con.close()
    return {'spent_usd': spent / CAP, 'reserved_usd': held / CAP,
            'remaining_usd': max(0, CAP-spent-held) / CAP, 'requests': n}


def config_error(settings):
    from .demo import CONVERSATION_SESSION
    if not settings.screening_enabled:
        return 'Prospect Screening is disabled in this workspace.'
    if Path(settings.db_path).resolve() == CONVERSATION_SESSION:
        return 'New paid prospect research is disabled in the protected conversation rehearsal.'
    if settings.model != MODEL or os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/') != 'https://api.openai.com/v1':
        return 'The prospect dollar limit supports the standard OpenAI gpt-6.1-sol endpoint only.'
    if not os.getenv('OPENAI_API_KEY', '').strip():
        return 'Configure the local OpenAI API key before starting a paid search.'
    return ''


def reserve(settings, job, inputs, outputs):
    kind = job['kind']
    if kind not in STAGE_CAP or not 0 < inputs <= 272_000 or not 0 < outputs <= OUTPUT[kind]:
        raise BudgetLimit('Prospect request exceeds the priced text-only context or output limits.')
    # Default 30-minute implicit cache policy: $2 input, $2.50 write, $10 output per million.
    amount = math.ceil(inputs * IMPLICIT_WRITE_PRICES[MODEL] + outputs * PRICES[MODEL][1])
    if amount > STAGE_CAP[kind]:
        raise BudgetLimit('Source packet exceeds the displayed per-stage ceiling; no generation was sent.')
    with transaction(ledger_path(settings)) as con:
        if con.execute('SELECT 1 FROM calls WHERE job_id=? OR state="violation"', (job['id'],)).fetchone():
            raise BudgetLimit('This job already reserved its single generation, or the meter is locked.')
        used = con.execute('SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM calls').fetchone()[0]
        if used + amount > CAP:
            raise BudgetLimit('The cumulative $1 prospect budget has insufficient unreserved funds.')
        con.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,NULL,?,NULL,NULL,?,NULL)',
                    (job['id'],kind,MODEL,inputs,outputs,amount,'reserved',utcnow()))


def settle(settings, job, response):
    body = response.model_dump(mode='json')
    info = body.get('usage') or {}
    it, ot = info.get('input_tokens'), info.get('output_tokens')
    model, tier = body.get('model') or '', body.get('service_tier')
    charge = implicit_cache_charge(MODEL,info)
    reliable = (model == MODEL or model.startswith(MODEL+'-')) and tier in ('default','standard') and charge is not None
    with transaction(ledger_path(settings)) as con:
        row = con.execute('SELECT * FROM calls WHERE job_id=?',(job['id'],)).fetchone()
        if not reliable:
            state = 'unknown'
            con.execute('UPDATE calls SET state=?,provider_id=? WHERE job_id=?',(state,body.get('id'),job['id']))
        else:
            state = 'settled' if it <= row['input_bound'] and ot <= row['output_bound'] and charge <= row['reserved'] else 'violation'
            con.execute('UPDATE calls SET charged=?,state=?,input_tokens=?,output_tokens=?,provider_id=? WHERE job_id=?',
                        (charge,state,it,ot,body.get('id'),job['id']))
    if state != 'settled':
        raise BudgetLimit('Provider usage was unavailable or outside its bound. The meter retains the reservation or locks.')


async def generate(store, job, settings, schema, instructions, payload):
    """Exactly one stateless, tool-free response, with an exact provider input count first."""
    from .telemetry import client_for
    error = config_error(settings)
    if error:
        raise BudgetLimit(error)
    text_format = {'type':'json_schema','name':schema.__name__,'strict':True,'schema':to_strict_json_schema(schema)}
    counted = dict(model=MODEL,instructions=instructions,input=json.dumps(payload,ensure_ascii=False),
                   text={'format':text_format},reasoning={'effort':'low'})
    if len(json.dumps(counted).encode()) > 130_000:
        raise BudgetLimit('Public source packet is too large for a bounded research pass.')
    from openai import AsyncOpenAI
    output = OUTPUT[job['kind']]
    # Count is non-generative and has no web tool or usage charge. Do not record it as a model request.
    async with AsyncOpenAI(max_retries=0,timeout=settings.timeout_seconds) as counter:
        count = await counter.responses.input_tokens.count(**counted)
    if type(count.input_tokens) is not int or count.input_tokens <= 0:
        raise BudgetLimit('Provider did not return a valid exact input count.')
    current = store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))
    if not current or current[0]['status'] != 'running':
        raise BudgetLimit('Job no longer active; no paid request was sent.')
    reserve(settings,job,count.input_tokens+256,output)
    async with client_for(store,job,settings) as client:
        response = await client.responses.create(**counted,max_output_tokens=output,service_tier='default',store=False)
    settle(settings,job,response)
    if response.status != 'completed':
        raise ValueError(f'Prospect model response was {response.status}; no unverified output was saved.')
    return schema.model_validate_json(response.output_text)
