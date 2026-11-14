"""Read-only account identity labels; never inputs to assessment or permissions."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from hashlib import sha256
from .data import basic
from .evidence import source_records

# Reuse the institution kinds already assigned by data.canonical; do not rematch.
INSTITUTIONS = {
    'county_jail': 'Detention facility', 'state_prison': 'Correctional facility',
    'sheriff': "Sheriff’s office", 'police_dept': 'Police department',
    'probation_parole': 'Probation or parole agency', 'drug_court': 'Drug or treatment court',
    'facility_security': 'Security or logistics facility',
}
STATES = dict(pair.split(':') for pair in (
    'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|'
    'FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|'
    'LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|'
    'MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|'
    'NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|'
    'RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|'
    'VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:Washington, DC'
).split('|'))


def describe_account(account, orders=(), source_available=True):
    e = account['evidence']
    key = account.get('account_key') or e.get('account_key', '')
    parts = key.split('|')
    kind = parts[1] if len(parts) > 1 else 'unknown'
    distributor = key.startswith('DISTRIBUTOR|buyer|')
    holds = set(account.get('holds', [])) | set(e.get('holds', []))
    ambiguous = bool(holds & {'ambiguous_identity', 'multiple_shipping_cities'}) or key.startswith(('UNRESOLVED|', 'CRM_UNRESOLVED|'))
    ids = {f'orders:{n}' for n in e.get('source_rows', [])}
    rows = [r for r in orders if r['ref'] in ids]
    names = {basic(n) for n in [account['name'], *e.get('aliases', [])] if n}
    # A named distributor bill-to record identifies the distributor, never its
    # unnamed downstream buyers. Only inspect this account's already-linked rows.
    distributor_role = any(r.get('sales_channel') == 'distributor' and basic(r.get('bill_to_account', '')) in names for r in rows)
    conflict = distributor_role and not distributor
    account_type = 'Unknown' if ambiguous or conflict else 'Distributor' if distributor else 'End buyer' if kind in INSTITUTIONS else 'Unknown'
    reasons = []
    if ambiguous or conflict:
        reasons.append('Account identity is unresolved or conflicting; purchasing routes are not asserted.')
    elif distributor:
        reasons.append('The saved account is explicitly a distributor bill-to buyer.')
    elif kind in INSTITUTIONS:
        reasons.append('The saved account identity identifies an institutional buyer.')
    else:
        reasons.append('The saved records do not establish an institutional buyer or distributor.')

    direct, indirect = [], []
    if not ambiguous and not conflict:
        for r in rows:
            try:
                purchased = r.get('status') == 'invoiced' and Decimal(r.get('qty', '0')) > 0
                within_cutoff = date.fromisoformat(r.get('order_date', '')) <= date.fromisoformat(e.get('as_of', ''))
            except (ValueError, InvalidOperation):
                continue
            if not purchased or not within_cutoff:
                continue
            if distributor:
                if basic(r.get('bill_to_account', '')) in names:
                    direct.append(r['ref'])
            elif r.get('sales_channel') == 'direct' and basic(r.get('bill_to_account', '')) in names:
                direct.append(r['ref'])
            elif r.get('sales_channel') == 'distributor' and basic(r.get('end_customer', '')) in names:
                indirect.append(r['ref'])
        # Reuse the scan's documented CRM route. Exact standalone note only:
        # uncertainty/negation/free-form correspondence must not imply purchases.
        if not distributor and e.get('crm_id') and e.get('crm_notes', '').strip().rstrip('.').casefold() == 'switched to distributor':
            indirect.append('crm:' + e['crm_id'])
    channel = 'Both' if direct and indirect else 'Direct' if direct else 'Through distributor' if indirect else 'Unknown'
    if direct:
        reasons.append('Dated positive invoices identify this account as the buyer from Clearline.' if distributor else 'Dated positive direct invoices are linked to this account.')
    if indirect:
        reasons.append('Named end-customer invoices or an explicit CRM switch document the distributor route; CRM notes are undated.')
    if channel == 'Unknown' and not ambiguous and not conflict:
        reasons.append('No reliable completed-purchase route is established by the available records.')
    if not source_available:
        reasons.append('The audited order snapshot is unavailable; order-based purchasing routes cannot be verified.')

    if ambiguous or conflict:
        description = 'Organization recorded in Clearline’s account history whose identity and purchasing relationship need confirmation.'
    else:
        noun = 'Distributor' if distributor else INSTITUTIONS.get(kind, 'Organization')
        location = STATES.get(account.get('state') or e.get('state'))
        # Distributor shipping states describe deliveries, not its own location.
        place = f' in {location}' if location and not distributor else ''
        relationship = ('with recorded purchases from Clearline, both directly and through a distributor' if channel == 'Both' else
                        'with a history of purchasing directly from Clearline' if direct else
                        'with a documented distributor purchasing relationship' if indirect else
                        'recorded in Clearline’s CRM, with no confirmed purchasing route' if e.get('crm_id') else
                        'recorded in Clearline’s account history, with its purchasing route unconfirmed')
        description = f'{noun}{place} {relationship}.'
    return {'account_type': account_type, 'purchasing_channel': channel, 'description': description,
            'evidence': reasons, 'channel_refs': direct + indirect,
            'channel_scope': 'Recorded purchasing routes over the saved history; not current exclusivity or contact authorization.'}


def account_profiles(store, settings, accounts):
    """Attach transient display metadata without writing to the saved evidence."""
    scans = store.rows('SELECT summary FROM scans ORDER BY created_at DESC,rowid DESC LIMIT 1')
    expected = json.loads(scans[0]['summary']).get('hashes', {}).get('orders') if scans else None
    rows, available = [], False
    if expected:
        try:
            path = settings.data_dir / 'orders.csv'
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Order snapshot changed')
            rows = source_records(str(path), expected)
            available = True
        except (OSError, ValueError):
            pass
    return {a['id']: describe_account(a, rows, available) for a in accounts}
