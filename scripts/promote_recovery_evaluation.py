"""Import validated isolated assessments without replacing live history or the demo baseline.

Default is a preview. --apply requires the registered demo API/worker to be stopped.
Changed human drafts, conversations or outcomes are skipped and must be reassessed separately.
"""
import argparse
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from clearline.config import ROOT, Settings
from clearline.data import scan, ScanPolicy
from clearline.demo import backup, exclusive, manifest
from clearline.evidence import ENGINE_VERSION, context_hash, current_assessment
from clearline.operations import latest_assessment
from clearline.store import Store, utcnow

FIELDS=('id','version','status','recipient','subject','body')


class ReadOnlySnapshot:
    def __init__(self,path):self.path=path
    def rows(self,sql,params=()):
        with sqlite3.connect(f'file:{self.path.resolve()}?mode=ro',uri=True) as con:
            con.row_factory=sqlite3.Row
            return [dict(r) for r in con.execute(sql,params)]

def draft_state(store,oid):
    return store.rows('SELECT '+','.join(FIELDS)+' FROM drafts WHERE opportunity_id=? ORDER BY version',(oid,))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--source',type=Path,required=True);p.add_argument('--before',type=Path,required=True);p.add_argument('--demo-dir',type=Path,default=ROOT/'runtime/demo');p.add_argument('--env-file',type=Path);args=p.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    root=args.source.parent;folder=args.demo_dir;manifest(folder)
    live_path=folder/'session.sqlite3'
    if args.source.resolve()==live_path.resolve() or args.before.resolve()==live_path.resolve():raise ValueError('Evaluation and before-snapshot must be separate from the live session')
    source=Store(args.source);before=ReadOnlySnapshot(args.before);live=ReadOnlySnapshot(live_path)
    settings=Settings.load();summary,items=scan(settings.data_dir,ScanPolicy(as_of=settings.as_of),True)
    source_summary=json.loads(source.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')[0]['summary'])
    for key in ('hashes','prior_cents','current_cents','prior_tests','current_tests','net_cents_whole_export','duplicate_excess_retained'):
        if summary[key]!=source_summary[key]:raise ValueError('Source snapshot changed: '+key)
    assessments={item['id']:latest_assessment(source,item['id']) for item in items}
    missing=[]
    for oid,a in assessments.items():
        with source.connect() as c:current=current_assessment(c,oid,a)
        if not current or a.get('review_failed'):missing.append(oid)
        expected={r['id'] for r in source.rows('SELECT id FROM commercial_signals WHERE active=1 AND opportunity_id=?',(oid,))}
        seen={d['signal_id'] for d in (a.get('commercial_plan') or {}).get('signal_decisions',[])} if a else set()
        if expected!=seen:missing.append(oid)
    if missing:raise ValueError(f'{len(missing)} accounts lack a current verified assessment; do not promote an incomplete evaluation')
    if not args.apply:
        print(json.dumps({'source':str(source.path),'destination':str(live.path),'current_assessments':len(items),
                          'human_draft_changes':sum(draft_state(live,x['id'])!=draft_state(before,x['id']) for x in items),
                          'note':'Preview only; final context checks occur after refreshing deterministic metadata in the stopped live session.'}));return
    imported=[];skipped=[];cached=[]
    with exclusive(folder):
        snapshot=root/('live-pre-promotion-'+uuid4().hex[:8]+'.sqlite3');backup(live.path,snapshot)
        live=Store(live_path)
        old=json.loads(live.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')[0]['summary'])
        for key in ('hashes','prior_cents','current_cents','prior_tests','current_tests','net_cents_whole_export','duplicate_excess_retained'):
            if old[key]!=summary[key]:raise ValueError('Live source totals changed: '+key)
        live.save_scan(summary,items)
        for oid,a in assessments.items():
            with live.connect() as c:
                unchanged=context_hash(c,oid)==a['context_hash']
                already=current_assessment(c,oid,latest_assessment(live,oid))
            if already:cached.append(oid);continue
            # Internal reassessment epochs are not new customer evidence. Copy an
            # evaluated epoch only if doing so produces an EXACT context match;
            # otherwise restore it and preserve the changed live account.
            if not unchanged and draft_state(live,oid)==draft_state(before,oid):
                epoch=source.rows('SELECT value FROM controls WHERE name=?',('reassessment:'+oid,))
                if epoch:
                    with live.connect(write=True) as c:
                        previous=c.execute('SELECT value FROM controls WHERE name=?',('reassessment:'+oid,)).fetchone()
                        c.execute('INSERT INTO controls VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',('reassessment:'+oid,epoch[0]['value']))
                        unchanged=context_hash(c,oid)==a['context_hash']
                        if not unchanged:
                            if previous:c.execute('UPDATE controls SET value=? WHERE name=?',(previous['value'],'reassessment:'+oid))
                            else:c.execute('DELETE FROM controls WHERE name=?',('reassessment:'+oid,))
            if not unchanged or draft_state(live,oid)!=draft_state(before,oid):
                skipped.append({'id':oid,'reason':'Live conversation, context, outcome or human draft changed since audit'});continue
            row=source.rows("SELECT job_id FROM events WHERE opportunity_id=? AND kind='agent_decision' AND json_extract(details,'$.engine_version')=? ORDER BY id DESC LIMIT 1",(oid,ENGINE_VERSION))[0]
            origin=source.rows('SELECT * FROM jobs WHERE id=?',(row['job_id'],))[0]
            jid=live.queue_analysis(oid,investigation=True,allow_simulation=True)
            with live.connect(write=True) as c:
                c.execute("UPDATE jobs SET status='running',attempts=?,started_at=?,error=NULL WHERE id=?",(origin['attempts'],origin['started_at'],jid))
                for event in source.rows("SELECT * FROM events WHERE job_id=? AND kind NOT IN ('agent_decision','job_completed') ORDER BY id",(origin['id'],)):
                    details=json.loads(event['details']);details['_evaluation_origin']={'job_id':origin['id'],'event_id':event['id']}
                    c.execute('INSERT INTO events(job_id,opportunity_id,kind,details,created_at) VALUES(?,?,?,?,?)',(jid,oid,event['kind'],json.dumps(details),event['created_at']))
                for attempt in source.rows('SELECT * FROM execution_attempts WHERE job_id=?',(origin['id'],)):
                    c.execute('INSERT OR REPLACE INTO execution_attempts VALUES(?,?,?,?,?,?)',(jid,attempt['attempt'],attempt['started_at'],attempt['seconds'],attempt['status'],attempt['concurrency']))
            job=live.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0];job['payload']=json.loads(job['payload'])
            live.save_analysis(job,a)
            if live.rows('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status']!='completed':raise ValueError('Context changed during import: '+oid)
            with live.connect(write=True) as c:c.execute('UPDATE jobs SET finished_at=? WHERE id=?',(origin['finished_at'],jid))
            imported.append(oid)
        result={'engine':ENGINE_VERSION,'imported':len(imported),'cached':len(cached),'skipped':skipped,'backup':str(snapshot),
                'baseline_replaced':False,'approved_or_sent':False,'at':utcnow()}
        live.event('validated_portfolio_import',result)
        (root/'promotion_results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
