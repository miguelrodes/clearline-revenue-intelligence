"""Read the existing prospect work queues without screening, researching or enqueuing work."""
import json
from collections import Counter

from .operations import latest_assessment
from .prospect_comparables import comparable_purchases
from .reporting import valid_draft
from .screening import QUALIFICATION_ENGINE, current_reports
from .screening_workflow import activity_revisions, assert_current, context_hash, prerequisites
from .store import STOPPED_STATUSES


SHORTLIST_SIZE = 10
GROUPS = {
    'real_email': ('phase4', 'Review real-world discovery outreach',
                   "The saved research connects a documented operational issue to a possible SwabTek application. Review the evidence, purchasing route and exact discovery email before approving a simulated send."),
    'agency_email': ('phase3', 'Review prepared prospect emails',
                     "These fictional institutions have a current qualification, recorded authorization and a prepared email. Review the exact message and intended recipient before approving simulated delivery."),
    'decision': ('phase3', 'Decide which qualified institutions to pursue',
                 "Saved qualifications identify a plausible application for these fictional institutions. Review the evidence and decide which merit internal pursuit before verifying a contact or discussing purchases."),
    'product': ('phase3', 'Verify a possible product application',
                "The saved assessments identify specific questions about how these institutions screen materials. Verify the proposed use before treating them as potential buyers."),
    'relationship': ('phase3', 'Resolve possible customer matches',
                     "These records may overlap with existing accounts or distributor customers. Check the cited identity and purchasing evidence before counting any of them as a new prospect."),
    'prerequisites': ('phase3', 'Complete the missing outreach checks',
                      "These institutions were accepted for further pursuit. Complete only the outstanding verification for each prospective buyer before preparing an introduction."),
    'reassess': ('phase3', 'Review changed prospect evidence',
                 "New evidence or activity has made an earlier qualification stale. Review what changed before requesting a targeted qualification."),
    'prepare': ('phase3', 'Prepare eligible prospect introductions',
                "These accepted institutions have verified applications, recipients, permissions and routes. Prepare a tailored introduction for human review."),
    'accepted_qualification': ('phase3', 'Review accepted candidates for qualification',
                              "These institutions were accepted for further review before a qualification was completed. Check the recorded reasons for pursuit and establish whether a concrete product application justifies qualification."),
    'shortlist': ('phase3', 'Review the next ranked candidates',
                  f"Review up to {SHORTLIST_SIZE} of the highest-ranked unassessed fictional institutions. Their type, scale and screening products supported by the catalogue warrant a closer look. Verify the use case and buying relationship before pursuing them."),
    'real_research': ('phase4', 'Review completed real-world research',
                      "Review the saved public evidence and unresolved commercial questions before deciding whether further discovery is justified."),
}


def _agency_rows(store):
    # Read large evidence blobs only for saved reviews, explicit pursuits and a
    # bounded window of unassessed candidates. The existing score is unchanged.
    return store.rows("""
        WITH busy AS (
            SELECT DISTINCT json_extract(payload,'$.agency_id') AS aid FROM jobs
            WHERE kind IN ('agency_qualify','agency_outreach') AND status IN ('queued','running')
        ), shortlist AS (
            SELECT a.id FROM agency_screenings a JOIN agency_rankings r ON r.agency_id=a.id
            LEFT JOIN agency_workflow w ON w.agency_id=a.id
            WHERE a.active=1 AND a.classification='unverified_prospect'
              AND json_extract(r.explanation,'$.eligible')=1
              AND COALESCE(w.decision,'new')='new'
              AND COALESCE(w.stage,'not_contacted')='not_contacted'
              AND NOT EXISTS (SELECT 1 FROM agency_qualifications q WHERE q.agency_id=a.id)
              AND NOT EXISTS (SELECT 1 FROM busy WHERE aid=a.id)
            ORDER BY r.score DESC,a.name,a.id LIMIT ?
        )
        SELECT a.*, r.score, w.decision, w.information, w.stage, q.result,
               EXISTS(SELECT 1 FROM agency_qualifications old WHERE old.agency_id=a.id) AS ever_assessed,
               o.status AS outreach_status
        FROM agency_screenings a
        LEFT JOIN agency_rankings r ON r.agency_id=a.id
        LEFT JOIN agency_workflow w ON w.agency_id=a.id
        LEFT JOIN opportunities o ON o.id='agency:'||a.id
        LEFT JOIN agency_qualifications q ON q.rowid=(
            SELECT q2.rowid FROM agency_qualifications q2
            WHERE q2.agency_id=a.id AND q2.evidence_hash=a.evidence_hash
            ORDER BY q2.created_at DESC,q2.rowid DESC LIMIT 1)
        WHERE a.active=1 AND (
           a.id IN (SELECT id FROM shortlist)
           OR a.id IN (SELECT agency_id FROM agency_qualifications)
           OR w.decision='accepted')
        AND COALESCE(w.decision,'new') NOT IN ('held','rejected')
        AND NOT EXISTS (SELECT 1 FROM busy WHERE aid=a.id)
        ORDER BY r.score DESC,a.name,a.id
    """, (SHORTLIST_SIZE,))


def _draft(store, oid):
    rows = store.rows("SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1", (oid,))
    if not rows or rows[0]['status'] != 'awaiting_approval':
        return None
    if store.rows("SELECT 1 FROM jobs WHERE opportunity_id=? AND kind='revise_draft' AND status IN ('queued','running') LIMIT 1", (oid,)):
        return None
    draft = rows[0]
    if not valid_draft(store, draft):
        return None
    if oid.startswith('agency:'):
        # Apply the same live qualification/context check as approval.
        opportunity = store.opportunity(oid)
        with store.connect() as con:
            try:
                assert_current(con, opportunity, json.loads(draft['analysis']))
            except ValueError:
                return None
    return draft


def _agency_action(row, report, current, workflow, store):
    classification = row['classification']
    if classification in ('verified_existing','unsuitable') or row['outreach_status'] in STOPPED_STATUSES | {'approved','awaiting_response'}:
        return None
    decision = report['decision'] if current else {}
    outcome = decision.get('outcome')
    if outcome in ('defer','reject'):
        return None
    if workflow['stage'] != 'not_contacted':
        return None
    if classification in ('possible_existing_channel','ambiguous_identity'):
        if current and outcome == 'human_verification':
            return 'relationship', 'Relationship unverified', decision['next_task'], 'Review identity evidence'
        return None
    if row['ever_assessed'] and not current:
        return 'reassess', 'Qualification out of date', 'Check the updated evidence against the earlier report before requesting a new review.', 'Review changed evidence'
    if not current and workflow['decision']=='accepted':
        return 'accepted_qualification', 'Accepted · qualification outstanding', 'Review the screening record and the saved reason for pursuit before requesting qualification.', 'Review accepted candidate'
    if not current:
        return 'shortlist', 'Screened only', 'Review the screening evidence and decide whether a targeted qualification is worthwhile.', 'Open screening record'
    if not report.get('review_passed'):
        return 'product', 'Qualification unresolved', 'Read the independent review findings and verify the open question before pursuing this institution.', 'Review qualification'
    if outcome in ('investigate','human_verification'):
        return 'product', 'Further verification needed', decision['next_task'], 'Review qualification'
    if outcome != 'qualified':
        return None
    if workflow['decision'] != 'accepted':
        return 'decision', 'Qualified for discovery', 'Decide whether to accept, hold or reject this institution for internal pursuit. ' + decision['next_task'], 'Review qualification'
    missing = prerequisites(dict(row, workflow=workflow, qualification=report, qualification_current=True))
    if missing:
        return 'prerequisites', 'Accepted · verification needed', ' '.join(f'{issue}.' for issue in missing), 'Open verification'
    if row['outreach_status'] == 'awaiting_approval':
        if _draft(store, 'agency:'+row['id']):
            return 'agency_email', 'Awaiting approval', 'Review the saved email and intended recipient before approving this version for simulated sending.', 'Review saved email'
        return None
    return 'prepare', 'Cleared for preparation', 'Review the verified facts and request one personalized introduction.', 'Open outreach preparation'


def _agency_members(store, comparisons):
    revisions = activity_revisions(store)
    for row in _agency_rows(store):
        information = json.loads(row['information'] or '{}')
        workflow = {'decision':row['decision'] or 'new','stage':row['stage'] or 'not_contacted','information':information}
        report = json.loads(row['result'] or 'null')
        current = bool(report and report.get('context_hash', row['evidence_hash']) == context_hash(row['evidence_hash'],information,revisions.get(row['id']))
                       and report.get('qualification_engine',QUALIFICATION_ENGINE) == QUALIFICATION_ENGINE)
        action = _agency_action(row, report, current, workflow, store)
        if not action:
            continue
        group, status, next_step, label = action
        evidence = json.loads(row['evidence'])
        source = evidence['agency'][0]
        kind = row['agency_type']
        location = ', '.join(filter(None,(source.get('city'),row['state'])))
        segment = {'county_jail':'County jail','state_prison':'State prison','sheriff':"Sheriff’s office",
                   'police_dept':'Police department','facility_security':'Security facility',
                   'probation_parole':'Probation or parole agency','drug_court':'Drug court'}.get(kind,'Institution')
        description = f"{segment} in {location}." if location else f"{segment} in the supplied agency records."
        refs = [s['ref'] for s in evidence['agency']]
        saved = [f"Supplied agency record: {', '.join(refs)}."]
        if kind in ('state_prison','county_jail') and source.get('jail_beds'):
            saved.append(f"The agency record lists {source['jail_beds']} beds.")
        elif kind in ('police_dept','sheriff') and source.get('population_served'):
            saved.append(f"The agency record lists a population served of {source['population_served']}.")
        skus = evidence.get('fit_hypothesis_skus') or []
        if skus:
            names = {p['sku']:p['name'] for p in evidence['products']}
            saved.append('Product-fit hypotheses: ' + ', '.join(names.get(s,s) for s in skus) + '.')
        if group == 'shortlist' and row['score'] is not None:
            saved.append(f"Saved discovery rank: {row['score']:.1f}/100, based on product fit, institutional scale, purchaser similarity and record completeness.")
        if current:
            saved.append(report['decision']['summary'])
            for ref in report['decision'].get('evidence_refs',[])[:4]:
                if isinstance(ref,str) and ref not in refs: saved.append(ref)
        if group=='relationship':
            commercial = evidence['classification_reason']
        else:
            commercial = comparisons.get(kind) or evidence['ranking_reason']
        member=dict(id=row['id'],name=row['name'],description=description,status=status,
                    commercial_context=commercial,next_step=next_step,evidence=saved,
                    action_label=label,href='/screening?agency='+row['id'])
        yield group,member,kind


def _real_members(store):
    preliminaries = []
    groups = []
    for row in store.rows("SELECT id,name,state,status,evidence,evidence_hash,holds FROM opportunities WHERE workflow='prospecting' AND active=1 ORDER BY name,id"):
        if row['status'] in STOPPED_STATUSES | {'no_action','monitor','defer','approved','awaiting_response'} or json.loads(row['holds']):
            continue
        evidence = json.loads(row['evidence'])
        profile = evidence.get('profile') or {}
        research = evidence.get('research') or {}
        sources = research.get('sources') or []
        if not sources:
            preliminaries.append(row['name'])
            continue
        assessment = latest_assessment(store,row['id']) or {}
        if assessment.get('evidence_hash')!=row['evidence_hash']:
            assessment={}
        if assessment.get('decision') in ('defer','reject','hold','no_action'):
            continue
        draft = _draft(store,row['id']) if row['status']=='awaiting_approval' and assessment.get('decision')=='pursue' else None
        group = 'real_email' if draft else 'real_research'
        context = (assessment.get('operational_need') or {}).get('statement') or profile.get('selection_reason','')
        role = assessment.get('target_role')
        next_step = (f"Review version {draft['version']} and its proposed purchasing route before approving a simulated discovery email."
                     if draft else 'Inspect the saved public sources and verify the outstanding product-fit or purchasing questions.')
        if draft and role: next_step += ' Intended role: '+role
        source_titles = []
        for field, label in [('product_fit','Product fit'),('purchasing_process','Procurement')]:
            finding = assessment.get(field) or {}
            if finding.get('statement'):
                citations = ', '.join(finding.get('source_ids', []))
                source_titles.append(f"{label} ({citations}): {finding['statement']}" if citations else f"{label}: {finding['statement']}")
        source_titles.extend(f"{s['id']} · {s['title']}" for s in sources)
        groups.append((group,dict(id=row['id'],name=row['name'],description='Public institution in '+row['state']+' with saved SwabTek research.',
                                 status='Discovery email awaiting approval' if draft else 'Public research saved',
                                 commercial_context=context,next_step=next_step,evidence=source_titles,
                                 **({'draft':{k:draft[k] for k in ('id','version','subject')}} if draft else {}),
                                 href='/accounts/'+row['id']+('#prospect-outreach' if draft else '#prospect-research'),
                                 action_label='Review saved email' if draft else 'Open saved research')))
    return groups,preliminaries


def overview(store, screening_enabled):
    members = {k:[] for k in GROUPS}
    comparison_types = {k:Counter() for k in GROUPS}
    comparisons = comparable_purchases(store) if screening_enabled else {}
    coverage = {}
    if screening_enabled:
        runs = store.rows('SELECT summary FROM agency_screening_runs ORDER BY created_at DESC,rowid DESC LIMIT 1')
        coverage['current_qualifications'] = len(current_reports(store))
        if runs:
            totals = json.loads(runs[0]['summary'])
            coverage.update({field:totals.get(field,0) for field in ('source_records','unique_records')})
        for key, member, kind in _agency_members(store,comparisons):
            members[key].append(member)
            if key!='relationship' and kind in comparisons:
                comparison_types[key][kind]+=1
    real, preliminary = _real_members(store)
    for key, member in real:
        members[key].append(member)
    groups = []
    for key,(source,title,description) in GROUPS.items():
        if not members[key]:
            continue
        kinds = comparison_types[key].most_common()
        if kinds:
            # One named segment example; never add segment spending across prospects.
            segment = next((kind for kind,_ in kinds if '$' in comparisons[kind]),kinds[0][0])
            description += ' ' + comparisons[segment]
        elif source=='phase4':
            description += ' '+ members[key][0]['commercial_context']
        groups.append(dict(id=key,title=title,description=description,source=source,count=len(members[key]),members=members[key]))
    brief = []
    if members['agency_email'] or members['prepare']:
        steps=[]
        if members['agency_email']:
            steps.append(f"Review {len(members['agency_email'])} prepared prospect emails for simulated sending")
        if members['prepare']:
            steps.append(f"Prepare introductions for {len(members['prepare'])} cleared institutions")
        brief.append(dict(title='Prospect outreach',text='. '.join(steps)+'.'))
    if members['reassess'] or members['accepted_qualification']:
        pieces=[]
        if members['reassess']:
            pieces.append(f"{len(members['reassess'])} earlier qualifications have changed evidence")
        if members['accepted_qualification']:
            pieces.append(f"{len(members['accepted_qualification'])} accepted candidates still need qualification")
        brief.append(dict(title='Qualification follow-up',text=' and '.join(pieces)+'. Review the saved facts before requesting analysis.'))
    if members['decision']:
        brief.append(dict(title='Qualified for discovery',text=f"{len(members['decision'])} fictional institutions have a reviewed product-fit case. Decide which merit further pursuit."))
    if members['product'] or members['relationship'] or members['prerequisites']:
        checks = [f"{len(members[k])} {label}" for k,label in [('product','product-use checks'),('relationship','relationship checks'),('prerequisites','outreach prerequisite checks')] if members[k]]
        brief.append(dict(title='Prospect checks',text='Review '+', '.join(checks)+' before treating these institutions as sales opportunities.'))
    if members['shortlist']:
        screened = coverage.get('unique_records')
        coverage_note = f"{screened:,} fictional institutions were screened and {coverage['current_qualifications']} have current assessments. " if screened else ""
        brief.append(dict(title='Next screening candidates',text=coverage_note + f"Review the next {len(members['shortlist'])} by product fit, scale and purchaser similarity."))
    if real or preliminary:
        parts=[]
        for k,label in [('real_email','has a saved discovery email for review'),('real_research','has completed public research to review')]:
            names=[m['name'] for m in members[k]]
            if names:parts.append(f"{names[0]} {label}" if len(names)==1 else f"{len(names)} real institutions have saved {'emails' if k=='real_email' else 'research'} to review")
        if preliminary:parts.append(f"{preliminary[0]} has preliminary evidence only" if len(preliminary)==1 else f"{len(preliminary)} additional real leads have preliminary evidence only")
        brief.append(dict(title='Real-world prospects',text='. '.join(parts)+'.'))
    if not brief and groups:
        brief=[dict(title=g['title'],text=f"{g['count']} records are available for review.") for g in groups[:4]]
    return dict(brief=brief,groups=groups,coverage=coverage)
