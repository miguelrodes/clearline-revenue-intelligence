import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clearline.prospect_agent import (ResearchBundle, Qualification, allowed_url,
    validate_research, validate_qualification, research_prospect)
from clearline.prospects import PROSPECTS, seed_prospects
from clearline.store import Store
from clearline.worker import run_one


@pytest.fixture
def bundle():
    return ResearchBundle(sources=[
        {"id":"S1","title":"Institutional incident","url":"https://www.pa.gov/incident","published_date":"2026-02-17","category":"institution"},
        {"id":"S2","title":"Manufacturer product","url":"https://swabtek.com/product","published_date":None,"category":"product"},
        {"id":"S3","title":"Procurement route","url":"https://www.pa.gov/purchasing","published_date":None,"category":"procurement"},
    ],facts=[
        {"statement":"Official report of contraband on paper.","source_ids":["S1"]},
        {"statement":"Manufacturer describes presumptive screening of items; confirmation required.","source_ids":["S2"]},
    ],unknowns=["Current buying intent and relationship are unknown."])


@pytest.fixture
def research(bundle):
    return validate_research(bundle,{s.url for s in bundle.sources},PROSPECTS[0]["allowed_domains"],"2026-11-01")


@pytest.fixture
def prospect(store,settings):
    return seed_prospects(store,settings.as_of)[0]


@pytest.fixture
def report():
    return Qualification(decision="pursue",rationale="Investigate fit, without assuming demand.",
        qualification="discovery_only",operational_need={"statement":"Paper screening may be relevant.","source_ids":["S1"]},
        product_fit={"statement":"Presumptive screening; validation needed.","source_ids":["S2"]},
        purchasing_process={"statement":"Verify the formal route.","source_ids":["S3"]},
        channel="direct_discovery",channel_reasoning={"statement":"Start with workflow questions.","source_ids":["S3"]},
        alternative_route="Use an authorized distributor if confirmed.",target_role="Security and procurement lead",
        customer_relationship="unknown",hypotheses=["An evaluation could test fit."],evidence_fields=["S1","S2","S3"],
        unresolved_questions=["Is there an unmet need?"],recommended_action="Human review before simulation.",
        subject="Screening workflow discussion",body="Who handles evaluation of paper screening tools?")


def test_public_identity_never_merges_with_case_scan(store,settings,opportunity,prospect):
    seed_prospects(store,settings.as_of)
    store.save_scan({},[opportunity])
    assert store.opportunity(prospect)["active"] == 1
    assert store.opportunity(prospect)["workflow"] == "prospecting"
    assert store.opportunity("example")["workflow"] == "recovery"
    assert len(store.rows("SELECT * FROM opportunities WHERE workflow='prospecting'")) == 2
    with pytest.raises(ValueError): store.queue_prospect("example")


def test_research_requires_observed_allowed_sources(bundle):
    with pytest.raises(ValueError,match="provider"):
        validate_research(bundle,set(),["pa.gov","swabtek.com"],"2026-11-01")
    assert not allowed_url("https://pa.gov.evil.example/page",["pa.gov"])
    assert not allowed_url("https://127.0.0.1/page",["pa.gov"])
    assert not allowed_url("javascript:alert(1)",["pa.gov"])


def test_cutoff_and_undated_context_are_distinct(bundle,research):
    assert research["sources"][0]["temporal_status"]=="dated_on_or_before_cutoff"
    assert research["sources"][1]["temporal_status"]=="undated_current_context"
    bundle.sources[0].published_date="2026-11-02"
    with pytest.raises(ValueError,match="cutoff"):
        validate_research(bundle,{s.url for s in bundle.sources},["pa.gov","swabtek.com"],"2026-11-01")


def test_unknown_fact_reference_rejected(bundle):
    bundle.facts[0].source_ids=["invented"]
    with pytest.raises(ValueError,match="unknown source"):
        validate_research(bundle,{s.url for s in bundle.sources},["pa.gov","swabtek.com"],"2026-11-01")


def test_qualification_grounding(report,research):
    validate_qualification(report,{"research":research})
    report.product_fit.source_ids=["S1"]
    with pytest.raises(ValueError,match="manufacturer"):
        validate_qualification(report,{"research":research})


def test_schema_rejects_descriptive_source_paths(report):
    payload=report.model_dump()
    payload["evidence_fields"]=["research.sources.S1"]
    with pytest.raises(ValueError): Qualification.model_validate(payload)


def test_product_evidence_must_be_manufacturer_hosted(bundle):
    bundle.sources[0].category="product"
    with pytest.raises(ValueError,match="manufacturer"):
        validate_research(bundle,{s.url for s in bundle.sources},["pa.gov","swabtek.com"],"2026-11-01")


def test_research_persistence_restarts_then_shared_approval(store,settings,prospect,research,report):
    jid=store.queue_prospect(prospect)
    assert store.queue_prospect(prospect)==jid
    store.save_prospect_research(store.claim(),research)
    restarted=Store(settings.db_path)
    assert len(restarted.rows("SELECT * FROM research_sources"))==3
    assert restarted.queue_prospect(prospect)==jid
    job=restarted.claim()
    assert job["kind"]=="prospect_qualify"
    restarted.save_analysis(job,report)
    draft=restarted.rows("SELECT * FROM drafts")[0]
    assert draft["status"]=="awaiting_approval"
    assert not restarted.rows("SELECT * FROM approvals")
    assert not restarted.rows("SELECT * FROM outbox")
    restarted.decide(draft["id"],True)  # Explicit human-decision boundary in this test only.
    run_one(restarted,settings)
    assert restarted.rows("SELECT delivery_mode FROM outbox")[0]["delivery_mode"]=="simulated"
    followup=restarted.rows("SELECT * FROM jobs WHERE kind='followup'")[0]
    followup_job=restarted.queue_analysis(prospect,followup_of=draft["id"])
    assert restarted.rows("SELECT kind FROM jobs WHERE id=?",(followup_job,))[0]["kind"]=="prospect_qualify"
    restarted.record_outcome(prospect,"opt_out","Synthetic stop test")
    assert restarted.rows("SELECT status FROM jobs WHERE id=?",(followup["id"],))[0]["status"]=="cancelled"


def test_cancellation_cannot_publish_research_or_qualification(store,prospect,research):
    jid=store.queue_prospect(prospect)
    job=store.claim()
    store.cancel_job(jid)
    store.save_prospect_research(job,research)
    assert not store.rows("SELECT * FROM research_sources")
    assert not store.rows("SELECT * FROM jobs WHERE kind='prospect_qualify'")


def test_recovery_identity_cannot_reach_web(store,settings,opportunity,monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-only-not-real")
    store.queue_analysis("example")
    with pytest.raises(ValueError,match="fictional"):
        asyncio.run(research_prospect(store,store.claim(),settings))


def test_live_tool_contract_is_bounded_and_records_sources(store,settings,prospect,bundle,monkeypatch):
    import agents
    monkeypatch.setenv("OPENAI_API_KEY","test-only-not-real")
    async def boundary(agent,*args,**kwargs):
        assert agent.model_settings.extra_args["max_tool_calls"] == 6
        assert kwargs["max_turns"] == 1
        assert agent.tools[0].filters.allowed_domains == PROSPECTS[0]["allowed_domains"]
        return SimpleNamespace(final_output=bundle,context_wrapper=SimpleNamespace(usage=SimpleNamespace(input_tokens=10,output_tokens=20,requests=1)),
            raw_responses=[SimpleNamespace(output=[{"type":"web_search_call","id":"test-search","status":"completed",
                "action":{"type":"search","sources":[{"url":s.url} for s in bundle.sources]}}])])
    monkeypatch.setattr(agents.Runner,"run",AsyncMock(side_effect=boundary))
    store.queue_prospect(prospect)
    result=asyncio.run(research_prospect(store,store.claim(),settings))
    assert len(result["sources"])==3
    assert store.rows("SELECT * FROM events WHERE kind='model_usage'")


def test_both_workflows_render_with_independent_approval_controls(store,settings,draft,prospect,research,report,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("CLEARLINE_DB_PATH",str(settings.db_path))
    monkeypatch.setenv("OPENAI_API_KEY","")
    store.queue_prospect(prospect)
    store.save_prospect_research(store.claim(),research)
    store.save_analysis(store.claim(),report)
    with store.connect(write=True) as con: con.execute("DELETE FROM scans")
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    assert len([b for b in app.button if b.label=="Approve for simulated outbox"])==2
    assert len(next(s for s in app.selectbox if s.label=="Account").options)==1
    assert len(next(s for s in app.selectbox if s.label=="Real prospect").options)==2
    [t for t in app.text_input if t.label=="Subject"][-1].set_value("Unsaved prospect edit")
    [b for b in app.button if b.label=="Approve for simulated outbox"][-1].click().run()
    assert not app.exception
    assert any("Save your edits first" in e.value for e in app.error)
    assert not store.rows("SELECT * FROM approvals")
