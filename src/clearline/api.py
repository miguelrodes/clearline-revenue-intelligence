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
            local_origins={f"http://{host}:{port}" for host in ("localhost","127.0.0.1") for port in (3000,3001,3002)}
            if request.headers.get("x-clearline-client") != "web" or request.headers.get("origin", "http://localhost:3000") not in local_origins:
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
        from .task_purpose import task_purpose
        from .practical_actions import practical_actions
        from .internal_inquiries import list_inquiries
        account=service.account(oid)
        notes=store.rows('SELECT * FROM contact_clearance_notes WHERE opportunity_id=?',(oid,))
        tasks=store.rows("SELECT * FROM investigation_tasks WHERE opportunity_id=? AND status='pending'",(oid,))
        recovery=account['workflow']=='recovery'
        reviews=store.rows("SELECT id,status,error,finished_at FROM jobs WHERE opportunity_id=? AND kind='analyze' ORDER BY created_at DESC,rowid DESC LIMIT 1",(oid,)) if recovery else []
        return {'signals':service.commercial_signals(oid),'tasks':[task | task_purpose(task) for task in tasks], 'authorizations':store.rows('SELECT * FROM contact_authorizations WHERE opportunity_id=?',(oid,)), 'contact_clearance':notes[0] if notes else None,
                'practical_actions':practical_actions(store,settings,oid) if recovery else [],'review_job':reviews[0] if reviews else None,
                'inquiry_data':list_inquiries(store,oid) if recovery else None}
    @app.post('/api/accounts/{oid}/contact-authorization')
    def authorize_contact(oid:str,body:AuthorizationInput):return service.authorize_contact(oid,**body.model_dump())
    @app.post('/api/accounts/{oid}/contact-clearance')
    def save_contact_clearance(oid:str,body:ContactClearanceInput):return service.save_contact_clearance(oid,**body.model_dump())
    @app.post('/api/investigations/{task_id}/resolve')
    def resolve_investigation(task_id:str,body:InvestigationResolution):return service.resolve_investigation(task_id,body.resolution)

    @app.get('/api/features')
    def features():return {'prospect_screening':settings.screening_enabled}
    @app.get('/api/overview/prospects')
    def prospect_overview():
        from .prospect_overview import overview
        return overview(store, settings.screening_enabled)
    @app.get('/api/prospect-pipeline')
    def prospect_pipeline(q:str='',origin:str='',state:str='',segment:str='',stage:str='',qualification:str='',
                          min_score:int=Query(0,ge=0,le=100),offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
        return service.prospect_pipeline(q=q,origin=origin,state=state,segment=segment,stage=stage,
                                        qualification=qualification,min_score=min_score,offset=offset,limit=limit)

    @app.get('/api/prospect-pipeline/candidates/{candidate_id}')
    def prospect_candidate(candidate_id:str):
        return service.candidate(candidate_id)

    @app.post('/api/prospect-pipeline/candidates/{candidate_id}/decision')
    def prospect_disposition(candidate_id:str,body:ProspectDispositionInput):
        return service.prospect_disposition(candidate_id,body.decision,body.rationale)

    @app.post('/api/prospect-pipeline/candidates/{candidate_id}/authorization')
    def prospect_authorization(candidate_id:str,body:AuthorizationInput):
        return service.authorize_prospect(candidate_id,**body.model_dump())

    @app.post('/api/prospect-pipeline/discovery/preview')
    def preview_discovery(body:ProspectDiscoveryInput):
        return service.prospect_run('discovery',body,preview=True)

    @app.post('/api/prospect-pipeline/discovery',status_code=202)
    def discover(body:ProspectDiscoveryInput):
        return service.prospect_run('discovery',body,preview=False)

    @app.post('/api/prospect-pipeline/research/preview')
    def preview_prospect_research(body:ProspectResearchInput):
        return service.prospect_run('research',body,preview=True)

    @app.post('/api/prospect-pipeline/research',status_code=202)
    def research_prospects(body:ProspectResearchInput):
        return service.prospect_run('research',body,preview=False)

    @app.get('/api/prospect-pipeline/jobs/{job_id}')
    def get_prospect_job(job_id:str):
        return service.prospect_job(job_id)

    @app.get('/api/screening')
    def screening_summary():return service.screening_summary()
    @app.get('/api/screening/agencies')
    def screening_agencies(q:str='',classification:str='',outcome:str='',sort:str='priority',offset:int=0,limit:int=50):
        return service.screening_list(q,classification,outcome,sort,offset,limit)
    @app.get('/api/screening/agencies/{aid}')
    def screening_detail(aid:str):return service.screening_detail(aid)
    class ScreeningInput(BaseModel):
        evidence_hash:str
    @app.post('/api/screening/agencies/{aid}/qualify',status_code=202)
    def screening_qualify(aid:str,body:ScreeningInput):return service.screening_qualify(aid,body.evidence_hash)
    @app.post('/api/screening/qualify-shortlist',status_code=202)
    def screening_shortlist():return service.screening_shortlist()
    @app.post('/api/screening/scan',status_code=202)
    def screening_scan():return service.screening_scan()

    class AgencyDecisionInput(BaseModel):
        decision:Literal['accepted','held','rejected']
        rationale:str
    class AgencyInformationInput(BaseModel):
        context_hash:str
        information:dict[str,str|bool]
    class AgencyContextInput(BaseModel):
        context_hash:str
    class AgencyActivityInput(BaseModel):
        kind:Literal['contact_attempted','response_received','advanced']
        note:str
    @app.post('/api/screening/agencies/{aid}/decision')
    def agency_decision(aid:str,body:AgencyDecisionInput):
        return service.screening_decision(aid,body.decision,body.rationale)
    @app.post('/api/screening/agencies/{aid}/information')
    def agency_information(aid:str,body:AgencyInformationInput):
        return service.screening_information(aid,body.information,body.context_hash)
    @app.post('/api/screening/agencies/{aid}/outreach',status_code=202)
    def agency_outreach(aid:str,body:AgencyContextInput):
        return service.screening_outreach(aid,body.context_hash)
    @app.post('/api/screening/agencies/{aid}/activity')
    def agency_activity(aid:str,body:AgencyActivityInput):
        return service.screening_activity(aid,body.kind,body.note)

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
        from .briefing import current_brief
        from .demo import CONVERSATION_SESSION
        return {**current_brief(store,live_fallback=True),
                'refresh_mode':'read' if store.path.resolve()==CONVERSATION_SESSION else 'generate'}

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

    @app.get("/api/accounts/{oid}/orders")
    def account_order_history(oid: str, offset: int=Query(default=0,ge=0), limit: int=Query(default=50,ge=1,le=100)):
        return service.account_orders(oid,offset=offset,limit=limit)

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

    class OutreachControlInput(BaseModel):
        action:Literal['pause','resume','do_not_contact']
        scope:Literal['account','recipient']|None=None
        reason:str=Field(default='',max_length=12000)
        recipient:str=Field(default='',max_length=320)
        reconsider_on:str|None=None
        clarify_id:str|None=None

    @app.post("/api/accounts/{oid}/outreach-control")
    def outreach_control(oid:str,body:OutreachControlInput):
        from .outreach_controls import change
        return change(store,oid,**body.model_dump())

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

    from .internal_inquiries import install_routes as install_internal_routes
    install_internal_routes(app,store,settings)
    app.mount("/",mcp_authenticated)
    return app
