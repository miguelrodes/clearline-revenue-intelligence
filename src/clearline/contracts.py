"""Typed requests shared by HTTP and MCP adapters."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ScanInput(Input):
    open_order_review_days:int=Field(default=30,ge=1,le=3650)
    replenishment_min_dates:int=Field(default=4,ge=4,le=100)
    replenishment_max_cv:float=Field(default=.5,gt=0,le=2)
    request_id: UUID | None = None
    analysis_limit: int = Field(default=-1, ge=-1)
    inactivity_days: int = Field(default=90, ge=1, le=3650)
    decline_fraction: float = Field(default=0.25, gt=0, lt=1)

class BatchInput(Input):
    request_id: UUID | None = None
    account_ids: list[str] | None = None

class CampaignInput(Input):
    request_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    account_ids: list[str] = Field(min_length=1)
    simulated_contacts: bool = False

class DraftSnapshot(Input):
    draft_id: str
    snapshot_hash: str

class CampaignDecision(Input):
    snapshots: list[DraftSnapshot]
    approve: bool

class RevisionInput(Input):
    snapshots: list[DraftSnapshot] = Field(min_length=1,max_length=100)
    instructions: str = Field(min_length=1,max_length=2000)

class DispositionInput(Input):
    decision: Literal['defer', 'reject', 'acknowledge']
    note: str = Field(min_length=1)

class AssessmentInput(Input):
    evidence_hash: str
    rerun: bool = False
    request_id: UUID | None = None

class DraftInput(Input):
    version: int
    recipient: str = Field(min_length=1, max_length=1000)
    subject: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=30000)

class ApprovalInput(DraftInput):
    approve: bool

class OutcomeInput(Input):
    kind: Literal['reply', 'qualified', 'quote', 'order', 'credit', 'lost', 'opt_out', 'closed']
    note: str = Field(min_length=1, max_length=10000)
    amount_cents: int | None = Field(default=None, ge=0)
    reference: str | None = None

class InboundInput(Input):
    reply_to: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=12000)

class ScheduleInput(ScanInput):
    enabled: bool

class RegenerateInput(Input):
    version: int = Field(ge=1)
    request_id: UUID

class ProspectDiscoveryInput(Input):
    state: str = Field(min_length=2, max_length=2)
    category: str = Field(min_length=1, max_length=160)
    keywords: str = Field(default='', max_length=400)
    maximum: int = Field(default=10, ge=1, le=15)
    directory_url: str | None = Field(default=None, max_length=2048)
    instructions: str = Field(default='', max_length=1200)
    confirmed: bool = Field(default=False, strict=True)


class ProspectResearchInput(Input):
    candidate_ids: list[str] = Field(min_length=1, max_length=3)
    refresh: bool = Field(default=False, strict=True)
    confirmed: bool = Field(default=False, strict=True)


class ProspectDispositionInput(Input):
    decision: Literal['select_for_research','hold','reject','resume']
    rationale: str = Field(min_length=1,max_length=1000)
