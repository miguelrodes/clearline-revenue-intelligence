"""Typed requests shared by HTTP and MCP adapters."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ScanInput(Input):
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
