"""Account-scoped evidence access. Original rows are never edited or rematched here."""
import csv,json
from collections import defaultdict
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from .data import digest,canonical,cents

ENGINE_VERSION='commercial-5.3'
SCHEMA='''CREATE TABLE IF NOT EXISTS investigation_tasks(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, context_hash TEXT NOT NULL,
 title TEXT NOT NULL, owner TEXT NOT NULL, reason TEXT NOT NULL, evidence_refs TEXT NOT NULL,
 blocking INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);'''

_CONTEXT_FIELDS = {
    'messages': 'id,direction,subject,body,reply_to',
    'outcomes': 'id,kind,note,amount_cents,reference',
    'customer_context': 'contact,channel,outreach_policy',
    'contact_authorizations': 'recipient,role,route,evidence,authorized,updated_at',
    'investigation_resolutions': 'task_id,resolution,updated_at',
    'contact_clearance_notes': 'task_id,contact_name,recipient,role,phone,route,distributor,verification_evidence,status,updated_at',
}


def _context_material(account):
    from .action_policy import SOFT_HOLDS
    material = {'evidence_hash': account['evidence_hash'] if account else None}
    holds = set(json.loads(account['holds'])) if account else set()
    if 'possible_missing_state_alias' in holds and not holds - SOFT_HOLDS:
        material['execution_policy_revision'] = 'missing-state-neutral-support-v1'
    for table in _CONTEXT_FIELDS:
        if table != 'contact_clearance_notes':
            material[table] = []
    material['reassessment_epoch'] = None
    return material


def _context_hashes(con, accounts):
    """Use the same evidence fields and row ordering for one account or a whole read snapshot."""
    materials = {oid: _context_material(account) for oid, account in accounts.items()}
    if not materials:
        return {}
    single = len(materials) == 1
    predicate = '= ?' if single else 'IN (SELECT value FROM json_each(?))'
    ids = (next(iter(materials)) if single else json.dumps(list(materials)),)
    for table, fields in _CONTEXT_FIELDS.items():
        verified = " AND status='verified'" if table == 'contact_clearance_notes' else ''
        query = f'SELECT opportunity_id,{fields} FROM {table} WHERE opportunity_id {predicate}{verified} ORDER BY rowid'
        for row in con.execute(query, ids):
            record = dict(row)
            materials[record.pop('opportunity_id')].setdefault(table, []).append(record)
    names = ['reassessment:' + oid for oid in materials]
    for row in con.execute(f'SELECT name,value FROM controls WHERE name {predicate}',
                           (names[0] if single else json.dumps(names),)):
        materials[row['name'].removeprefix('reassessment:')]['reassessment_epoch'] = row['value']
    return {oid: digest(material) for oid, material in materials.items()}


def context_hash(con,oid):
    row = con.execute('SELECT evidence_hash,holds FROM opportunities WHERE id=?',(oid,)).fetchone()
    return _context_hashes(con, {oid: row})[oid]


def assessment_eligible(assessment):
    from .store import utcnow
    return bool(assessment and assessment.get('engine_version') == ENGINE_VERSION
                and (not assessment.get('reassess_at') or assessment['reassess_at'] > utcnow()))


def current_assessment(con,oid,assessment):
    return assessment_eligible(assessment) and assessment.get('context_hash') == context_hash(con,oid)

@lru_cache(maxsize=12)
def source_records(path,expected):
    from pathlib import Path
    p=Path(path)
    if sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('Source evidence changed; run a new scan before investigating')
    with p.open(newline='') as f:return [dict(ref=f'{p.stem}:{i}',**r) for i,r in enumerate(csv.DictReader(f),2)]

class EvidenceAccess:
    def __init__(self,store,job,settings):
        self.store,self.job,self.settings=store,job,settings
        self.opp=store.opportunity(job['opportunity_id']);self.oid=self.opp['id'];self.accessed=set();self.refs=set();self.outputs={}
        with store.connect() as con:self.version=context_hash(con,self.oid)
        scans=store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
        self.hashes=json.loads(scans[0]['summary']).get('hashes',{}) if scans else {}
        self.finding_review = (job.get('kind')=='analyze'
            and len(self.opp['evidence'].get('source_rows',[]))>100
            and bool(store.rows('SELECT 1 FROM investigation_resolutions WHERE opportunity_id=? LIMIT 1',(self.oid,))))

    def finding_packet(self):
        """Cover the complete assigned ledger once. Exact detail remains available to both reviewers."""
        self.overview()
        self.purchasing()
        self.relationships()
        page=self.outputs['relationships:0']['next_offset']
        while page is not None:
            self.relationships(page)
            page=self.outputs[f'relationships:{page}']['next_offset']
        self.catalogue()
        self.identity()
        self.previous()
        return self.outputs

    def record(self,section,value):
        if self.finding_review and section=='overview':
            # Canonical signal IDs, amounts and payloads already appear in detected_signals.
            account=dict(value['account'])
            account.pop('commercial_signals',None)
            account['assigned_source_rows']=len(account.pop('source_rows',[]))
            value={**value,'account':account}
        if self.finding_review and section=='identity':
            for candidate in value['related_records']:
                # Keep other identity candidates' evidence. Only the current account is indexed here.
                if candidate['id']==self.oid:
                    candidate['assigned_source_rows']=len(candidate.pop('source_rows') or [])
        self.accessed.add(section);self.outputs[section]=value
        def refs(v):
            if isinstance(v,dict):
                if 'ref' in v:self.refs.add(v['ref'])
                for x in v.values():refs(x)
            elif isinstance(v,list):
                for x in v:refs(x)
        refs(value)
        self.store.event('evidence_retrieved',{'section':section,'context_hash':self.version,'evidence':value},self.job['id'],self.oid)
        return json.dumps(value,default=str)
    def source(self,name):
        expected=self.hashes.get(name)
        if not expected:raise ValueError('An audited source snapshot is required')
        path=self.settings.data_dir/(name+'.csv')
        if sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Source evidence changed; run a new scan before investigating')
        return source_records(str(path),expected)
    def orders(self):
        ids={f'orders:{n}' for n in self.opp['evidence'].get('source_rows',[])}
        return [r for r in self.source('orders') if r['ref'] in ids]
    def overview(self):
        e=self.opp['evidence']
        from .action_policy import SOFT_HOLDS,SAFE_SCOPES
        return self.record('overview',{'ref':'account','kind':'deterministic_account_evidence','account':e,
            'status':self.opp['status'],'context_hash':self.version,
            'commercial_eligibility':__import__('clearline.commercial',fromlist=['eligibility']).eligibility(self.store,self.oid),
            'detected_signals':self.store.rows('SELECT * FROM commercial_signals WHERE opportunity_id=? AND active=1',(self.oid,)),
            'internal_resolutions':self.store.rows('SELECT * FROM investigation_resolutions WHERE opportunity_id=?',(self.oid,)),
            'contact_clearance_notes':self.store.rows("SELECT * FROM contact_clearance_notes WHERE opportunity_id=? AND status='verified'",(self.oid,)),
            'application_policy':{'ref':'workflow_policy','kind':'application_configuration',
                'followup_days':self.settings.followup_days,
                'hard_hold_reasons':sorted(set(self.opp['holds'])-SOFT_HOLDS),
                'reviewed_scopes_under_warnings':sorted(SAFE_SCOPES),
                'missing_state_warning':'Unassigned same-name transactions may conceal purchases. Do not merge them, claim complete totals or assert inactivity. If no separate identity conflict exists, neutral support or channel clarification for the established account is permitted after review.',
                'scheduling':'One follow-up is scheduled after the first approved simulated send; replies and stopped outcomes cancel it. Existing pending jobs provide actual due dates. A due follow-up prepares a new draft requiring fresh approval.'},
            'constraints':{'business_date':self.settings.as_of,'all_identities':'fictional; no web enrichment',
            'distributor_sell_through':'unavailable; do not request it from distributors or make it a prerequisite',
            'duplicate_rows':'25 duplicate-looking excess rows retained; line identity is unresolved',
            'CRM_notes':'source facts about a note, not a verified current customer need; last_contacted does not date the note',
            'communications':'simulated; live clock governs message scheduling, business cutoff governs CSV comparisons',
            'source_holds':'Remain attached to financial evidence. Identity conflicts block outreach. Operational/channel warnings require action-specific review, not blanket stopping.'},
            'manifest':{'order_rows':len(e.get('source_rows',[])),'messages':self.store.rows('SELECT COUNT(*) n FROM messages WHERE opportunity_id=?',(self.oid,))[0]['n']}})
    def purchasing(self,offset=0,status='all'):
        if self.finding_review:
            if offset<0:raise ValueError('Invalid evidence page')
            if status=='all':
                if offset:return json.dumps({'complete':True,'note':'The complete purchase summary is page 0. For exact records use raw, order:<ID> or ref:<source ref>.'})
                return self.purchase_summary()
            if status=='raw' or status.startswith(('order:','ref:')):
                rows=self.orders()
                if status!='raw':
                    field,_,key=status.partition(':')
                    rows=[r for r in rows if r['order_id' if field=='order' else 'ref']==key]
                return self.record(f'purchases:{status}:{offset}',{'ref':'purchasing','rows':rows[offset:offset+100],
                    'total':len(rows),'next_offset':offset+100 if offset+100<len(rows) else None})
        if offset<0 or status not in ('all','open','credit_memo','invoiced'):raise ValueError('Invalid evidence page')
        rows=self.orders();selected=[r for r in rows if status=='all' or r['status']==status]
        # These counts describe source dates, not inventory usage or confirmed fulfillment.
        periods={}
        for year in ('2025','2026'):
            eligible=[r for r in rows if r['order_date']>=year+'-01-01' and r['order_date']<year+'-11-01']
            dates=sorted({r['order_date'] for r in eligible if r['status']=='invoiced' and cents(r['line_total'])>0})
            periods[year]={'distinct_invoice_dates':dates,'purchase_dates':len(dates),'open_value_cents':sum(cents(r['line_total']) for r in eligible if r['status']=='open'),'credit_cents':sum(cents(r['line_total']) for r in eligible if r['status']=='credit_memo')}
        return self.record(f'purchases:{status}:{offset}',{'ref':'purchasing','kind':'source_rows_and_calculations','periods':periods,
            'units':{'unit_price':'USD dollars','line_total':'USD dollars','*_cents':'integer USD cents','qty':'packs or training sessions'},'rows':selected[offset:offset+100],'total':len(selected),'next_offset':offset+100 if offset+100<len(selected) else None,
            'note':'Rows preserve original quantity, unit price, line total, channel, identity, and date; open orders are not booked revenue or known overdue.'})

    def purchase_summary(self):
        rows=self.orders()
        tasks=self.store.rows('SELECT evidence_refs FROM investigation_tasks WHERE opportunity_id=? AND status IN (\'pending\',\'resolved\')',(self.oid,))
        refs={ref for t in tasks for ref in json.loads(t['evidence_refs'])}
        exceptions={r['order_id'] for r in rows if r['status']!='invoiced' or r['ref'] in refs}
        exceptions.update(order.removesuffix('-CR') for order in tuple(exceptions))
        invoices=defaultdict(list)
        detail=[]
        for r in rows:
            if r['status']=='invoiced':
                invoices[(r['order_date'][:7],r['sku'],r['sales_channel'])].append(r)
            if (r['order_id'] in exceptions or not r['order_date']
                or Decimal(r['qty'])<=0 or cents(r['line_total'])<=0):
                detail.append(r)
        summaries=[]
        for (month,sku,channel),group in sorted(invoices.items()):
            summaries.append([month or 'undated',sku,channel,len(group),
                str(sum(Decimal(r['qty']) for r in group)),sum(cents(r['line_total']) for r in group)])
        dates=sorted({r['order_date'] for r in rows if r['status']=='invoiced' and r['order_date'] and cents(r['line_total'])>0})
        comparable_periods={}
        for year in ('2025','2026'):
            start,end=year+'-01-01',year+'-11-01'
            period=[r for r in rows if start<=r['order_date']<end]
            comparable_periods[year]={'purchase_dates':sum(start<=date<end for date in dates),
                'open_value_cents':sum(cents(r['line_total']) for r in period if r['status']=='open'),
                'credit_cents':sum(cents(r['line_total']) for r in period if r['status']=='credit_memo')}
        return self.record('purchases:all:0',{'ref':'purchasing','total':len(rows),'next_offset':None,
            'invoice_columns':['month','sku','channel','source_lines','qty_packs_or_sessions','invoiced_value_cents'],
            'invoice_totals':summaries,'distinct_positive_invoice_dates':dates,'january_october':comparable_periods,'detail_rows':detail,
            'note':'Complete assigned history, including duplicate-looking lines. Invoice totals group every invoice once. Detail rows overlap those totals and include open orders, credits, companion lines, task-linked orders, undated and nonpositive lines. Detail unit_price/line_total are USD dollars. Open lines are not booked revenue. Use raw pages, order:<ID> or ref:<source ref> for exact records when needed.'})
    def relationships(self,offset=0):
        if offset<0:raise ValueError('Invalid page')
        e=self.opp['evidence'];key=self.opp['account_key']
        crm=[r for r in self.source('crm_accounts') if (e.get('crm_id') and r['crm_id']==e['crm_id']) or canonical(r['account_name'],r['state'])[0]==key or r['ref'] in {f'crm_accounts:{n}' for n in e.get('crm_source_rows',[])}]
        messages=self.store.rows('SELECT * FROM messages WHERE opportunity_id=? ORDER BY created_at,rowid',(self.oid,))
        for m in messages:m['ref']='message:'+m['id'];m['kind']='simulated_customer_statement' if m['direction']=='inbound' else 'approved_simulated_outbound'
        ctx=self.store.rows('SELECT * FROM customer_context WHERE opportunity_id=?',(self.oid,))
        contact_clearance=self.store.rows("SELECT * FROM contact_clearance_notes WHERE opportunity_id=? AND status='verified'",(self.oid,))
        contact_authorizations=self.store.rows('SELECT * FROM contact_authorizations WHERE opportunity_id=?',(self.oid,))
        tasks=self.store.rows('SELECT * FROM commercial_tasks WHERE opportunity_id=?',(self.oid,))
        outcomes=self.store.rows('SELECT * FROM outcomes WHERE opportunity_id=? ORDER BY created_at,rowid',(self.oid,))
        for x in outcomes:x['ref']='outcome:'+x['id']
        inquiries={}
        if self.finding_review and offset==0:
            from .internal_inquiries import list_inquiries
            inquiries['internal_inquiries']=[{
                'id':i['id'],'task_ids':i['task_ids'],'status':i['status'],'simulated_send_at':i['sent_at'],
                'replies':[{'reported_body':r['body'],'record_refs':r['record_refs'],'confirmed_task_ids':r['confirmed_task_ids']} for r in i['replies']]
            } for i in list_inquiries(self.store,self.oid)['inquiries']]
        return self.record(f'relationships:{offset}',{'ref':'relationship','crm':crm,'context':ctx,'messages':messages[offset:offset+100],**inquiries,
            'total_messages':len(messages),'next_offset':offset+100 if offset+100<len(messages) else None,'outcomes':outcomes,
            'tasks':tasks,'investigation_tasks':self.store.rows("SELECT id,title,owner,reason,evidence_refs,blocking,status FROM investigation_tasks WHERE opportunity_id=?",(self.oid,)),
            'contact_clearance':contact_clearance,'contact_authorizations':contact_authorizations,
            'pending_jobs':self.store.rows("SELECT kind,due_at,status FROM jobs WHERE opportunity_id=? AND status IN ('queued','running')",(self.oid,))})
    def identity(self):
        key=self.opp['account_key'];sig='|'.join(key.split('|')[1:]);related=[]
        for r in self.store.rows("SELECT id,account_key,name,state,evidence FROM opportunities WHERE workflow='recovery' AND active=1"):
            if sig and '|'.join(r['account_key'].split('|')[1:])==sig:
                e=json.loads(r.pop('evidence'));r.update(aliases=e.get('aliases'),source_rows=e.get('source_rows'),holds=e.get('holds'));related.append(r)
        public=[r for r in self.source('public_agencies') if canonical(r['agency_name'],r['state'])[0]==key]
        return self.record('identity',{'ref':'identity','kind':'identity_candidates_not_confirmed_merges','public_matches':public,'related_records':related,
            'note':'Same-name entities in different states are distinct. Do not merge or remove source holds through model judgment.'})
    def catalogue(self):
        return self.record('catalogue',{'ref':'catalogue','kind':'fictional_product_records','products':self.source('products'),
            'note':'List prices are historical, not an authorized current quote. No unsupported efficacy, discounts or training availability promises.'})
    def previous(self,offset=0,full=False):
        rows=self.store.rows("SELECT id,details,created_at FROM events WHERE opportunity_id=? AND kind='agent_decision' ORDER BY id DESC",(self.oid,))
        for r in rows:r['ref']='assessment:'+str(r['id']);r['details']=json.loads(r['details'])
        drafts=self.store.rows('SELECT id,version,status,subject,body FROM drafts WHERE opportunity_id=? ORDER BY version DESC',(self.oid,))
        page_size=1 if full else 10
        page=rows[offset:offset+page_size]
        if self.finding_review and not full:
            for row in page:
                row['details']={k:row['details'][k] for k in ('decision','objective','recommended_action','strategy','review_failed') if k in row['details']}
        key='previous_full' if full else 'previous'
        return self.record(f'{key}:{offset}',{'ref':'previous_work','kind':'AI_interpretations_not_source_truth','assessments':page,
            'total':len(rows),'next_offset':offset+page_size if offset+page_size<len(rows) else None,'drafts':drafts})
    def tools(self):
        from agents import function_tool
        @function_tool
        def get_account_overview()->str:
            """Read audited account facts, limitations, workflow state and available evidence inventory."""
            return self.overview()
        @function_tool
        def get_purchase_history(offset:int=0,status:str='all')->str:
            """Read account purchases. On finding reviews, all returns complete totals and material lines; raw, order:<ID> or ref:<source ref> retrieves exact detail. Open/credit_memo/invoiced filter rows; use lowercase status and offsets from the result."""
            return self.purchasing(offset,status)
        @function_tool
        def get_relationship_history(offset:int=0)->str:
            """Read full CRM rows, customer context, simulated messages, outcomes, tasks and scheduled work. Page messages by 100."""
            return self.relationships(offset)
        @function_tool
        def investigate_identity()->str:
            """Inspect public identity matches and same-stem account candidates without merging them."""
            return self.identity()
        @function_tool
        def get_product_catalogue()->str:
            """Read supplied product and training records; historical list prices are not a current quote."""
            return self.catalogue()
        @function_tool
        def get_previous_work(offset:int=0,full:bool=False)->str:
            """Read previous AI decisions and drafts. Finding reviews summarize old decisions. Set full=true and offset to retrieve one full assessment. These are not verified facts."""
            return self.previous(offset,full)
        @function_tool
        def get_product_associations()->str:
            """Read reproducible portfolio product associations with sample sizes and reliability; not proof of demand."""
            return self.record('associations',{'ref':'associations','rows':self.opp['evidence'].get('product_associations',[])})
        return [get_product_associations,get_account_overview,get_purchase_history,get_relationship_history,investigate_identity,get_product_catalogue,get_previous_work]
