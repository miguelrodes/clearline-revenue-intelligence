"""Local HTTP adapter. Store and the existing worker retain execution authority."""
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import json
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .store import Store, STOPPED_STATUSES
from .services import ApplicationService,NotFound
from .contracts import *
from .reporting import opportunities, monthly_trends, valid_draft, portfolio_transactions


def create_app(settings=None):
    settings = settings or Settings.load()
    service=ApplicationService(settings)
    store=service.store
    from .mcp_server import build_mcp
    mcp_server,mcp_app,mcp_authenticated=build_mcp(service)
    @asynccontextmanager
    async def lifespan(app):
        from .demo import use_guard
        with use_guard(settings.db_path):
            async with mcp_app.router.lifespan_context(mcp_app):yield
    app = FastAPI(title="Clearline local API", docs_url="/docs",lifespan=lifespan)
    app.state.store = store
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1","localhost","testserver"])

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.url.path not in ("/mcp","/mcp/") and request.method not in ("GET","HEAD","OPTIONS"):
            if request.headers.get("x-clearline-client") != "web" or request.headers.get("origin", "http://localhost:3000") not in ("http://localhost:3000","http://127.0.0.1:3000"):
                return JSONResponse({"detail":"Local app requests only"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NotFound)
    async def missing(request,exc):
        return JSONResponse({"detail":str(exc)},status_code=404)

    @app.exception_handler(ValueError)
    async def business_error(request, exc):
        return JSONResponse({"detail":str(exc)}, status_code=409)





    class AuthorizationInput(BaseModel):
        recipient:str
        role:str
        route:Literal['direct','distributor']
        evidence:str
        authorized:bool
    class ContactClearanceInput(BaseModel):
        task_id:str|None=None
        contact_name:str=Field(default='',max_length=200)
        recipient:str=Field(default='',max_length=320)
        role:str=Field(default='',max_length=200)
        phone:str=Field(default='',max_length=80)
        route:Literal['','direct','distributor']=''
        distributor:str=Field(default='',max_length=200)
        verification_evidence:str=Field(default='',max_length=4000)
        verified:bool=False
    class InvestigationResolution(BaseModel):
        resolution:str
    @app.get('/api/commercial-signals')
    def commercial_signals(oid:str|None=None):return service.commercial_signals(oid)
    @app.get('/api/accounts/{oid}/commercial-work')
    def commercial_work(oid:str):
        service.account(oid)
        notes=store.rows('SELECT * FROM contact_clearance_notes WHERE opportunity_id=?',(oid,))
        return {'signals':service.commercial_signals(oid),'tasks':store.rows("SELECT * FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,)), 'authorizations':store.rows('SELECT * FROM contact_authorizations WHERE opportunity_id=?',(oid,)), 'contact_clearance':notes[0] if notes else None}
    @app.post('/api/accounts/{oid}/contact-authorization')
    def authorize_contact(oid:str,body:AuthorizationInput):return service.authorize_contact(oid,**body.model_dump())
    @app.post('/api/accounts/{oid}/contact-clearance')
    def save_contact_clearance(oid:str,body:ContactClearanceInput):return service.save_contact_clearance(oid,**body.model_dump())
    @app.post('/api/investigations/{task_id}/resolve')
    def resolve_investigation(task_id:str,body:InvestigationResolution):return service.resolve_investigation(task_id,body.resolution)

    @app.get("/api/health")
    def get_health():
        return service.get_health()

    @app.get("/api/opportunities")
    def get_opportunities(workflow: Literal["recovery","prospecting"]="recovery", queue: Literal["contacts","unassessed","held","approvals"] | None=None):
        return service.get_opportunities(workflow,queue)

    from .operations import start_batch, batches, create_campaign, campaign_view, decide_campaign, financial_segments, metrics, queue_brief, review_recommendation

    @app.get("/api/work")
    def work():
        return service.work()

    @app.post("/api/work/{group_id}/revise")
    def work_revision(group_id: str,body: RevisionInput):
        return service.work_revision(group_id,body)

    @app.post("/api/work/{group_id}/decision")
    def work_decision(group_id: str,body: CampaignDecision):
        return service.work_decision(group_id,body)

    @app.post("/api/portfolio/refresh",status_code=202)
    def refresh_portfolio():
        return service.refresh_portfolio()

    @app.get("/api/portfolio/coverage")
    def portfolio_coverage():
        return service.portfolio_coverage()

    @app.get("/api/signals/{key}")
    def signal_view(key: Literal['inactivity','partial','product_decline','direct_gap_channel_review']):
        return service.signal_view(key)

    @app.get("/api/performance")
    def performance(workflow: Literal['recovery','prospecting']='recovery'):
        return service.performance(workflow)

    @app.get("/api/search")
    def search(q: str=''):
        return service.search(q)

    @app.get("/api/checks")
    def checks():
        return service.checks()

    @app.get("/api/checks/{key}/export")
    def check_export(key: Literal['orders','dates','channel','identity','other'],signal: str|None=None,focus: str|None=None):
        return Response(service.check_export(key,signal,focus),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="customer-{key}-check.csv"'})

    @app.get("/api/checks/{key}")
    def check_detail(key: Literal['orders','dates','channel','identity','other'],signal: str|None=None,focus: str|None=None):
        return service.check_detail(key,signal,focus)

    @app.get("/api/execution")
    def execution():
        return service.execution()

    @app.post("/api/batches",status_code=202)
    def batch(body: BatchInput):
        return service.batch(body)

    @app.get("/api/campaigns")
    def campaigns():
        return service.campaigns()

    @app.post("/api/campaigns",status_code=202)
    def campaign(body: CampaignInput):
        return service.campaign(body)

    @app.post("/api/campaigns/{cid}/decision")
    def campaign_decide(cid: str,body: CampaignDecision):
        return service.campaign_decide(cid,body)

    @app.get("/api/brief")
    def operational_brief():
        return service.operational_brief()

    @app.post("/api/brief",status_code=202)
    def regenerate_brief():
        return service.regenerate_brief()

    @app.post("/api/accounts/{oid}/disposition")
    def disposition(oid: str,body: DispositionInput):
        return service.disposition(oid,body)

    @app.get("/api/overview")
    def overview():
        return service.overview()

    @app.get("/api/transactions")
    def transactions(year: int=Query(default=2026,ge=2025,le=2026), q: str="", offset: int=Query(default=0,ge=0)):
        return service.transactions(year,q,offset)

    @app.get("/api/accounts/{oid}")
    def detail(oid: str):
        return service.detail(oid)

    @app.get("/api/activity")
    def activity():
        return service.activity()

    @app.get("/api/actions")
    def actions():
        return service.actions()

    @app.post("/api/scan", status_code=202)
    def run_scan(body: ScanInput):
        return service.run_scan(body)

    @app.post("/api/accounts/{oid}/assess", status_code=202)
    def assess(oid: str, body: AssessmentInput):
        return service.assess(oid,body)

    @app.patch("/api/drafts/{did}")
    def edit(did: str, body: DraftInput):
        return service.edit(did,body)

    @app.post("/api/drafts/{did}/decision")
    def decide(did: str, body: ApprovalInput):
        return service.decide(did,body)

    @app.get("/api/accounts/{oid}/conversation")
    def conversation(oid: str):
        return service.conversation(oid)

    @app.post("/api/accounts/{oid}/conversation/replies")
    def inbound(oid: str, body: InboundInput):
        return service.inbound(oid,body)

    @app.post("/api/accounts/{oid}/outcomes")
    def outcome(oid: str, body: OutcomeInput):
        return service.outcome(oid,body)

    @app.post("/api/jobs/{jid}/{action}")
    def job_action(jid: str, action: Literal["retry","cancel"]):
        return service.job_action(jid,action)

    @app.post("/api/worker/{action}")
    def worker_action(action: Literal["pause","resume"]):
        return service.worker_action(action)

    @app.put("/api/schedule")
    def schedule(body: ScheduleInput):
        return service.schedule(body)

    @app.post('/api/drafts/{did}/regenerate',status_code=202)
    def regenerate(did:str,body:RegenerateInput):
        return service.regenerate_draft(did,body.version,body.request_id)

    app.mount("/",mcp_authenticated)
    return app
