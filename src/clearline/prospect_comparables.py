"""Historical product purchases by verified, same-type buyers in the fictional screening dataset."""
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .data import basic, cents
from .screening import FIT


_BUYERS = {
    'county_jail': 'county detention facilities', 'state_prison': 'state correctional facilities',
    'sheriff': 'sheriff’s offices', 'police_dept': 'police departments',
    'facility_security': 'security facilities',
}
_MIN_BUYERS = 5


def _direct_purchases(evidence, start, stop):
    """Exclude the buyer from the dollar benchmark if any relevant direct line is uncertain."""
    agency = evidence['agency'][0]
    products = set(evidence['fit_hypothesis_skus'])
    net = 0
    observed = set()
    uncertain = False
    seen = set()
    for row in evidence['relationship_records']:
        if (row.get('source') != 'order' or row['sales_channel'] != 'direct'
                or row['status'] not in ('invoiced', 'credit_memo') or row['sku'] not in products):
            continue
        if not row['order_date']:
            uncertain = True
            continue
        if not start <= row['order_date'] < stop:
            continue
        if (basic(row['bill_to_account']) != basic(agency['agency_name'])
                or row['ship_to_state'] != agency['state'] or basic(row['ship_to_city']) != basic(agency['city'])):
            uncertain = True
            continue
        # The export has no line ID to disambiguate two otherwise identical lines.
        line = (row['order_id'], row['order_date'], row['sku'], row['qty'], row['unit_price'], row['line_total'], row['status'])
        if line in seen:
            uncertain = True
        seen.add(line)
        if row['status'] == 'invoiced' and Decimal(row['qty']) > 0:
            observed.add(row['sku'])
        net += cents(row['line_total'])
    return observed, None if uncertain or not observed else net


def comparable_purchases(store):
    """Compute the comparison once per projection, exclusively from saved fictional records."""
    result = {
        kind: ('Check the institution’s screening needs and buying route. The saved evidence does not establish '
               'a reliable spending comparison.' if skus else
               'The screening has no established product fit for this institution type. Verify its operational need first.')
        for kind, skus in FIT.items()
    }
    scans = store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
    if not scans:
        return result
    snapshot = json.loads(scans[0]['summary'])
    hashes = snapshot.get('hashes', {})
    if not all(hashes.get(k) for k in ('orders', 'products', 'public_agencies')) or not snapshot.get('as_of'):
        return result
    stop = date.fromisoformat(snapshot['as_of'])
    start = stop.replace(month=1, day=1)
    period = f'{start:%b} {start.day}–{stop - timedelta(days=1):%b %d, %Y}'
    spend = defaultdict(list)
    observed_products = defaultdict(set)
    comparable_products = defaultdict(set)
    product_names = {}
    for row in store.rows("""SELECT agency_type,evidence FROM agency_screenings
                            WHERE active=1 AND classification='verified_existing'"""):
        evidence = json.loads(row['evidence'])
        kind = row['agency_type']
        if (kind not in _BUYERS or evidence.get('as_of') != snapshot['as_of'] or evidence.get('identity_conflicts')
                or evidence.get('provenance') != 'fictional_agency_dataset'
                or any(evidence.get('source_hashes', {}).get(k) != hashes[k] for k in ('orders', 'products', 'public_agencies'))):
            continue
        observed, net = _direct_purchases(evidence, start.isoformat(), stop.isoformat())
        observed_products[kind].update(observed)
        if net is not None:
            spend[kind].append(Decimal(net) / 100)
            comparable_products[kind].update(evidence['fit_hypothesis_skus'])
        for product in evidence['products']:
            product_names[product['sku']] = product['name'].split(',')[0].split(' (')[0].lower()
    for kind, skus in observed_products.items():
        if not skus:
            continue
        products = comparable_products[kind] if len(spend[kind]) >= _MIN_BUYERS else skus
        names = ' and '.join(product_names.get(sku, sku) for sku in sorted(products))
        if len(spend[kind]) < _MIN_BUYERS:
            result[kind] = (f'Existing {_BUYERS[kind]} in the case data bought the {names} directly. '
                            'Fewer than five buyers have sufficiently clear records for a spending comparison.')
        else:
            result[kind] = (f'Across {len(spend[kind])} {_BUYERS[kind]} with unambiguous direct records in the case data, median net '
                            f'purchases for the {names} were ${median(spend[kind]):,.2f} per buyer '
                            f'({period}, invoices less credits). Verify this prospect’s needs and buying route before estimating demand.')
    return result
