"""Read-only acceptance report for a completed, isolated commercial assessment.

Named expectations are declared here, independently of the saved model responses.
Private source evidence and outputs stay in the ignored runtime directory.
"""
import argparse
from collections import Counter
import json
import sqlite3
from pathlib import Path

from clearline.commercial_agent import strategy_accepted
from clearline.commercial import workflow_control_task
from clearline.evidence import ENGINE_VERSION, current_assessment
from clearline.operations import latest_assessment
from clearline.store import Store

NAMED = [
    ('Range Line Distributors', 'MULTI', {'internal_investigation'}, {'distributor_recovery', 'aging_open_order'}),
    ('Kimball County Adult Probation', 'NM', {'internal_investigation', 'human_verification', 'monitor', 'defer', 'no_action'}, {'purchasing_obstacle'}),
    ('TX State Correctional Facility - Boulder Ridge', 'TX', {'internal_investigation', 'human_verification', 'monitor', 'defer', 'no_action'}, set()),
    ('Granite Falls Police Department', 'NM', {'internal_investigation'}, {'churn_prevention'}),
    ("Hawk County Sheriff's Office", 'AZ', {'internal_investigation', 'human_verification'}, {'purchasing_obstacle'}),
    ('ID DOC - Lone Tree', 'ID', {'internal_investigation', 'human_verification'}, {'inactive_recovery', 'purchasing_obstacle'}),
    ('KS State Correctional Facility - Juniper Hills', 'KS', {'internal_investigation', 'human_verification'}, {'purchasing_decline', 'purchasing_obstacle'}),
    ('Iron County Jail', 'UT', {'internal_investigation', 'human_verification', 'monitor', 'defer', 'no_action'}, set()),
]


def report(source, before):
    store = Store(source)
    original = sqlite3.connect(f'file:{before.resolve()}?mode=ro', uri=True)
    original.row_factory = sqlite3.Row
    accounts = store.rows("SELECT id,name,state,account_key FROM opportunities WHERE active=1 AND workflow='recovery'")
    failures, outcomes, decisions = [], Counter(), {}
    for account in accounts:
        oid = account['id']
        assessment = latest_assessment(store, oid) or {}
        decisions[oid] = assessment
        with store.connect() as con:
            current = current_assessment(con, oid, assessment)
        plan = assessment.get('commercial_plan') or {}
        actual = {r['id'] for r in store.rows('SELECT id FROM commercial_signals WHERE active=1 AND opportunity_id=?', (oid,))}
        reported = [d['signal_id'] for d in plan.get('signal_decisions', [])]
        if not current or assessment.get('review_failed') or not strategy_accepted(assessment.get('commercial_review'), plan):
            failures.append({'account_id': oid, 'reason': 'Missing current accepted commercial decision'})
        if actual != set(reported) or len(reported) != len(set(reported)):
            failures.append({'account_id': oid, 'reason': 'Incomplete or duplicate opportunity dispositions'})
        if any(workflow_control_task(t) for t in plan.get('verification_tasks', [])):
            failures.append({'account_id': oid, 'reason': 'Execution-control tasks incorrectly used as business prerequisites'})
        outcomes[plan.get('outcome', 'missing')] += 1
        if plan.get('outcome') == 'contact':
            from clearline.reporting import valid_draft
            drafts = store.rows('SELECT * FROM drafts WHERE opportunity_id=? ORDER BY version DESC LIMIT 1', (oid,))
            if not drafts or not valid_draft(store, drafts[0]):
                failures.append({'account_id': oid, 'reason': 'Contact disposition lacks eligible, exact-version draft'})
    old_drafts = [dict(r) for r in original.execute("SELECT d.* FROM drafts d JOIN opportunities o ON o.id=d.opportunity_id WHERE d.status='awaiting_approval' AND o.workflow='recovery'")]
    old_channel = [r for r in old_drafts if json.loads(r['analysis']).get('action_scope') == 'channel_support']
    immutable = ('id', 'opportunity_id', 'version', 'evidence_hash', 'recipient', 'subject', 'body', 'analysis', 'created_at')
    for row in original.execute('SELECT * FROM drafts'):
        newer = store.rows('SELECT * FROM drafts WHERE id=?', (row['id'],))
        if not newer or any(newer[0][k] != row[k] for k in immutable):
            failures.append({'draft_id': row['id'], 'reason': 'Original draft content was altered or deleted'})
    preserved = {}
    for table in ('approvals', 'outbox', 'outcomes', 'messages'):
        rows = [dict(r) for r in original.execute(f'SELECT * FROM {table}')]
        now = store.rows(f'SELECT * FROM {table}')
        preserved[table] = rows == now
        if rows != now:
            failures.append({'table': table, 'reason': 'Historical activity differs from baseline'})
    baseline_summary = json.loads(original.execute('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()[0])
    summary = json.loads(store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')[0]['summary'])
    for key in ('hashes', 'prior_cents', 'current_cents', 'prior_tests', 'current_tests', 'net_cents_whole_export'):
        if baseline_summary[key] != summary[key]:
            failures.append({'reason': 'Source or financial totals changed', 'field': key})
    named = []
    for name, state, expected, categories in NAMED:
        candidates = [a for a in accounts if a['name'] == name and a['state'] == state]
        if len(candidates) != 1:
            failures.append({'name': name, 'reason': 'Named regression identity is not unique'})
            continue
        account = candidates[0]
        assessment = decisions[account['id']]
        plan = assessment.get('commercial_plan') or {}
        signals = store.rows('SELECT category,evidence,disposition,next_action FROM commercial_signals WHERE active=1 AND opportunity_id=?', (account['id'],))
        actual_categories = {s['category'] for s in signals}
        passed = plan.get('outcome') in expected and categories <= actual_categories
        if name == 'TX State Correctional Facility - Boulder Ridge':
            passed = passed and 'aging_open_order' not in actual_categories
        if name == 'Iron County Jail':
            passed = passed and plan.get('outcome') != 'contact'
        named.append({'name': name, 'state': state, 'account_id': account['id'], 'passed': passed,
                      'outcome': plan.get('outcome'), 'objective': plan.get('objective'),
                      'intervention': plan.get('intervention'), 'signals': signals,
                      'tasks': plan.get('verification_tasks', [])})
        if not passed:
            failures.append({'name': name, 'state': state, 'reason': 'Named-case regression expectation failed'})
    def distribution(rows):
        return dict(Counter((decisions.get(r['opportunity_id'], {}).get('commercial_plan') or {}).get('outcome', 'missing') for r in rows))
    channel_types = Counter()
    for d in old_channel:
        o = store.opportunity(d['opportunity_id'])
        direct = o['evidence'].get('direct_current_cents', 0) or o['evidence'].get('direct_prior_cents', 0)
        # Source channels, including purchases outside comparable periods, establish the relationship class.
        import csv
        from clearline.config import Settings
        indexes = set(o['evidence'].get('source_rows', []))
        with (Settings.load().data_dir / 'orders.csv').open() as f:
            direct = any(n in indexes and r['sales_channel'] == 'direct' for n, r in enumerate(csv.DictReader(f), 2))
        channel_types['distributor_bill_to' if o['account_key'].startswith('DISTRIBUTOR|') else 'institution_with_direct_history' if direct else 'institution_distributor_only'] += 1
    base_id = original.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
    return {'engine': ENGINE_VERSION, 'accounts': len(accounts), 'outcomes': dict(outcomes),
            'signals': store.rows('SELECT category,investigation_status,count(*) n FROM commercial_signals WHERE active=1 GROUP BY category,investigation_status'),
            'old_drafts': {'count': len(old_drafts), 'new_decisions': distribution(old_drafts)},
            'old_channel_drafts': {'count': len(old_channel), 'relationship_classes': dict(channel_types), 'new_decisions': distribution(old_channel)},
            'original_activity_preserved': preserved, 'named_cases': named,
            'tasks': store.rows("SELECT blocking,count(*) tasks,count(DISTINCT opportunity_id) accounts FROM investigation_tasks WHERE status='pending' GROUP BY blocking"),
            'usage': store.rows("SELECT count(*) responses,SUM(json_extract(details,'$.cost_usd')) cost_usd,SUM(json_extract(details,'$.input_tokens')) input_tokens,SUM(json_extract(details,'$.output_tokens')) output_tokens FROM events WHERE id>? AND kind='api_response'", (base_id,)),
            'failures': failures, 'passed': not failures and len(accounts) == 486}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--env-file', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    result = report(args.source, args.before)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('named_cases', 'signals', 'tasks')}))
    raise SystemExit(0 if result['passed'] else 1)
