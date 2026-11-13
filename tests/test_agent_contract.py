import asyncio,json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from clearline.agent import analyze,RecoveryDecision,QualityReview
from clearline.commercial_agent import Strategy,DecisionReview,Communication
from clearline.evidence import EvidenceAccess
from test_commercial import good_review

@pytest.mark.parametrize('contact',[True,False])
@pytest.mark.parametrize('schema_repair',[False,True])
def test_strategy_review_precedes_email_and_no_action_has_no_draft(store,settings,opportunity,decision,monkeypatch,contact,schema_repair):
    import agents
    from agents.tool_context import ToolContext
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    monkeypatch.setattr(EvidenceAccess,'source',lambda self,name:[])
    stages=[]
    plan=dict(outcome='contact' if contact else 'no_action',capability='inactive_recovery',objective='Recover established supply relationship' if contact else 'Avoid unnecessary contact',timing='Documented purchase gap' if contact else 'Recent purchase',intervention='Ask about upcoming supplies' if contact else 'Monitor',rationale='Fixture commercial decision',alternatives=[{'approach':'monitor','reason':'Compared timing'}],change_conditions=['New customer information'],recipient='buyer@example.org' if contact else '',route='direct' if contact else 'none',action_scope='recovery' if contact else 'none',verification_tasks=[],signal_decisions=[],citations=[dict(ref='account',kind='source_fact',claim='Fixture')],reassess_days=30)
    async def boundary(agent,*args,**kwargs):
        stages.append(agent.output_type)
        if schema_repair and len(stages)==1:
            from agents.exceptions import ModelBehaviorError
            raise ModelBehaviorError('Invalid schema')
        if agent.output_type is Strategy:
            for name in ('get_account_overview','get_purchase_history','get_relationship_history','get_product_catalogue','investigate_identity'):
                tool=next(t for t in agent.tools if t.name==name);params={'offset':0,'status':'all'} if name=='get_purchase_history' else {'offset':0} if name=='get_relationship_history' else {}
                ctx=ToolContext(context=None,tool_name=name,tool_call_id='test',tool_arguments=json.dumps(params),run_config=agents.RunConfig(tracing_disabled=True))
                await tool.on_invoke_tool(ctx,json.dumps(params))
            value=Strategy(**plan)
        elif agent.output_type is DecisionReview:value=DecisionReview(**good_review())
        elif agent.output_type is Communication:value=Communication(subject=decision['subject'],body=decision['body'])
        else:value=QualityReview(passed=True,evidence_coverage=5,commercial_specificity=5,personalization=5,appropriateness=5,conversation_progress=5,uncertainty_handling=5,factuality=5,issues=[],strengths=['Fixture'])
        return SimpleNamespace(final_output=value,to_input_list=lambda:[])
    monkeypatch.setattr(agents.Runner,'run',AsyncMock(side_effect=boundary));store.queue_analysis('example');j=store.claim()
    result=asyncio.run(analyze(store,j,settings))
    assert stages.index(DecisionReview)>stages.index(Strategy)
    assert bool(result.body)==contact
    if contact:assert stages.index(Communication)>stages.index(DecisionReview)
    else:assert Communication not in stages

def test_strategy_contract_does_not_require_email(decision):
    decision['subject']='';decision['body']='';RecoveryDecision(**decision)

def test_unknown_evidence_reference_cannot_pass_schema(decision):
    decision['evidence_fields']=['imagined_external_claim']
    with pytest.raises(ValueError):RecoveryDecision(**decision)

def test_reasoning_setting_is_case_insensitive(settings):
    from dataclasses import replace
    assert replace(settings,reasoning=' HIGH ').reasoning=='high'
