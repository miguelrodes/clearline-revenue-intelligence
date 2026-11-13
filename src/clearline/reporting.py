"""Read models for the HTTP UI. Business decisions remain in data.py and Store."""
from functools import lru_cache
from hashlib import sha256
import json

import pandas as pd

from .data import cents
from .store import STOPPED_STATUSES


def primary_opportunity(signals):
    """Assign each account one display group, matching the opportunity table."""
    if "inactivity" in signals:
        return "inactivity"
    if "reduced_purchasing" in signals:
        return "purchasing_decline"
    if "product_decline" in signals:
        return "product_decline"
    if "direct_gap_channel_review" in signals:
        return "channel_review"
    return "other"


def opportunities(store, workflow="recovery"):
    result = []
    for row in store.rows("SELECT * FROM opportunities WHERE active=1 AND workflow=?", (workflow,)):
        e = json.loads(row.pop("evidence"))
        row["holds"] = json.loads(row["holds"])
        signals = sorted({s["type"] for s in e.get("signals", [])})
        prior, current = e.get("prior_cents", 0), e.get("current_cents", 0)
        decisions = store.rows("SELECT e.details,e.created_at,j.payload FROM events e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.opportunity_id=? AND e.kind='agent_decision' ORDER BY e.id DESC LIMIT 1", (row["id"],))
        decision = json.loads(decisions[0]["details"]) if decisions else None
        if decision and decision.get('evidence_hash',json.loads(decisions[0]['payload'] or '{}').get('evidence_hash'))!=row['evidence_hash']: decision=None
        row.update(engine_version=decision.get('engine_version') if decision else None, recommended_action=decision.get('recommended_action') if decision else None,prior_cents=prior, current_cents=current,
                   change_cents=current-prior, decline_pct=(prior-current)/prior*100 if prior > 0 else None,
                   prior_tests=e.get("prior_tests", 0), current_tests=e.get("current_tests", 0),
                   signals=signals, primary_opportunity=primary_opportunity(signals),
                   partial_decline="reduced_purchasing" in signals and "inactivity" not in signals and current>0,
                   evidence_quality="Review required" if row["holds"] else ("Name & state match" if e.get("match_tier")=="exact_name_state" else "Alias needs verification"),
                   owner=e.get("owner") or "Unassigned", last_purchase=e.get("last_purchase"),
                   assessment=decision["decision"] if decision else None,
                   next_action="Review email" if row["status"]=="awaiting_approval" and decision and (decision.get("quality") or {}).get("passed") else "No action recommended" if row["status"]=="no_action" else "Investigate evidence" if row["holds"] and not decision else "Review agent findings" if row["holds"] else "Verify contact / prepare simulated campaign" if row["status"]=="needs_contact" else "No action recommended" if row["status"]=="no_action" else "Review email" if row["status"]=="awaiting_approval" else "Track follow-up" if row["status"]=="awaiting_response" else "Review recorded outcome" if row["status"] in STOPPED_STATUSES else "Investigate agent hold" if row["status"]=="agent_held" else "Review agent work" if decision else "Assess opportunity")
        result.append(row)
    return sorted(result, key=lambda r: (bool(r["holds"]), -r["decline_cents"], r["id"]))


@lru_cache(maxsize=4)
def _audited_orders(folder, orders_hash, products_hash):
    from pathlib import Path
    folder = Path(folder)
    for name, expected in [("orders",orders_hash),("products",products_hash)]:
        if sha256((folder/f"{name}.csv").read_bytes()).hexdigest() != expected:
            raise ValueError("Source files changed since the saved scan. Run a new scan before using monthly trends.")
    orders = pd.read_csv(folder/"orders.csv", dtype=str, keep_default_na=False)
    products = pd.read_csv(folder/"products.csv", dtype=str, keep_default_na=False)
    orders["source_row"] = range(2, len(orders)+2)
    orders["date"] = pd.to_datetime(orders.order_date, errors="coerce")
    orders["net_cents"] = orders.line_total.map(cents).where(orders.status.isin(["invoiced","credit_memo"]), 0)
    packs = products.set_index("sku").tests_per_pack.astype(int)
    orders["tests"] = (orders.qty.astype(int)*orders.sku.map(packs)).where(orders.status.ne("open") & orders.sku.ne("CL-TRN"),0)
    return orders


def monthly_trends(store, settings, evidence=None):
    """Read-only aggregation of the exact source snapshot used by the scan.

    Same signed credit/open-order/date/physical-volume semantics as data.scan.
    No new matching: account rows come exclusively from persisted source_row IDs.
    """
    scans = store.rows("SELECT summary FROM scans ORDER BY created_at DESC LIMIT 1")
    if not scans: return {"rows":[], "limitation":"No saved purchase scan."}
    summary = json.loads(scans[0]["summary"])
    try:
        hashes = summary["hashes"]
        orders = _audited_orders(str(settings.data_dir), hashes["orders"], hashes["products"])
        if evidence is not None:
            orders = orders[orders.source_row.isin(evidence.get("source_rows",[]))]
        end = pd.Timestamp(summary["as_of"])
        rows = [{"month":pd.Timestamp(2025,m,1).strftime("%b"),"prior_cents":0,"current_cents":0,"prior_tests":0,"current_tests":0} for m in range(1, end.month+1) if pd.Timestamp(end.year,m,1)<end]
        frequency = {}
        for label, cutoff in [("prior",end-pd.DateOffset(years=1)),("current",end)]:
            period = orders[orders.date.ge(cutoff.replace(month=1,day=1)) & orders.date.lt(cutoff)]
            for m, group in period.groupby(period.date.dt.month):
                rows[int(m)-1][label+"_cents"] = int(group.net_cents.sum())
                rows[int(m)-1][label+"_tests"] = int(group.tests.sum())
            purchases = period[period.status.eq("invoiced") & period.qty.astype(int).gt(0) & period.sku.ne("CL-TRN")]
            frequency[label+"_purchase_dates"] = int(purchases.date.nunique())
        return {"rows":rows,"frequency":frequency,"limitation":None}
    except (KeyError, ValueError, OSError) as exc:
        return {"rows":[],"limitation":str(exc)}


def valid_draft(store, draft):
    from .conversations import policy
    from .action_policy import permitted
    from .evidence import ENGINE_VERSION,context_hash
    opp=store.opportunity(draft['opportunity_id']);a=json.loads(draft['analysis']) if isinstance(draft['analysis'],str) else draft['analysis']
    with store.connect() as con:
        restriction=policy(con,opp['id'])
        stale=bool(a.get('engine_version')) and a.get('context_hash')!=context_hash(con,opp['id'])
    return bool(not stale and permitted(opp,a,restriction,draft) and opp['active'] and opp['status'] not in STOPPED_STATUSES and opp['evidence_hash']==draft['evidence_hash'])


def portfolio_transactions(store, settings, year, query="", offset=0):
    scans=store.rows("SELECT summary FROM scans ORDER BY created_at DESC LIMIT 1")
    if not scans: return {"rows":[],"total":0,"net_cents":0,"tests":0}
    summary=json.loads(scans[0]["summary"])
    hashes=summary["hashes"]
    orders=_audited_orders(str(settings.data_dir),hashes["orders"],hashes["products"])
    end=pd.Timestamp(summary["as_of"]).replace(year=year)
    period=orders[orders.date.ge(end.replace(month=1,day=1)) & orders.date.lt(end)].copy()
    if query:
        period=period[period.bill_to_account.str.contains(query,case=False,regex=False)|period.end_customer.str.contains(query,case=False,regex=False)|period.order_id.str.contains(query,case=False,regex=False)]
    period=period.sort_values(["date","source_row"],ascending=[False,True])
    selected=period.iloc[offset:offset+100][["source_row","order_id","order_date","bill_to_account","end_customer","sales_channel","sku","qty","status","net_cents","tests"]]
    return {"rows":selected.to_dict(orient="records"),"total":len(period),"net_cents":int(period.net_cents.sum()),"tests":int(period.tests.sum())}
