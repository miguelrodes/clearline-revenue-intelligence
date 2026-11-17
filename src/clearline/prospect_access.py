"""Shared user actions for the real and fictional prospect pipeline."""
import json
import re
from uuid import uuid4

from .store import utcnow


def web_candidate(opportunity):
    if opportunity['workflow'] != 'prospecting':
        return False
    evidence = opportunity['evidence']
    if isinstance(evidence, str):
        evidence = json.loads(evidence)
    return evidence.get('profile', {}).get('origin') == 'real_web'


def permitted_web_draft(con, opportunity, analysis, draft):
    if not web_candidate(opportunity):
        return True
    auth = con.execute("SELECT * FROM contact_authorizations WHERE opportunity_id=?", (opportunity['id'],)).fetchone()
    route = {'direct_discovery': 'direct', 'distributor_led': 'distributor'}.get(analysis.get('channel'))
    return bool(auth and auth['authorized'] and route == auth['route']
                and auth['recipient'] == analysis.get('recipient') and draft['recipient'] == 'simulation@example.invalid')


class ProspectAccess:
    def prospect_pipeline(self, **filters):
        from .prospect_pipeline import pipeline
        self.screening_guard()
        return pipeline(self.store, **filters)

    def candidate(self, candidate_id):
        from .prospect_pipeline import candidate_detail
        self.screening_guard()
        return candidate_detail(self.store, candidate_id)

    def prospect_disposition(self, candidate_id, decision, rationale):
        from .prospect_pipeline import candidate_decision
        self.screening_guard()
        return candidate_decision(self.store, candidate_id, decision, rationale)

    def prospect_run(self, kind, body, *, preview):
        from . import prospect_discovery as runs
        self.screening_guard()
        if kind == 'discovery':
            operation = runs.discovery_scope if preview else runs.queue_discovery
        else:
            operation = runs.research_scope if preview else runs.queue_research
        kwargs = body.model_dump()
        if preview:
            kwargs.pop('confirmed', None)
        return operation(self.store, self.settings, **kwargs)

    def prospect_job(self, job_id):
        self.screening_guard()
        data = self.job_result(job_id)
        job = data['job']
        if job['kind'] not in ('pipeline_discover', 'pipeline_research', 'pipeline_qualify'):
            raise ValueError('Unknown prospect pipeline job.')
        result = next((e['details'] for e in data['events'] if e['kind'] == 'prospect_discovery_saved'), None)
        return {k: job[k] for k in ('id','kind','status','opportunity_id','error')} | {'result': result}

    def authorize_prospect(self, candidate_id, recipient, role, route, evidence, authorized):
        self.screening_guard()
        recipient, role, evidence = recipient.strip().lower(), role.strip(), evidence.strip()
        if not authorized or not role or not evidence or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', recipient) or recipient.endswith('.invalid'):
            raise ValueError('Record a verified purchasing recipient, role, buying route and explicit permission evidence.')
        with self.store.connect(write=True) as con:
            opp = con.execute('SELECT * FROM opportunities WHERE id=?', (candidate_id,)).fetchone()
            if not opp or not web_candidate(opp) or not opp['active'] or opp['status'] != 'awaiting_approval':
                raise ValueError('Select a researched web prospect with a current outreach recommendation.')
            draft = con.execute("""SELECT * FROM drafts WHERE opportunity_id=? AND evidence_hash=? AND status='awaiting_approval'
                                   ORDER BY version DESC LIMIT 1""", (candidate_id, opp['evidence_hash'])).fetchone()
            if not draft:
                raise ValueError('There is no current outreach draft for this prospect.')
            analysis = json.loads(draft['analysis'])
            if {'direct_discovery':'direct','distributor_led':'distributor'}.get(analysis.get('channel')) != route:
                raise ValueError('The authorized route must match the researched buying approach.')
            if analysis.get('decision') != 'pursue':
                raise ValueError('This prospect has no recommendation for outreach.')
            now = utcnow()
            con.execute("""INSERT INTO contact_authorizations VALUES(?,?,?,?,?,1,?) ON CONFLICT(opportunity_id)
                           DO UPDATE SET recipient=excluded.recipient,role=excluded.role,route=excluded.route,
                           evidence=excluded.evidence,authorized=1,updated_at=excluded.updated_at""",
                        (candidate_id,recipient,role,route,evidence,now))
            if analysis.get('recipient') != recipient:
                # Bind the exact version presented for human approval to the verified intended recipient.
                analysis['recipient'] = recipient
                new_id = uuid4().hex
                version = con.execute('SELECT MAX(version)+1 FROM drafts WHERE opportunity_id=?',(candidate_id,)).fetchone()[0]
                con.execute("UPDATE drafts SET status='superseded' WHERE id=?", (draft['id'],))
                con.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (new_id,candidate_id,version,opp['evidence_hash'],'simulation@example.invalid',draft['subject'],
                             draft['body'],'awaiting_approval',json.dumps(analysis),now))
            self.store.event('prospect_contact_verified', {'role':role,'route':route},opportunity_id=candidate_id,con=con)
        return self.candidate(candidate_id)
