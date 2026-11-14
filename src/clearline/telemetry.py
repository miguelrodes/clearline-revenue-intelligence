"""Safe provider telemetry: usage, prices and rate headers, never request bodies."""
import json
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .store import utcnow

# Standard service tier, verified 2026-11-12 at https://developers.openai.com/api/docs/pricing
PRICES={'gpt-6.1-sol':(2.0,10.0,.10),'gpt-6.1-terra':(1.0,5.0,.05),'gpt-6-astra':(10.0,50.0,1.0),'gpt-6-luna':(.1,.5,.01)}


def reset_seconds(value):
    if not value: return 0
    try: return float(value)
    except ValueError:
        try: return max(0,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
        except (TypeError,ValueError): pass
        return sum(float(n)*{'ms':.001,'s':1,'m':60,'h':3600}[unit] for n,unit in re.findall(r'([\d.]+)(ms|s|m|h)',value))


@asynccontextmanager
async def client_for(store,job,settings):
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    budget_store=store
    if job.get('kind') in ('agency_qualify','agency_outreach') and settings.screening_budget_path and settings.screening_budget_path.resolve()!=store.path.resolve():
        from .store import Store
        budget_store=Store(settings.screening_budget_path)
    inflight = {}
    async def started(request):
        if '/responses' not in str(request.url): return
        rid=uuid4().hex
        if job.get('kind') in ('agency_qualify','agency_outreach'):
            current=store.rows('SELECT status FROM jobs WHERE id=?',(job['id'],))
            if not current or current[0]['status']!='running':raise ValueError('Agency job was cancelled; no further model request sent')
            from .screening_budget import reserve
            reserve(budget_store,job,settings,rid,json.loads(request.content))
        request.extensions['clearline_request_id']=rid
        inflight[rid]=time.monotonic()
        store.event('model_request_started',{'request_id':rid},job['id'],job.get('opportunity_id'))
    async def record(response):
        if '/responses' not in str(response.url): return
        await response.aread()
        rid=response.request.extensions.get('clearline_request_id')
        start=inflight.pop(rid,None)
        if start is not None:
            store.event('model_request_finished',{'request_id':rid,'seconds':time.monotonic()-start,'status':response.status_code},job['id'],job.get('opportunity_id'))
        headers={k:v for k,v in response.headers.items() if k.startswith('x-ratelimit-') or k in ('retry-after','retry-after-ms')}
        store.event('rate_headers',headers,job['id'],job.get('opportunity_id'))
        try: body=response.json()
        except ValueError: body={}
        if job.get('kind') in ('agency_qualify','agency_outreach'):
            from .screening_budget import settle
            settle(budget_store,rid,body,response.status_code)
        if job.get('kind') in ('analyze','prepare','reply','revise_draft') and response.status_code==200:
            store.event('model_output',{'response_id':body.get('id'),'status':body.get('status'),'incomplete_details':body.get('incomplete_details'),'output':body.get('output',[])},job['id'],job.get('opportunity_id'))
        usage=body.get('usage') or {}; model=body.get('model',settings.model)
        it=usage.get('input_tokens',0); ot=usage.get('output_tokens',0); cached=(usage.get('input_tokens_details') or {}).get('cached_tokens',0)
        rates=PRICES.get(settings.model); tier=body.get('service_tier')
        cost=((it-cached)*rates[0]+ot*rates[1]+cached*rates[2])/1e6 if rates and usage and tier in (None,'default','standard') else None
        store.event('api_response',{'model':model,'requests':1,'status':response.status_code,'input_tokens':it,'output_tokens':ot,'cached_tokens':cached,'cost_usd':cost,'usage_available':bool(usage),'price_basis':'standard 2026-11-12','service_tier':tier},job['id'],job.get('opportunity_id'))
    async with AsyncOpenAI(timeout=settings.timeout_seconds,max_retries=0,http_client=DefaultAsyncHttpxClient(event_hooks={'request':[started],'response':[record]})) as client:
        try: yield client
        finally:
            for rid,start in inflight.items():
                store.event('model_request_finished',{'request_id':rid,'seconds':time.monotonic()-start,'status':'interrupted_or_connection_error'},job['id'],job.get('opportunity_id'))
