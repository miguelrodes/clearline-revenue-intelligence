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
