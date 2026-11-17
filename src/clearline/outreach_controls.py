"""Persistent human and customer restrictions on existing-customer correspondence."""
from datetime import date
from uuid import uuid4
import re

from .store import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach_restrictions(
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 kind TEXT NOT NULL CHECK(kind IN ('pause','do_not_contact')), scope TEXT NOT NULL CHECK(scope IN ('account','recipient','thread')),
 recipient TEXT NOT NULL, reason TEXT NOT NULL, source TEXT NOT NULL, message_id TEXT REFERENCES messages(id),
 reconsider_on TEXT, prior_status TEXT NOT NULL, created_at TEXT NOT NULL, released_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS active_outreach_restriction ON outreach_restrictions(opportunity_id,kind,scope,recipient) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS pending_customer_reply ON messages(opportunity_id,status) WHERE direction='inbound';
"""

def intended_recipient(con, outbound_id):
    row = con.execute("""SELECT json_extract(d.analysis,'$.recipient') FROM messages m
        JOIN outbox b ON b.id=m.outbox_id JOIN drafts d ON d.id=b.draft_id WHERE m.id=?""", (outbound_id,)).fetchone()
    address = (row[0] or '').strip().lower() if row else ''
    return address if address != 'simulation@example.invalid' else ''

def active(con, oid):
    return [dict(row) for row in con.execute(
        'SELECT * FROM outreach_restrictions WHERE opportunity_id=? AND released_at IS NULL ORDER BY created_at,id', (oid,))]

def restriction(con, oid, recipient):
    address = (recipient or '').strip().lower()
    return next((r for r in active(con, oid) if r['scope'] == 'account' or
                 (r['scope']=='recipient' and r['recipient']==address) or
                 (r['scope']=='thread' and (not r['recipient'] or r['recipient']==address))), None)

def pending_reply(con, oid, excluding=''):
    return con.execute("""SELECT 1 FROM messages WHERE opportunity_id=? AND direction='inbound'
        AND status='received' AND id!=? LIMIT 1""", (oid, excluding)).fetchone() is not None

def cancel_outreach(con, oid, now, recipient=None):
    args = (oid,)
    matching = 'opportunity_id=?'
    if recipient is not None:
        matching += " AND lower(json_extract(analysis,'$.recipient'))=?"
        args += (recipient,)
    current = "status IN ('queued','running','blocked_config')"
    # Follow-ups and deliveries carry their original draft id, even after approval.
    con.execute(f"""UPDATE jobs SET status='cancelled',finished_at=? WHERE opportunity_id=? AND {current}
        AND (kind IN ('followup','deliver','prepare','revise_draft') OR
        (kind='analyze' AND json_extract(payload,'$.followup_of') IS NOT NULL)) AND
        (? IS NULL OR coalesce(json_extract(payload,'$.draft_id'),json_extract(payload,'$.parent_draft_id'),
        json_extract(payload,'$.followup_of'),json_extract(payload,'$.regenerate_id')) IN
        (SELECT id FROM drafts WHERE {matching}))""", (now,oid,recipient,*args))
    con.execute(f"UPDATE drafts SET status='cancelled' WHERE {matching} AND status IN ('awaiting_approval','approved')", args)
    con.execute(f"""UPDATE commercial_tasks SET status='superseded',updated_at=? WHERE opportunity_id=? AND
        status IN ('awaiting_approval','approved') AND (? IS NULL OR message_id IN
        (SELECT json_extract(analysis,'$.reply_message_id') FROM drafts WHERE {matching}))""", (now,oid,recipient,*args))

def record(con, store, opportunity, kind, scope, target, reason, source, *, message_id=None, reconsider_on=None):
    oid, now = opportunity['id'], utcnow()
    previous = con.execute("""SELECT id FROM outreach_restrictions WHERE opportunity_id=? AND kind=? AND
        scope=? AND recipient=? AND released_at IS NULL""", (oid,kind,scope,target)).fetchone()
    if previous:
        return previous['id']
    rid = uuid4().hex
    con.execute("""INSERT INTO outreach_restrictions VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (rid,oid,kind,scope,target,reason,source,message_id,reconsider_on,opportunity['status'],now))
    cancel_outreach(con, oid, now, target if scope!='account' and target else None)
    if scope=='account':
        # A pause cannot hide a permanent account opt-out or an existing terminal outcome.
        if kind=='do_not_contact' or opportunity['status'] not in ('opted_out','lost','won','closed'):
            con.execute('UPDATE opportunities SET status=?,updated_at=? WHERE id=?',
                        ('outreach_paused' if kind=='pause' else 'opted_out',now,oid))
    elif scope=='recipient':
        auth=con.execute("SELECT recipient FROM contact_authorizations WHERE opportunity_id=? AND authorized=1",(oid,)).fetchone()
        if auth and auth['recipient'].lower()==target and opportunity['status'] not in ('opted_out','outreach_paused','lost','won','closed'):
            con.execute("UPDATE opportunities SET status='recipient_opted_out',updated_at=? WHERE id=?",(now,oid))
    store.event('outreach_'+kind,{'restriction_id':rid,'scope':scope,'recipient':target,'reason':reason,'source':source,
                                  'reconsider_on':reconsider_on,'message_id':message_id},opportunity_id=oid,con=con)
    return rid

def change(store, oid, action, *, reason='', scope=None, recipient='', reconsider_on=None, clarify_id=None):
    reason=reason.strip()
    recipient=recipient.strip().lower()
    if scope is None and action in ('pause','resume'):scope='account'
    if action not in ('pause','resume','do_not_contact') or scope not in ('account','recipient'):
        raise ValueError('Choose a supported outreach control and scope')
    if action!='resume' and not reason:raise ValueError('Record the reason or original opt-out request')
    if action!='do_not_contact' and scope!='account':raise ValueError('A pause applies to the entire account')
    if scope=='recipient' and (not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',recipient) or recipient=='simulation@example.invalid'):
        raise ValueError('Identify the individual recipient covered by the request')
    if reconsider_on:
        if action!='pause':raise ValueError('A reconsideration date applies only to a pause')
        date.fromisoformat(reconsider_on)
    with store.connect(write=True) as con:
        o=con.execute("SELECT * FROM opportunities WHERE id=? AND workflow='recovery'",(oid,)).fetchone()
        if not o:raise ValueError('Choose an existing customer')
        ambiguous=None
        if clarify_id:
            ambiguous=con.execute("""SELECT * FROM outreach_restrictions WHERE id=? AND opportunity_id=?
                AND scope='thread' AND kind='do_not_contact' AND released_at IS NULL""",(clarify_id,oid)).fetchone()
            if not ambiguous or action!='do_not_contact':raise ValueError('Choose an unresolved opt-out request for this account')
        if action=='resume':
            pause=next((r for r in active(con,oid) if r['kind']=='pause'),None)
            if not pause:raise ValueError('This account has no active manual pause')
            now=utcnow()
            con.execute('UPDATE outreach_restrictions SET released_at=? WHERE id=?',(now,pause['id']))
            if o['status']=='outreach_paused':
                auth=con.execute('SELECT recipient FROM contact_authorizations WHERE opportunity_id=?',(oid,)).fetchone()
                covered=restriction(con,oid,auth[0] if auth else '')
                state='recipient_opted_out' if covered else pause['prior_status']
                if not covered:
                    new_reply=con.execute("""SELECT 1 FROM messages WHERE opportunity_id=? AND
                        direction='inbound' AND created_at>=? LIMIT 1""",(oid,pause['created_at'])).fetchone()
                    if pending_reply(con,oid):state='replied'
                    elif new_reply or state in ('approved','awaiting_approval','analyzing','replied'):state='needs_review'
                con.execute('UPDATE opportunities SET status=?,updated_at=? WHERE id=?',(state,now,oid))
            store.event('outreach_resumed',{'restriction_id':pause['id']},opportunity_id=oid,con=con)
        else:
            rid=record(con,store,o,action,scope,recipient if scope=='recipient' else '',reason,'manual_salesperson',
                       message_id=ambiguous['message_id'] if ambiguous else None,reconsider_on=reconsider_on)
            if ambiguous:
                con.execute('UPDATE outreach_restrictions SET released_at=? WHERE id=?',(utcnow(),clarify_id))
                con.execute("UPDATE commercial_tasks SET status='completed',updated_at=? WHERE message_id=?",(utcnow(),ambiguous['message_id']))
                store.event('opt_out_scope_verified',{'original':clarify_id,'restriction_id':rid,'evidence':reason},opportunity_id=oid,con=con)
        return {'restrictions':active(con,oid)}
