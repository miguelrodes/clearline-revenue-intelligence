import json

from fastapi.testclient import TestClient

from clearline.api import create_app
from clearline.data import digest
from clearline.store import utcnow


def add_task(store, oid, task_id, title, reason, *, blocking=1):
    with store.connect(write=True) as con:
        con.execute(
            "INSERT INTO investigation_tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, oid, "fixture-context", title, "Account owner", reason,
             json.dumps(["crm_notes"]), blocking, "pending", utcnow()),
        )


def set_account_context(store, opportunity, name, crm_note, *, holds=None, account_key=None):
    item = dict(opportunity)
    item["name"] = name
    item["holds"] = list(holds or [])
    item["account_key"] = account_key or item["account_key"]
    item["evidence"] = {**item["evidence"], "name": name, "crm_notes": crm_note}
    item["evidence_hash"] = digest(item["evidence"])
    store.save_scan({"contact_clearance_fixture": True}, [item])
    return item


def api_for(settings):
    return TestClient(create_app(settings), headers={"X-Clearline-Client": "web"})


def verified_payload(task_id=None, *, route="direct", distributor=""):
    return {
        "task_id": task_id,
        "contact_name": "Morgan Reyes",
        "recipient": "morgan.reyes@example.test",
        "role": "Purchasing coordinator",
        "phone": "555-0104",
        "route": route,
        "distributor": distributor,
        "verification_evidence": "Account owner confirmed the current buyer and route during a recorded internal review.",
        "verified": True,
    }


def legacy_context_hash(con, oid):
    """The contact-clearance schema must preserve hashes from the prior engine context."""
    from clearline.data import digest
    from clearline.action_policy import SOFT_HOLDS
    o=con.execute('SELECT evidence_hash,holds FROM opportunities WHERE id=?',(oid,)).fetchone()
    material={'evidence_hash':o['evidence_hash'] if o else None}
    holds=set(json.loads(o['holds'])) if o else set()
    if 'possible_missing_state_alias' in holds and not holds-SOFT_HOLDS:
        material['execution_policy_revision']='missing-state-neutral-support-v1'
    for table,fields in [('messages','id,direction,subject,body,reply_to'),('outcomes','id,kind,note,amount_cents,reference'),('customer_context','contact,channel,outreach_policy')]:
        material[table]=[dict(r) for r in con.execute(f'SELECT {fields} FROM {table} WHERE opportunity_id=? ORDER BY rowid',(oid,))]
    for table,fields in [('contact_authorizations','recipient,role,route,evidence,authorized,updated_at'),('investigation_resolutions','task_id,resolution,updated_at')]:
        material[table]=[dict(r) for r in con.execute(f'SELECT {fields} FROM {table} WHERE opportunity_id=? ORDER BY rowid',(oid,))]
    epoch=con.execute('SELECT value FROM controls WHERE name=?',('reassessment:'+oid,)).fetchone()
    material['reassessment_epoch']=epoch['value'] if epoch else None
    return digest(material)


def test_empty_contact_clearance_schema_preserves_cached_assessment_hash(store, opportunity):
    from clearline.evidence import ENGINE_VERSION, context_hash, current_assessment
    with store.connect() as con:
        prior_hash=legacy_context_hash(con,opportunity['id'])
        assessment={'engine_version':ENGINE_VERSION,'context_hash':prior_hash}
        assert context_hash(con,opportunity['id'])==prior_hash
        assert current_assessment(con,opportunity['id'],assessment)


def test_lone_tree_partial_contact_is_saved_without_clearing_hold_or_authorizing(settings, store, opportunity):
    from clearline.evidence import context_hash

    set_account_context(store, opportunity, "ID DOC – Lone Tree", "Captain retired - new contact TBD.")
    add_task(store, "example", "contact-lone-tree", "Identify current purchasing contact",
             "The CRM says the captain retired; the current buyer is not identified.")
    api = api_for(settings)
    with store.connect() as con:
        context_before = context_hash(con, "example")

    response = api.post("/api/accounts/example/contact-clearance", json={
        "task_id": "contact-lone-tree", "contact_name": "Purchasing office",
        "recipient": "buyer@example.test", "route": "direct", "verified": False,
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "partial"
    assert response.json()["task_status"] == "pending"
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='contact-lone-tree'")[0]["status"] == "pending"
    assert store.rows("SELECT * FROM contact_authorizations") == []
    note = api.get("/api/accounts/example/commercial-work").json()["contact_clearance"]
    assert note["contact_name"] == "Purchasing office"
    assert note["verification_evidence"] == ""
    assert store.rows("SELECT * FROM jobs") == []
    with store.connect() as con:
        assert context_hash(con, "example") == context_before
    assert api.post("/api/investigations/contact-lone-tree/resolve", json={"resolution": "I entered an email address."}).status_code == 409


def test_verified_contact_resolves_only_selected_contact_task_and_reassesses_once(settings, store, opportunity):
    set_account_context(store, opportunity, "ID DOC – Lone Tree", "Captain retired - new contact TBD.")
    add_task(store, "example", "contact-lone-tree", "Identify current purchasing contact",
             "The CRM says the captain retired; the current buyer is not identified.")
    add_task(store, "example", "order-lone-tree", "Check open purchase order",
             "Confirm whether order 1004 was fulfilled or canceled.")
    api = api_for(settings)

    response = api.post("/api/accounts/example/contact-clearance", json=verified_payload("contact-lone-tree"))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert response.json()["task_status"] == "resolved"
    assert response.json()["requires_reassessment"] is True
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='contact-lone-tree'")[0]["status"] == "resolved"
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='order-lone-tree'")[0]["status"] == "pending"
    remaining = api.get("/api/accounts/example/commercial-work").json()["tasks"]
    assert "contact-lone-tree" not in {task["id"] for task in remaining}
    assert "order-lone-tree" in {task["id"] for task in remaining}
    assert store.rows("SELECT recipient,route,authorized FROM contact_authorizations WHERE opportunity_id='example'") == [
        {"recipient": "morgan.reyes@example.test", "route": "direct", "authorized": 1}
    ]
    assert len(store.rows("SELECT * FROM jobs WHERE kind='analyze'")) == 1
    assert store.rows("SELECT * FROM drafts") == []
    assert store.rows("SELECT * FROM approvals") == []
    assert store.rows("SELECT * FROM outbox") == []
    stale = api.post("/api/accounts/example/contact-clearance", json=verified_payload("contact-lone-tree"))
    assert stale.status_code == 409
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='order-lone-tree'")[0]["status"] == "pending"

    # Saving the exact same verified facts is idempotent and does not create another paid run.
    repeated = api.post("/api/accounts/example/contact-clearance", json=verified_payload())
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["requires_reassessment"] is False
    assert len(store.rows("SELECT * FROM jobs WHERE kind='analyze'")) == 1


def test_distributor_account_requires_distributor_route_and_never_clears_by_direct_contact(settings, store, opportunity):
    set_account_context(store, opportunity, "Range Line-served agency", "Purchases may continue through Range Line.",
                        holds=["known_distributor_channel"])
    add_task(store, "example", "channel-contact", "Confirm purchasing contact and route",
             "Current buyer and distributor route need verification.")
    api = api_for(settings)

    direct = api.post("/api/accounts/example/contact-clearance", json=verified_payload("channel-contact"))
    assert direct.status_code == 409
    assert store.rows("SELECT * FROM contact_authorizations") == []
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='channel-contact'")[0]["status"] == "pending"

    routed = api.post("/api/accounts/example/contact-clearance", json=verified_payload(
        "channel-contact", route="distributor", distributor="Range Line"))
    assert routed.status_code == 200, routed.text
    assert store.rows("SELECT route,authorized FROM contact_authorizations WHERE opportunity_id='example'") == [
        {"route": "distributor", "authorized": 1}
    ]
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='channel-contact'")[0]["status"] == "resolved"


def test_customer_match_check_is_not_resolved_by_contact_authorization(settings, store, opportunity):
    set_account_context(store, opportunity, "Alias-conflicted account", "Two possible location matches.")
    add_task(store, "example", "match-check", "Resolve customer match",
             "The supplied name may refer to more than one institution.")
    api = api_for(settings)
    response = api.post("/api/accounts/example/contact-clearance", json=verified_payload("match-check"))
    assert response.status_code == 200, response.text
    assert response.json()["authorized"] is True
    assert response.json()["task_status"] == "pending"
    assert store.rows("SELECT status FROM investigation_tasks WHERE id='match-check'")[0]["status"] == "pending"
    assert store.rows("SELECT * FROM investigation_resolutions WHERE task_id='match-check'") == []


def test_saved_contact_note_invalidates_draft_that_used_older_context(settings, store, opportunity, draft):
    from clearline.reporting import valid_draft

    assert valid_draft(store, draft)
    api = api_for(settings)
    response = api.post("/api/accounts/example/contact-clearance", json={
        "contact_name": "Verified purchasing office",
        "recipient": "buyer@example.org", "role": "Purchasing", "route": "direct",
        "verification_evidence": "Explicit fictional test authorization", "verified": False,
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "partial"
    assert response.json()["authorized"] is True
    assert store.rows("SELECT authorized FROM contact_authorizations WHERE opportunity_id='example'")[0]["authorized"] == 1
    assert valid_draft(store, draft)

    verified = api.post("/api/accounts/example/contact-clearance", json={
        "contact_name": "Verified purchasing office",
        "recipient": "buyer@example.org", "role": "Purchasing", "route": "direct",
        "verification_evidence": "Explicit fictional test authorization", "verified": True,
    })
    assert verified.status_code == 200, verified.text
    assert verified.json()["requires_reassessment"] is True
    assert not valid_draft(store, draft)
    assert store.rows("SELECT * FROM approvals") == []
