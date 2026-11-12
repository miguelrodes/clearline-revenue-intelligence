"""One independently running local worker. SQLite contains all schedules and jobs."""
import asyncio
from contextlib import contextmanager
import fcntl
import logging
import time
from .agent import MissingCredentials, analyze
from .data import ScanPolicy, scan
from .store import Store, STOPPED_STATUSES
from .prospect_agent import research_prospect, qualify_prospect

log = logging.getLogger(__name__)


@contextmanager
def worker_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A worker already owns this database") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_one(store, settings, analyst=analyze):
    if store.paused(): return False
    store.tick()
    job = store.claim()
    if not job: return False
    store.event("job_started", {"kind":job["kind"]}, job["id"], job["opportunity_id"])
    try:
        if job["kind"] == "scan":
            overrides = job["payload"].get("policy", {})
            policy = ScanPolicy(**{"as_of":settings.as_of, **overrides})
            summary, items = scan(settings.data_dir, policy)
            store.save_scan(summary, items)
            # One new case by default protects model spend; scans never regenerate existing drafts.
            remaining = max(0, min(3, int(job["payload"].get("analysis_limit", 1))))
            for item in items:
                if remaining == 0: break
                opp = store.opportunity(item["id"])
                if not opp["holds"] and opp["status"] == "needs_review":
                    store.queue_analysis(opp["id"])
                    remaining -= 1
        elif job["kind"] in ("analyze", "prospect_qualify", "prospect_research"):
            opp = store.opportunity(job["opportunity_id"])
            if opp["holds"] or not opp["active"] or opp["evidence_hash"] != job["payload"]["evidence_hash"] or opp["status"] in STOPPED_STATUSES:
                store.finish(job["id"], "cancelled", "Opportunity changed or requires review")
                return True
            if job["kind"] == "prospect_research":
                result = asyncio.run(research_prospect(store, job, settings))
                store.save_prospect_research(job, result)
            else:
                runner = qualify_prospect if job["kind"] == "prospect_qualify" else analyst
                result = asyncio.run(runner(store, job, settings))
                store.save_analysis(job, result)
        elif job["kind"] == "deliver":
            store.deliver(job, settings.followup_days)
        elif job["kind"] == "followup":
            opp = store.opportunity(job["opportunity_id"])
            if opp["status"] != "awaiting_response" or not opp["active"] or opp["holds"]:
                store.finish(job["id"], "cancelled", "Follow-up no longer appropriate")
                return True
            store.queue_analysis(opp["id"], job["payload"]["parent_draft_id"])
        else:
            raise ValueError("Unknown job kind")
        store.finish(job["id"])
        saved = store.rows("SELECT status FROM jobs WHERE id=?", (job["id"],))[0]["status"]
        store.event("job_"+saved, {"kind":job["kind"]}, job["id"], job["opportunity_id"])
    except MissingCredentials as exc:
        store.finish(job["id"], "blocked_config", str(exc))
        store.event("configuration_required", {"variable":"OPENAI_API_KEY"}, job["id"],job["opportunity_id"])
    except Exception as exc:
        # Never persist provider exception bodies, which may echo confidential request input.
        status = getattr(exc,"status_code",None)
        code = getattr(exc,"code",None)
        # Status/code are sufficient to diagnose auth, quota and unsupported models without request bodies.
        safe = str(exc) if isinstance(exc, ValueError) and not type(exc).__module__.startswith("pydantic") else f"{type(exc).__name__} (status={status}, code={code}): review access, limits or configuration, then retry explicitly"
        store.finish(job["id"], "failed", safe)
        store.event("job_failed", {"error_type":type(exc).__name__,"message":safe}, job["id"],job["opportunity_id"])
        log.error("Job %s failed: %s",job["id"],type(exc).__name__)
    return True


def run(settings, once=False):
    store = Store(settings.db_path)
    with worker_lock(settings.db_path):
        store.recover_interrupted()
        try:
            while True:
                store.heartbeat("paused" if store.paused() else "running")
                did_work = run_one(store, settings)
                if once: return
                if not did_work: time.sleep(1)
        finally:
            store.heartbeat("stopped")
