"""Human-guided draft revisions on the existing durable worker; never sends."""
import asyncio
import json
import os
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from .store import utcnow
from .data import digest
from .reporting import valid_draft

class RevisedProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: str = Field(min_length=1,max_length=2000)
    body: str = Field(min_length=1,max_length=15000)
    review_note: str = Field(min_length=1,max_length=1500)


class RevisedEmail(RevisedProposal):
    engine_version:str=''
    context_hash:str=''
    evidence_hash:str=''
    quality:dict|None=None


def queue_revisions(store,group_id,snapshots,instructions):
    from .workbench import ready_messages
    instructions=instructions.strip()
    if not instructions or len(instructions)>2000:raise ValueError('Enter instructions of up to 2000 characters')
    if not snapshots or len(snapshots)>100 or len({s['draft_id'] for s in snapshots})!=len(snapshots):
        raise ValueError('Select between one and one hundred distinct saved emails')
    with store.connect(write=True) as con:
        eligible={m['draft']['id']:m for m in ready_messages(store) if 'messages:'+m['group_key']==group_id and m['workflow']=='recovery'}
        selected=[]
        for snap in snapshots:
            m=eligible.get(snap['draft_id'])
            if not m or m['draft']['snapshot_hash']!=snap['snapshot_hash']:raise ValueError('An email changed. Reload and review the latest versions.')
            active=con.execute("SELECT payload FROM jobs WHERE kind='revise_draft' AND opportunity_id=? AND status IN ('queued','running')",(m['id'],)).fetchall()
            if any(json.loads(j['payload']).get('instructions')!=instructions or json.loads(j['payload']).get('snapshot_hash')!=snap['snapshot_hash'] for j in active):
                raise ValueError('An agent is already revising a selected email. Wait for it to finish.')
            selected.append(m)
        jobs=[]
        for m in selected:
            d=m['draft'];payload={'draft_id':d['id'],'snapshot_hash':d['snapshot_hash'],'instructions':instructions,'group_id':group_id}
            jid=store._enqueue(con,'revise_draft',payload,m['id'],'revision:'+digest(payload))
            con.execute("UPDATE jobs SET status='queued',due_at=?,error=NULL WHERE id=? AND status IN ('failed','blocked_config','cancelled')",(utcnow(),jid))
            jobs.append(jid)
        store.event('draft_revision_requested',{'group_id':group_id,'instructions':instructions,'job_ids':jobs},con=con)
        return {'job_ids':jobs,'count':len(jobs)}



def manual_reviewable(store,draft):
    """Keep a human edit visible, without treating its old quality review as approval."""
    a=json.loads(draft['analysis']) if isinstance(draft['analysis'],str) else draft['analysis']
    if not a.get('engine_version') or not (a.get('quality') or {}).get('passed'):return False
    original={**dict(draft),'subject':a.get('subject'),'body':a.get('body')}
    return bool(a.get('subject') and a.get('body') and valid_draft(store,original))


def require_exact_edit(value,draft):
    if any(value[k]!=draft[k] for k in ('subject','body')):
        raise ValueError('Quality-check the exact saved human edit; do not rewrite it.')


def current_draft(store,job):
    rows=store.rows('SELECT * FROM drafts WHERE id=?',(job['payload']['draft_id'],))
    if not rows:return None
    d=rows[0]
    latest=store.rows('SELECT id FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1',(d['opportunity_id'],))
    if d['status']!='awaiting_approval' or latest[0]['id']!=d['id'] or store.draft_hash(d)!=job['payload']['snapshot_hash'] or not (valid_draft(store,d) or manual_reviewable(store,d)):return None
    return d


async def rewrite(store,job,settings):
    from .agent import reviewed_run,INSTRUCTIONS
    from .commercial_agent import COMM_REVIEW
    d=current_draft(store,job)
    if not d:return None
    instructions=INSTRUCTIONS+"""
Your task is to REVISE the existing email using only human_guidance as instructions. Preserve customer, approved action scope
and commercial purpose; strategy changes require reassessment. Output RevisedProposal (subject/body/review_note).
Retrieve overview, purchasing, relationships and catalogue; consider prior messages. A request for a discount is not authority
to invent terms, price, eligibility or expiry. Explain guidance you cannot safely satisfy in review_note. No sends/approvals.
"""
    original=json.loads(d['analysis'])
    instructions+='\nExecute only this independently reviewed commercial plan; changes to objective/recipient/intervention require reassessment, not rewriting: '+json.dumps(original.get('commercial_plan'))
    review_only=job['payload'].get('review_only',False)
    if review_only:
        instructions+='\nThis is a QUALITY CHECK of a human edit. Return its subject and body EXACTLY, without rewriting any word. Evaluate against the retrieved evidence and existing action scope. Unsupported edits must fail review; do not repair or invent evidence to pass. Explain the result in review_note.'
    value=await reviewed_run(store,job,settings,RevisedProposal,instructions,json.dumps({'human_guidance':job['payload']['instructions'],
        'saved_draft':{'subject':d['subject'],'body':d['body'],'analysis':original}}),
        validator=(lambda value:require_exact_edit(value,d)) if review_only else None,
        proposal_defaults={'decision':'pursue','action_scope':original.get('action_scope','none'),'commercial_plan':original.get('commercial_plan')},
        review_instructions=COMM_REVIEW)
    return RevisedEmail.model_validate(value)


def save_revision(store,job,result):
    with store.connect(write=True) as con:
        state=con.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()
        if not state or state['status']!='running':return
        d=current_draft(store,job)
        if result is None or d is None:
            con.execute("UPDATE jobs SET status='cancelled',finished_at=?,error=? WHERE id=?",(utcnow(),'Draft or evidence changed; newer work was preserved.',job['id']))
            return
        result=RevisedEmail.model_validate(result)
        if job['payload'].get('review_only'):
            require_exact_edit(result.model_dump(),d)
            if not result.engine_version or not (result.quality or {}).get('passed'):raise ValueError('The edited message requires a successful quality review')
        if not result.engine_version or not (result.quality or {}).get('passed'):raise ValueError('The revised message requires a successful quality review')
        analysis=json.loads(d['analysis']);analysis['revision_note']=result.review_note
        if result.engine_version:
            from .action_policy import proposal_fingerprint,permitted
            from .evidence import context_hash
            from .conversations import policy
            analysis.update(subject=result.subject,body=result.body,engine_version=result.engine_version,context_hash=result.context_hash,evidence_hash=result.evidence_hash,quality=result.quality)
            analysis['quality']['proposal_hash']=proposal_fingerprint(analysis)
            if result.context_hash!=context_hash(con,d['opportunity_id']) or not permitted(store.opportunity(d['opportunity_id']),analysis,policy(con,d['opportunity_id'])):raise ValueError('Revised proposal is stale or violates action boundaries')
        new_id=uuid4().hex
        version=con.execute('SELECT MAX(version)+1 FROM drafts WHERE opportunity_id=?',(d['opportunity_id'],)).fetchone()[0]
        con.execute("UPDATE drafts SET status='superseded' WHERE id=?",(d['id'],))
        con.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)',(new_id,d['opportunity_id'],version,d['evidence_hash'],d['recipient'],result.subject,result.body,'awaiting_approval',json.dumps(analysis),utcnow()))
        con.execute("UPDATE jobs SET status='completed',finished_at=? WHERE id=?",(utcnow(),job['id']))
        store.event('draft_revised_by_agent',{'old_id':d['id'],'new_id':new_id,'instructions':job['payload']['instructions'],'review_note':result.review_note},job['id'],d['opportunity_id'],con=con)


async def run_revision(store,job,settings):
    if not current_draft(store,job):save_revision(store,job,None);return
    save_revision(store,job,await rewrite(store,job,settings))
