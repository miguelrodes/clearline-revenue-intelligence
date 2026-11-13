"""Application service shared by dashboard HTTP and MCP. Business rules stay below adapters."""
from datetime import datetime,timezone
import json
from typing import Literal
from .contracts import *
from .store import Store,STOPPED_STATUSES
from .reporting import opportunities,monthly_trends,valid_draft,portfolio_transactions
from .operations import start_batch,batches,create_campaign,campaign_view,decide_campaign,financial_segments,metrics,queue_brief,review_recommendation

class NotFound(ValueError):pass

from .service_access import BusinessAccess

class ApplicationService(BusinessAccess):
    def __init__(self,settings,store=None):
        self.settings=settings
        self.store=store or Store(settings.db_path)
    def account(self, oid):
        try:
            return self.store.opportunity(oid)
        except ValueError:
            raise NotFound('Account not found')

    def draft(self, did):
        rows = self.store.rows('SELECT * FROM drafts WHERE id=?', (did,))
        if not rows:
            raise NotFound('Draft not found')
        return rows[0]

    def jobs(self):
        return self.store.rows('SELECT j.*,p.name AS account_name,p.workflow FROM jobs j LEFT JOIN opportunities p ON p.id=j.opportunity_id ORDER BY j.created_at DESC,j.rowid DESC')

    def health(self):
        rows = self.store.rows('SELECT * FROM worker_state WHERE id=1')
        row = rows[0] if rows else None
        alive = bool(row and row['state'] != 'stopped' and ((datetime.now(timezone.utc) - datetime.fromisoformat(row['seen_at'])).total_seconds() < self.settings.timeout_seconds + 30))
        return {'alive': alive, 'paused': self.store.paused(), 'last_seen': row['seen_at'] if row else None, 'state': 'paused' if alive and self.store.paused() else 'running' if alive else 'offline', 'schedules': self.store.rows('SELECT * FROM schedules'), 'as_of': self.settings.as_of, 'disposable_demo': self.disposable_demo()}

    def disposable_demo(self):
        from .demo import manifest
        try:return manifest(self.settings.db_path.parent)['session']==str(self.settings.db_path.resolve())
        except (ValueError,OSError,KeyError):return False

    def get_health(self):
        return self.health()

    def get_opportunities(self, workflow: Literal['recovery', 'prospecting']='recovery', queue: Literal['contacts', 'unassessed', 'held', 'approvals'] | None=None):
        if queue:
            if workflow != 'recovery':
                raise ValueError('Operational queues apply to recovery accounts only')
            from .briefing import operational_queue
            return operational_queue(self.store, queue)
        return opportunities(self.store, workflow)

    def work(self):
        from .workbench import work_groups
        return work_groups(self.store, workflow='recovery')

    def work_decision(self, group_id: str, body: CampaignDecision):
        from .workbench import decide_messages
        decide_messages(self.store, group_id, [s.model_dump() for s in body.snapshots], body.approve)
        return {'status': 'approved' if body.approve else 'rejected', 'delivery_mode': 'simulated'}

    def work_revision(self, group_id: str, body: RevisionInput):
        from .draft_revision import queue_revisions
        return queue_revisions(self.store,group_id,[s.model_dump() for s in body.snapshots],body.instructions)

    def refresh_portfolio(self):
        from .workbench import refresh_portfolio
        return {'job_id': refresh_portfolio(self.store)}

    def portfolio_coverage(self):
        from .signal_views import coverage
        return coverage(self.store)

    def signal_view(self, key: Literal['inactivity', 'partial', 'product_decline', 'direct_gap_channel_review']):
        from .signal_views import signal_detail
        return signal_detail(self.store, key)

    def performance(self, workflow: Literal['recovery', 'prospecting']='recovery'):
        from .workbench import recovery_performance
        return recovery_performance(self.store, workflow)

    def search(self, q: str=''):
        if len(q.strip()) < 2:
            return []
        term = q.strip().lower()
        found = []
        for a in self.store.rows('SELECT id,name,state,workflow,evidence FROM opportunities WHERE active=1'):
            e = json.loads(a.pop('evidence'))
            if term in ' '.join([a['name'], a['state'], *e.get('aliases', [])]).lower():
                found.append(a)
        return sorted(found, key=lambda a: a['name'])[:20]

    def checks(self):
        from .review_checks import review_batches
        return review_batches(self.store)

    def check_export(self, key: Literal['orders', 'dates', 'channel', 'identity', 'other'], signal: str | None=None, focus: str | None=None):
        from .review_checks import batch_details, batch_csv
        body = batch_csv(batch_details(self.store, self.settings, key, signal, focus))
        return body

    def check_detail(self, key: Literal['orders', 'dates', 'channel', 'identity', 'other'], signal: str | None=None, focus: str | None=None):
        from .review_checks import batch_details
        detail = batch_details(self.store, self.settings, key, signal, focus)
        return {k: v for k, v in detail.items() if k != 'records'}

    def execution(self):
        return metrics(self.store)

    def batch(self, body: BatchInput):
        return {'batch_id': start_batch(self.store, body.account_ids, body.request_id)}

    def campaigns(self):
        return [campaign_view(self.store, r['id']) for r in self.store.rows('SELECT id FROM campaigns ORDER BY created_at DESC,rowid DESC')]

    def campaign(self, body: CampaignInput):
        return {'campaign_id': create_campaign(self.store, body.name, body.account_ids, body.simulated_contacts, body.request_id)}

    def campaign_decide(self, cid: str, body: CampaignDecision):
        decide_campaign(self.store, cid, [d.model_dump() for d in body.snapshots], body.approve)
        return {'status': 'approved' if body.approve else 'rejected'}

    def operational_brief(self):
        from .briefing import current_brief
        return current_brief(self.store)

    def regenerate_brief(self):
        return {'job_id': queue_brief(self.store, True)}

    def disposition(self, oid: str, body: DispositionInput):
        self.account(oid)
        review_recommendation(self.store, oid, body.decision, body.note)
        return {'recorded': True}

    def overview(self):
        accounts = opportunities(self.store)
        scans = self.store.rows('SELECT * FROM scans ORDER BY created_at DESC LIMIT 1')
        summary = json.loads(scans[0]['summary']) if scans else {}
        all_jobs = self.jobs()
        pending = [d for d in self.store.rows("SELECT d.*,p.workflow FROM drafts d JOIN opportunities p ON p.id=d.opportunity_id WHERE d.status='awaiting_approval'") if d['workflow'] == 'recovery' and valid_draft(self.store, d)]
        pending_ids = {j['opportunity_id'] for j in all_jobs if j['status'] in ('queued', 'running') and j['kind'] == 'analyze'}
        counts = {'inactivity': sum(('inactivity' in a['signals'] for a in accounts)), 'inactivity_reviewable': sum(('inactivity' in a['signals'] and (not a['holds']) for a in accounts)), 'partial': sum((a['partial_decline'] for a in accounts)), 'product_decline': sum(('product_decline' in a['signals'] for a in accounts)), 'channel_review': sum(('direct_gap_channel_review' in a['signals'] for a in accounts)), 'awaiting_analysis': sum((a['status'] == 'needs_review' and (not a['holds']) and (a['id'] not in pending_ids) for a in accounts)), 'approvals': len(pending), 'scheduled': sum((j['status'] == 'queued' and j['workflow'] == 'recovery' and (j['kind'] in ('followup', 'deliver')) for j in all_jobs)), 'held': sum((bool(a['holds']) for a in accounts)), 'accounts': len(accounts)}
        primary_declines = {key: 0 for key in ('inactivity', 'purchasing_decline', 'product_decline', 'channel_review')}
        for account_row in accounts:
            key = account_row['primary_opportunity']
            if key in primary_declines:
                primary_declines[key] += max(0, int(account_row['decline_cents']))
        return {'summary': summary, 'counts': counts, 'primary_declines': primary_declines, 'segments': financial_segments(self.store), 'brief': None, 'execution': metrics(self.store), 'trends': monthly_trends(self.store, self.settings), 'health': self.health(), 'last_scan': scans[0]['created_at'] if scans else None}

    def transactions(self, year: int=2026, q: str='', offset: int=0):
        return portfolio_transactions(self.store, self.settings, year, q, offset)

    def detail(self, oid: str):
        opp = self.account(oid)
        drafts = self.store.rows('SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC', (oid,))
        from .draft_revision import manual_reviewable
        revisions={json.loads(j['payload']).get('draft_id'):j['status'] for j in self.store.rows("SELECT payload,status FROM jobs WHERE opportunity_id=? AND kind='revise_draft' ORDER BY created_at,rowid",(oid,))}
        for d in drafts:
            valid=valid_draft(self.store,d)
            d['review_status']=revisions.get(d['id'])
            d['can_review'] = d['status'] == 'awaiting_approval' and valid and d['review_status'] not in ('queued','running')
            d['can_edit'] = d['status'] in ('awaiting_approval','approved') and (valid or manual_reviewable(self.store,d))
            d['analysis'] = json.loads(d['analysis'])
        events = self.store.rows('SELECT * FROM events WHERE opportunity_id=? ORDER BY id DESC', (oid,))
        for event in events:
            event['details'] = json.loads(event['details'])
        assessment = next((e for e in events if e['kind'] == 'agent_decision'), None)
        if assessment:
            from .operations import latest_assessment
            current = latest_assessment(self.store, oid)
            if not current or current.get('evidence_hash') != opp['evidence_hash']:
                assessment = None
        return {**opp, 'drafts': drafts, 'events': events, 'assessment': assessment, 'jobs': [j for j in self.jobs() if j['opportunity_id'] == oid], 'outbox': self.store.rows('SELECT * FROM outbox WHERE opportunity_id=? ORDER BY created_at DESC', (oid,)), 'outcomes': self.store.rows('SELECT * FROM outcomes WHERE opportunity_id=? ORDER BY created_at DESC', (oid,)), 'trends': monthly_trends(self.store, self.settings, opp['evidence']) if opp['workflow'] == 'recovery' else None}

    def activity(self):
        events = self.store.rows('SELECT e.*,p.name AS account_name,p.workflow FROM events e LEFT JOIN opportunities p ON p.id=e.opportunity_id ORDER BY e.id DESC LIMIT 200')
        for event in events:
            event['details'] = json.loads(event['details'])
        return {'jobs': self.jobs(), 'events': events, 'health': self.health(), 'outcomes': self.store.rows('SELECT o.*,p.name AS account_name,p.workflow FROM outcomes o JOIN opportunities p ON p.id=o.opportunity_id ORDER BY o.created_at DESC')}

    def actions(self):
        result = []
        for workflow in ('recovery', 'prospecting'):
            for a in opportunities(self.store, workflow):
                if a['status'] in STOPPED_STATUSES:
                    continue
                if a['status'] == 'awaiting_approval':
                    ds = self.store.rows('SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1', (a['id'],))
                    if ds and valid_draft(self.store, ds[0]):
                        result.append({**a, 'category': 'approval', 'reason': 'Review the saved email and its supporting assessment.'})
                elif a['status'] in ('needs_review', 'needs_research'):
                    result.append({**a, 'category': 'assessment', 'reason': 'No completed agent assessment is saved.'})
                elif a['holds'] or a['status'] in ('agent_held', 'needs_contact'):
                    result.append({**a, 'category': 'exception', 'reason': a.get('recommended_action') or 'Evidence or agent findings require investigation before outreach.'})
        for j in self.jobs():
            if j['status'] in ('queued', 'running', 'failed', 'blocked_config'):
                result.append({'id': j['opportunity_id'], 'name': j['account_name'] or 'Portfolio scan', 'workflow': j['workflow'] or 'recovery', 'status': j['status'], 'category': 'exception' if j['status'] in ('failed', 'blocked_config') else 'scheduled' if j['kind'] in ('followup', 'deliver') else 'in_progress', 'reason': j['error'] or j['kind'].replace('_', ' '), 'job_id': j['id'], 'kind': j['kind'], 'due_at': j['due_at']})
        active_ids = {r['id'] for r in result if r['category'] == 'in_progress'}
        return [r for r in result if r['category'] != 'assessment' or r['id'] not in active_ids]

    def run_scan(self, body: ScanInput):
        payload = {'analysis_limit': body.analysis_limit, 'policy': {'inactivity_days': body.inactivity_days, 'decline_fraction': body.decline_fraction}}
        key='manual-scan:'+str(body.request_id) if body.request_id else None
        with self.store.connect(write=True) as con:
            if key:
                old=con.execute('SELECT id,payload FROM jobs WHERE dedupe_key=?',(key,)).fetchone()
                if old:
                    if json.loads(old['payload'])!=payload:raise ValueError('Request ID already used with different scan rules')
                    return {'job_id':old['id']}
            return {'job_id':self.store._enqueue(con,'scan',payload,key=key)}

    def assess(self, oid: str, body: AssessmentInput):
        opp = self.account(oid)
        if opp['evidence_hash'] != body.evidence_hash:
            raise ValueError('Evidence changed. Reload the account.')
        if not opp['active'] or opp['status'] in STOPPED_STATUSES:
            raise ValueError('Account is stopped or inactive')
        if body.rerun:
            if not body.request_id:
                raise ValueError('A request ID is required for a reassessment')
            if opp['status'] in ('approved', 'awaiting_response'):
                raise ValueError('Outreach already approved or simulated. Use the existing follow-up workflow.')
            busy = self.store.rows("SELECT id FROM jobs WHERE opportunity_id=? AND status IN ('queued','running') AND kind IN ('analyze','prospect_research','prospect_qualify')", (oid,))
            if busy:
                return {'job_id': busy[0]['id']}
            kind = 'analyze' if opp['workflow'] == 'recovery' else 'prospect_qualify' if opp['evidence'].get('research') else 'prospect_research'
            jid = self.store.enqueue(kind, {'evidence_hash': opp['evidence_hash'], 'followup_of': None, 'portfolio': opp['workflow'] == 'recovery'}, oid, f'manual:{oid}:{body.request_id}')
        else:
            jid = self.store.queue_prospect(oid) if opp['workflow'] == 'prospecting' else self.store.queue_analysis(oid, investigation=True)
        return {'job_id': jid}

    def edit(self, did: str, body: DraftInput):
        d = self.draft(did)
        if d['version'] != body.version or not valid_draft(self.store, d):
            raise ValueError('Draft or evidence changed. Reload before editing.')
        return {'draft_id': self.store.revise_draft(did, body.recipient, body.subject, body.body)}

    def decide(self, did: str, body: ApprovalInput):
        d = self.draft(did)
        if any((d[k] != getattr(body, k) for k in ('version', 'recipient', 'subject', 'body'))):
            raise ValueError('Save your edits first. Approval applies only to the exact saved draft.')
        self.store.decide(did, body.approve)
        return {'status': 'approved' if body.approve else 'rejected', 'delivery_mode': 'simulated'}

    def conversation(self, oid: str):
        self.account(oid)
        from .transport import SimulatedProvider
        return SimulatedProvider(self.store).conversation(oid)

    def inbound(self, oid: str, body: InboundInput):
        a = self.store.opportunity(oid)
        if a['workflow'] != 'recovery':
            raise ValueError('This simulator is for fictional recovery accounts')
        from .transport import SimulatedProvider
        return SimulatedProvider(self.store).ingest(oid, body.reply_to, body.message_id, body.body)

    def outcome(self, oid: str, body: OutcomeInput):
        self.account(oid)
        self.store.record_outcome(oid, body.kind, body.note, body.amount_cents, body.reference)
        return {'status': 'recorded', 'provenance': 'manual_demo_input'}

    def job_action(self, jid: str, action: Literal['retry', 'cancel']):
        found = self.store.rows('SELECT status FROM jobs WHERE id=?', (jid,))
        if not found:
            raise NotFound('Job not found')
        if action == 'retry' and found[0]['status'] not in ('failed', 'blocked_config'):
            raise ValueError('Only failed or blocked jobs can be retried')
        if action == 'cancel' and found[0]['status'] not in ('queued', 'running', 'blocked_config', 'failed'):
            raise ValueError('Job is no longer cancellable')
        getattr(self.store, 'retry' if action == 'retry' else 'cancel_job')(jid)
        return {'status': 'queued' if action == 'retry' else 'cancelled'}

    def worker_action(self, action: Literal['pause', 'resume']):
        self.store.set_paused(action == 'pause')
        return self.health()

    def schedule(self, body: ScheduleInput):
        self.store.schedule(enabled=body.enabled, analysis_limit=body.analysis_limit, policy={'inactivity_days': body.inactivity_days, 'decline_fraction': body.decline_fraction})
        return self.health()
