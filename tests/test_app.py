from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_control_panel_renders_without_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv("CLEARLINE_DB_PATH",str(tmp_path/"ui.sqlite3"))
    monkeypatch.setenv("OPENAI_API_KEY","")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    assert any("OPENAI_API_KEY" in item.value for item in app.info)
    next(b for b in app.button if b.label=="Run recovery scan").click().run()
    assert not app.exception


def test_unsaved_draft_edits_cannot_be_approved(store,settings,draft,monkeypatch):
    monkeypatch.setenv("CLEARLINE_DB_PATH",str(settings.db_path))
    monkeypatch.setenv("OPENAI_API_KEY","")
    # Use the real persisted draft from the test-only SDK boundary fixture.
    with store.connect(write=True) as con:
        con.execute("DELETE FROM scans")
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    next(x for x in app.text_input if x.label=="Subject").set_value("Unsaved subject")
    next(x for x in app.button if x.label=="Approve for simulated outbox").click().run()
    assert not app.exception
    assert any("Save your edits first" in e.value for e in app.error)
    assert not store.rows("SELECT * FROM approvals")
    assert store.rows("SELECT status FROM drafts")[0]["status"]=="awaiting_approval"


def test_review_screen_tracks_human_approval_and_delivery(store,settings,draft,monkeypatch):
    from clearline.worker import run_one
    monkeypatch.setenv("CLEARLINE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    assert any("Your review is needed" in item.value for item in app.info)
    next(b for b in app.button if b.label=="Approve for simulated outbox").click().run()
    assert not app.exception
    assert any("Approved — waiting" in item.value for item in app.info)
    assert len(store.rows("SELECT * FROM approvals")) == 1
    run_one(store, settings)  # Only the explicitly approved test simulation; no model call.
    app.run()
    assert not app.exception
    assert any("Outreach simulated — no action needed now" in item.value for item in app.success)
    assert any("Next follow-up:" in item.value for item in app.info)
    assert not [b for b in app.button if b.label=="Approve for simulated outbox"]
    assert len(store.rows("SELECT * FROM outbox")) == 1


def test_changed_evidence_offers_reassessment_instead_of_stale_approval(store,settings,draft,opportunity,monkeypatch):
    monkeypatch.setenv("CLEARLINE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    opportunity["evidence_hash"] = "new-evidence"
    store.save_scan({}, [opportunity])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    assert any("Purchase evidence has changed" in item.value for item in app.warning)
    assert not [b for b in app.button if b.label=="Approve for simulated outbox"]
    next(b for b in app.button if b.label=="Analyze account & prepare email").click().run()
    assert not app.exception
    assert any("Agent work in progress" in item.value for item in app.info)
    assert not store.rows("SELECT * FROM approvals")
    assert store.rows("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'")[0]["n"] == 1


def test_navigation_separates_workflow_from_monitoring(store,settings,draft,monkeypatch):
    monkeypatch.setenv("CLEARLINE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    assert not app.exception
    assert [t.value for t in app.title] == ["Customer Recovery Agent"]
    assert [h.value for h in app.header] == ["1. Find recovery opportunities", "2. Review an account", "3. Approve outreach", "4. Track follow-up & results"]
    assert not any("Demo mode" in x.value for x in app.caption)
    for path, title in [("views/activity.py", "Agent activity"), ("views/outreach.py", "Outreach history")]:
        app.switch_page(path).run()
        assert not app.exception
        assert [t.value for t in app.title] == [title]
        assert not [b for b in app.button if b.label=="Approve for simulated outbox"]
    assert not store.rows("SELECT * FROM approvals")
    assert not store.rows("SELECT * FROM outbox")
