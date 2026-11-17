"""Fictional-agency screening. Source rows are evidence, never contact permission."""
import csv,json
from collections import defaultdict,Counter
from pathlib import Path
from .data import basic,canonical,digest
from .store import utcnow

VERSION='screening-1.1'
QUALIFICATION_ENGINE='agency-qualification-1'
CATEGORIES=('verified_existing','possible_existing_channel','unverified_prospect','ambiguous_identity','unsuitable')
OUTCOMES=('qualified','investigate','human_verification','defer','reject')
SCHEMA="""
CREATE TABLE IF NOT EXISTS agency_screenings(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,state TEXT NOT NULL,agency_type TEXT NOT NULL,
 classification TEXT NOT NULL,priority INTEGER NOT NULL,evidence_hash TEXT NOT NULL,
 evidence TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agency_priority ON agency_screenings(active,priority,name);
CREATE TABLE IF NOT EXISTS agency_qualifications(
 job_id TEXT PRIMARY KEY REFERENCES jobs(id),agency_id TEXT NOT NULL REFERENCES agency_screenings(id),
 evidence_hash TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agency_reports ON agency_qualifications(agency_id,evidence_hash,created_at);
CREATE INDEX IF NOT EXISTS agency_jobs ON jobs(json_extract(payload,'$.agency_id'),json_extract(payload,'$.evidence_hash'),created_at) WHERE kind='agency_qualify';
CREATE TABLE IF NOT EXISTS agency_screening_runs(
 fingerprint TEXT PRIMARY KEY,summary TEXT NOT NULL,created_at TEXT NOT NULL);
"""
LIMITS=[
 'Fictional identities: do not look these organizations up on the real web.',
 'Unmatched does not mean net-new; unidentified distributor sales conceal customers.',
 'Product fit and institutional size do not establish demand, budget or purchasing intent.',
 'No verified contacts or authorization are provided; qualification never enables outreach.',
 'HIDTA is context only. Fiscal year-end is not a procurement deadline.',
]
FIT={
 'county_jail':['CL-MAIL50','CL-FS10'], 'state_prison':['CL-MAIL50','CL-FS10'],
 'sheriff':['CL-PAT25','CL-MP10'], 'police_dept':['CL-PAT25','CL-MP10'],
 'facility_security':['CL-FS10','CL-MAIL50'],
 'probation_parole':[], 'drug_court':[],
}

def read_sources(folder):
    from hashlib import sha256
    tables={};hashes={}
    for name in ('public_agencies','orders','crm_accounts','products'):
        path=Path(folder)/(name+'.csv');hashes[name]=sha256(path.read_bytes()).hexdigest()
        with path.open(newline='',encoding='utf-8-sig') as f:
            tables[name]=[dict(row,ref=f'{name}:{i}') for i,row in enumerate(csv.DictReader(f),2)]
    return tables,hashes

def screen(store,settings):
    tables,hashes=read_sources(settings.data_dir)
    fingerprint=digest(dict(version=VERSION,hashes=hashes,as_of=settings.as_of))
    latest=store.rows('SELECT fingerprint FROM agency_screening_runs ORDER BY created_at DESC,rowid DESC LIMIT 1')
    if latest and latest[0]['fingerprint']==fingerprint:
        from .screening_rank import rebuild
        rebuild(store)
        return summary(store)
    agencies=tables['public_agencies']; grouped=defaultdict(list);key_groups=defaultdict(set)
    exact_index=defaultdict(list);alias_index=defaultdict(list);missing_state=defaultdict(list)
    for row in agencies:
        identity={k:v for k,v in row.items() if k!='ref'};gid=digest(identity)[:24]
        grouped[gid].append(row)
        key,_,_=canonical(row['agency_name'],row['state'])
        key_groups[key].add(gid)
    records=[]
    for row in tables['orders']:
        if row['order_date'] and row['order_date']>settings.as_of:continue
        name=row['bill_to_account'] if row['sales_channel']=='direct' else row['end_customer']
        if not name:continue
        item=dict(row,identity_name=name,identity_state=row['ship_to_state'],identity_city=row['ship_to_city'],source='order')
        records.append(item)
    records.extend(dict(r,identity_name=r['account_name'],identity_state=r['state'],identity_city='',source='crm') for r in tables['crm_accounts'])
    for r in records:
        exact_index[(basic(r['identity_name']),r['identity_state'])].append(r)
        key,kind,stem=canonical(r['identity_name'],r['identity_state']);alias_index[key].append(r)
        if not r['identity_state']:missing_state[basic(r['identity_name'])].append(r)
    # Observed segment breadth uses distinct canonical buyers, not transaction frequency.
    segment=defaultdict(set);product_patterns=defaultdict(lambda:defaultdict(set))
    for r in records:
        key,kind,_=canonical(r['identity_name'],r['identity_state'])
        if r['source']=='order' and key and r['status']=='invoiced' and float(r['qty'])>0:
            segment[kind].add(key);product_patterns[kind][r['sku']].add(key)
    items=[]
    for gid,rows in grouped.items():
        a=rows[0];key,kind,stem=canonical(a['agency_name'],a['state'])
        candidates={r['ref']:r for r in exact_index[(basic(a['agency_name']),a['state'])]+alias_index.get(key,[])+missing_state.get(basic(a['agency_name']),[])}
        relations=list(candidates.values())
        exact=[r for r in relations if basic(r['identity_name'])==basic(a['agency_name']) and r['identity_state']==a['state']]
        direct=[r for r in exact if r['source']=='order' and r['sales_channel']=='direct' and r['status']=='invoiced' and float(r['qty'])>0 and basic(r['identity_city'])==basic(a['city']) and a['city']]
        channel=[r for r in relations if (r['source']=='order' and r['sales_channel']=='distributor') or (r['source']=='crm' and 'distributor' in r.get('notes','').lower())]
        conflicts=[]
        if not key or len(a['state'])!=2 or not a['city'] or not a['agency_name']:conflicts.append('Missing or conflicting identity attributes')
        if len(key_groups[key])>1:conflicts.append('Multiple agency records share a canonical name and state; no automatic merge')
        cities={basic(r['identity_city']) for r in exact if r['identity_city']}
        if cities and cities!={basic(a['city'])}:conflicts.append('Purchasing and agency location evidence conflicts')
        if kind!='unknown' and kind!=a['agency_type']:conflicts.append('Name and supplied agency type conflict')
        if conflicts:category='ambiguous_identity';reason='; '.join(conflicts)
        elif direct:category='verified_existing';reason='Exact normalized name, state and city match positive direct invoiced purchases'
        elif relations:category='possible_existing_channel';reason='Prior CRM, order, alias or distributor evidence requires relationship verification'
        elif a['agency_type'] not in FIT:category='unsuitable';reason='No supported institutional application in the supplied product catalogue'
        else:category='unverified_prospect';reason='No matched named history; net-new status and channel remain unverified'
        skus=[s for s in FIT.get(a['agency_type'],[]) if s in {p['sku'] for p in tables['products']}]
        patterns={'ref':'patterns:'+a['agency_type'],'segment':a['agency_type'],'distinct_named_buyers':len(segment[a['agency_type']]),'product_buyers':{s:len(v) for s,v in product_patterns[a['agency_type']].items()},'interpretation':'Descriptive named purchasing only; canonical aliases may remain unresolved. Not conversion probability or need.'}
        # Tiers make the choice reproducible without invented conversion scores.
        priority=1 if category=='unverified_prospect' and skus and a['agency_type'] in ('county_jail','state_prison') else 2 if category=='unverified_prospect' and skus else 3 if category=='unverified_prospect' else 4 if category in ('possible_existing_channel','ambiguous_identity') else 5
        ranking_reason={1:'Custodial institution with plausible screening applications; verify operational need first',2:'Potential physical screening application; institutional workflow must be verified',3:'Catalogue use is not established for this segment; investigate purpose before spending sales time',4:'Resolve existing relationship or identity before prospect qualification',5:'Exclude from new-prospect shortlist; existing customer or unsupported institution'}[priority]
        evidence={'version':VERSION,'as_of':settings.as_of,'source_hashes':hashes,'provenance':'fictional_agency_dataset','agency':rows,'classification':category,'classification_reason':reason,'identity_conflicts':conflicts,'relationship_records':relations,'known_distributor_evidence':bool(channel),'products':tables['products'],'fit_hypothesis_skus':skus,'segment_patterns':patterns,'ranking_reason':ranking_reason,'limits':LIMITS}
        items.append((gid,a['agency_name'],a['state'],a['agency_type'],category,priority,digest(evidence),json.dumps(evidence),utcnow()))
    counts=dict(Counter(x[4] for x in items));run={'source_records':len(agencies),'unique_records':len(items),'exact_duplicate_rows':len(agencies)-len(items),'classifications':counts,'fingerprint':fingerprint,'hashes':hashes,'version':VERSION}
    with store.connect(write=True) as con:
        con.execute('UPDATE agency_screenings SET active=0')
        con.executemany('INSERT INTO agency_screenings(id,name,state,agency_type,classification,priority,evidence_hash,evidence,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,state=excluded.state,agency_type=excluded.agency_type,classification=excluded.classification,priority=excluded.priority,evidence_hash=excluded.evidence_hash,evidence=excluded.evidence,active=1,updated_at=excluded.updated_at',items)
        con.execute('INSERT OR REPLACE INTO agency_screening_runs VALUES(?,?,?)',(fingerprint,json.dumps(run),utcnow()))
        store.event('agency_screening_complete',run,con=con)
    from .screening_rank import rebuild
    rebuild(store)
    return summary(store)

def detail(store,aid):
    rows=store.rows('SELECT * FROM agency_screenings WHERE id=? AND active=1',(aid,))
    if not rows:raise ValueError('Screened agency not found')
    row=rows[0];row['evidence']=json.loads(row['evidence'])
    q=store.rows('SELECT result,created_at FROM agency_qualifications WHERE agency_id=? AND evidence_hash=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(aid,row['evidence_hash']))
    row['qualification']=json.loads(q[0]['result']) if q else None
    from .screening_rank import get
    from .screening_workflow import state,context_hash,prerequisites
    row['ranking']=get(store,aid)
    row['workflow']=state(store,aid)
    row['context_hash']=context_hash(row['evidence_hash'],row['workflow']['information'],row['workflow']['activity_revision'])
    row['qualification_current']=bool(row['qualification'] and row['qualification'].get('context_hash',row['evidence_hash'])==row['context_hash'] and row['qualification'].get('qualification_engine',QUALIFICATION_ENGINE)==QUALIFICATION_ENGINE)
    row['last_assessed_at']=q[0]['created_at'] if q else None
    row['outreach_prerequisites']=prerequisites(row)
    row['history']=store.rows('SELECT * FROM agency_activity WHERE agency_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100',(aid,))
    row['drafts']=store.rows('SELECT id,version,recipient,subject,body,status,created_at FROM drafts WHERE opportunity_id=? ORDER BY version DESC',('agency:'+aid,))
    row['jobs']=store.rows("SELECT id,status,error,attempts FROM jobs WHERE kind='agency_qualify' AND json_extract(payload,'$.agency_id')=? AND json_extract(payload,'$.evidence_hash')=? ORDER BY created_at DESC,rowid DESC LIMIT 3",(aid,row['evidence_hash']))
    return row

def search_state(value):
    from .account_profile import STATES
    term=value.strip().casefold()
    if term=='district of columbia':return 'DC'
    return next((code for code,name in STATES.items() if term in (code.casefold(),name.casefold())),None)

def listing(store,q='',classification='',outcome='',sort='priority',offset=0,limit=50):
    if classification and classification not in CATEGORIES:raise ValueError('Unknown classification')
    if outcome and outcome not in OUTCOMES+('not_assessed','queued','failed','needs_reassessment','accepted','held','rejected','any_rejection','qualification_reject'):raise ValueError('Unknown qualification status')
    if sort not in ('priority','name','state') or not 1<=limit<=100 or offset<0:raise ValueError('Invalid sort or page size')
    rows=store.rows("""SELECT a.*, ar.score,ar.explanation ranking,aw.decision user_decision,aw.rationale,aw.information,aw.stage,
    (SELECT result FROM agency_qualifications r WHERE r.agency_id=a.id AND r.evidence_hash=a.evidence_hash ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1) assessment,
    (SELECT status FROM jobs j WHERE j.kind='agency_qualify' AND json_extract(j.payload,'$.agency_id')=a.id AND json_extract(j.payload,'$.evidence_hash')=a.evidence_hash ORDER BY j.created_at DESC,j.rowid DESC LIMIT 1) job_status
    FROM agency_screenings a LEFT JOIN agency_rankings ar ON ar.agency_id=a.id LEFT JOIN agency_workflow aw ON aw.agency_id=a.id WHERE active=1""")
    items=[]
    query=q.strip().casefold()
    state=search_state(query)
    from .screening_workflow import activity_revisions
    activity=activity_revisions(store)
    for r in rows:
        e=json.loads(r.pop('evidence'));a=json.loads(r.pop('assessment') or 'null');r['qualification_status']=a['decision']['outcome'] if a else 'queued' if r['job_status'] in ('queued','running') else 'failed' if r['job_status'] in ('failed','blocked_config') else 'not_assessed'
        from .screening_workflow import context_hash
        h=context_hash(r['evidence_hash'],json.loads(r.pop('information') or '{}'),activity.get(r['id']))
        if a and (a.get('context_hash',r['evidence_hash'])!=h or a.get('qualification_engine',QUALIFICATION_ENGINE)!=QUALIFICATION_ENGINE):r['qualification_status']='needs_reassessment'
        r['user_decision']=r['user_decision'] or 'new';r['ranking']=json.loads(r['ranking'] or 'null')
        if r['user_decision']=='rejected' and outcome not in ('rejected','any_rejection','qualification_reject'):continue
        if classification and r['classification']!=classification:continue
        if outcome=='any_rejection':
            if r['qualification_status']!='reject' and r['user_decision']!='rejected':continue
        elif outcome=='qualification_reject':
            if r['qualification_status']!='reject':continue
        elif outcome and outcome not in (r['qualification_status'],r['user_decision']):continue
        name=r['name'].casefold()
        city=(e['agency'][0].get('city') or '').casefold()
        if state:
            if r['state']!=state:continue
            r['matched_on']='state'
        elif query:
            if query in name:r['matched_on']='name'
            elif query in city:r['matched_on']='city'
            else:continue
        r.update(product_fit=e['fit_hypothesis_skus'],ranking_reason=e['ranking_reason'],source_refs=[x['ref'] for x in e['agency']],next_action=a['decision']['next_task'] if a else e['classification_reason'],review_passed=a['review_passed'] if a else None)
        if r['user_decision'] in ('held','rejected'):r['next_action']=('On hold: ' if r['user_decision']=='held' else 'Discarded: ')+(r['rationale'] or '')
        elif r['stage'] and r['stage']!='not_contacted':r['next_action']='Review recorded '+r['stage'].replace('_',' ')+' activity before any further outreach.'
        items.append(r)
    if sort=='priority':items.sort(key=lambda r:(0 if r['ranking'] and r['ranking']['eligible'] and r['user_decision'] not in ('held','rejected') and r['stage'] in (None,'not_contacted') and r['qualification_status'] not in ('reject','defer') else 1,-(r['score'] or 0),r['name'],r['id']))
    else:items.sort(key=lambda r:(r[sort],r['name'],r['id']))
    if query and not state and sort=='priority':
        items.sort(key=lambda r:(r['matched_on']!='name',r['name'].casefold()!=query))
    return dict(items=items[offset:offset+limit],total=len(items),offset=offset,limit=limit)

def current_reports(store):
    # SQL counts only current accepted-or-explicitly-held reports, never stale reports.
    reports=store.rows("""SELECT a.id,r.result,a.evidence_hash,aw.information FROM agency_qualifications r JOIN agency_screenings a ON a.id=r.agency_id AND a.evidence_hash=r.evidence_hash AND a.active=1 LEFT JOIN agency_workflow aw ON aw.agency_id=a.id WHERE r.rowid=(SELECT r2.rowid FROM agency_qualifications r2 WHERE r2.agency_id=a.id AND r2.evidence_hash=a.evidence_hash ORDER BY created_at DESC,rowid DESC LIMIT 1)""")
    from .screening_workflow import context_hash,activity_revisions
    activity=activity_revisions(store)
    reports=[r for r in reports if json.loads(r['result']).get('context_hash',r['evidence_hash'])==context_hash(r['evidence_hash'],json.loads(r['information'] or '{}'),activity.get(r['id'])) and json.loads(r['result']).get('qualification_engine',QUALIFICATION_ENGINE)==QUALIFICATION_ENGINE]
    return reports

def summary(store):
    runs=store.rows('SELECT summary FROM agency_screening_runs ORDER BY created_at DESC,rowid DESC LIMIT 1')
    result=json.loads(runs[0]['summary']) if runs else {'source_records':0,'unique_records':0,'classifications':{}}
    reports=current_reports(store)
    result['qualification_counts']=dict(Counter(json.loads(r['result'])['decision']['outcome'] for r in reports));result['assessed']=len(reports);result['limits']=LIMITS
    rejected={r['id'] for r in reports if json.loads(r['result'])['decision']['outcome']=='reject'}
    held={r['id'] for r in reports if json.loads(r['result'])['decision']['outcome']=='defer'}
    for r in store.rows('SELECT a.id,a.classification,w.decision FROM agency_screenings a LEFT JOIN agency_workflow w ON w.agency_id=a.id WHERE a.active=1'):
        if r['classification']=='unsuitable' or r['decision']=='rejected':rejected.add(r['id'])
        if r['decision']=='held':held.add(r['id'])
    result['excluded_records']=len(rejected);result['held_or_deferred']=len(held-rejected)
    result['jobs']=store.rows("SELECT status,COUNT(*) count FROM jobs WHERE kind='agency_qualify' GROUP BY status")
    result['user_decisions']={r['decision']:r['n'] for r in store.rows('SELECT decision,COUNT(*) n FROM agency_workflow GROUP BY decision')}
    result['awaiting_qualification']=listing(store,classification='unverified_prospect',outcome='not_assessed',limit=1)['total']
    from .screening_budget import summary as budget_summary
    result['budget']=budget_summary(store)
    return result

def queue(store,settings,aid,evidence_hash):
    if not settings.screening_enabled:raise ValueError('Prospect Screening is not enabled')
    row=detail(store,aid)
    if row['evidence_hash']!=evidence_hash:raise ValueError('Evidence changed; reload before qualification')
    if row['workflow']['decision'] in ('held','rejected'):raise ValueError('Accept the prospect before requesting another assessment')
    if row['qualification_current']:return {'job_id':None,'reused':True,'qualification':row['qualification']}
    return {'job_id':store.enqueue('agency_qualify',{'agency_id':aid,'evidence_hash':evidence_hash,'context_hash':row['context_hash'],'version':VERSION},key='agency:'+aid+':'+row['context_hash']+':'+VERSION)}

def save_result(store,job,result):
    with store.connect(write=True) as con:
        live=con.execute('SELECT evidence_hash FROM agency_screenings WHERE id=? AND active=1',(job['payload']['agency_id'],)).fetchone()
        state=con.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()
        if not live or live['evidence_hash']!=job['payload']['evidence_hash'] or state['status']!='running':raise ValueError('Cancelled or stale qualification; no result saved')
        from .screening_workflow import current_context,log
        current=current_context(con,job['payload']['agency_id'],live['evidence_hash'])
        if job['payload'].get('context_hash',live['evidence_hash'])!=current:raise ValueError('Verified information changed during qualification')
        result={**result,'context_hash':current,'qualification_engine':QUALIFICATION_ENGINE}
        con.execute('INSERT OR IGNORE INTO agency_qualifications VALUES(?,?,?,?,?)',(job['id'],job['payload']['agency_id'],live['evidence_hash'],json.dumps(result),utcnow()))
        log(con,job['payload']['agency_id'],'qualification',result['decision']['outcome'],{'job_id':job['id'],'review_passed':result.get('review_passed',False)})


def queue_shortlist(store,settings,limit=10):
    if not settings.screening_enabled:raise ValueError('Prospect Screening is not enabled')
    if not 1<=limit<=10:raise ValueError('Qualify at most ten candidates per batch')
    rows=listing(store,classification='unverified_prospect',outcome='not_assessed',limit=100)['items']
    rows=[r for r in rows if r['priority']<=2 and r['user_decision'] not in ('held','rejected')][:limit]
    return {'job_ids':[queue(store,settings,r['id'],r['evidence_hash'])['job_id'] for r in rows], 'note':'Bounded internal qualification only; no outreach or automatic continuation.'}
