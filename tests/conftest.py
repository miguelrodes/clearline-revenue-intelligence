import pytest
from clearline.config import Settings
from clearline.data import digest
from clearline.store import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "state.sqlite3", tmp_path)


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


@pytest.fixture
def opportunity(store):
    evidence = {"name":"Example County Jail","holds":[],"signals":[{"type":"inactivity"}],
                "crm_notes":"Contact may have changed","limits":["Fictional test data"]}
    item = {"id":"example","account_key":"MA|county_jail|example","name":"Example County Jail",
            "state":"MA","decline_cents":10000,"holds":[],"evidence":evidence,"evidence_hash":digest(evidence)}
    store.save_scan({"test_fixture":True},[item])
    return item


@pytest.fixture
def decision(store,opportunity):
    # Lightweight structured response fixture, exclusively for boundary tests.
    from test_commercial import certified
    return certified(store,opportunity["id"],{"decision":"pursue","rationale":"Verify a possible contact change.",
            "hypotheses":["Contact changed"],"evidence_fields":["crm_notes"],
            "unresolved_questions":["Who handles purchasing?"],"recommended_action":"Ask for the right contact",
            "subject":"Purchasing contact","body":"Could you confirm the right purchasing contact?"})


@pytest.fixture
def draft(store,opportunity,decision):
    store.queue_analysis(opportunity["id"])
    job = store.claim()
    store.save_analysis(job,decision)
    return store.rows("SELECT * FROM drafts")[0]

@pytest.fixture
def reply_decision():
    return {'decision':'pursue','intent':'training','opportunity_status':'support_needed','facts':[], 'products':[], 'contact':None,'channel':None,'uncertainties':[], 'rationale':'The customer needs training.','recommended_action':'Ask which shift needs support.','subject':'Training question','body':'Which shift needs support?'}
