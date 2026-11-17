"""Current human work for the conversational interface, drawn from the saved work queues."""
from collections import defaultdict
import re

from .conversations import policy
from .outreach_controls import pending_reply, restriction
from .prospect_overview import overview as prospect_overview
from .task_purpose import task_purpose
from .workbench import work_groups

REMINDER_REVIEW = re.compile(
    r'\b(?:queued|scheduled|upcoming)\s+(?:follow[ -]?up|reminder)\b|'
    r'\b(?:follow[ -]?up|reminder)\s+(?:review|job|due)\b', re.I)


def _upcoming(store, screening_enabled):
    # A reminder belongs to one delivery. A later reply or outbound supersedes it.
    with store.connect() as con:
        rows = con.execute("""
            SELECT j.id AS job_id,j.status,j.due_at,o.id,o.name,o.workflow,
                   json_extract(d.analysis,'$.recipient') AS recipient
            FROM jobs j JOIN opportunities o ON o.id=j.opportunity_id
            JOIN messages m ON m.id=(SELECT last.id FROM messages last WHERE last.opportunity_id=o.id
                ORDER BY last.created_at DESC,last.rowid DESC LIMIT 1)
            JOIN outbox b ON b.id=m.outbox_id AND b.opportunity_id=o.id
            JOIN drafts d ON d.id=b.draft_id AND d.id=json_extract(j.payload,'$.parent_draft_id')
            WHERE j.kind='followup' AND j.status IN ('queued','running') AND o.active=1
              AND o.status='awaiting_response' AND m.direction='outbound'
            ORDER BY j.due_at,j.id
        """)
        return [{k:r[k] for k in ('id','name','workflow','job_id','status','due_at')}
                | {'next_step':'The scheduled worker will check whether a follow-up is warranted.'}
                for r in rows if (screening_enabled or r['workflow']!='agency_screening')
                and policy(con,r['id'])!='stop' and not pending_reply(con,r['id'])
                and not restriction(con,r['id'],r['recipient'])]


def _waiting_inquiries(waiting_group, review_members):
    """Keep one conversational summary per sent inquiry. Group counts use distinct pending tasks."""
    outstanding = defaultdict(list)
    for member in review_members:
        outstanding[member['inquiry_id']].extend(member['outstanding_order_ids'])
    inquiries = {}
    for m in waiting_group.get('members', []):
        iid = m['inquiry_id']
        summary = inquiries.setdefault(iid, {k:m[k] for k in ('id','name','workflow','href','inquiry_id',
            'responsibility','status','sent_at','delivery_mode','next_step')} | {'task_ids':[], 'order_ids':[]})
        summary['task_ids'].append(m['task_id'])
        summary['order_ids'].extend(m['order_ids'])
    for iid, summary in inquiries.items():
        summary['order_ids'] = list(dict.fromkeys(summary['order_ids'] + outstanding[iid]))
    return list(inquiries.values())


def _group(key, title, members, status):
    return dict(id=key,title=title,kind='accounts',members=members,status=status,
                accounts=len({m['id'] for m in members}),tasks=len(members))


def _headline(group, member):
    item = {k:member[k] for k in ('id','name','status','href','task_id','job_id','inquiry_id','order_ids') if k in member}
    workflow = {'phase3':'fictional_agency','phase4':'real_world_prospect'}.get(group.get('source'),'recovery')
    item.update(group_id=group['id'],workflow=member.get('workflow') or workflow)
    item.setdefault('status',group['status'])
    if member.get('decline_cents') and member.get('account_key') and not member['account_key'].startswith('DISTRIBUTOR|'):
        item['account_historical_decline_cents'] = member['decline_cents']
    draft = member.get('draft')
    if draft:
        item['draft'] = {k:draft[k] for k in ('id','version','subject')}
        item['next_step'] = member.get('next_step') or f"Review the prepared email, version {draft['version']}, for simulated sending."
    else:
        item['next_step'] = (member.get('next_step') or (member.get('recommended_action') or '').partition(' — ')[0]
                             or group.get('button_label') or group['title'])
    return item


def current_work(service):
    store = service.store
    work = work_groups(store)
    enabled = service.settings.screening_enabled
    prospects = prospect_overview(store,enabled)
    account_states = {r['id']:r['status'] for r in store.rows('SELECT id,status FROM opportunities WHERE active=1')}
    waiting_group = {}
    review_members = []
    prospect_threads = set()
    ranked = []
    for original in work['groups']:
        key = original['id']
        if key=='internal:waiting':
            waiting_group = original
            continue
        if key=='internal:review':
            review_members = original['members']
        if key=='followups':
            continue  # Scheduled work has its own live queue below.
        members = []
        for m in original['members']:
            workflow = m.get('workflow','recovery')
            if workflow=='agency_screening' and not enabled:
                continue
            if original['kind']=='messages' and workflow!='recovery' and key not in ('messages:prospect_reply','messages:prospect_followup'):
                continue  # The prospect queue checks qualification and permissions for introductions.
            title = (m.get('recommended_action') or '').partition(' — ')[0]
            # A saved assessment may describe a then-queued reminder. Only the job
            # and its current conversation can establish a scheduled next step.
            if not m.get('inquiry_id') and m.get('task_id') and REMINDER_REVIEW.search(title):
                continue
            if (m.get('revision') or {}).get('status') in ('queued','running'):
                continue
            if workflow=='prospecting' and (original['kind']=='messages' or key in ('conversation_tasks','replies_pending','real_questions')):
                prospect_threads.add(m['id'])
            members.append(m)
        if not members:
            continue
        # Surface an actual contact clearance before a secondary route question
        # on an account whose current decision is a different investigation.
        def member_order(m):
            clearance = (key=='investigation:contacts' and account_states.get(m['id'])=='human_verification'
                         and task_purpose({'title':m['recommended_action'].partition(' — ')[0]})['contact_resolvable'])
            return (not clearance,not m.get('blocking'),-(m.get('decline_cents') or 0),m['id'])
        if key.startswith('investigation:'):
            members.sort(key=member_order)
        workflows = {m.get('workflow','recovery') for m in members}
        group = dict(original,members=members,tasks=len(members),accounts=len({m['id'] for m in members}),
                     source=next(iter(workflows)) if len(workflows)==1 else 'multiple')
        if group['accounts']!=original['accounts']:
            # Original financials refer to the full group, not this filtered subset.
            group.update(historical_decline_cents=None,financial_cents=None)
        rank = (0 if key in ('conversation_tasks','internal:review') else 1 if group['kind']=='messages' else
                2 if key in ('investigation:contacts','contacts','failed') else 5 if key=='replies_pending' else 3)
        ranked.append((rank,group))

    waiting = _waiting_inquiries(waiting_group,review_members)
    for prospect in prospects['groups']:
        key = prospect['id']
        members = [m for m in prospect['members'] if m['id'] not in prospect_threads]
        if not members:
            continue
        group = {**prospect,**_group('prospect:'+key,prospect['title'],members,'needs_review'), 'count':len(members)}
        rank = 1 if key in ('agency_email','real_email') else 3 if key=='prepare' else 4
        ranked.append((rank,group))
    ranked.sort(key=lambda entry:entry[0])  # Preserve the source ordering within each action tier.
    groups = [g for _,g in ranked]
    upcoming = _upcoming(store,enabled)
    priorities = [_headline(g,g['members'][0]) for g in groups if g['status']!='preparing'][:3]
    if waiting_group:
        groups.append(waiting_group)
    if upcoming:
        groups.append(_group('followups','Scheduled follow-ups',upcoming,'scheduled'))
    summary = {'priorities':priorities,'waiting':waiting[:5],'waiting_count':len(waiting),
               'waiting_tasks':waiting_group.get('tasks',0), 'waiting_accounts':waiting_group.get('accounts',0),
               'upcoming':upcoming[:5],'upcoming_count':len(upcoming)}
    counts = {'groups':len(groups),'ready_messages':sum(g['tasks'] for g in groups
              if g['kind']=='messages' or g['id'] in ('prospect:real_email','prospect:agency_email'))}
    if enabled:
        pipeline = service.prospect_pipeline(limit=1)
        summary['prospect_pipeline'] = {k: pipeline[k] for k in ('brief','actions','metrics')}
    return summary, dict(groups=groups,checks=work['checks'],counts=counts)
