"""Persistent, fail-closed incremental Phase 3 model-usage budget.

Reserve a conservative upper bound BEFORE dispatch, release only on known usage.
Unknown/network-interrupted requests retain their entire reservation. No hosted
tools, media, server-side history, streaming, or nonstandard billing tiers allowed.
"""
import json
import math
from .store import utcnow

LIMIT_MICRO_USD = 5_000_000
MAX_AGENCIES = 15
MAX_REQUESTS_PER_JOB = 24
SCHEMA = """
CREATE TABLE IF NOT EXISTS agency_usage(
 request_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,agency_id TEXT NOT NULL,stage TEXT NOT NULL,
 model TEXT NOT NULL,reserved_micro INTEGER NOT NULL,charged_micro INTEGER,
 input_bound INTEGER NOT NULL,output_bound INTEGER NOT NULL,input_tokens INTEGER,output_tokens INTEGER,
 state TEXT NOT NULL,created_at TEXT NOT NULL);
"""

class BudgetLimit(ValueError):
    pass

def reserve(store, job, settings, request_id, body):
    from .telemetry import PRICES
    rates = PRICES.get(body.get('model'))
    if not rates or body.get('model') != settings.model or body.get('service_tier') not in (None,'default'):
        raise BudgetLimit('Phase 3 budget requires a priced model and standard service tier')
    if any(body.get(k) for k in ('previous_response_id','conversation','background','stream')):
        raise BudgetLimit('Stateful or streaming requests cannot use this bounded budget')
    if any(t.get('type') != 'function' for t in body.get('tools', [])):
        raise BudgetLimit('Hosted tools and web research are disabled for fictional agencies')
    def inspect(value):
        if isinstance(value,dict):
            if value.get('encrypted_content'):
                raise BudgetLimit('Opaque reasoning history cannot be priced by the text-input bound')
            if value.get('type') in ('input_image','input_file','input_audio','computer_call','compaction') or any(k in value for k in ('file_id','image_url','audio_url')):
                raise BudgetLimit('Nontext input is outside the Phase 3 budget model')
            for v in value.values():inspect(v)
        elif isinstance(value,list):
            for v in value:inspect(v)
    inspect(body)
    raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
    output = body.get('max_output_tokens')
    if not isinstance(output,int) or not 1 <= output <= 6000 or len(raw) > 200000:
        raise BudgetLimit('Request exceeds the bounded text/output envelope')
    # Byte-level text cannot have more tokens than bytes. Double serialized UTF-8
    # bytes plus 8192 covers message/tool/schema framing conservatively. Cached
    # input is charged at full input price for reservation, never discounted early.
    input_bound = 2*len(raw)+8192
    amount = math.ceil(input_bound*rates[0]+output*rates[1])
    aid = job['payload']['agency_id']
    with store.connect(write=True) as con:
        existing = {r[0] for r in con.execute('SELECT DISTINCT agency_id FROM agency_usage')}
        if aid not in existing and len(existing) >= MAX_AGENCIES:
            raise BudgetLimit('Phase 3 limit of 15 additional agencies reached')
        if con.execute('SELECT COUNT(*) FROM agency_usage WHERE job_id=?',(job['id'],)).fetchone()[0] >= MAX_REQUESTS_PER_JOB:
            raise BudgetLimit('Request cap reached for this job, including retries')
        if con.execute("SELECT 1 FROM agency_usage WHERE state='violation'").fetchone():
            raise BudgetLimit('Usage bound requires review; further paid requests are blocked')
        used = con.execute('SELECT COALESCE(SUM(COALESCE(charged_micro,reserved_micro)),0) FROM agency_usage').fetchone()[0]
        if used+amount > LIMIT_MICRO_USD:
            raise BudgetLimit('Phase 3 $5 cap: insufficient unreserved budget for this request')
        con.execute('INSERT INTO agency_usage VALUES(?,?,?,?,?,?,NULL,?,?,NULL,NULL,?,?)',
            (request_id,job['id'],aid,job.get('usage_stage','investigation'),settings.model,amount,input_bound,output,'reserved',utcnow()))

def settle(store, request_id, body, status):
    from .telemetry import PRICES
    usage = body.get('usage') or {};it=usage.get('input_tokens');ot=usage.get('output_tokens')
    with store.connect(write=True) as con:
        row=con.execute('SELECT * FROM agency_usage WHERE request_id=?',(request_id,)).fetchone()
        if not row:return
        known = status==200 and isinstance(it,int) and isinstance(ot,int) and it>=0 and ot>=0 and body.get('service_tier') in (None,'default','standard')
        model=body.get('model','')
        known = known and (model==row['model'] or model.startswith(row['model']+'-'))
        if not known:
            con.execute("UPDATE agency_usage SET state='unknown' WHERE request_id=?",(request_id,));return
        rates=PRICES[row['model']]; cached=min(it,max(0,(usage.get('input_tokens_details') or {}).get('cached_tokens',0)))
        amount=math.ceil((it-cached)*rates[0]+cached*rates[2]+ot*rates[1])
        violation=it>row['input_bound'] or ot>row['output_bound'] or amount>row['reserved_micro']
        con.execute('UPDATE agency_usage SET charged_micro=?,input_tokens=?,output_tokens=?,state=? WHERE request_id=?',(amount,it,ot,'violation' if violation else 'settled',request_id))

def summary(store):
    rows=store.rows('SELECT * FROM agency_usage')
    stages={}
    for r in rows:
        v=stages.setdefault(r['stage'],dict(requests=0,input_tokens=0,output_tokens=0,estimated_usd=0))
        v['requests']+=1;v['input_tokens']+=r['input_tokens'] or 0;v['output_tokens']+=r['output_tokens'] or 0;v['estimated_usd']+=(r['charged_micro'] or 0)/1e6
    return dict(limit_usd=5,agency_limit=MAX_AGENCIES,agencies=len({r['agency_id'] for r in rows}),requests=len(rows),
        estimated_usd=sum(r['charged_micro'] or 0 for r in rows)/1e6,
        reserved_usd=sum(r['reserved_micro'] for r in rows if r['charged_micro'] is None)/1e6,
        remaining_usd=max(0,(LIMIT_MICRO_USD-sum(r['charged_micro'] if r['charged_micro'] is not None else r['reserved_micro'] for r in rows))/1e6),
        stages=stages,price_basis='Local standard-tier price table; unknown requests retain full reservation, not an OpenAI invoice.')
