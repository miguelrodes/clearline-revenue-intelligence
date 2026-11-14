"""Explainable shortlist ranking; independent of AI evidence/cache identity."""
import json
import math
from collections import defaultdict
from .data import digest
from .store import utcnow

VERSION = 'agency-ranking-1'
WEIGHTS = {'fit': 40, 'scale': 25, 'similarity': 25, 'context': 10}
SCHEMA = """
CREATE TABLE IF NOT EXISTS agency_rankings(
 agency_id TEXT PRIMARY KEY REFERENCES agency_screenings(id), version TEXT NOT NULL,
 fingerprint TEXT NOT NULL, score REAL NOT NULL, explanation TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else 0
    except (ValueError, TypeError):
        return 0

def scale_field(kind):
    return 'jail_beds' if kind in ('county_jail', 'state_prison') else 'population_served' if kind in ('police_dept', 'sheriff') else None

def rebuild(store):
    rows = store.rows('SELECT id,evidence_hash,evidence FROM agency_screenings WHERE active=1 ORDER BY id')
    fingerprint = digest([VERSION, [(r['id'], r['evidence_hash']) for r in rows]])
    prior = store.rows('SELECT fingerprint,COUNT(*) n FROM agency_rankings GROUP BY fingerprint')
    if len(prior) == 1 and prior[0]['fingerprint'] == fingerprint and prior[0]['n'] == len(rows):
        return
    records = [(r, json.loads(r['evidence'])) for r in rows]
    scales = defaultdict(list)
    max_buyers = 1
    for _, e in records:
        a = e['agency'][0]; field = scale_field(a['agency_type'])
        if field and positive(a.get(field)):
            scales[a['agency_type']].append(positive(a[field]))
        max_buyers = max(max_buyers, e['segment_patterns']['distinct_named_buyers'])
    # A within-segment 95th percentile caps outliers. No extrapolated demand.
    caps = {kind: sorted(vals)[max(0, math.ceil(.95 * len(vals)) - 1)] for kind, vals in scales.items()}
    updates = []
    for r, e in records:
        a = e['agency'][0]; kind = a['agency_type']; skus = e['fit_hypothesis_skus']
        fit = {'county_jail':1, 'state_prison':1, 'sheriff':.8, 'police_dept':.8, 'facility_security':.7}.get(kind, 0) if skus else 0
        field = scale_field(kind); value = positive(a.get(field)) if field else 0
        cap = caps.get(kind, 0)
        scale = math.log1p(min(value, cap)) / math.log1p(cap) if value and cap else 0
        patterns = e['segment_patterns']; counts = patterns['product_buyers']
        coverage = sum(counts.get(s, 0) > 0 for s in skus) / len(skus) if skus else 0
        breadth = math.log1p(patterns['distinct_named_buyers']) / math.log1p(max_buyers)
        similarity = coverage * (.5 + .5 * breadth)
        # Completeness dominates context. HIDTA contributes at most ONE point;
        # fiscal-year presence contributes one, never an inferred deadline.
        complete = sum(bool(a.get(k)) for k in ('agency_name','state','city','county')) / 4
        context = .7 * complete + .1 * bool(value) + .1 * (a.get('in_hidta_region','').lower() in ('yes','true','1')) + .1 * bool(a.get('fy_end'))
        factors = [
            {'key':'fit','label':'Institution and product fit','points':round(40*fit,2),'maximum':40,'reason':f'{kind}: plausible catalogue applications in {", ".join(skus) if skus else "no supported physical-screening SKU"}; operational use remains unverified.'},
            {'key':'scale','label':'Relevant operational scale','points':round(25*scale,2),'maximum':25,'reason':f'{field or "No defensible size field"}: {value:g}; segment 95th-percentile cap {cap:g}. Log-scaled workload proxy, not consumption or demand.'},
            {'key':'similarity','label':'Observed purchaser similarity','points':round(25*similarity,2),'maximum':25,'reason':f'{patterns["distinct_named_buyers"]} distinct named buyers in this segment; {sum(counts.get(s,0)>0 for s in skus)}/{len(skus)} proposed SKUs observed. Segment resemblance only, not a matched institution.'},
            {'key':'context','label':'Supporting context and completeness','points':round(10*context,2),'maximum':10,'reason':'Identity-field completeness (7), scale supplied (1), HIDTA yes (1), fiscal-year field supplied (1). No inferred budgets or intent.'},
        ]
        score = round(sum(f['points'] for f in factors),2)
        eligible = e['classification'] == 'unverified_prospect' and bool(skus)
        explanation = dict(version=VERSION,score=score,factors=factors,eligible=eligible,
            restriction='No named customer match; hidden distributor coverage remains unresolved.' if eligible else 'Excluded from the discovery shortlist until relationship, identity or product-fit restrictions are resolved.',
            interpretation='Relative discovery priority, not purchase probability or estimated revenue.')
        updates.append((r['id'],VERSION,fingerprint,score,json.dumps(explanation),utcnow()))
    with store.connect(write=True) as con:
        con.execute('DELETE FROM agency_rankings')
        con.executemany('INSERT INTO agency_rankings VALUES(?,?,?,?,?,?)',updates)

def get(store, aid):
    rows = store.rows('SELECT explanation FROM agency_rankings WHERE agency_id=?',(aid,))
    return json.loads(rows[0]['explanation']) if rows else None
