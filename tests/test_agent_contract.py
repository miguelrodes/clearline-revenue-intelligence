import asyncio,json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from clearline.agent import analyze,RecoveryDecision,RecoveryProposal,QualityReview,QualityFailure
from clearline.evidence import EvidenceAccess

@pytest.mark.parametrize('followup',[False,True])
@pytest.mark.parametrize('schema_repair',[False,True])
def test_real_sdk_tools_review_and_unmodified_email(store,settings,opportunity,decision,monkeypatch,followup,schema_repair):
    import agents
    from agents.tool_context import ToolContext
    monkeypatch.setenv('OPENAI_API_KEY','test-only-not-a-real-key')
    monkeypatch.setattr(EvidenceAccess,'source',lambda self,name:[])
    proposal={**decision,'strategy':'support-led purchasing handoff','action_scope':'clarification','citations':[{'ref':'account','kind':'source_fact','claim':'Contact may have changed'}]}
    names=[]
    async def boundary(agent,*args,**kwargs):
        names.append(agent.name)
        if agent.output_type is QualityReview:
            return SimpleNamespace(final_output=QualityReview(passed=True,evidence_coverage=5,commercial_specificity=5,personalization=5,appropriateness=5,conversation_progress=5,uncertainty_handling=5,factuality=5,issues=[],strengths=['Grounded contact question']))
        assert agent.output_type is RecoveryProposal
        if schema_repair and len(names)==1:
            from agents.exceptions import ModelBehaviorError
            raise ModelBehaviorError('Inconsistent proposed status')
        for name in ('get_account_overview','get_purchase_history','get_relationship_history','get_product_catalogue'):
            tool=next(t for t in agent.tools if t.name==name)
            args={'offset':0,'status':'all'} if name=='get_purchase_history' else {'offset':0} if name=='get_relationship_history' else {}
            ctx=ToolContext(context=None,tool_name=name,tool_call_id='test-call',tool_arguments=json.dumps(args),run_config=agents.RunConfig(tracing_disabled=True))
            data=await tool.on_invoke_tool(ctx,json.dumps(args));assert 'Error' not in data
        return SimpleNamespace(final_output=RecoveryProposal(**proposal),to_input_list=lambda:[])
    monkeypatch.setattr(agents.Runner,'run',AsyncMock(side_effect=boundary))
    store.queue_analysis('example',followup_of='previous' if followup else None);job=store.claim()
    value=asyncio.run(analyze(store,job,settings))
    assert value.body==decision['body'] and value.strategy=='support-led purchasing handoff'
    assert value.quality['passed'] and len(names)==(3 if schema_repair else 2) and names[0]!=names[-1]
    assert len(store.rows("SELECT * FROM events WHERE kind='evidence_retrieved'"))==4


def test_missing_retrieval_cannot_pass_even_if_reviewer_passes(store,settings,opportunity,decision,monkeypatch):
    import agents
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    async def boundary(agent,*args,**kwargs):
        value=QualityReview(passed=True,evidence_coverage=5,commercial_specificity=5,personalization=5,appropriateness=5,conversation_progress=5,uncertainty_handling=5,factuality=5,issues=[],strengths=[]) if agent.output_type is QualityReview else RecoveryProposal(**decision)
        return SimpleNamespace(final_output=value,to_input_list=lambda:[])
    monkeypatch.setattr(agents.Runner,'run',AsyncMock(side_effect=boundary))
    store.queue_analysis('example');job=store.claim()
    with pytest.raises(QualityFailure):asyncio.run(analyze(store,job,settings))
    assert len(store.rows("SELECT * FROM events WHERE kind='quality_review'"))==3
    assert not store.rows('SELECT * FROM drafts')


def test_typed_output_requires_evidence_and_real_draft(decision):
    decision['subject']=''
    with pytest.raises(ValueError):RecoveryDecision(**decision)

def test_unknown_evidence_reference_cannot_pass_schema(decision):
    decision['evidence_fields']=['imagined_external_claim']
    with pytest.raises(ValueError):RecoveryDecision(**decision)

def test_reasoning_setting_is_case_insensitive(settings):
    from dataclasses import replace
    assert replace(settings,reasoning=' HIGH ').reasoning=='high'


def test_followup_policy_is_shared_evidence_not_a_hidden_prompt(store,settings,opportunity,monkeypatch):
    from dataclasses import replace
    store.queue_analysis('example');job=store.claim()
    access=EvidenceAccess(store,job,replace(settings,followup_days=14))
    value=json.loads(access.overview())
    assert value['application_policy']['followup_days']==14
    assert 'workflow_policy' in access.refs
