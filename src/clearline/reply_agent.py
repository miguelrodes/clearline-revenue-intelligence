"""Bounded genuine AI interpretation; facts are grounded before any state mutation."""
import asyncio,json,os,re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .agent import MissingCredentials
from .telemetry import client_for

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class ExtractedFact(Strict):
    fact:str=Field(max_length=300)
    quote:str=Field(min_length=1,max_length=600)
class ProductRequest(Strict):
    description:str=Field(max_length=200)
    sku:str|None
    quantity:float|None=Field(ge=0)
    unit:str|None
    quote:str=Field(min_length=1,max_length=600)
class Contact(Strict):
    name:str|None
    email:str|None
    phone:str|None
    quote:str=Field(min_length=1,max_length=600)
class Channel(Strict):
    route:Literal['direct','distributor','unknown']
    distributor:str|None
    quote:str=Field(min_length=1,max_length=600)
class ReplyProposal(Strict):
    decision:Literal['pursue','hold','reject']
    intent:Literal['reorder','training','support','pricing','purchasing_contact','distributor','not_interested','opt_out','other']
    opportunity_status:Literal['reorder_interest','support_needed','contact_updated','needs_information','channel_review','not_interested','opted_out','response_prepared']
    facts:list[ExtractedFact]=Field(max_length=8)
    products:list[ProductRequest]=Field(max_length=6)
    contact:Contact|None
    channel:Channel|None
    uncertainties:list[str]=Field(max_length=8)
    rationale:str=Field(max_length=3000)
    recommended_action:str=Field(min_length=1,max_length=1200)
    subject:str=Field(max_length=200)
    body:str=Field(max_length=2200)
    action_scope:Literal['none','recovery','clarification','support','order_status','channel_support']='none'

    @model_validator(mode='after')
    def coherent(self):
        if self.intent in ('opt_out','not_interested'):
            if self.decision!='reject' or self.subject or self.body or self.opportunity_status!=('opted_out' if self.intent=='opt_out' else 'not_interested'):raise ValueError('Rejections must stop outreach')
        if self.intent=='distributor' and self.opportunity_status!='channel_review':raise ValueError('Distributor replies require channel review')
        if self.decision!='pursue' and (self.subject or self.body):raise ValueError('Held or rejected replies cannot prepare outbound communication')
        if self.decision=='pursue' and (not self.subject.strip() or not self.body.strip()):raise ValueError('Incomplete reply draft')
        allowed={'reorder':{'reorder_interest','needs_information'},'training':{'support_needed','needs_information'},'support':{'support_needed','needs_information'},'purchasing_contact':{'contact_updated','needs_information'},'pricing':{'reorder_interest','needs_information'},'other':{'response_prepared','needs_information'}}
        # A customer can ask for support while preserving a distributor relationship.
        # Intent and purchasing route are independent dimensions.
        distributor_review=self.opportunity_status=='channel_review' and self.channel and self.channel.route=='distributor'
        if self.intent in allowed and self.opportunity_status not in allowed[self.intent] and not distributor_review:
            raise ValueError('Intent and opportunity status do not agree')
        return self


class ReplyDecision(ReplyProposal):
    engine_version:str=''
    context_hash:str=''
    evidence_hash:str=''
    quality:dict|None=None

def validate_reply(value,body,evidence):
    d=ReplyDecision.model_validate(value)
    def grounded(quote):
        if quote not in body:raise ValueError('Extracted facts must cite exact text from the inbound message')
    for f in d.facts:grounded(f.quote)
    known={p['sku'] for p in evidence.get('products',[])}
    for p in d.products:
        grounded(p.quote)
        if p.sku is not None and p.sku not in known:raise ValueError('Product is not in supplied account evidence')
    if d.contact:
        grounded(d.contact.quote)
        for field in (d.contact.name,d.contact.email,d.contact.phone):
            if field and field.lower() not in d.contact.quote.lower():raise ValueError('Contact information was not provided in the cited text')
        if d.contact.email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',d.contact.email):raise ValueError('Invalid contact email')
    if d.channel:
        grounded(d.channel.quote)
        if d.channel.distributor and d.channel.distributor.lower() not in d.channel.quote.lower():raise ValueError('Distributor name is not grounded')
    if re.search(r'[$€£]\s*\d|\b\d[\d,.]*\s*(USD|dollars|euros)\b',d.subject+' '+d.body,re.I):raise ValueError('Reply drafts cannot quote unverified pricing')
    return d

async def draft_reply(store,job,settings):
    from .agent import reviewed_run,INSTRUCTIONS as RECOVERY_INSTRUCTIONS
    o=store.opportunity(job['opportunity_id'])
    rows=store.rows('SELECT * FROM messages WHERE outcome_id=? AND opportunity_id=?',(job['payload']['outcome_id'],o['id']))
    if not rows:raise ValueError('Inbound message not found')
    target=rows[0]
    instructions=RECOVERY_INSTRUCTIONS+"""
You are now handling a customer RESPONSE, not initial recovery. Read complete relationship history and purchasing evidence.
Extract facts/contacts/products using exact verbatim substrings from the TARGET inbound message, not older messages.
Use conversation history to avoid asking again for known contact, channel, quantities or timing. A stated order request is
interest, not booked revenue. Prepare the next useful step (scope a quote, clarify a missing delivery requirement, discuss
training/support), not another initial purchasing check. No invented price, availability, technical claims or commitments.
Products must be from existing account evidence or null if unresolved. Preserve quantity and units exactly.
Opt-out/not-interested means reject, stopped status, no email; never opt a customer back in from a later message.
An existing stop policy remains binding. Distributor responses retain channel_review: support/channel_support clarification
may be useful, never direct selling or a demand for sell-through. A response can supply facts but cannot clear source identity
holds. If identity conflicts remain, extract facts and prepare the precise internal task without outbound email.
Return the ReplyProposal fields, not the initial-recovery schema. action_scope describes the proposed communication boundary.
Use appropriate status for intent. Quotes must be verbatim from the target body. Keep uncertainties separate from facts.
"""
    value=await reviewed_run(store,job,settings,ReplyProposal,instructions,
        'Respond to target message '+target['id']+': '+target['body'],
        validator=lambda v:validate_reply(v,target['body'],o['evidence']))
    return validate_reply(value,target['body'],o['evidence']).model_dump()
