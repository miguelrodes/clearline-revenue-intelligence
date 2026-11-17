"""Disposable, registered demo snapshots. Never reset the source database."""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4
from .config import ROOT,Settings
from .store import Store,utcnow

DEMO_DIR=ROOT/'runtime'/'demo'
CONVERSATION_DIR=ROOT/'runtime/phase12-acceptance/conversation-demo'
CONVERSATION_SESSION=CONVERSATION_DIR/'session.sqlite3'
CONVERSATION_BUDGET=CONVERSATION_DIR/'interactive-budget.sqlite3'


def conversation_spending(path):
    """Live incremental meter for the isolated conversation, independent of restored business records."""
    if path.resolve()!=CONVERSATION_SESSION:return None
    with sqlite3.connect(CONVERSATION_BUDGET.as_uri()+'?mode=ro',uri=True) as con:
        meta=dict(con.execute('SELECT key,value FROM metadata'))
        if (not meta.get('interactive_budget_id') or meta['interactive_budget_id']!=manifest(CONVERSATION_DIR).get('interactive_budget_id')
                or meta.get('db_path')!=str(path.resolve()) or meta.get('limit_micro')!='2000000'):
            raise ValueError('Rehearsal spending ledger does not match this session.')
        count,settled,reserved=con.execute("""SELECT COUNT(*),COALESCE(SUM(charged_micro),0),
            COALESCE(SUM(CASE WHEN charged_micro IS NULL THEN reserved_micro ELSE 0 END),0) FROM requests""").fetchone()
    limit=int(meta['limit_micro'])
    return dict(limit_usd=limit/1e6,charged_usd=settled/1e6,reserved_usd=reserved/1e6,
                remaining_usd=max(0,limit-settled-reserved)/1e6,generation_requests=count)


def paths(folder=DEMO_DIR):
    folder=Path(folder).resolve()
    return folder/'baseline.sqlite3',folder/'session.sqlite3',folder/'manifest.json'


def manifest(folder=DEMO_DIR):
    baseline,session,marker=paths(folder)
    data=json.loads(marker.read_text())
    if data.get('kind')!='clearline-disposable-demo-v1' or data.get('session')!=str(session) or data.get('baseline')!=str(baseline):
        raise ValueError('This is not a registered disposable demo')
    source=Path(data['source']).resolve()
    if source in (baseline,session) or any(p.is_symlink() for p in (baseline,session,marker)):
        raise ValueError('Demo paths must be separate from the original database and cannot be symlinks')
    if baseline.exists() and session.exists() and (os.path.samefile(baseline,session) or source.exists() and (os.path.samefile(source,baseline) or os.path.samefile(source,session))):
        raise ValueError('Demo files must not share the original database inode')
    return data


@contextmanager
def use_guard(path):
    """API and worker hold shared leases; reset requires both to be stopped."""
    if path.name!='session.sqlite3' or not (path.parent/'manifest.json').exists():
        yield;return
    manifest(path.parent)
    with (path.parent/'use.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH)
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


@contextmanager
def exclusive(folder):
    with (Path(folder)/'use.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ValueError('Stop demo serve with Ctrl+C before resetting or capturing the demo.') from exc
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def backup(source,target):
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Snapshot integrity check failed')
        dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def initialize(source,folder=DEMO_DIR):
    source=Path(source).resolve();baseline,session,marker=paths(folder)
    if marker.exists() or baseline.exists() or session.exists():raise ValueError('Demo already exists. Use reset; never overwrite a baseline implicitly.')
    if source in (baseline,session) or not source.is_file():raise ValueError('A separate existing source database is required')
    baseline.parent.mkdir(parents=True,exist_ok=True)
    backup(source,baseline)
    s=Store(baseline)
    # Rewind only delivered campaign members without recorded outcomes, inside the copy.
    ids=[r['opportunity_id'] for r in s.rows("SELECT DISTINCT ca.opportunity_id FROM campaign_accounts ca JOIN opportunities o ON o.id=ca.opportunity_id WHERE ca.exclusion IS NULL AND o.workflow='recovery' AND o.status='awaiting_response' AND NOT EXISTS(SELECT 1 FROM outcomes x WHERE x.opportunity_id=o.id)")]
    # Lone Tree is the repeatable conversation example, even outside a saved campaign.
    lone='c966fd651cca1e9020fa'
    if lone not in ids and s.rows("SELECT 1 FROM opportunities WHERE id=? AND workflow='recovery' AND status='awaiting_response' AND holds='[]' AND NOT EXISTS(SELECT 1 FROM outcomes WHERE opportunity_id=?)",(lone,lone)):ids.append(lone)
    with s.connect(write=True) as con:
        con.execute('UPDATE schedules SET enabled=0')
        con.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('running','queued','blocked_config') AND kind!='followup'")
        con.execute('DELETE FROM worker_state')
        con.execute("DELETE FROM controls WHERE name IN ('capacity','paused')")
        for oid in ids:
            con.execute('DELETE FROM messages WHERE opportunity_id=?',(oid,))
            con.execute('DELETE FROM conversations WHERE opportunity_id=?',(oid,))
            con.execute('DELETE FROM outbox WHERE opportunity_id=?',(oid,))
            con.execute('DELETE FROM approvals WHERE draft_id IN (SELECT id FROM drafts WHERE opportunity_id=?)',(oid,))
            con.execute("DELETE FROM jobs WHERE opportunity_id=? AND kind IN ('deliver','followup')",(oid,))
            con.execute("UPDATE drafts SET status='awaiting_approval',recipient='simulation@example.invalid' WHERE opportunity_id=? AND version=(SELECT MAX(version) FROM drafts WHERE opportunity_id=?)",(oid,oid))
            con.execute("UPDATE opportunities SET status='awaiting_approval' WHERE id=?",(oid,))
        con.execute("UPDATE campaigns SET status='preparing'")
        s.event('demo_baseline_prepared',{'source':str(source),'restored_pending_accounts':ids,'delivery_mode':'simulated','original_database_modified':False},con=con)
    # Saved AI already contains personalized prose. Add simulator drafts, not new analysis.
    from .operations import create_campaign,latest_assessment
    contact_ids=[a['id'] for a in s.rows("SELECT id FROM opportunities WHERE workflow='recovery' AND status='needs_contact' AND holds='[]'") if (latest_assessment(s,a['id']) or {}).get('decision')=='pursue']
    if contact_ids:
        create_campaign(s,'Demo recovery — prepared from saved AI',contact_ids,True)
        while job:=s.claim(['prepare']):
            s.save_analysis(job,latest_assessment(s,job['opportunity_id']))
    with s.connect() as con:con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    data={'kind':'clearline-disposable-demo-v1','source':str(source),'baseline':str(baseline),'session':str(session),'captured_at':utcnow(),'baseline_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest()}
    marker.write_text(json.dumps(data,indent=2));reset(folder)
    return {'session':str(session),'restored_campaign_accounts':len(ids),'cached_drafts_prepared':len(contact_ids)}


def reset(folder=DEMO_DIR):
    stop_serving(folder)
    data=manifest(folder);baseline,session,marker=paths(folder)
    with exclusive(folder):
        if hashlib.sha256(baseline.read_bytes()).hexdigest()!=data['baseline_sha256']:raise ValueError('Baseline changed; capture a validated baseline explicitly before resetting')
        if session.exists():
            archive=session.parent/'history';archive.mkdir(exist_ok=True)
            backup(session,archive/(uuid4().hex+'.sqlite3'))
        backup(baseline,session)
        s=Store(session)
        delta=datetime.now(timezone.utc)-datetime.fromisoformat(data['captured_at'])
        with s.connect(write=True) as con:
            for row in con.execute("SELECT id,due_at FROM jobs WHERE status='queued' AND kind='followup'").fetchall():
                due=datetime.fromisoformat(row['due_at'])+delta
                con.execute('UPDATE jobs SET due_at=? WHERE id=?',(due.isoformat(timespec='seconds'),row['id']))
            con.execute('DELETE FROM worker_state')
            s.event('demo_reset',{'baseline_sha256':data['baseline_sha256'],'delivery_mode':'simulated'},con=con)
        # Reuse bounded AI wording when only relative demonstration dates changed.
        from .briefing import snapshot,render_brief
        from .data import digest
        saved=s.rows('SELECT body FROM operational_briefs ORDER BY created_at DESC,rowid DESC LIMIT 1')
        if saved:
            state=snapshot(s);body=json.loads(saved[0]['body'])
            try:render_brief(body,state)
            except ValueError:pass
            else:
                with s.connect(write=True) as con:con.execute('INSERT INTO operational_briefs VALUES(?,?,?,?,?)',(uuid4().hex,digest(state),json.dumps(state),json.dumps(body),utcnow()))
        return str(session)


def capture(folder=DEMO_DIR):
    """Explicitly replace only the demo baseline, keeping the previous snapshot."""
    data=manifest(folder);baseline,session,marker=paths(folder)
    with exclusive(folder):
        s=Store(session)
        if s.rows("SELECT 1 FROM jobs WHERE status='running'"):raise ValueError('Finish running work before capture')
        archive=session.parent/'history';archive.mkdir(exist_ok=True)
        backup(baseline,archive/('baseline-'+uuid4().hex+'.sqlite3'))
        backup(session,baseline)
        data.update(captured_at=utcnow(),baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest())
        marker.write_text(json.dumps(data,indent=2))


def stop_serving(folder=DEMO_DIR):
    pidfile=Path(folder)/'server.json'
    if not pidfile.exists():return
    data=json.loads(pidfile.read_text());pid=int(data['pid'])
    def process_identity():
        return subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart=','-o','command='],capture_output=True,text=True).stdout.strip()
    current=process_identity()
    if not current:return
    if current!=data['identity'] or 'clearline.demo serve' not in current:
        raise ValueError('Demo process identity changed; refusing to stop an unrelated process')
    os.kill(pid,signal.SIGTERM)
    for _ in range(180):
        if process_identity()!=current:return
        time.sleep(1)
    raise ValueError('Demo is still finishing work. Retry reset once it stops.')


def serve(folder=DEMO_DIR):
    data=manifest(folder);pidfile=Path(folder)/'server.json'
    if pidfile.exists():
        old=json.loads(pidfile.read_text())
        if subprocess.run(['/bin/ps','-p',str(old['pid']),'-o','command='],capture_output=True,text=True).stdout.strip():
            raise ValueError('A demo server is already registered. Stop it before starting another.')
    identity=subprocess.run(['/bin/ps','-p',str(os.getpid()),'-o','lstart=','-o','command='],capture_output=True,text=True).stdout.strip()
    pidfile.write_text(json.dumps({'pid':os.getpid(),'identity':identity}))
    env={**os.environ,'CLEARLINE_DB_PATH':data['session']};children=[]
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','clearline.api:create_app','--factory','--host','127.0.0.1','--port','8000','--no-access-log'],env=env))
        children.append(subprocess.Popen([sys.executable,'-m','clearline.cli','worker'],env=env))
        print('Demo API and agents running. Open http://127.0.0.1:3000. Ctrl+C stops them before reset.',flush=True)
        while all(p.poll() is None for p in children):time.sleep(.5)
    except KeyboardInterrupt:pass
    finally:
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=180)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        pidfile.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description='Manage the isolated local demo; original data is never reset.')
    parser.add_argument('command',choices=['init','reset','serve','capture','stop']);args=parser.parse_args()
    try:
        if args.command=='init':print(json.dumps(initialize(Settings.load().db_path),indent=2))
        elif args.command=='reset':print('Restored '+reset())
        elif args.command=='capture':capture();print('Validated demo baseline captured.')
        elif args.command=='stop':stop_serving();print('Demo services stopped.')
        else:serve()
    except (ValueError,OSError) as exc:parser.exit(2,str(exc)+'\n')

if __name__=='__main__':main()
