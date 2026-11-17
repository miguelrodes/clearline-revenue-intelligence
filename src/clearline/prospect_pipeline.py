"""One sales-facing projection of original CSV records and independently sourced real prospects."""
import json
import math
import re
from collections import Counter
from datetime import date
from urllib.parse import urlencode, urlsplit, urlunsplit

from .data import basic, digest
from .prospect_comparables import comparable_purchases
from .prospects import PARTNER_URL, PRODUCT_URL
from .screening import FIT, QUALIFICATION_ENGINE, search_state
from .screening_rank import VERSION, explain, positive, scale_field
from .screening_workflow import activity_revisions, context_hash
from .store import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospect_candidate_profiles(
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id),
 origin TEXT NOT NULL CHECK(origin IN ('real_web','real_manual')),
 identity_key TEXT NOT NULL UNIQUE, attributes TEXT NOT NULL, sources TEXT NOT NULL,
 field_sources TEXT NOT NULL, rank_fingerprint TEXT NOT NULL, ranking TEXT NOT NULL,
 stale_bundle TEXT, discovered_run TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prospect_discovery_members(
 run_id TEXT NOT NULL, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 disposition TEXT NOT NULL, PRIMARY KEY(run_id,opportunity_id));
CREATE TABLE IF NOT EXISTS prospect_candidate_decisions(
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id), decision TEXT NOT NULL,
 rationale TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
HIGH_PRIORITY = 70
ORIGINS = ('fictional_csv', 'real_web', 'real_manual')
ATTRIBUTES = ('name','state','segment','city','county','jail_beds','population_served','in_hidta_region','fy_end','operational_context','official_url')


def _url(value):
    try:
        parts=urlsplit(str(value or '').strip())
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.port not in (None,443):
            raise ValueError
        return urlunsplit(('https',parts.hostname.lower(),parts.path.rstrip('/'),parts.query,''))
    except (ValueError,UnicodeError) as exc:
        raise ValueError('A verified HTTPS institutional source is required.') from exc


def _host(url):
    return urlsplit(url).hostname.removeprefix('www.')


def _identity(name,state):
    return state+'|'+basic(name)


def _web_input(candidate):
    attrs={k:candidate[k] for k in ATTRIBUTES if candidate.get(k) not in (None,'')}
    attrs['name']=str(attrs.get('name','')).strip()
    attrs['state']=str(attrs.get('state','')).strip().upper()
    if not (2<=len(attrs['name'])<=300 and re.fullmatch(r'[A-Z]{2}',attrs['state'])):
        raise ValueError('An institution name and state are required.')
    attrs['segment']=str(attrs.get('segment','unknown')).strip()
    capacity_field=scale_field(attrs['segment'])
    if capacity_field and candidate.get('capacity') and not attrs.get(capacity_field):
        attrs[capacity_field]=candidate['capacity']
    url=attrs['official_url']=_url(attrs.get('official_url'))
    sources=[dict(s,url=_url(s['url'])) for s in candidate.get('sources',[]) if s.get('url')]
    identity=next((s for s in sources if s['url']==url),None)
    if identity is None:
        identity={'url':url}
        sources.insert(0,identity)
    for target,source in [('title','source_title'),('retrieved_at','retrieved_at'),('identity_quote','identity_quote')]:
        if candidate.get(source) and not identity.get(target):identity[target]=candidate[source]
    quote=identity.get('identity_quote') or identity.get('excerpt') or identity.get('quote')
    if not quote or not identity.get('title') or not identity.get('retrieved_at'):
        raise ValueError('Real discovery requires the official identity excerpt, page title and retrieval date.')
    date.fromisoformat(identity['retrieved_at'][:10])
    if basic(attrs['name']) not in basic(quote):
        raise ValueError('The official source excerpt must name the institution.')
    identity['identity_quote']=quote
    urls={s['url'] for s in sources}
    field_sources={}
    for k in attrs:
        u=_url((candidate.get('field_sources') or {}).get(k) or url)
        if u not in urls:raise ValueError('Candidate fields must cite a saved source.')
        field_sources[k]=u
    return attrs,sources,field_sources


def _rank(con, attrs):
    kind=attrs['segment']
    patterns={'distinct_named_buyers':0,'product_buyers':{}}
    row=con.execute("""SELECT json_extract(evidence,'$.segment_patterns'),json_extract(evidence,'$.fit_hypothesis_skus')
                       FROM agency_screenings WHERE active=1 AND agency_type=? LIMIT 1""",(kind,)).fetchone()
    skus=FIT.get(kind,[])
    if row:patterns=json.loads(row[0]);skus=json.loads(row[1])
    benchmark=con.execute("SELECT MAX(json_extract(evidence,'$.segment_patterns.distinct_named_buyers')) FROM agency_screenings WHERE active=1").fetchone()[0] or 1
    field=scale_field(kind);values=[]
    if field:
        values=sorted(v for (entry,) in con.execute("SELECT json_extract(evidence,?) FROM agency_screenings WHERE active=1 AND agency_type=?",('$.agency[0].'+field,kind))
                      if (v:=positive(entry)))
    cap=values[math.ceil(.95*len(values))-1] if values else 0
    agency={**attrs,'agency_name':attrs['name'],'agency_type':kind}
    rank=explain({'agency':[agency],'classification':'unverified_prospect','fit_hypothesis_skus':skus,'segment_patterns':patterns},{kind:cap},benchmark)
    rank['restriction']='Real buying and distributor relationships are unknown. Comparisons use fictional case records.'
    if field and not positive(attrs.get(field)):
        next(f for f in rank['factors'] if f['key']=='scale')['reason']='No sourced capacity for this institution. No scale points awarded.'
    return rank


def upsert_web(con,candidate,run_id,as_of='2026-11-01'):
    """Called only with source-verified discovery output, inside the caller's write transaction."""
    attrs,sources,refs=_web_input(candidate)
    key=_identity(attrs['name'],attrs['state'])
    prior=con.execute('SELECT * FROM prospect_candidate_profiles WHERE identity_key=?',(key,)).fetchone()
    oid=prior['opportunity_id'] if prior else None
    origin=prior['origin'] if prior else 'real_web'
    if prior and _host(json.loads(prior['attributes'])['official_url'])!=_host(attrs['official_url']):
        raise ValueError('Conflicting official domains for this real identity require verification.')
    if not prior:
        # The same official directory URL can list multiple distinct facilities.
        for row in con.execute("SELECT id,name,evidence FROM opportunities WHERE workflow='prospecting' AND state=?",(attrs['state'],)):
            if basic(attrs['name'])!=basic(row['name']):continue
            old_url=(json.loads(row['evidence']).get('profile') or {}).get('official_url')
            if not old_url or _host(_url(old_url))!=_host(attrs['official_url']):
                raise ValueError('A matching real name has conflicting identity evidence.')
            oid=row['id']
            # Attach independent verification without rewriting existing manual research or its draft.
            origin='real_manual'
            break
    old_attrs=json.loads(prior['attributes']) if prior else {}
    merged={**old_attrs,**attrs}
    old_sources=json.loads(prior['sources']) if prior else []
    # A new retrieval date alone has no bearing on the score or research cache.
    retained={s['url']:s for s in old_sources}
    for s in sources:
        old=retained.get(s['url'])
        if not old or {k:v for k,v in s.items() if k!='retrieved_at'}!={k:v for k,v in old.items() if k!='retrieved_at'}:retained[s['url']]=s
    sources=list(retained.values());refs={**(json.loads(prior['field_sources']) if prior else {}),**refs}
    scan=con.execute('SELECT fingerprint FROM agency_screening_runs ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
    score_fields={k:v for k,v in merged.items() if k not in ('official_url','operational_context')}
    rank_key=digest([VERSION,score_fields,scan[0] if scan else None])
    rank=json.loads(prior['ranking']) if prior and prior['rank_fingerprint']==rank_key else _rank(con,merged)
    changed=not prior or old_attrs!=merged or old_sources!=sources or json.loads(prior['field_sources'])!=refs
    disposition='created' if not oid else 'updated' if changed or prior['rank_fingerprint']!=rank_key else 'unchanged'
    if not oid:oid=digest('real_web:'+key)[:20]
    if disposition!='unchanged':
        opp=con.execute("SELECT evidence FROM opportunities WHERE id=? AND workflow='prospecting'",(oid,)).fetchone()
        evidence=json.loads(opp[0]) if opp else {'provenance':'real_public_web','as_of':as_of,'customer_relationship':'unknown','research':None}
        stale=prior['stale_bundle'] if prior else None
        if changed and origin=='real_web':
            if prior and evidence.get('research'):stale=digest(evidence['research'])
            profile={'key':'real_web:'+key,'name':merged['name'],'state':merged['state'],'origin':'real_web',
                     'official_url':merged['official_url'],'allowed_domains':sorted({_host(s['url']) for s in sources}|{'swabtek.com'}),
                     'seed_urls':list(dict.fromkeys([merged['official_url'],*[s['url'] for s in sources], PRODUCT_URL,PARTNER_URL])),
                     'discovery_attributes':merged, 'field_sources':refs,
                     'selection_reason':merged.get('operational_context') or 'Official institutional identity verified. Product need requires research.',
                     'seed_notes':[s['identity_quote'] for s in sources if s.get('identity_quote')]}
            evidence['profile']=profile
            con.execute("""INSERT INTO opportunities(id,account_key,name,state,decline_cents,evidence,evidence_hash,holds,status,active,updated_at,workflow)
                           VALUES(?,?,?,?,0,?,?,'[]','needs_research',1,?,'prospecting')
                           ON CONFLICT(id) DO UPDATE SET name=excluded.name,state=excluded.state,
                           evidence=excluded.evidence,evidence_hash=excluded.evidence_hash,updated_at=excluded.updated_at""",
                        (oid,profile['key'],merged['name'],merged['state'],json.dumps(evidence),digest(evidence),utcnow()))
        con.execute("""INSERT INTO prospect_candidate_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(opportunity_id) DO UPDATE SET attributes=excluded.attributes,sources=excluded.sources,
                       field_sources=excluded.field_sources,rank_fingerprint=excluded.rank_fingerprint,ranking=excluded.ranking,
                       stale_bundle=excluded.stale_bundle,updated_at=excluded.updated_at""",
                    (oid,origin,key,json.dumps(merged),json.dumps(sources),json.dumps(refs),rank_key,json.dumps(rank),stale,run_id,utcnow()))
    con.execute('INSERT OR IGNORE INTO prospect_discovery_members VALUES(?,?,?)',(run_id,oid,disposition))
    return oid,disposition


def save_discoveries(store,candidates,as_of,run_id):
    counts=Counter();ids=[]
    with store.connect(write=True) as con:
        for candidate in candidates:
            oid,result=upsert_web(con,candidate,run_id,as_of)
            if oid not in ids:
                ids.append(oid);counts[result]+=1
    return {'candidate_ids':ids,**{k:counts[k] for k in ('created','updated','unchanged')}}


def _latest_report(store,oid,evidence_hash):
    from .operations import latest_assessment
    report = latest_assessment(store, oid)
    return report if report and report.get('evidence_hash') == evidence_hash else None


_ACTIVITY_LABELS = {
    'human_approved': 'Email approved', 'human_rejected': 'Draft rejected',
    'outbox_simulated': 'Simulated delivery recorded', 'inbound_received': 'Simulated reply recorded',
    'agent_decision': 'Assessment saved',
    'draft_revised': 'Draft revised', 'prospect_contact_verified': 'Purchasing contact verified',
    'research_saved': 'Research saved', 'prospect_manual_decision': 'Screening decision saved',
    'outcome_recorded': 'Sales outcome recorded', 'approval_invalidated': 'Earlier approval withdrawn',
}


def _last_activity(store, oid):
    kinds=tuple(_ACTIVITY_LABELS)
    saved=store.rows(f"""SELECT kind,created_at FROM events WHERE opportunity_id=?
                        AND kind IN ({','.join('?' for _ in kinds)}) ORDER BY id DESC LIMIT 1""",(oid,*kinds))
    if saved:
        return dict(label=_ACTIVITY_LABELS[saved[0]['kind']],at=saved[0]['created_at'])
    return dict(label='Prospect record saved',at=None)


def _real_rows(store,comparisons,only=None,detail=False):
    suffix=' AND o.id=?' if only else ''
    rows=store.rows("""SELECT o.*,p.attributes,p.sources,p.field_sources,p.ranking,p.stale_bundle,p.origin,
                              p.discovered_run,d.decision AS manual_decision,d.rationale AS manual_reason,
                              EXISTS(SELECT 1 FROM outbox b WHERE b.opportunity_id=o.id AND b.delivery_mode='simulated'
                                AND b.draft_id=COALESCE((SELECT dd.id FROM drafts dd
                                  WHERE dd.opportunity_id=o.id AND dd.evidence_hash=o.evidence_hash
                                  ORDER BY dd.version DESC LIMIT 1),b.draft_id)) AS delivered,
                              EXISTS(SELECT 1 FROM messages m WHERE m.opportunity_id=o.id AND m.direction='inbound') AS received_reply
                       FROM opportunities o
                       LEFT JOIN prospect_candidate_profiles p ON p.opportunity_id=o.id
                       LEFT JOIN prospect_candidate_decisions d ON d.opportunity_id=o.id
                       WHERE o.workflow='prospecting' AND o.active=1"""+suffix,(only,) if only else ())
    for r in rows:
        oid=r['id'];e=json.loads(r['evidence']);profile=e.get('profile') or {};research=e.get('research') or {}
        rank=json.loads(r['ranking'] or '{}');origin=r['origin'] or 'real_manual'
        attrs=json.loads(r['attributes'] or '{}')
        sources=json.loads(r['sources'] or '[]');institutional=[s for s in research.get('sources',[]) if s.get('category')=='institution']
        verified=bool(sources and r['origin']) or bool(institutional and profile.get('official_url') and
            any(_host(s['url'])==_host(profile['official_url']) for s in institutional))
        attrs.setdefault('name',r['name']);attrs.setdefault('state',r['state'])
        attrs.setdefault('segment',profile.get('segment') or ('corrections_department' if 'department of correction' in r['name'].lower() else 'unknown'))
        attrs.setdefault('official_url',profile.get('official_url'))
        source=attrs['official_url']
        if not sources:
            sources=institutional or ([{'title':r['name'],'url':source,'retrieved_at':None}] if source else [])
        # Legacy manually curated records lack a source-derived facility size or a type-matched buyer cohort.
        # Without case data for a matching segment, the score stays unknown.
        verified_evidence=bool(research.get('sources'))
        current_research=verified_evidence and r['stale_bundle']!=digest(research)
        assessment=_latest_report(store,oid,r['evidence_hash']) if current_research else None
        job=store.rows("""SELECT id,kind,status,error FROM jobs WHERE opportunity_id=? AND kind IN
                    ('prospect_research','prospect_qualify','pipeline_research','pipeline_qualify') ORDER BY created_at DESC,rowid DESC LIMIT 1""",(oid,))
        job=job[0] if job else {}
        ds=store.rows('SELECT id,version,status,subject,body,recipient,evidence_hash,analysis FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1',(oid,))
        draft=ds[0] if ds and ds[0]['evidence_hash']==r['evidence_hash'] else None
        auth=store.rows('SELECT recipient,role,route,evidence,authorized FROM contact_authorizations WHERE opportunity_id=? AND authorized=1',(oid,))
        auth=auth[0] if auth else None
        permission_missing=False
        if origin=='real_web' and assessment and assessment['decision']=='pursue':
            from .prospect_access import permitted_web_draft
            with store.connect() as con:
                permission_missing=not draft or not permitted_web_draft(con,r,json.loads(draft['analysis']),draft)
        if draft:draft.pop('analysis',None)
        manual=r['manual_decision']
        stop=manual in ('hold','reject') or r['status'] in ('rejected','lost','opted_out','no_action','closed','deferred','outreach_paused') or bool(json.loads(r['holds']))
        job_status=job.get('status')
        research_eligible=verified and not stop and not (assessment and assessment.get('decision') in ('hold','reject'))
        q=(assessment or {}).get('qualification') or ('unassessed' if not verified_evidence else 'unassessed' if current_research else 'stale')
        if stop or (assessment and assessment.get('decision') in ('hold','reject')):
            rejected=manual=='reject' or r['status'] in ('rejected','lost','opted_out') or (assessment or {}).get('decision')=='reject'
            stage='rejected' if rejected else 'hold'
            next_step=r['manual_reason'] or (assessment or {}).get('recommended_action') or 'Keep this prospect out of outreach.'
        elif r['status']=='approved':
            stage='awaiting_delivery'
            delivery=store.rows("""SELECT status FROM jobs WHERE opportunity_id=? AND kind='deliver'
                                   AND json_extract(payload,'$.draft_id')=? ORDER BY rowid DESC LIMIT 1""",
                                (oid,draft['id'] if draft else None))
            status=delivery[0]['status'] if delivery else None
            if status=='queued':next_step='The approved email is queued for simulated delivery.'
            elif status=='running':next_step='Simulated delivery is in progress. Wait for its outbox record.'
            else:next_step='Check the delivery job before proceeding. Delivery of the approved email is unconfirmed.'
        elif r['status']=='awaiting_response' and r['delivered']:
            reminders=store.rows("SELECT due_at FROM jobs WHERE opportunity_id=? AND kind='followup' AND status IN ('queued','running') ORDER BY due_at LIMIT 1",(oid,))
            if reminders and reminders[0]['due_at']<=utcnow():
                stage='follow_up';next_step='Review the follow-up due for the previously simulated introduction.'
            else:
                stage='awaiting_response';next_step='A simulated delivery was recorded. Check for a response.'
                if reminders:next_step+=' Follow-up scheduled for '+reminders[0]['due_at'][:10]+'.'
        elif r['received_reply'] and r['status'] in ('replied','response_prepared','qualified','quoted'):
            stage='in_conversation';next_step='Review the saved conversation and its next step.'
        elif permission_missing:
            stage='needs_verification';next_step='Verify the intended recipient, role, permission and buying route before approving outreach.'
        elif r['status']=='awaiting_approval' and draft and draft['status']=='awaiting_approval' and assessment and assessment['decision']=='pursue':
            stage='awaiting_approval';next_step='Review the saved discovery email and its proposed purchasing route.'
        elif r['status']=='awaiting_response':
            stage='needs_verification';next_step='Check the delivery history. No simulated outbox record is available.'
        elif r['received_reply']:
            stage='in_conversation';next_step='Review the recorded reply and the latest assessment.'
        elif job_status in ('queued','running'):
            stage='selected_for_research' if job_status=='queued' and job['kind'] in ('pipeline_research','prospect_research') else 'research_in_progress'
            next_step='Wait for the selected research and qualification to finish.'
        elif job_status in ('failed','blocked_config') and not current_research:
            stage='needs_verification';next_step='Inspect the research job and resolve its recorded blocker.'
        elif current_research:
            stage='research_completed';next_step=(assessment or {}).get('recommended_action') or 'Review the research evidence and qualification status.'
        elif manual=='select_for_research' and not current_research:
            stage='selected_for_research';next_step='Review the research budget and start the selected investigation.'
        elif not verified:
            stage='needs_verification';next_step='Verify this lead’s identity from an official institutional source.'
        else:
            stage='screened' if rank else 'discovered';next_step='Inspect the score and sources, then select this institution for research if justified.'
        shortlisted=research_eligible and not current_research and stage in ('screened','discovered','selected_for_research') and job_status not in ('queued','running')
        baseline=comparisons.get(attrs['segment'])
        row=dict(id=oid,name=r['name'],state=r['state'],segment=attrs['segment'],origin=origin,stage=stage,qualification=q,
                 score=rank.get('score'),score_version=rank.get('version'),factors=rank.get('factors',[]),verified=verified,
                 researched=current_research,researchable=research_eligible and job_status not in ('queued','running'),
                 awaiting_research=shortlisted,high_priority=bool(rank.get('eligible') and verified and not stop and (rank.get('score') or 0)>=HIGH_PRIORITY),
                 reason=(rank.get('factors') or [{}])[0].get('reason') or profile.get('selection_reason',''),
                 comparison=('Fictional Clearline comparison: '+baseline) if baseline else 'No comparable facility-level spending benchmark is established for this institution.',
                 next_action=next_step,href='/accounts/'+oid,detail_href='/screening?candidate='+oid,
                 outreach_permission_required=permission_missing,manual_decision=manual,discovery_run=r.get('discovered_run'),
                 has_conversation=stage=='in_conversation' or bool(r['received_reply'] and stage not in ('hold','rejected')))
        if stage=='awaiting_approval':
            row['action_href']=row['href']+'#prospect-outreach'
        elif stage=='research_completed':
            row['action_href']=row['href']+'#prospect-research'
        elif stage=='needs_verification' and (permission_missing or not verified):
            row['action_href']=row['detail_href']+('#prospect-permission' if permission_missing else '#prospect-evidence')
        else:
            row['action_href']=row['detail_href']
        if detail:
            missing=[k for k in ('city','county',scale_field(attrs['segment']),'operational_context','in_hidta_region') if k and attrs.get(k) in (None,'')]
            row.update(attributes=attrs,fields=attrs,sources=sources,field_sources=json.loads(r['field_sources'] or '{}'),
                       missing_fields=missing,identity_confidence='verified_official' if verified else 'needs_verification',
                       research=research or None,assessment=assessment,draft=draft,job=job or None,outreach_authorization=auth,
                       latest_activity=_last_activity(store,oid),
                       customer_relationship=e.get('customer_relationship','unknown'),limitations=[
                            'Real customer and distributor relationships are unknown without real CRM evidence.',
                            'Scores prioritize investigation. Public evidence alone does not establish buying intent or contact permission.'])
        yield row


def _csv_rows(store,comparisons,only=None,detail=False):
    from .screening import detail as agency_detail
    revisions=activity_revisions(store)
    sql="""SELECT a.id,a.name,a.state,a.agency_type,a.classification,a.evidence_hash,r.score,r.explanation,
             w.stage AS workflow_stage,w.decision AS disposition,w.information,w.rationale,
             q.result, o.status AS outreach_status FROM agency_screenings a
             LEFT JOIN agency_rankings r ON r.agency_id=a.id
             LEFT JOIN agency_workflow w ON w.agency_id=a.id
             LEFT JOIN opportunities o ON o.id='agency:'||a.id
             LEFT JOIN agency_qualifications q ON q.rowid=(SELECT q2.rowid FROM agency_qualifications q2
                 WHERE q2.agency_id=a.id AND q2.evidence_hash=a.evidence_hash ORDER BY q2.created_at DESC,q2.rowid DESC LIMIT 1)
             WHERE a.active=1"""
    for r in store.rows(sql+(' AND a.id=?' if only else ''),(only,) if only else ()):
        a=r['id'];segment=r['agency_type'];rank=json.loads(r['explanation'] or '{}');assessment=json.loads(r['result'] or 'null')
        if assessment and (assessment.get('context_hash',r['evidence_hash'])!=context_hash(r['evidence_hash'],json.loads(r['information'] or '{}'),revisions.get(a)) or
                           assessment.get('qualification_engine',QUALIFICATION_ENGINE)!=QUALIFICATION_ENGINE):
            assessment=None
        q=(assessment or {}).get('decision') or {};outcome=q.get('outcome') or 'unassessed'
        classification=r['classification'];disposition=r['disposition'];activity=r['workflow_stage']
        if disposition=='held' or outcome=='defer' or classification=='verified_existing':stage='hold'
        elif disposition=='rejected' or outcome=='reject' or classification=='unsuitable':stage='rejected'
        elif activity in ('response_received','advanced'):stage='in_conversation'
        elif activity=='contact_attempted' or r['outreach_status']=='awaiting_response':stage='awaiting_response'
        elif r['outreach_status']=='awaiting_approval':
            from .prospect_overview import _draft
            stage='awaiting_approval' if _draft(store,'agency:'+a) else 'needs_verification'
        elif r['outreach_status']=='approved':stage='awaiting_delivery'
        elif outcome=='human_verification' or classification in ('ambiguous_identity','possible_existing_channel') or disposition=='accepted':stage='needs_verification'
        else:stage='screened' if rank else 'discovered'
        default={'hold':'Keep outside new-prospect outreach.','rejected':'No prospecting action.',
                 'needs_verification':'Open the saved agency evidence and check the outstanding facts.',
                 'in_conversation':'Review recorded fictional outreach activity.','awaiting_response':'Wait for the simulated response.',
                 'awaiting_approval':'Review the simulated agency email.','awaiting_delivery':'Wait for simulated delivery.'}
        next_step=r['rationale'] if disposition in ('held','rejected') else q.get('next_task')
        if stage in ('awaiting_delivery','awaiting_response','in_conversation','awaiting_approval'):
            next_step=default[stage]
        row=dict(id=a,name=r['name'],state=r['state'],segment=segment,origin='fictional_csv',stage=stage,
                 qualification=outcome,classification=classification,score=r['score'],score_version=rank.get('version'),
                 factors=rank.get('factors',[]),reason=(rank.get('factors') or [{}])[0].get('reason') or classification.replace('_',' '),
                 comparison=comparisons.get(segment,'No reliable historical comparison.'),next_action=next_step or default.get(stage,'Inspect the saved screening evidence for internal qualification.'),
                 href='/screening?agency='+a,detail_href='/screening?agency='+a,verified=False,researched=False,researchable=False,
                 awaiting_research=False,high_priority=bool(stage in ('screened','discovered') and rank.get('eligible') and (r['score'] or 0)>=HIGH_PRIORITY),
                 has_conversation=stage=='in_conversation',outreach_permission_required=False)
        if detail:
            record=agency_detail(store,a);e=record['evidence'];attrs=e['agency'][0]
            row.update(attributes=attrs,fields=attrs,sources=[{'reference':s['ref'],'title':'Supplied public agencies CSV'} for s in e['agency']],
                       field_sources={k:attrs.get('ref') for k in attrs if k!='ref'},missing_fields=[k for k,v in attrs.items() if not v],
                       identity_confidence='fictional_csv',limitations=e['limits'],assessment=assessment,draft=None,research=None)
        yield row


def candidate_detail(store,candidate_id):
    comparisons=comparable_purchases(store)
    real=next(_real_rows(store,comparisons,candidate_id,True),None)
    if real:return real
    agency=next(_csv_rows(store,comparisons,candidate_id,True),None)
    if not agency:raise ValueError('Prospect candidate not found.')
    return agency


def prospect_progress(store,oid,agency_record=None):
    # The account page uses the same stage and next step as its pipeline row.
    rows=_real_rows(store,{},only=oid) if agency_record is None else _csv_rows(store,{},only=oid)
    row=next(rows,None)
    if row:
        activity=_last_activity(store,oid if agency_record is None else 'agency:'+oid)
        if agency_record is not None and agency_record['history']:
            last=agency_record['history'][0]
            if not activity['at'] or last['created_at']>activity['at']:
                activity=dict(label=last['kind'].replace('_',' ').capitalize(),at=last['created_at'])
        return dict(stage=row['stage'],next_action=row['next_action'],latest_activity=activity)


def candidate_decision(store, candidate_id, decision, rationale=''):
    if decision not in ('select_for_research','hold','reject','resume'):
        raise ValueError('Choose select for research, hold, reject or resume.')
    rationale=(rationale or '').strip()
    if len(rationale)>2000 or (decision in ('hold','reject') and not rationale):
        raise ValueError('Give a short reason for this decision.')
    record=candidate_detail(store,candidate_id)
    if record['origin']=='fictional_csv' or not record['verified']:
        raise ValueError('Select a verified real institution.')
    if record['researched'] or record['stage'] not in ('screened','discovered','selected_for_research','hold','rejected'):
        raise ValueError('This prospect has already entered a later workflow.')
    if decision=='resume' and record.get('manual_decision') not in ('hold','reject'):
        raise ValueError('Only a manually held or rejected prospect can be resumed.')
    if decision=='select_for_research' and not record['researchable']:
        raise ValueError('Resolve the current blocker before selecting research.')
    with store.connect(write=True) as con:
        busy=con.execute("""SELECT 1 FROM jobs WHERE opportunity_id=? AND kind IN
                        ('pipeline_research','pipeline_qualify','prospect_research','prospect_qualify')
                        AND status IN ('queued','running')""",(candidate_id,)).fetchone()
        current=con.execute("SELECT evidence,status,holds FROM opportunities WHERE id=? AND active=1 AND workflow='prospecting'",(candidate_id,)).fetchone()
        if busy or not current or current['status'] not in ('needs_research','needs_review') or json.loads(current['holds']) or json.loads(current['evidence']).get('research'):
            raise ValueError('Research or outreach state has changed. Refresh this candidate.')
        previous=con.execute('SELECT decision,rationale FROM prospect_candidate_decisions WHERE opportunity_id=?',(candidate_id,)).fetchone()
        changed=not previous or tuple(previous)!=(decision,rationale)
        if decision=='resume':
            if not previous or previous['decision'] not in ('hold','reject'):
                raise ValueError('Only a manually held or rejected prospect can be resumed.')
            con.execute('DELETE FROM prospect_candidate_decisions WHERE opportunity_id=?',(candidate_id,))
        elif changed:
            if decision=='select_for_research' and previous and previous['decision'] in ('hold','reject'):
                raise ValueError('Resolve the current blocker before selecting research.')
            con.execute("""INSERT INTO prospect_candidate_decisions VALUES(?,?,?,?)
                           ON CONFLICT(opportunity_id) DO UPDATE SET decision=excluded.decision,
                           rationale=excluded.rationale,updated_at=excluded.updated_at""",(candidate_id,decision,rationale,utcnow()))
        if changed:
            store.event('prospect_manual_decision',{'decision':decision,'rationale':rationale},opportunity_id=candidate_id,con=con)
    return candidate_detail(store,candidate_id)


# These shortcuts use exactly the same predicates as the tiles, action cards and paged list.
def _stage_matches(row, stage):
    if stage=='outreach_draft_ready':stage='awaiting_delivery'
    if stage=='awaiting_response':return row['stage'] in ('awaiting_response','follow_up')
    if stage=='in_conversation':return row['has_conversation']
    if stage.startswith('csv_'):return row.get('csv_work')==stage[4:]
    if stage=='researched':return row['researched']
    if stage in ('high_priority','awaiting_research','latest_discovery'):return row[stage]
    return row['stage']==stage


def _link(**params):
    return '/screening?'+urlencode(params)


def _actions(rows, recent):
    def action(key, title, description, button, members, **params):
        href=_link(**params)
        if members:
            href+='#candidates'
        if len(members)==1 and key!='new_sources' and members[0]['origin']!='fictional_csv':
            href=members[0]['action_href']
        return dict(id=key,title=title,description=description,button_label=button,count=len(members),href=href)
    groups=[
        ('review_emails','Review discovery emails','Research supports a first conversation. Review the saved message and purchasing route before simulated delivery.','Review outreach','awaiting_approval'),
        ('verify_permissions','Verify prospect purchasing details','Check the outstanding identity, recipient or purchasing-route evidence before advancing these real prospects.','Review missing facts','needs_verification'),
        ('review_research','Review completed research','Inspect the sourced findings and buying-route recommendation to decide how to proceed.','Review research','research_completed'),
        ('select_research','Investigate real prospects','Inspect the official evidence and screening score. Select an institution to preview the cost of deeper research.','Review candidates','awaiting_research'),
        ('follow_up','Review due prospect follow-ups','Check the previously simulated introduction and its due reminder before taking the next step.','Review follow-ups','follow_up'),
        ('review_conversations','Review prospect conversations','Read the recorded reply and determine the next justified action.','Open conversations','in_conversation'),
    ]
    items=[]
    for key,title,body,button,stage in groups:
        eligible=[r for r in rows if (r['stage']==stage if stage=='in_conversation' else _stage_matches(r,stage))
                  and (stage!='needs_verification' or r['origin']!='fictional_csv')]
        if eligible:
            params={'stage':stage}
            if stage=='needs_verification':params['origin']='real'
            items.append(action(key,title,body,button,eligible,**params))
    from .prospect_overview import GROUPS
    for group in ('decision','product','relationship','prerequisites','reassess','prepare','accepted_qualification','shortlist'):
        members=[r for r in rows if r.get('csv_work')==group]
        if members:
            _,title,body=GROUPS[group]
            items.append(action('csv_'+group,title,body,'Review candidates',members,origin='fictional_csv',stage='csv_'+group))
    if recent:
        items.append(action('new_sources','Inspect the latest discovery results','Review the identified institutions, sources and screening factors before selecting any for deeper investigation.','Review candidates',recent,stage='latest_discovery'))
    items.append(action('discover','Discover new institutions','Define a region and institutional criteria, then preview the scope and cost of one search.','Discover prospects',[],discover='1'))
    return items


def pipeline(store, *, q='', origin='', state='', segment='', stage='', qualification='', min_score=0, offset=0, limit=25):
    if not 0<=float(min_score)<=100 or not 0<=int(offset) or not 1<=int(limit)<=200:
        raise ValueError('Use a score from 0–100, a positive page size up to 200 and a nonnegative offset.')
    comparisons=comparable_purchases(store)
    from .prospect_overview import _agency_members
    agency_actions={member['id']:(group,member['next_step']) for group,member,_ in _agency_members(store,comparisons)}
    rows=[*_real_rows(store,comparisons),*_csv_rows(store,comparisons)]
    for record in rows:
        if record['origin']=='fictional_csv' and record['id'] in agency_actions:
            record['csv_work'],record['next_action']=agency_actions[record['id']]

    latest=store.rows("SELECT job_id AS run_id FROM events WHERE kind='prospect_discovery_saved' ORDER BY id DESC LIMIT 1")
    if not latest:latest=store.rows("SELECT run_id FROM prospect_discovery_members ORDER BY rowid DESC LIMIT 1")
    recent_ids={r['opportunity_id'] for r in store.rows('SELECT opportunity_id FROM prospect_discovery_members WHERE run_id=?',(latest[0]['run_id'],))} if latest else set()
    for r in rows:r['latest_discovery']=r['id'] in recent_ids and r['origin']!='fictional_csv'
    recent=[r for r in rows if r['latest_discovery']]
    metrics={'total':len(rows),**{o:sum(r['origin']==o for r in rows) for o in ORIGINS}}
    metrics.update(high_priority=sum(r['high_priority'] for r in rows),awaiting_research=sum(r['awaiting_research'] for r in rows),
                   research_completed=sum(r['researched'] for r in rows))
    for stage_key in ('awaiting_approval','awaiting_delivery','awaiting_response','in_conversation'):
        metrics[stage_key]=sum(_stage_matches(r,stage_key) for r in rows)
    brief=[]
    if recent:
        brief.append(f"The latest discovery run verified {len(recent)} real institution{'s' if len(recent)!=1 else ''}. Check their sources and scores before selecting research.")
    if metrics['awaiting_approval']:
        n=metrics['awaiting_approval'];brief.append(f"{n} discovery email{'s are' if n!=1 else ' is'} ready for exact-version review and simulated delivery.")
    if metrics['awaiting_research']:
        n=metrics['awaiting_research'];brief.append(f"{n} verified real prospect{'s can' if n!=1 else ' can'} be selected for deeper research. Review institutional fit and purchasing evidence first.")
    if not brief:
        brief.append('Review the saved screening evidence or start a bounded discovery search for real institutions.')
    actions=_actions(rows,recent)
    filters={k:sorted({str(r[field]) for r in rows if r[field]}) for k,field in
             [('segments','segment'),('qualifications','qualification'),('states','state'),('stages','stage')]}
    query=(q or '').strip().casefold()
    query_state=search_state(query)
    filter_state=search_state(state) or state.strip().upper()
    filtered=[r for r in rows if (not origin or origin=='real' and r['origin']!='fictional_csv' or r['origin']==origin)
              and (not stage or _stage_matches(r,stage)) and (not filter_state or r['state']==filter_state)
              and (not segment or r['segment']==segment) and (not qualification or r['qualification']==qualification)
              and (not min_score or r['score'] is not None and r['score']>=float(min_score))
              and (r['state']==query_state or r['name'].casefold()==query if query_state else query in r['name'].casefold())]
    # Surface current commercial work before untouched screening rows; rank similarly situated candidates by score.
    order={'awaiting_approval':0,'in_conversation':1,'follow_up':1,'research_in_progress':2,'selected_for_research':3,'research_completed':4,
           'screened':6,'discovered':6,'hold':8,'rejected':9}
    filtered.sort(key=lambda r:(order.get(r['stage'],5),r['origin']=='fictional_csv',-(r['score'] or 0),r['name'].casefold(),r['id']))
    return dict(metrics=metrics,brief=brief,actions=actions,filters=filters,rows=filtered[int(offset):int(offset)+int(limit)],
                total=len(filtered),offset=int(offset),limit=int(limit))
