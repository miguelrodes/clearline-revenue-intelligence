"""Bounded business queries and review sessions, shared across interface adapters."""
import json
from datetime import datetime,timedelta,timezone
from uuid import uuid4

SCHEMA='''
CREATE TABLE IF NOT EXISTS approval_reviews(id TEXT PRIMARY KEY, snapshots TEXT NOT NULL, expires_at TEXT NOT NULL, decision TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS operation_requests(id TEXT PRIMARY KEY, operation TEXT NOT NULL, input_hash TEXT NOT NULL, result TEXT NOT NULL);
'''

DEFINITIONS={
 'money':'All monetary values use integer USD cents. Historical decline is not forecast or attributable recovery.',
 'period':'Comparable January–October 2025 and 2026; business cutoff November 1, 2026.',
 'historical_decline':'Signed company-wide net revenue difference, including increases and credits; distributor sales counted once.',
 'signals':'Overlapping account groups; never add signal dollars or counts together. SKU dollars sum positive qualifying product reductions without offsetting other product growth.',
 'volumes':'Physical tests purchased, not usage. Training is not physical test volume. Open orders are excluded from booked net revenue.',
 'identity':'Unidentified distributor end customers can conceal purchases. Aliases can be hypotheses. Fictional recovery accounts and real prospects remain separate.',
 'outcomes':'All messages and outcomes here are simulated or manually recorded; do not claim incremental revenue from an expression of interest.'}

def page(rows,offset=0,limit=25):
    if offset<0 or not 1<=limit<=100:raise ValueError('Use offset >= 0 and limit 1–100')
    return {'items':rows[offset:offset+limit],'total':len(rows),'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<len(rows) else None}

class BusinessAccess:
    def commercial_signals(self,oid=None):
        if oid:self.account(oid)
        rows=self.store.rows('SELECT * FROM commercial_signals WHERE active=1'+(' AND opportunity_id=?' if oid else ''),(oid,) if oid else ())
        from .evidence import context_hash
        with self.store.connect() as con:contexts={r['opportunity_id']:context_hash(con,r['opportunity_id']) for r in rows}
        for row in rows:
            row['evidence']=json.loads(row['evidence'])
            if row['assessment_context']!=contexts[row['opportunity_id']]:row['investigation_status']='pending'

        return {'signals':rows,'count':len(rows),'assessed':sum(r['investigation_status']=='assessed' for r in rows),'note':'Overlapping signals are not additive revenue.'}

    def authorize_contact(self,oid,recipient,role,route,evidence,authorized):
        from .store import utcnow
        account=self.account(oid)
        if account['workflow']!='recovery':raise ValueError('Recovery accounts only')
        if route not in ('direct','distributor') or not all(str(v).strip() for v in (recipient,role,evidence)):raise ValueError('Recipient, role, relationship route and supporting evidence are required')
        import re
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',recipient):raise ValueError('Enter a valid recipient email address')
        if recipient.lower().endswith('.invalid'):raise ValueError('A simulator address does not establish contact eligibility')
        if not account['account_key'].startswith('DISTRIBUTOR|') and 'known_distributor_channel' in account['holds'] and route!='distributor':raise ValueError('Preserve distributor route; downstream direct permission needs separately verified channel policy')
        with self.store.connect(write=True) as con:
            con.execute('INSERT INTO contact_authorizations VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET recipient=excluded.recipient,role=excluded.role,route=excluded.route,evidence=excluded.evidence,authorized=excluded.authorized,updated_at=excluded.updated_at',(oid,recipient,role,route,evidence,int(authorized),utcnow()))
            self.store.event('contact_authorization_recorded',{'recipient':recipient,'route':route,'evidence':evidence,'authorized':authorized},opportunity_id=oid,con=con)
        return {'job_id':self.store.queue_analysis(oid,investigation=True),'requires_reassessment':True}

    def save_contact_clearance(self,oid,task_id=None,contact_name='',recipient='',role='',phone='',route='',distributor='',verification_evidence='',verified=False):
        """Save partial contact facts without clearing the hold; complete verified facts authorize and reassess once."""
        import re
        from .store import utcnow
        account=self.account(oid)
        if account['workflow']!='recovery':raise ValueError('Recovery accounts only')
        if not account['active']:raise ValueError('Inactive accounts cannot receive contact authorization')
        values={k:str(v or '').strip() for k,v in {'contact_name':contact_name,'recipient':recipient,'role':role,'phone':phone,'route':route,'distributor':distributor,'verification_evidence':verification_evidence}.items()}
        if values['route'] not in ('','direct','distributor'):raise ValueError('Choose direct, distributor, or leave the route unconfirmed')
        if not any(values.values()):raise ValueError('Enter at least one contact detail or verification finding')
        if values['recipient']:
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['recipient']):raise ValueError('Enter a valid email address or leave it blank')
            if values['recipient'].lower().endswith('.invalid'):raise ValueError('A simulator address does not establish contact eligibility')
        task=None;task_is_contact=False
        if task_id:
            rows=self.store.rows("SELECT * FROM investigation_tasks WHERE id=? AND opportunity_id=? AND status='pending'",(task_id,oid))
            if not rows:raise ValueError('This contact check is no longer pending. Refresh the account before saving.')
            task=rows[0]
            from .task_purpose import task_purpose
            purpose=task_purpose(task)
            if not (purpose['contact_check'] or purpose['identity_check']):
                raise ValueError('This task is not a purchasing-contact or route check')
            task_is_contact=purpose['contact_resolvable']
        if verified:
            if not all((values['recipient'],values['role'],values['route'],values['verification_evidence'])):
                raise ValueError('To verify the contact, provide a recipient, role, purchasing route, and how it was verified')
            if not account['account_key'].startswith('DISTRIBUTOR|') and 'known_distributor_channel' in account['holds'] and values['route']!='distributor':
                raise ValueError('Preserve the existing distributor route; direct authorization needs separately verified channel evidence')
        now=utcnow();queue_reassessment=False;status='partial';task_status='pending' if task else None
        with self.store.connect(write=True) as con:
            prior=con.execute('SELECT * FROM contact_authorizations WHERE opportunity_id=?',(oid,)).fetchone()
            saved=con.execute('SELECT * FROM contact_clearance_notes WHERE opportunity_id=?',(oid,)).fetchone()
            if task_id:
                current_task=con.execute("SELECT id FROM investigation_tasks WHERE id=? AND opportunity_id=? AND status='pending'",(task_id,oid)).fetchone()
                if not current_task:raise ValueError('This contact check was completed or changed before the save. Refresh the account and review the current task.')
            effective_task_id=task_id if task_id else (saved['task_id'] if saved else None)
            note_fields=('contact_name','recipient','role','phone','route','distributor','verification_evidence')
            was_verified_note=bool(saved and saved['status']=='verified')
            note_changed=not saved or any((saved[k] or '')!=values[k] for k in note_fields) or saved['task_id']!=effective_task_id
            changed_authorized=False
            if prior and prior['authorized']:
                if saved:
                    changed_authorized=any((saved[k] or '')!=values[k] for k in note_fields)
                else:
                    changed_authorized=any(values[k]!=prior[k] for k in ('recipient','role','route'))
            authorization_changed=bool(not prior or not prior['authorized'] or any(prior[k]!=values[v] for k,v in [('recipient','recipient'),('role','role'),('route','route'),('evidence','verification_evidence')]))
            if verified:
                status='verified'
                if authorization_changed:
                    con.execute('INSERT INTO contact_authorizations VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET recipient=excluded.recipient,role=excluded.role,route=excluded.route,evidence=excluded.evidence,authorized=1,updated_at=excluded.updated_at',(oid,values['recipient'],values['role'],values['route'],values['verification_evidence'],1,now))
                    self.store.event('contact_authorization_recorded',{'recipient':values['recipient'],'role':values['role'],'route':values['route'],'evidence':values['verification_evidence'],'authorized':True},opportunity_id=oid,con=con)
                if task and task_is_contact:
                    refs=task['evidence_refs']
                    resolution=f"Verified purchasing contact {values['contact_name'] or values['role']} at {values['recipient']} via {values['route']} route. Verification: {values['verification_evidence']}"
                    con.execute('INSERT INTO investigation_resolutions VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET resolution=excluded.resolution,updated_at=excluded.updated_at',(task_id,oid,resolution,now))
                    updated=con.execute("UPDATE investigation_tasks SET status='resolved' WHERE id=? AND status='pending'",(task_id,))
                    if updated.rowcount!=1:raise ValueError('This contact check was completed before the save. Refresh the account and review the current task.')
                    self.store.event('investigation_resolved',{'task_id':task_id,'resolution':resolution,'evidence_refs':refs},opportunity_id=oid,con=con)
                    task_status='resolved'
                queue_reassessment=authorization_changed or note_changed or bool(task and task_is_contact)
            elif prior and prior['authorized'] and changed_authorized:
                con.execute('UPDATE contact_authorizations SET authorized=0,updated_at=? WHERE opportunity_id=?',(now,oid))
                self.store.event('contact_authorization_revoked',{'reason':'Contact details changed without renewed verification'},opportunity_id=oid,con=con)
                queue_reassessment=True
            elif was_verified_note and not note_changed:status='verified'
            note_changed=note_changed or not saved or saved['status']!=status
            if note_changed:
                con.execute('''INSERT INTO contact_clearance_notes(opportunity_id,task_id,contact_name,recipient,role,phone,route,distributor,verification_evidence,status,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET task_id=excluded.task_id,contact_name=excluded.contact_name,recipient=excluded.recipient,role=excluded.role,phone=excluded.phone,route=excluded.route,distributor=excluded.distributor,verification_evidence=excluded.verification_evidence,status=excluded.status,updated_at=excluded.updated_at''',
                    (oid,effective_task_id,values['contact_name'],values['recipient'],values['role'],values['phone'],values['route'],values['distributor'],values['verification_evidence'],status,now))
                self.store.event('contact_clearance_saved',{'status':status,'task_id':task_id,'contact_name':values['contact_name'],'recipient':values['recipient'],'role':values['role'],'phone':values['phone'],'route':values['route'],'distributor':values['distributor'],'verification_evidence':values['verification_evidence']},opportunity_id=oid,con=con)
            if verified and note_changed:queue_reassessment=True
            if was_verified_note and status!='verified':queue_reassessment=True
            authorized_now=True if verified else bool(prior and prior['authorized'] and not changed_authorized)
        job_id=self.store.queue_analysis(oid,investigation=True) if queue_reassessment else None
        return {'status':status,'task_status':task_status,'job_id':job_id,'requires_reassessment':queue_reassessment,'authorized':authorized_now}

    def resolve_investigation(self,task_id,resolution):
        from .store import utcnow
        if not resolution.strip():raise ValueError('Explain the verified finding; completion alone is not evidence')
        rows=self.store.rows("SELECT * FROM investigation_tasks WHERE id=? AND status='pending'",(task_id,))
        if not rows:raise ValueError('Pending investigation task not found')
        task=rows[0]
        from .task_purpose import task_purpose
        if task_purpose(task)['contact_check']:
            auth=self.store.rows('SELECT 1 FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(task['opportunity_id'],))
            if not auth:raise ValueError('Contact checks require a verified purchasing recipient and route. Use Contact Clearance; a note alone cannot clear this blocker.')
        with self.store.connect(write=True) as con:
            con.execute('INSERT INTO investigation_resolutions VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET resolution=excluded.resolution,updated_at=excluded.updated_at',(task_id,task['opportunity_id'],resolution,utcnow()))
            con.execute("UPDATE investigation_tasks SET status='resolved' WHERE id=?",(task_id,))
            self.store.event('investigation_resolved',{'task_id':task_id,'resolution':resolution},opportunity_id=task['opportunity_id'],con=con)
        return {'job_id':self.store.queue_analysis(task['opportunity_id'],investigation=True),'requires_reassessment':True}

    def query_accounts(self,q='',workflow='recovery',signal=None,queue=None,status=None,actionable_only=False,uncontacted=False,min_decline_cents=None,sort='decline',offset=0,limit=25):
        from .store import STOPPED_STATUSES
        from .signal_views import disposition
        rows=self.get_opportunities(workflow,queue)
        if isinstance(rows,dict):rows=rows.get('accounts',rows.get('items',[]))
        sent={r['opportunity_id'] for r in self.store.rows('SELECT DISTINCT opportunity_id FROM outbox')}
        term=q.strip().casefold()
        rows=[r for r in rows if (not term or term in (r['name']+' '+r.get('state','')+' '+' '.join(self.account(r['id'])['evidence'].get('aliases',[]))).casefold())
              and (not signal or (r.get('partial_decline') if signal=='partial' else signal in r.get('signals',[])))
              and (not status or r['status']==status) and (min_decline_cents is None or r['decline_cents']>=min_decline_cents)
              and (not uncontacted or r['id'] not in sent and r['status'] not in ('approved','awaiting_response'))
              and (not actionable_only or not r['holds'] and r['status'] not in STOPPED_STATUSES|{'agent_held','no_action'} and r.get('assessment')=='pursue')]
        priorities={'human_decision':0,'actionable':1,'verification':2,'unassessed':3,'no_action':4}
        sorters={'decline':lambda r:(-r['decline_cents'],r['id']),'name':lambda r:(r['name'],r['id']),'urgency':lambda r:(priorities[disposition(r)],-r['decline_cents'],r['id'])}
        if sort not in sorters:raise ValueError('Unsupported sort')
        rows.sort(key=sorters[sort]);return page(rows,offset,limit)

    def account_view(self,oid,section='summary',offset=0,limit=25):
        d=self.detail(oid)
        if section=='summary':return {k:v for k,v in d.items() if k not in ('drafts','events','jobs','outbox','outcomes','trends','evidence')}|{'assessment':d['assessment'],'limits':d['evidence'].get('limits',[])}
        if section=='evidence':return {'account_id':oid,'evidence_hash':d['evidence_hash'],'evidence':d['evidence'],'definitions':DEFINITIONS}
        if section=='history':return {'account_id':oid,'trends':d['trends'],'events':page(d['events'],offset,limit)}
        if section=='conversation':return self.conversation(oid)
        if section in ('drafts','jobs','outbox','outcomes','events'):return {'account_id':oid,**page(d[section],offset,limit)}
        raise ValueError('Unsupported section')

    def account_orders(self,oid,year=None,status=None,offset=0,limit=25):
        from .reporting import _audited_orders
        a=self.account(oid)
        if a['workflow']!='recovery':raise ValueError('Real prospects have no fictional order history')
        scans=self.store.rows('SELECT summary FROM scans ORDER BY created_at DESC LIMIT 1')
        hashes=json.loads(scans[0]['summary']).get('hashes',{}) if scans else {}
        if not {'orders','products'}<=hashes.keys():raise ValueError('No audited order snapshot is available')
        rows=_audited_orders(str(self.settings.data_dir),hashes['orders'],hashes['products'])
        rows=rows[rows.source_row.isin(a['evidence'].get('source_rows',[]))]
        if year:rows=rows[rows.date.dt.year==year]
        if status:rows=rows[rows.status==status]
        rows=rows.sort_values(['order_date','source_row'],ascending=[False,True]).drop(columns=['date'])
        return {'account_id':oid,'note':'Exact assigned source rows; open or future-dated records are shown as evidence and are not booked revenue.',**page(rows.to_dict('records'),offset,limit)}

    def action_groups(self,group_id=None,offset=0,limit=25):
        data=self.work()
        if group_id:
            g=next((g for g in data['groups'] if g['id']==group_id),None)
            if not g:raise ValueError('Action group not found')
            return {k:v for k,v in g.items() if k!='members'}|{'members':page(g['members'],offset,limit)}
        return {k:v for k,v in data.items() if k!='groups'}|{'groups':page([{k:v for k,v in g.items() if k!='members'}|{'member_count':len(g['members'])} for g in data['groups']],offset,limit)}

    def signal_page(self,key,offset=0,limit=25):
        data=self.signal_view(key)
        return {**data,'actions':page(data['actions'],offset,limit),'chart':page(data['chart'],offset,limit)}

    def campaign_page(self,cid=None,offset=0,limit=25,responses_only=False):
        from .operations import campaign_view
        if cid:
            data=campaign_view(self.store,cid)
            if responses_only:
                members=[]
                for m in data['members']:
                    thread=self.conversation(m['opportunity_id'])
                    if any(x['direction']=='inbound' for x in thread['messages']):members.append({'account_id':m['opportunity_id'],'conversation':thread})
                return {'campaign_id':cid,'responses':page(members,offset,limit)}
            return {**data,'members':page(data['members'],offset,limit)}
        return page([{k:v for k,v in c.items() if k!='members'} for c in self.campaigns()],offset,limit)

    def list_jobs(self,status=None,kind=None,account_id=None,offset=0,limit=25):
        return page([j for j in self.jobs() if (not status or j['status']==status) and (not kind or j['kind']==kind) and (not account_id or j['opportunity_id']==account_id)],offset,limit)

    def job_result(self,jid):
        rows=self.store.rows('SELECT * FROM jobs WHERE id=?',(jid,))
        if not rows:raise ValueError('Job not found')
        row=rows[0];row['payload']=json.loads(row['payload'])
        events=self.store.rows('SELECT * FROM events WHERE job_id=? ORDER BY id',(jid,))
        for e in events:e['details']=json.loads(e['details'])
        return {'job':row,'events':events,'drafts':self.store.rows('SELECT id,version,status FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 5',(row['opportunity_id'],))}

    def review_outreach(self,draft_ids):
        from .reporting import valid_draft
        if not draft_ids or len(draft_ids)>100 or len(set(draft_ids))!=len(draft_ids):raise ValueError('Choose 1–100 distinct drafts')
        snapshots=[]
        for did in draft_ids:
            d=self.draft(did)
            if d['status']!='awaiting_approval' or not valid_draft(self.store,d):raise ValueError('Draft is no longer eligible for review: '+did)
            snapshots.append({k:d[k] for k in ('id','opportunity_id','version','recipient','subject','body')}|{'snapshot_hash':self.store.draft_hash(d)})
        rid=uuid4().hex;expiry=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
        with self.store.connect(write=True) as con:
            con.execute('INSERT INTO approval_reviews VALUES(?,?,?,NULL,NULL)',(rid,json.dumps(snapshots),expiry))
        return {'review_id':rid,'expires_at':expiry,'drafts':snapshots,'required_confirmation':'APPROVE '+rid,'instruction':'Show every exact recipient, subject and body to the human. Only call decide_outreach after explicit confirmation. All delivery is simulated.'}

    def get_review(self,review_id):
        rows=self.store.rows('SELECT * FROM approval_reviews WHERE id=?',(review_id,))
        if not rows:raise ValueError('Review not found')
        r=rows[0]
        return {'review_id':r['id'],'drafts':json.loads(r['snapshots']),'expires_at':r['expires_at'],'decision':r['decision'],'result':json.loads(r['result']) if r['result'] else None}

    def decide_review(self,review_id,approve,confirmation):
        from .store import utcnow
        decision='approved' if approve else 'rejected'
        expected=('APPROVE ' if approve else 'REJECT ')+review_id
        if confirmation!=expected:raise ValueError('Explicit confirmation must match the review ID and decision')
        with self.store.connect(write=True) as con:
            review=con.execute('SELECT * FROM approval_reviews WHERE id=?',(review_id,)).fetchone()
            if not review:raise ValueError('Review not found')
            if review['decision']:
                if review['decision']!=decision:raise ValueError('Review already has a different decision')
                return json.loads(review['result'])
            if datetime.fromisoformat(review['expires_at'])<datetime.now(timezone.utc):raise ValueError('Review expired; review the messages again')
            snapshots=json.loads(review['snapshots'])
            for snap in snapshots:
                d=con.execute('SELECT * FROM drafts WHERE id=?',(snap['id'],)).fetchone()
                if not d or d['status']!='awaiting_approval' or self.store.draft_hash(d)!=snap['snapshot_hash']:raise ValueError('Draft changed; review current versions again')
                self.store._decide(con,d['id'],approve)
            result={'review_id':review_id,'status':decision,'draft_ids':[s['id'] for s in snapshots],'delivery_mode':'simulated','job_ids':[r['id'] for r in con.execute("SELECT id FROM jobs WHERE dedupe_key IN ("+','.join('?' for s in snapshots)+')',['deliver:'+s['id'] for s in snapshots])] if approve else []}
            con.execute('UPDATE approval_reviews SET decision=?,result=? WHERE id=?',(decision,json.dumps(result),review_id))
            con.execute("UPDATE campaigns SET status=? WHERE id IN (SELECT campaign_id FROM campaign_accounts WHERE opportunity_id IN ("+','.join('?' for s in snapshots)+'))',('partially_reviewed',*[s['opportunity_id'] for s in snapshots]))
            self.store.event('review_confirmed',{'review_id':review_id,'decision':decision,'draft_ids':result['draft_ids']},con=con)
        return result

    def approved_sends(self,draft_ids):
        result=[]
        for did in draft_ids:
            d=self.draft(did)
            sent=self.store.rows('SELECT id,created_at FROM outbox WHERE draft_id=?',(did,))
            jobs=self.store.rows('SELECT id,status,error FROM jobs WHERE dedupe_key=?',('deliver:'+did,))
            approvals=self.store.rows("SELECT snapshot_hash FROM approvals WHERE draft_id=? AND decision='approved' ORDER BY created_at DESC LIMIT 1",(did,))
            if not sent and (d['status']!='approved' or not approvals or approvals[0]['snapshot_hash']!=self.store.draft_hash(d)):raise ValueError('Draft does not have current approval')
            result.append({'draft_id':did,'sent':bool(sent),'outbox':sent,'jobs':jobs})
        return {'items':result,'note':'Approval already queues delivery. The same worker executes it once. Retry only a failed job; a cancelled delivery requires a new draft and approval.'}

    def regenerate_draft(self,did,version,request_id):
        from .reporting import valid_draft
        d=self.draft(did)
        if version!=d['version'] or d['status']!='awaiting_approval' or not valid_draft(self.store,d):raise ValueError('Only a current unapproved draft can be regenerated')
        analysis=json.loads(d['analysis']);payload={'evidence_hash':d['evidence_hash'],'portfolio':True,'allow_simulation':True,'regenerate_id':did,'regenerate_hash':self.store.draft_hash(d)}
        if analysis.get('reply_to'):payload['outcome_id']=analysis['reply_to'];kind='reply'
        else:
            kind='prospect_qualify' if self.account(d['opportunity_id'])['workflow']=='prospecting' else 'analyze'
            if analysis.get('outreach_kind')=='followup':
                sent=self.store.rows('SELECT draft_id FROM outbox WHERE opportunity_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(d['opportunity_id'],))
                payload['followup_of']=sent[0]['draft_id'] if sent else None
        return {'job_id':self.store.enqueue(kind,payload,d['opportunity_id'],f'regenerate:{did}:{request_id}')}


def regeneration_current(store,con,job):
    old=job['payload'].get('regenerate_id')
    if not old:return True
    d=con.execute('SELECT * FROM drafts WHERE id=?',(old,)).fetchone()
    return bool(d and d['status']=='awaiting_approval' and store.draft_hash(d)==job['payload'].get('regenerate_hash'))
