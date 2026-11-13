"""Investigate -> strategy -> independent decision review -> communication -> review."""
import asyncio,json,os
from typing import Literal
from datetime import datetime,timedelta,timezone
from pydantic import Field
from .agent import Strict,Alternative,Citation,VerificationTask,COMMON,QualityReview,MissingCredentials,behavioral_issues
from .evidence import EvidenceAccess,ENGINE_VERSION
from .commercial import decision_issues,CATEGORIES
from .data import digest

Outcome=Literal['contact','internal_investigation','human_verification','monitor','defer','no_action']
Category=Literal['inactive_recovery','purchasing_decline','sku_deterioration','missed_replenishment','distributor_recovery','aging_open_order','cross_sell','purchasing_obstacle','churn_prevention']
class SignalDecision(Strict):
    signal_id:str
    disposition:Literal['qualified','investigate','verify','monitor','defer','no_action']
    reason:str
class Strategy(Strict):
    outcome:Outcome
    capability:Category|None
    objective:str
    timing:str
    intervention:str
    rationale:str
    alternatives:list[Alternative]=Field(min_length=1)
    change_conditions:list[str]=Field(min_length=1)
    recipient:str=Field(description='Exact authorized email address ONLY, copied from commercial_eligibility.authorization.recipient. No name or explanatory text. Empty string for noncontact.')
    route:Literal['direct','distributor','none']
    action_scope:Literal['none','recovery','clarification','support','order_status','channel_support']
    verification_tasks:list[VerificationTask]
    signal_decisions:list[SignalDecision]
    citations:list[Citation]=Field(min_length=1)
    reassess_days:int|None=Field(default=None,ge=1,le=90)
class Finding(Strict):
    passed:bool
    explanation:str
class DecisionReview(Strict):
    verdict:Literal['approve','revise','internal_investigation','human_verification','defer','no_action']
    revenue_objective:Finding
    evidence:Finding
    timing:Finding
    intervention:Finding
    recipient_channel:Finding
    prerequisites:Finding
    commercial_value:Finding
    explanation:str
class Communication(Strict):
    subject:str=Field(min_length=1)
    body:str=Field(min_length=1)

STRATEGY=COMMON+'''
Select the best commercial intervention across the nine approved capabilities in the account's detected signals.
Do NOT compose an email. Investigation and no action are successful outcomes. For EVERY detected signal return one
signal_decision with its exact id, disposition and reason. Even when no signal exists assess the account and explain no action.
Retrieve overview, ALL purchase-history pages, ALL relationship-history pages, catalogue and identity. When relevant retrieve
product associations and previous work. Compare timing, quantities, credits, mix, recent orders and CRM context.
No contact without recorded authorization: the simulator address is not authorization. Direct invoice history alone is not
verified recipient permission. Distributor-only institutional records never authorize downstream contact. A named distributor
route must have explicit authorization. A verified DISTRIBUTOR bill-to account is its own buyer relationship;
its own decline may justify a direct discussion with its authorized distributor purchasing contact, not downstream outreach. Never ask for unavailable sell-through information.
First choose whether there is a worthwhile intervention; THEN determine missing prerequisites. Do not create contact tasks
for a healthy account merely because it has no contact. Stable accounts without an additional supported need require no action.
An aged order requires internal investigation even without confirmed fulfillment failure. Read its rows first; if disposition
is unavailable, assign order operations a precise task naming the order and missing fact. Never ask a customer whether they
want us to investigate our own records. Same-day open orders are normal, not overdue; no outreach from that fact alone.
Credits require internal explanation and resolution checks before credit-led outreach; they do not establish dissatisfaction.
Recent CRM contact (within 14 days of business cutoff) plus an undated concern warrants checking what that interaction resolved,
not repeating a customer question. A current customer request can justify prompt response despite recent contact.
Training interest plus a purchasing gap may justify training-led recovery; merely owning a product does not imply training need.
An already purchased SKU does not itself constitute cross-selling. Associations are observational and require adequate samples,
confidence, lift and relevance. Missing SKU alone is not a trigger. Declines must be assessed even if contact is deferred.
For contact, require a specific revenue mechanism, reason to act now, useful intervention, correct verified recipient/route,
and no blocking prerequisites. Otherwise choose internal_investigation/human_verification/monitor/defer/no_action.
Noncontact internal/verification outcomes must contain precise actionable tasks for missing BUSINESS FACTS only.
Never create tasks to review/hold an old draft, obtain exact-version approval, or perform checks the workflow already enforces.
Those are later execution controls, not prerequisites to preparing a new proposal.
Reuse existing_task_id for the same pending business question; copy its exact evidence_refs and do not create a reworded duplicate.
 Separate training from unrelated order uncertainty.
Explain why monitoring/no action is inferior before choosing external action. Past AI recommendations are not source facts.
Do not require knowledge absent from the source unless it is necessary for the selected intervention. Do not promise revenue.
Use citations with exact returned refs. Reassessment days reflect a meaningful review interval, not repeated unchanged analysis.
'''
SUPERVISOR=COMMON+'''
Independently assess a COMMERCIAL DECISION before any email exists. Retrieve further evidence if material.
Evaluate each critical finding explicitly. Permission to provide support is NOT a commercial reason to contact someone.
Would this intervention advance revenue/relationship or create unnecessary work? Why now? Could internal investigation
answer the question? Is monitoring better? Check recent interaction, healthy purchasing, open-order age, credit resolution,
authorized recipient and channel. Conditional polite language cannot rescue an unjustified intervention. Reject redundant draft-review/approval tasks presented as missing business facts; approval is a later execution control.
For no-action/internal/verification outcomes judge suitability of that disposition; missing recipient need not fail a decision
that deliberately avoids contact. For contact, any failed critical criterion prohibits approve. Recommend a concrete alternate
verdict rather than repeatedly polishing outreach. A supported training or product-interest opportunity can exist without decline.
Respect deterministic issues as binding. Do not mistake a simulation recipient for relationship authorization.
'''
COMMUNICATION=COMMON+'''
Write only the communication executing the approved commercial strategy. Do not broaden its purpose, invent support needs,
quantities or commitments. One specific useful next step. Preserve channel and recipient. Do not ask the customer to perform
an internal investigation. Use the supplied source evidence and customer conversation; avoid repeating answered questions.
'''
COMM_REVIEW=COMMON+'''
Review this email against the independently approved commercial decision and evidence. It must execute the exact intervention,
address the authorized relationship, preserve known facts, add a specific useful next step and avoid invented needs/commitments.
Reject vague support requests or internal-work questions even if polite. All dimensions >=4 and no critical issue required.
'''

def review_passes(review):
    return review['verdict']=='approve' and all(review[k]['passed'] for k in ('revenue_objective','evidence','timing','intervention','recipient_channel','prerequisites','commercial_value'))

def strategy_accepted(review,plan):
    if not review:return False
    findings=all(review[k]['passed'] for k in ('revenue_objective','evidence','timing','intervention','recipient_channel','prerequisites','commercial_value'))
    return findings and (review['verdict']=='approve' or (plan['outcome']!='contact' and review['verdict']==plan['outcome']))

async def investigate(store,job,settings):
    if not os.getenv('OPENAI_API_KEY'):raise MissingCredentials('Configure OPENAI_API_KEY locally')
    from agents import Agent,Runner,ModelSettings,RunConfig,OpenAIResponsesModel
    from agents.exceptions import ModelBehaviorError
    from openai.types.shared import Reasoning
    from .telemetry import client_for
    from .action_policy import proposal_fingerprint
    access=EvidenceAccess(store,job,settings);tools=access.tools()
    async def execute():
        async with client_for(store,job,settings) as client:
            model=OpenAIResponsesModel(model=settings.model,openai_client=client)
            def agent(name,instructions,schema):return Agent(name=name,instructions=instructions,model=model,tools=tools,output_type=schema,model_settings=ModelSettings(reasoning=Reasoning(effort=settings.reasoning),max_tokens=settings.investigation_max_tokens,store=False))
            investigator=agent('Commercial investigator',STRATEGY,Strategy)
            supervisor=agent('Commercial decision supervisor',SUPERVISOR,DecisionReview)
            task={'account_id':access.oid,'task':'Assess every applicable opportunity and choose the best intervention','followup':job['payload'].get('followup_of'),'human_guidance':job['payload'].get('instructions')}
            inputs=json.dumps(task);plan=None;review=None;issues=[]
            for attempt in range(settings.quality_max_revisions+1):
                try:r=await Runner.run(investigator,inputs,max_turns=20,run_config=RunConfig(tracing_disabled=True))
                except ModelBehaviorError as exc:
                    store.event('commercial_schema_failure',{'attempt':attempt,'error':str(exc)[:1500]},job['id'],access.oid)
                    inputs=json.dumps(task)+'\nCorrect schema failure: '+str(exc)[:1500];continue
                plan=r.final_output.model_dump()
                issues=decision_issues(plan,access)+behavioral_issues({'decision':'hold','citations':plan['citations']},access)
                if plan['outcome'] in ('internal_investigation','human_verification') and not plan['verification_tasks']:issues.append('Internal/verification intervention requires a concrete task')
                store.event('commercial_strategy',{'attempt':attempt,'plan':plan,'issues':issues},job['id'],access.oid)
                q=await Runner.run(supervisor,json.dumps({'plan':plan,'evidence':access.outputs,'deterministic_issues':issues}),max_turns=8,run_config=RunConfig(tracing_disabled=True))
                review=q.final_output.model_dump();store.event('commercial_decision_review',{'attempt':attempt,**review},job['id'],access.oid)
                if not issues and strategy_accepted(review,plan):break
                inputs=r.to_input_list()+[{'role':'user','content':'Reconsider the intervention using this independent decision review. You may change to internal work, deferral or no action. '+json.dumps({'review':review,'mandatory_issues':issues})}]
            if not plan:raise ValueError('No valid commercial decision produced; see saved validation events')
            passed=not issues and strategy_accepted(review,plan)
            if not passed:
                # Preserve failed decision and avoid converting rejection into fabricated approved judgment.
                plan['outcome']='human_verification';plan['recipient']='';plan['route']='none'
                plan['verification_tasks']=[dict(title='Review unresolved commercial decision',owner='Account owner',reason=json.dumps({'review':review,'issues':issues}),evidence_refs=['account'],blocking=True)]
                for signal in plan['signal_decisions']:signal.update(disposition='verify',reason='Independent commercial review unresolved; human review required')
            outcome=plan['outcome'];subject=body='';quality=None
            if outcome=='contact' and passed:
                writer=agent('Commercial communication preparation',COMMUNICATION,Communication)
                checker=agent('Communication quality review',COMM_REVIEW,QualityReview)
                comm_input=json.dumps({'approved_strategy':plan,'evidence':access.outputs})
                for attempt in range(settings.quality_max_revisions+1):
                    d=await Runner.run(writer,comm_input,max_turns=8,run_config=RunConfig(tracing_disabled=True));message=d.final_output.model_dump()
                    qa=await Runner.run(checker,json.dumps({'strategy':plan,'email':message,'evidence':access.outputs}),max_turns=6,run_config=RunConfig(tracing_disabled=True));quality=qa.final_output.model_dump()
                    problems=behavioral_issues({'decision':'pursue','action_scope':plan['action_scope'],'citations':plan['citations'],**message},access)
                    valid=quality['passed'] and not problems and min(quality[k] for k in ('evidence_coverage','commercial_specificity','personalization','appropriateness','conversation_progress','uncertainty_handling','factuality'))>=4
                    store.event('communication_review',{'attempt':attempt,**quality,'issues_deterministic':problems},job['id'],access.oid)
                    if valid:subject=message['subject'];body=message['body'];break
                    comm_input=d.to_input_list()+[{'role':'user','content':json.dumps({'review':quality,'issues':problems})}]
                if not body:raise ValueError('Communication review failed; approved strategy preserved in events, no email created')
            decision='pursue' if body else 'hold' if outcome in ('internal_investigation','human_verification') else 'no_action'
            result=dict(decision=decision,rationale=plan['rationale'],hypotheses=[],evidence_fields=['signals','crm_notes','action_history'],unresolved_questions=plan['change_conditions'],recommended_action=plan['intervention'],strategy=plan['capability'] or 'monitor',personalized_context='',subject=subject,body=body,objective=plan['objective'],action_scope=plan['action_scope'],alternatives=plan['alternatives'],citations=plan['citations'],verification_tasks=plan['verification_tasks'],followup_plan='Reassess on new evidence; exact approval required for each communication',engine_version=ENGINE_VERSION,context_hash=access.version,evidence_hash=access.opp['evidence_hash'],quality=quality,review_failed=not passed,commercial_plan=plan,commercial_review=review,recipient=plan['recipient'],reassess_at=(datetime.now(timezone.utc)+timedelta(days=plan['reassess_days'])).isoformat() if plan['reassess_days'] else None)
            if quality:result['quality']={**quality,'proposal_hash':proposal_fingerprint(result)}
            return result
    return await asyncio.wait_for(execute(),timeout=settings.investigation_timeout_seconds)
