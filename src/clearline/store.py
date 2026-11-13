"""SQLite is the source of truth for workflow state and simulated actions."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import sqlite3
from uuid import uuid4
from .data import digest


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities(
 id TEXT PRIMARY KEY, account_key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, state TEXT NOT NULL,
 decline_cents INTEGER NOT NULL, evidence TEXT NOT NULL, evidence_hash TEXT NOT NULL,
 holds TEXT NOT NULL, status TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, opportunity_id TEXT, dedupe_key TEXT UNIQUE,
 payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', due_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT, error TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS due_jobs ON jobs(status,due_at);
CREATE TABLE IF NOT EXISTS schedules(
 name TEXT PRIMARY KEY, interval_seconds INTEGER NOT NULL CHECK(interval_seconds>0),
 next_run TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id), version INTEGER NOT NULL,
 evidence_hash TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
 status TEXT NOT NULL, analysis TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(opportunity_id,version));
CREATE TABLE IF NOT EXISTS approvals(
 id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id), snapshot_hash TEXT NOT NULL,
 decision TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(
 id TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE REFERENCES drafts(id), opportunity_id TEXT NOT NULL,
 recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
 delivery_mode TEXT NOT NULL CHECK(delivery_mode='simulated'), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outcomes(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id), kind TEXT NOT NULL,
 note TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, job_id TEXT, opportunity_id TEXT, kind TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_kind_job ON events(kind,job_id);
CREATE INDEX IF NOT EXISTS events_account_kind ON events(opportunity_id,kind,id);
CREATE TABLE IF NOT EXISTS controls(name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worker_state(id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prospect_research(
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 evidence_hash TEXT NOT NULL, bundle TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_sources(
 job_id TEXT NOT NULL REFERENCES prospect_research(job_id), source_id TEXT NOT NULL,
 opportunity_id TEXT NOT NULL REFERENCES opportunities(id), title TEXT NOT NULL, url TEXT NOT NULL,
 published_date TEXT, retrieved_at TEXT NOT NULL, temporal_status TEXT NOT NULL, provenance TEXT NOT NULL,
 PRIMARY KEY(job_id,source_id));
"""


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            from .operations import SCHEMA as OPERATIONS_SCHEMA
            con.executescript(OPERATIONS_SCHEMA)
            opportunity_columns = {r["name"] for r in con.execute("PRAGMA table_info(opportunities)")}
            if "workflow" not in opportunity_columns:
                con.execute("ALTER TABLE opportunities ADD COLUMN workflow TEXT NOT NULL DEFAULT 'recovery'")
            columns = {r["name"] for r in con.execute("PRAGMA table_info(outcomes)")}
            if "amount_cents" not in columns:
                con.execute("ALTER TABLE outcomes ADD COLUMN amount_cents INTEGER")
            if "reference" not in columns:
                con.execute("ALTER TABLE outcomes ADD COLUMN reference TEXT")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS outcome_reference ON outcomes(opportunity_id,kind,reference) WHERE reference IS NOT NULL")

            from .conversations import migrate
            migrate(con)
            from .service_access import SCHEMA as ACCESS_SCHEMA
            con.executescript(ACCESS_SCHEMA)
            from .evidence import SCHEMA as EVIDENCE_SCHEMA
            con.executescript(EVIDENCE_SCHEMA)
            from .commercial import SCHEMA as COMMERCIAL_SCHEMA
            con.executescript(COMMERCIAL_SCHEMA)
            from .screening import SCHEMA as SCREENING_SCHEMA
            con.executescript(SCREENING_SCHEMA)

    def heartbeat(self, state):
        with self.connect(write=True) as con:
            con.execute("INSERT INTO worker_state VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,seen_at=excluded.seen_at", (state,utcnow()))

    def set_paused(self, paused):
        with self.connect(write=True) as con:
            con.execute("INSERT INTO controls VALUES('paused',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (str(int(paused)),))
            self.event("worker_paused" if paused else "worker_resumed", {}, con=con)

    def paused(self):
        value = self.rows("SELECT value FROM controls WHERE name='paused'")
        return bool(value and value[0]["value"] == "1")

    def cancel_job(self, jid):
        with self.connect(write=True) as con:
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=? AND status IN ('queued','running','blocked_config','failed')", (utcnow(),jid))
            self.event("job_cancelled", {"note":"An in-flight API call may finish; its result will not create a draft or action."}, job_id=jid, con=con)

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def rows(self, sql, params=()):
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql, params)]

    def opportunity(self, oid):
        rows = self.rows("SELECT * FROM opportunities WHERE id=?", (oid,))
        if not rows: raise ValueError("Opportunity not found")
        row = rows[0]
        row["evidence"] = json.loads(row["evidence"])
        row["holds"] = json.loads(row["holds"])
        return row

    def event(self, kind, details, job_id=None, opportunity_id=None, con=None):
        args = (job_id, opportunity_id, kind, json.dumps(details), utcnow())
        if con is not None:
            con.execute("INSERT INTO events(job_id,opportunity_id,kind,details,created_at) VALUES(?,?,?,?,?)", args)
        else:
            with self.connect(write=True) as c:
                c.execute("INSERT INTO events(job_id,opportunity_id,kind,details,created_at) VALUES(?,?,?,?,?)", args)

    def _enqueue(self, con, kind, payload, oid=None, key=None, due=None):
        jid = uuid4().hex
        con.execute("INSERT OR IGNORE INTO jobs(id,kind,opportunity_id,dedupe_key,payload,due_at,created_at) VALUES(?,?,?,?,?,?,?)",
                    (jid, kind, oid, key, json.dumps(payload), due or utcnow(), utcnow()))
        if key:
            return con.execute("SELECT id FROM jobs WHERE dedupe_key=?", (key,)).fetchone()["id"]
        return jid

    def enqueue(self, kind, payload, oid=None, key=None, due=None):
        with self.connect(write=True) as con:
            return self._enqueue(con, kind, payload, oid, key, due)

    def queue_analysis(self, oid, followup_of=None, investigation=False, allow_simulation=False):
        opp = self.opportunity(oid)
        if not opp["active"] or (not investigation and (opp["holds"] or opp["status"] in STOPPED_STATUSES)):
            raise ValueError("This opportunity is held, inactive, or already stopped")
        from .evidence import context_hash,ENGINE_VERSION
        with self.connect(write=True) as con:
            last=con.execute("SELECT details FROM events WHERE opportunity_id=? AND kind='agent_decision' ORDER BY id DESC LIMIT 1",(oid,)).fetchone()
            a=json.loads(last['details']) if last else {}
            if a.get('reassess_at') and a['reassess_at']<=utcnow():
                con.execute("INSERT INTO controls VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",('reassessment:'+oid,a['reassess_at']))
            revision=context_hash(con,oid)
        payload = {"context_hash":revision,"engine_version":ENGINE_VERSION,"evidence_hash": opp["evidence_hash"], "followup_of": followup_of, "portfolio": investigation, "allow_simulation": allow_simulation}
        kind = "prospect_qualify" if opp["workflow"] == "prospecting" else "analyze"
        if kind == "prospect_qualify" and not opp["evidence"].get("research"):
            return self.queue_prospect(oid)
        key = f"{kind}:{oid}:{revision}:{ENGINE_VERSION}:{followup_of or 'initial'}"
        return self.enqueue(kind, payload, oid, key)

    def add_prospect(self, profile, as_of):
        """Seed public leads without ever joining them to fictional case accounts."""
        if not profile["key"].startswith("real:"):
            raise ValueError("Real prospects require an independent identity namespace")
        oid = digest(profile["key"])[:20]
        evidence = {"provenance": "real_public_web", "as_of": as_of, "profile": profile,
                    "customer_relationship": "unknown", "research": None}
        with self.connect(write=True) as con:
            con.execute("""INSERT OR IGNORE INTO opportunities
                (id,account_key,name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at,workflow)
                VALUES(?,?,?,?,0,?,?,'[]','needs_research',1,?,'prospecting')""",
                (oid,profile["key"],profile["name"],profile["state"],json.dumps(evidence),digest(evidence),utcnow()))
        return oid

    def queue_prospect(self, oid):
        opp = self.opportunity(oid)
        if opp["workflow"] != "prospecting" or not opp["active"] or opp["holds"] or opp["status"] in STOPPED_STATUSES:
            raise ValueError("Public research requires an active, unstopped real prospect")
        # One discovery run per seeded prospect; failures are retried explicitly.
        return self.enqueue("prospect_research", {"evidence_hash":opp["evidence_hash"]}, oid, f"prospect_research:{oid}:v1")

    def save_prospect_research(self, job, research):
        """Persist sources and enqueue qualification atomically; never repeat research after a restart."""
        with self.connect(write=True) as con:
            opp = con.execute("SELECT * FROM opportunities WHERE id=?", (job["opportunity_id"],)).fetchone()
            current = con.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not current or current["status"] != "running" or not opp or not opp["active"] or opp["workflow"] != "prospecting" or opp["status"] in STOPPED_STATUSES or json.loads(opp["holds"]) or opp["evidence_hash"] != job["payload"]["evidence_hash"]:
                con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=? AND status='running'", (utcnow(),job["id"]))
                return
            evidence = json.loads(opp["evidence"])
            evidence["research"] = research
            evidence_hash = digest(evidence)
            con.execute("INSERT INTO prospect_research VALUES(?,?,?,?,?)",(job["id"],opp["id"],evidence_hash,json.dumps(research),utcnow()))
            for source in research["sources"]:
                con.execute("INSERT INTO research_sources VALUES(?,?,?,?,?,?,?,?,?)",(job["id"],source["id"],opp["id"],source["title"],source["url"],source["published_date"],source["retrieved_at"],source["temporal_status"],source["provenance"]))
            con.execute("UPDATE opportunities SET evidence=?,evidence_hash=?,status='researched',updated_at=? WHERE id=?",(json.dumps(evidence),evidence_hash,utcnow(),opp["id"]))
            self._enqueue(con,"prospect_qualify",{"evidence_hash":evidence_hash,"followup_of":None},opp["id"],f"prospect_qualify:{opp['id']}:{evidence_hash}:initial")
            con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job["id"]))
            self.event("research_saved",{"sources":len(research["sources"]),"evidence_hash":evidence_hash},job["id"],opp["id"],con=con)

    def save_scan(self, summary, opportunities):
        with self.connect(write=True) as con:
            sid = uuid4().hex
            con.execute("INSERT INTO scans VALUES(?,?,?)", (sid, utcnow(), json.dumps(summary)))
            con.execute("UPDATE opportunities SET active=0 WHERE workflow='recovery'")
            for o in opportunities:
                con.execute("""INSERT INTO opportunities
                    (id,account_key,name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,1,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name, state=excluded.state,
                    decline_cents=excluded.decline_cents,evidence=excluded.evidence,evidence_hash=excluded.evidence_hash,
                    holds=excluded.holds,active=1,updated_at=excluded.updated_at""",
                    (o["id"],o["account_key"],o["name"],o["state"],o["decline_cents"],json.dumps(o["evidence"]),
                     o["evidence_hash"],json.dumps(o["holds"]),"needs_review",utcnow()))
                con.execute('UPDATE commercial_signals SET active=0 WHERE opportunity_id=?',(o['id'],))
                for signal in o['evidence'].get('commercial_signals',[]):
                    encoded=json.dumps(signal['evidence'],sort_keys=True)
                    con.execute("""INSERT INTO commercial_signals VALUES(?,?,?,?,?,?,1,'pending',NULL,NULL,NULL,?)
                    ON CONFLICT(id) DO UPDATE SET active=1,evidence=excluded.evidence,amount_cents=excluded.amount_cents,
                    investigation_status=CASE WHEN commercial_signals.evidence!=excluded.evidence THEN 'pending' ELSE commercial_signals.investigation_status END,updated_at=excluded.updated_at""",
                    (signal['id'],o['id'],signal['category'],signal['trigger_key'],encoded,signal['amount_cents'],utcnow()))
                if 'owned_product_skus' in o:
                    con.execute('INSERT INTO controls VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',('purchased_skus:'+o['id'],json.dumps(o['owned_product_skus'])))
                from .commercial import refresh_message_signals
                refresh_message_signals(con,o['id'],utcnow())
            con.execute('UPDATE commercial_signals SET active=0 WHERE opportunity_id IN (SELECT id FROM opportunities WHERE active=0)')
            self.event("scan_completed", summary, con=con)

    def claim(self, kinds=None):
        with self.connect(write=True) as con:
            where = " AND j.kind IN ("+",".join("?" for _ in kinds)+")" if kinds else ""
            row = con.execute("""SELECT j.* FROM jobs j WHERE j.status='queued' AND j.due_at<=?
                AND NOT EXISTS (SELECT 1 FROM jobs active WHERE active.status='running' AND
                  (active.kind='scan' OR j.kind='scan' OR (j.opportunity_id IS NOT NULL AND active.opportunity_id=j.opportunity_id)))""" + where + " ORDER BY CASE j.kind WHEN 'deliver' THEN 0 WHEN 'revenue_brief' THEN 1 WHEN 'followup' THEN 2 WHEN 'prepare' THEN 3 ELSE 4 END,j.due_at,j.created_at,j.rowid LIMIT 1", (utcnow(),*(kinds or []))).fetchone()
            if row is None: return None
            con.execute("UPDATE jobs SET status='running',started_at=?,attempts=attempts+1,error=NULL WHERE id=?", (utcnow(),row["id"]))
            job = dict(row)
            job["payload"] = json.loads(job["payload"])
            job["attempts"] += 1
            return job

    def finish(self, jid, status="completed", error=None):
        with self.connect(write=True) as con:
            con.execute("UPDATE jobs SET status=?,error=?,finished_at=? WHERE id=? AND status='running'", (status,error,utcnow(),jid))

    def recover_interrupted(self):
        # Caller holds the exclusive worker lock, so no other process is executing these jobs.
        with self.connect(write=True) as con:
            rows = con.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
            for r in rows:
                con.execute("UPDATE jobs SET status='queued',error='Recovered after worker interruption' WHERE id=?", (r["id"],))
                self.event("job_recovered", {"note":"Model calls interrupted before persistence may repeat; actions remain deduplicated."}, r["id"], con=con)

    def retry(self, jid):
        with self.connect(write=True) as con:
            job=con.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
            if job and job['status']=='blocked_config' and con.execute("SELECT 1 FROM controls WHERE name='api_blocked'").fetchone():
                con.execute("DELETE FROM controls WHERE name='api_blocked'")
                con.execute("UPDATE jobs SET status='queued',due_at=?,error=NULL WHERE status='blocked_config' AND kind IN ('analyze','prepare','reply','revise_draft','revenue_brief','prospect_research','prospect_qualify','agency_qualify')",(utcnow(),))
            con.execute("UPDATE jobs SET status='queued',due_at=?,error=NULL WHERE id=? AND status IN ('failed','blocked_config')", (utcnow(),jid))

    def schedule(self, interval_seconds=86400, enabled=True, analysis_limit=-1, policy=None):
        if interval_seconds < 1: raise ValueError("Interval must be positive")
        if analysis_limit < -1: raise ValueError("Use -1 for all accounts, 0 for scan only, or a positive limit")
        with self.connect(write=True) as con:
            con.execute("""INSERT INTO schedules VALUES('recovery_scan',?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET interval_seconds=excluded.interval_seconds,
                next_run=excluded.next_run,enabled=excluded.enabled,payload=excluded.payload""",
                (interval_seconds,later(interval_seconds),int(enabled),json.dumps({"analysis_limit":analysis_limit,"policy":policy or {}})))

    def tick(self, now=None):
        now = now or utcnow()
        with self.connect(write=True) as con:
            for r in con.execute("SELECT * FROM schedules WHERE enabled=1 AND next_run<=?", (now,)).fetchall():
                self._enqueue(con,"scan",json.loads(r["payload"]),key=f"schedule:{r['name']}:{r['next_run']}")
                # Coalesce missed intervals into one scan, never a burst of old AI jobs.
                next_run = (datetime.fromisoformat(now)+timedelta(seconds=r["interval_seconds"])).isoformat(timespec="seconds")
                con.execute("UPDATE schedules SET next_run=? WHERE name=?", (next_run,r["name"]))

    def save_analysis(self, job, result):
        """One transaction saves the result and completes the job, including rejection/hold."""
        if job["kind"] == "reply":
            from .conversations import save_reply
            return save_reply(self,job,result)
        with self.connect(write=True) as con:
            opp = con.execute("SELECT * FROM opportunities WHERE id=?", (job["opportunity_id"],)).fetchone()
            current_job = con.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not current_job or current_job["status"] != "running" or not opp or not opp["active"] or opp["evidence_hash"] != job["payload"]["evidence_hash"] or (not job["payload"].get("portfolio") and opp["status"] in STOPPED_STATUSES):
                con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=? AND status='running'", (utcnow(),job["id"]))
                return
            from .service_access import regeneration_current
            if not regeneration_current(self,con,job):
                con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?",(utcnow(),job['id']));return
            analysis = result.model_dump(mode="json") if hasattr(result,"model_dump") else result
            from .evidence import context_hash,ENGINE_VERSION
            if analysis.get('engine_version')==ENGINE_VERSION and analysis.get('context_hash')!=context_hash(con,opp['id']):
                con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error='Account context changed during investigation' WHERE id=?",(utcnow(),job['id']))
                return
            analysis["evidence_hash"] = opp["evidence_hash"]
            analysis["outreach_kind"] = "followup" if job["payload"].get("followup_of") else "initial"
            from .conversations import policy
            from .action_policy import permitted
            if analysis['decision']=='pursue' and not permitted(opp,analysis,policy(con,opp['id'])):
                if analysis.get('engine_version')==ENGINE_VERSION:
                    raise ValueError('Reviewed action violates execution boundaries; no draft saved')
                analysis.update(decision='hold',subject='',body='')
            from .commercial import persist_investigation,execution_issues
            if opp['workflow']=='recovery' and analysis['decision']=='pursue' and execution_issues(con,opp['id'],analysis):
                raise ValueError('Unresolved prerequisites or missing recipient authorization; no draft saved')
            persist_investigation(con,opp['id'],analysis,utcnow())
            self.event("agent_decision",analysis,job["id"],opp["id"],con=con)
            if analysis.get('engine_version')==ENGINE_VERSION:
                obsolete=con.execute("SELECT id FROM jobs WHERE opportunity_id=? AND id!=? AND kind='analyze' AND status IN ('failed','blocked_config') AND json_extract(payload,'$.followup_of') IS NULL AND (COALESCE(json_extract(payload,'$.context_hash'),'')!=? OR COALESCE(json_extract(payload,'$.engine_version'),'')!=?)",(opp['id'],job['id'],analysis.get('context_hash'),ENGINE_VERSION)).fetchall()
                for previous in obsolete:
                    con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?",(utcnow(),previous['id']))
                    self.event('investigation_failure_superseded',{'previous_job':previous['id'],'replacement_job':job['id'],'reason':'A current reviewed assessment supersedes the failed older context.'},job['id'],opp['id'],con=con)
            preserve = opp["status"] in STOPPED_STATUSES or opp["status"] in ("approved","awaiting_response")
            if opp['status']=='approved':
                prior=con.execute("SELECT * FROM drafts WHERE opportunity_id=? AND status='approved' ORDER BY version DESC LIMIT 1",(opp['id'],)).fetchone()
                saved=json.loads(prior['analysis']) if prior else {}
                still_valid=bool(prior and saved.get('context_hash')==context_hash(con,opp['id']) and permitted(opp,saved,policy(con,opp['id']),prior))
                if not still_valid:
                    con.execute("UPDATE drafts SET status='superseded' WHERE opportunity_id=? AND status='approved'",(opp['id'],))
                    con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error='Approval invalidated by new evidence or commercial policy' WHERE opportunity_id=? AND kind='deliver' AND status IN ('queued','running','blocked_config')",(utcnow(),opp['id']))
                    self.event('approval_invalidated',{'reason':'Evidence or commercial policy changed; approval history retained'},job['id'],opp['id'],con=con)
                    preserve=False
            if opp['status']=='awaiting_response' and analysis.get('engine_version')==ENGINE_VERSION and analysis['decision']!='pursue':
                # Retain sent messages and outcomes, but the new commercial decision
                # supersedes an unexecuted follow-up plan.
                con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error='Current commercial decision does not justify a follow-up' WHERE opportunity_id=? AND id!=? AND status IN ('queued','running','blocked_config') AND (kind='followup' OR (kind='analyze' AND json_extract(payload,'$.followup_of') IS NOT NULL))",(utcnow(),opp['id'],job['id']))
                preserve=False
            contact_ready = not job["payload"].get("portfolio") or job["payload"].get("allow_simulation") or analysis.get("engine_version")==ENGINE_VERSION
            parent=job['payload'].get('followup_of')
            latest_send=con.execute('SELECT draft_id FROM outbox WHERE opportunity_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(opp['id'],)).fetchone() if parent else None
            valid_followup=bool(parent and latest_send and latest_send['draft_id']==parent and opp['status']=='awaiting_response')
            if preserve and not valid_followup:
                con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job["id"]))
                return
            if analysis["decision"] == "pursue" and not contact_ready:
                con.execute("UPDATE opportunities SET status='needs_contact',updated_at=? WHERE id=?",(utcnow(),opp["id"]))
                con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job["id"]))
                return
            if analysis["decision"] == "pursue":
                version = con.execute("SELECT COALESCE(MAX(version),0)+1 FROM drafts WHERE opportunity_id=?",(opp["id"],)).fetchone()[0]
                con.execute("UPDATE drafts SET status='superseded' WHERE opportunity_id=? AND status IN ('awaiting_approval','approved')",(opp["id"],))
                con.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (uuid4().hex,opp["id"],version,opp["evidence_hash"],"simulation@example.invalid",
                             analysis["subject"],analysis["body"],"awaiting_approval",json.dumps(analysis),utcnow()))
                state = "awaiting_approval"
            else:
                con.execute("UPDATE drafts SET status='superseded' WHERE opportunity_id=? AND status='awaiting_approval'",(opp['id'],))
                state = "agent_held" if analysis["decision"] == "hold" else "no_action" if analysis["decision"] == "no_action" else "rejected"
            if analysis.get('commercial_plan') and analysis['decision']!='pursue':state=analysis['commercial_plan']['outcome']
            con.execute("UPDATE opportunities SET status=?,updated_at=? WHERE id=?",(state,utcnow(),opp["id"]))
            con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job["id"]))

    @staticmethod
    def draft_hash(draft):
        return digest({k:draft[k] for k in ("id","version","recipient","subject","body","evidence_hash")})

    def revise_draft(self, did, recipient, subject, body):
        if not recipient.strip() or not subject.strip() or not body.strip(): raise ValueError("Recipient, subject and body are required")
        with self.connect(write=True) as con:
            d = con.execute("SELECT * FROM drafts WHERE id=?",(did,)).fetchone()
            if not d or d["status"] not in ("awaiting_approval","approved"): raise ValueError("Draft is no longer editable")
            if all(d[k]==v for k,v in (("recipient",recipient),("subject",subject),("body",body))): return did
            con.execute("UPDATE drafts SET status='superseded' WHERE id=?",(did,))
            version = con.execute("SELECT MAX(version)+1 FROM drafts WHERE opportunity_id=?",(d["opportunity_id"],)).fetchone()[0]
            new_id = uuid4().hex
            con.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)",(new_id,d["opportunity_id"],version,d["evidence_hash"],recipient,subject,body,"awaiting_approval",d["analysis"],utcnow()))
            con.execute("UPDATE opportunities SET status='awaiting_approval' WHERE id=?",(d["opportunity_id"],))
            self.event("draft_revised",{"old_id":did,"new_id":new_id},opportunity_id=d["opportunity_id"],con=con)
            # A changed narrow-scope email needs fresh QA, not a new initial investigation.
            # Debounce autosaves and preserve the human's exact text throughout review.
            from .reporting import valid_draft
            from .draft_revision import manual_reviewable
            edited=dict(con.execute('SELECT * FROM drafts WHERE id=?',(new_id,)).fetchone())
            if not valid_draft(self,edited) and manual_reviewable(self,edited):
                con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error=? WHERE opportunity_id=? AND kind='revise_draft' AND status IN ('queued','running','blocked_config')",(utcnow(),'A newer human edit superseded this review.',d['opportunity_id']))
                payload={'draft_id':new_id,'snapshot_hash':self.draft_hash(edited),'review_only':True,'instructions':'Check this exact human-edited message against the evidence and existing action scope. Preserve every word.'}
                self._enqueue(con,'revise_draft',payload,d['opportunity_id'],'manual-review:'+new_id,later(10))
            return new_id

    def decide(self, did, approve):
        with self.connect(write=True) as con:
            self._decide(con, did, approve)

    def _decide(self, con, did, approve):
        d = con.execute("SELECT * FROM drafts WHERE id=?",(did,)).fetchone()
        if not d or d["status"] != "awaiting_approval": raise ValueError("Draft is not awaiting approval")
        opp = con.execute("SELECT * FROM opportunities WHERE id=?",(d["opportunity_id"],)).fetchone()
        from .conversations import policy
        from .action_policy import permitted
        from .evidence import context_hash,ENGINE_VERSION
        a=json.loads(d['analysis'])
        stale=bool(a.get('engine_version')) and a.get('context_hash')!=context_hash(con,opp['id'])
        from .commercial import execution_issues
        if approve and opp['workflow']=='recovery' and execution_issues(con,opp['id'],a):raise ValueError('Resolve blocking prerequisites and authorize the recipient before approval')
        if approve and (stale or not permitted(opp,a,policy(con,opp['id']),d) or not opp['active'] or opp['evidence_hash']!=d['evidence_hash'] or opp['status'] in STOPPED_STATUSES):
            raise ValueError("Opportunity changed or is held; reassess before approval")
        if approve and con.execute("SELECT 1 FROM jobs WHERE opportunity_id=? AND kind='revise_draft' AND status IN ('queued','running')",(opp['id'],)).fetchone():
            raise ValueError("An agent is revising this email. Review the new version before approving.")
        decision = "approved" if approve else "rejected"
        con.execute("INSERT INTO approvals VALUES(?,?,?,?,?)",(uuid4().hex,did,self.draft_hash(d),decision,utcnow()))
        con.execute("UPDATE drafts SET status=? WHERE id=?",(decision,did))
        con.execute("UPDATE opportunities SET status=? WHERE id=?",(decision,d["opportunity_id"]))
        parent=json.loads(d["analysis"]).get("reply_message_id")
        if parent:con.execute("UPDATE commercial_tasks SET status=?,updated_at=? WHERE message_id=?",(decision,utcnow(),parent))
        if approve:
            self._enqueue(con,"deliver",{"draft_id":did},d["opportunity_id"],f"deliver:{did}")
        if not approve:
            con.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE opportunity_id=? AND kind IN ('deliver','followup','prepare') AND status IN ('queued','running','blocked_config')",(utcnow(),opp['id']))
        self.event("human_"+decision,{"draft_id":did,"version":d["version"]},opportunity_id=d["opportunity_id"],con=con)

    def deliver(self, job, followup_days=7):
        from .transport import SimulatedProvider
        return SimulatedProvider(self).send_approved(job,followup_days)

    def _deliver_simulated(self, job, followup_days=7):
        """Atomic simulated outbox. No email provider, credentials, or network send exists."""
        with self.connect(write=True) as con:
            did = job["payload"]["draft_id"]
            current_job = con.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not current_job or current_job["status"] != "running":
                raise ValueError("Action job is no longer running")
            d = con.execute("SELECT * FROM drafts WHERE id=?",(did,)).fetchone()
            if con.execute("SELECT 1 FROM outbox WHERE draft_id=?",(did,)).fetchone(): return
            opp = con.execute("SELECT * FROM opportunities WHERE id=?",(job["opportunity_id"],)).fetchone()
            approval = con.execute("SELECT * FROM approvals WHERE draft_id=? AND decision='approved' ORDER BY created_at DESC LIMIT 1",(did,)).fetchone()
            if not d or d["status"]!="approved" or not approval or approval["snapshot_hash"] != self.draft_hash(d):
                raise ValueError("Action has no current approval")
            from .conversations import policy,outbound_record
            from .action_policy import permitted
            from .evidence import context_hash,ENGINE_VERSION
            a=json.loads(d['analysis'])
            stale=bool(a.get('engine_version')) and a.get('context_hash')!=context_hash(con,opp['id'])
            from .commercial import execution_issues
            if opp['workflow']=='recovery' and execution_issues(con,opp['id'],a):raise ValueError('Commercial prerequisites changed before delivery')
            if stale or not permitted(opp,a,policy(con,opp['id']),d) or not opp['active'] or opp['evidence_hash']!=d['evidence_hash'] or opp['status'] in STOPPED_STATUSES:
                raise ValueError("Opportunity changed or stopped; action blocked")
            con.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?,?)",(uuid4().hex,did,opp["id"],d["recipient"],d["subject"],d["body"],"simulated",utcnow()))
            outbound_record(con,con.execute("SELECT * FROM outbox WHERE draft_id=?",(did,)).fetchone(),d)
            con.execute("UPDATE drafts SET status='simulated' WHERE id=?",(did,))
            con.execute("UPDATE opportunities SET status='awaiting_response' WHERE id=?",(opp["id"],))
            # One follow-up is sufficient to prove scheduling without unbounded campaigns.
            count = con.execute("SELECT COUNT(*) FROM outbox WHERE opportunity_id=?",(opp["id"],)).fetchone()[0]
            if count == 1:
                self._enqueue(con,"followup",{"parent_draft_id":did},opp["id"],f"followup:{did}",later(followup_days*86400))
            self.event("outbox_simulated",{"draft_id":did,"real_email_sent":False},job["id"],opp["id"],con=con)

    def record_outcome(self, oid, kind, note, amount_cents=None, reference=None):
        if kind=="reply":
            from .transport import SimulatedProvider
            parents=self.rows("SELECT id FROM messages WHERE opportunity_id=? AND direction='outbound' ORDER BY created_at DESC,rowid DESC LIMIT 1",(oid,))
            if parents:return SimulatedProvider(self).ingest(oid,parents[0]["id"],uuid4().hex,note)
        statuses = {"reply":"replied","opt_out":"opted_out","closed":"closed","qualified":"qualified","quote":"quoted","order":"won","credit":"won","lost":"lost"}
        if kind not in statuses: raise ValueError("Unknown outcome")
        if not note.strip(): raise ValueError("Record the response or reason")
        if kind in ("quote","order","credit"):
            if not isinstance(amount_cents,int) or amount_cents < 0 or not reference or not reference.strip():
                raise ValueError("Quote/order outcomes need a nonnegative amount and unique reference")
            reference = reference.strip()
        else:
            amount_cents, reference = None, None
        status = statuses[kind]
        with self.connect(write=True) as con:
            if reference and con.execute("SELECT 1 FROM outcomes WHERE opportunity_id=? AND kind=? AND reference=?", (oid,kind,reference)).fetchone():
                raise ValueError("This reference has already been recorded; no duplicate outcome was added")
            outcome_id=uuid4().hex
            con.execute("INSERT INTO outcomes(id,opportunity_id,kind,note,provenance,created_at,amount_cents,reference) VALUES(?,?,?,?,?,?,?,?)",(outcome_id,oid,kind,note,"manual_demo_input",utcnow(),amount_cents,reference))
            prior=con.execute('SELECT id FROM outbox WHERE opportunity_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(oid,)).fetchone()
            if prior:con.execute('INSERT INTO outcome_outreach VALUES(?,?)',(outcome_id,prior['id']))
            from .conversations import policy
            if kind in ("opt_out","lost"):
                con.execute("INSERT INTO customer_context(opportunity_id,outreach_policy,updated_at) VALUES(?,'stop',?) ON CONFLICT(opportunity_id) DO UPDATE SET outreach_policy='stop',updated_at=excluded.updated_at",(oid,utcnow()))
            stopped=policy(con,oid)=="stop"
            prior_status=con.execute("SELECT status FROM opportunities WHERE id=?",(oid,)).fetchone()["status"]
            if stopped and kind not in ("opt_out","lost"):status=prior_status
            con.execute("UPDATE opportunities SET status=? WHERE id=?",(status,oid))
            con.execute("UPDATE conversations SET status=?,updated_at=? WHERE opportunity_id=?",(status,utcnow(),oid))
            con.execute("UPDATE commercial_tasks SET status='completed',updated_at=? WHERE opportunity_id=? AND status IN ('pending','awaiting_approval','approved')",(utcnow(),oid))
            con.execute("UPDATE jobs SET status='cancelled' WHERE opportunity_id=? AND status IN ('queued','running','blocked_config')",(oid,))
            con.execute("UPDATE drafts SET status='cancelled' WHERE opportunity_id=? AND status IN ('awaiting_approval','approved')",(oid,))
            if kind=='reply' and prior:
                o=con.execute('SELECT evidence_hash,holds,active FROM opportunities WHERE id=?',(oid,)).fetchone()
                if o and o['active'] and not json.loads(o['holds']):
                    self._enqueue(con,'reply',{'evidence_hash':o['evidence_hash'],'outcome_id':outcome_id},oid,'reply:'+outcome_id)
            self.event("outcome_recorded",{"kind":kind,"provenance":"manual_demo_input"},opportunity_id=oid,con=con)


# Responses and commercial milestones hand control to a person; never continue a blind sequence.
STOPPED_STATUSES = {"deferred", "replied", "closed", "opted_out", "rejected", "qualified", "quoted", "won", "lost"}
