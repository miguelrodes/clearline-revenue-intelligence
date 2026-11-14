import type {Account, Evidence} from './types';

type SituationAccount = Pick<Account, 'workflow' | 'holds' | 'evidence' | 'account_key'>;
const numeric = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const count = (value: number) => value.toLocaleString('en-US');
const money = (cents: number) => (cents / 100).toLocaleString('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  maximumFractionDigits: 2,
});

function date(value?: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? parsed : null;
}
function dateLabel(value?: string | null) {
  return date(value)?.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
}
function period(startValue?: string, endValue?: string) {
  const start = date(startValue), end = date(endValue);
  if (!start || !end || end <= start) return null;
  const last = new Date(end.getTime() - 86400000);
  if (start.getUTCDate() === 1 && end.getUTCDate() === 1 && start.getUTCFullYear() === last.getUTCFullYear()) {
    const month = (d: Date) => d.toLocaleDateString('en-US', {month: 'short', timeZone: 'UTC'});
    return `${month(start)}${start.getUTCMonth() === last.getUTCMonth() ? '' : `–${month(last)}`} ${start.getUTCFullYear()}`;
  }
  return `${dateLabel(startValue)}–${dateLabel(last.toISOString().slice(0, 10))}`;
}

function purchasing(e: Evidence, provisional: boolean, missingHistory: boolean) {
  if (missingHistory) return 'No confidently linked purchase history is saved, so inactivity or purchasing growth cannot be established.';
  const prior = e.prior_cents, current = e.current_cents;
  if (!numeric(prior) || !numeric(current)) return 'The saved purchase totals are incomplete, so a reliable purchasing comparison is unavailable.';
  const oldPeriod = period(e.comparison?.prior_start, e.comparison?.prior_end_exclusive);
  const newPeriod = period(e.comparison?.current_start, e.comparison?.current_end_exclusive);
  // Missing comparison boundaries stay unknown; do not infer a prior end date.
  const scope = oldPeriod && newPeriod ? `${oldPeriod} vs. ${newPeriod}` : 'In the saved comparison periods';
  const prefix = `${scope}, ${provisional ? 'provisionally assigned' : 'recorded'} net purchases`;
  if (prior === current) return `${prefix} ${prior === 0 ? 'total $0 in both periods; this is not proof of no purchasing' : `were unchanged at ${money(current)}`}.`;
  const delta = current - prior;
  const percent = prior > 0 ? `, ${Number((Math.abs(delta) * 100 / prior).toFixed(1))}%` : '';
  return `${prefix} ${delta > 0 ? 'rose' : 'fell'} from ${money(prior)} to ${money(current)} (${delta > 0 ? 'up' : 'down'} ${money(Math.abs(delta))}${percent})${prior === 0 ? '; a zero recorded baseline does not establish a new customer' : ''}.`;
}

function productHistory(e: Evidence, distributor: boolean) {
  const products = (e.products || []).filter(p => numeric(p.prior_cents) && numeric(p.current_cents));
  const change = (e.current_cents ?? 0) - (e.prior_cents ?? 0);
  // In growth accounts, keep a flagged product decline visible instead of hiding it behind total growth.
  const decliningSkus = new Set((e.signals || []).filter(s => s.type === 'product_decline').map(s => s.sku));
  const declining = change >= 0 ? products.filter(p => decliningSkus.has(p.sku) && p.current_tests < p.prior_tests) : [];
  const candidates = declining.length ? declining : products.filter(p => change < 0 ? p.current_cents < p.prior_cents : p.current_cents > p.prior_cents);
  const product = [...candidates].sort((a, b) => Math.abs(b.current_cents - b.prior_cents) - Math.abs(a.current_cents - a.prior_cents) || a.sku.localeCompare(b.sku))[0];
  const parts: string[] = [];
  if (!distributor && product) {
    const units = product.sku === 'CL-TRN' ? [product.prior_packs_or_sessions, product.current_packs_or_sessions] : [product.prior_tests, product.current_tests];
    const unitName = product.sku === 'CL-TRN' ? 'sessions' : 'tests';
    const qualifier = declining.length ? `Despite ${change > 0 ? 'the overall purchasing increase' : 'unchanged total purchases'}, ` : '';
    parts.push(`${qualifier}${product.name} (${product.sku}) net purchases ${product.current_cents < product.prior_cents ? 'fell' : product.current_cents > product.prior_cents ? 'rose' : 'were unchanged'} ${product.current_cents === product.prior_cents ? `at ${money(product.current_cents)}` : `from ${money(product.prior_cents)} to ${money(product.current_cents)}`}${units.every(numeric) ? `, with ${unitName} purchased changing from ${count(units[0])} to ${count(units[1])}` : ''}`);
  } else if (numeric(e.prior_tests) && numeric(e.current_tests) && (e.prior_tests || e.current_tests)) {
    parts.push(`Total recorded test quantities ${e.prior_tests === e.current_tests ? `were unchanged at ${count(e.current_tests)}` : `changed from ${count(e.prior_tests)} to ${count(e.current_tests)}`}`);
  }
  const last = dateLabel(e.last_purchase);
  if (last) parts.push(`${parts.length ? 'the' : 'The'} last identified consumables invoice was ${last}`);
  return parts.length ? `${parts.join('; ')}.` : null;
}

function orderHistory(e: Evidence, holds: string[]) {
  const flagged = (e.commercial_signals || []).filter(s => s.category === 'aging_open_order' && s.evidence?.order_id);
  const orders = [...new Map(flagged.map(s => [s.evidence!.order_id!, s])).values()];
  const cutoff = dateLabel(e.as_of);
  const scope = cutoff ? `At the ${cutoff} cutoff, ` : 'The saved order snapshot shows ';
  if (orders.length) {
    const valuesKnown = orders.every(s => numeric(s.amount_cents));
    const amount = orders.reduce((sum, s) => sum + (s.amount_cents || 0), 0);
    const largest = [...orders].sort((a, b) => (b.amount_cents || 0) - (a.amount_cents || 0))[0];
    const ages = orders.map(s => s.evidence?.age_days);
    const age = ages.every(numeric) ? ` (${Math.min(...ages) === Math.max(...ages) ? Math.min(...ages) : `${Math.min(...ages)}–${Math.max(...ages)}`} days old)` : '';
    return `${scope}${orders.length} flagged open ${orders.length === 1 ? `order, ${largest.evidence!.order_id},` : 'orders'}${valuesKnown ? ` had ${money(amount)} in open lines` : ' had unconfirmed open-line value'}${age}${orders.length > 1 ? `, including ${largest.evidence!.order_id}` : ''}; open lines are excluded from net purchases, and age alone does not establish a fulfillment delay.`;
  }
  if (holds.includes('open_orders_require_review')) {
    const references = [...new Set((e.commercial_signals || []).flatMap(s => s.category === 'missed_replenishment' ? s.evidence?.recent_open_orders || [] : []))];
    return `${scope}${references.length ? `open order${references.length === 1 ? '' : 's'} ${references.join(', ')}` : 'open orders'} ${references.length === 1 ? 'was' : 'were'} recorded separately from net purchases; completion is not established by those records.`;
  }
  return null;
}

/** Presentation only: no model calls, decisions, database writes or reassessment. */
export function businessSituation(account: SituationAccount): string[] {
  if (account.workflow !== 'recovery') return [];
  const e = account.evidence, holds = account.holds;
  const distributor = (account.account_key || e.account_key || '').startsWith('DISTRIBUTOR|');
  const missingHistory = holds.includes('missing_purchase_history');
  const identity = holds.some(h => ['ambiguous_identity', 'identity_needs_review', 'possible_missing_state_alias', 'multiple_shipping_cities'].includes(h));
  const sentences = [purchasing(e, identity, missingHistory)];
  const history = !missingHistory && productHistory(e, distributor);
  if (history) sentences.push(history);
  const note = e.crm_notes?.trim().replace(/\s+/g, ' ');
  const lastContact = dateLabel(e.last_contacted);
  if (note && /[\p{L}\p{N}]/u.test(note)) {
    sentences.push(`An undated CRM note says “${note.replace(/[.!?]+$/, '')}”${lastContact ? ` (last recorded contact: ${lastContact})` : ''}; its current relevance is unconfirmed.`);
  } else if (missingHistory && lastContact) {
    sentences.push(`CRM records contact on ${lastContact}, but that does not establish a purchase.`);
  }
  const orders = !missingHistory && orderHistory(e, holds);
  const limits: string[] = [];
  if (identity) limits.push('customer matching remains uncertain');
  if (holds.includes('undated_history')) limits.push('undated transactions cannot be placed in the comparison periods');
  if (distributor) limits.push('these are distributor bill-to purchases, overlapping attributed end-customer sales, so the two views must not be added together');
  else if (!missingHistory && (holds.includes('known_distributor_channel') || (e.signals || []).some(s => s.type === 'inactivity' || s.type === 'direct_gap_channel_review'))) {
    limits.push('unidentified distributor purchases may be missing from this customer’s history');
  }
  // Keep the narrative to four sentences without suppressing material limitations.
  if (orders) sentences.push(orders);
  if (limits.length) {
    if (sentences.length === 4) sentences[3] = `${sentences[3].slice(0, -1)}; ${limits.join('; ')}.`;
    else sentences.push(`${limits[0][0].toUpperCase()}${limits.join('; ').slice(1)}.`);
  }
  return sentences;
}
