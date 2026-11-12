import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from clearline.agent import analyze, RecoveryDecision


@pytest.mark.parametrize("followup", [False, True])
def test_real_sdk_agent_construction_and_tool_contract(store,settings,opportunity,decision,monkeypatch,followup):
    import agents
    from agents.tool_context import ToolContext
    monkeypatch.setenv("OPENAI_API_KEY","test-only-not-a-real-key")
    async def sdk_boundary(agent,*args,**kwargs):
        assert agent.output_type is RecoveryDecision
        tool = next(t for t in agent.tools if t.name=="get_account_evidence")
        context = ToolContext(context=None,tool_name=tool.name,tool_call_id="test-call",tool_arguments="{}",run_config=agents.RunConfig(tracing_disabled=True))
        evidence = await tool.on_invoke_tool(context,"{}")
        assert "Contact may have changed" in evidence
        return SimpleNamespace(final_output=RecoveryDecision(**decision),context_wrapper=SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10,output_tokens=10,requests=1)))
    monkeypatch.setattr(agents.Runner,"run",AsyncMock(side_effect=sdk_boundary))
    store.queue_analysis("example",followup_of="previous-draft" if followup else None)
    job=store.claim()
    if followup:
        with pytest.raises(ValueError,match="previous outreach"):
            asyncio.run(analyze(store,job,settings))
    else:
        result=asyncio.run(analyze(store,job,settings))
        assert result.decision=="pursue"
    assert store.rows("SELECT * FROM events WHERE kind='model_usage'")


def test_typed_output_requires_evidence_and_real_draft(decision):
    decision["subject"]=""
    with pytest.raises(ValueError): RecoveryDecision(**decision)


def test_unknown_evidence_reference_cannot_pass_schema(decision):
    decision["evidence_fields"]=["imagined_external_claim"]
    with pytest.raises(ValueError): RecoveryDecision(**decision)


def test_reasoning_setting_is_case_insensitive(settings):
    from dataclasses import replace
    assert replace(settings,reasoning=" HIGH ").reasoning=="high"
