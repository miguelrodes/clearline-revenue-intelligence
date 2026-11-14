import {describe, expect, it} from 'vitest';
import {businessSituation} from '../src/lib/business-situation';
import type {Evidence} from '../src/lib/types';

const comparison = {prior_start: '2025-01-01', prior_end_exclusive: '2025-11-01', current_start: '2026-01-01', current_end_exclusive: '2026-11-01'};
function account(evidence: Evidence = {}, holds: string[] = []) {
  return {workflow: 'recovery', holds, evidence: {comparison, ...evidence}};
}
const product = {sku: 'CL-MAIL50', name: 'Mailroom screening kit, 50 tests', prior_cents: 200000, current_cents: 50000, prior_tests: 500, current_tests: 100, prior_packs_or_sessions: 10, current_packs_or_sessions: 2};
describe('saved-evidence business situation', () => {
  it('explains a decline using precise dollars, volumes and dated invoices without treating a CRM note as current fact', () => {
    const a = account({prior_cents: 300000, current_cents: 150000, products: [product], last_purchase: '2026-07-16', last_contacted: '2025-05-05', crm_notes: 'Wants training for night shift'});
    const text = businessSituation(a).join(' ');
    expect(text).toContain('Jan–Oct 2025 vs. Jan–Oct 2026');
    expect(text).toContain('fell from $3,000 to $1,500 (down $1,500, 50%)');
    expect(text).toContain('CL-MAIL50');
    expect(text).toContain('tests purchased changing from 500 to 100');
    expect(text).toContain('consumables invoice was Jul 16, 2026');
    expect(text).toContain('An undated CRM note says “Wants training for night shift” (last recorded contact: May 5, 2025); its current relevance is unconfirmed');
    expect(text).not.toMatch(/caused|overdue|recoverable|recommend/i);
  });
  it('does not equate a zero net total with no purchases or unavailable distributor activity', () => {
    const text = businessSituation(account({prior_cents: 500000, current_cents: 0, signals: [{type: 'inactivity'}], last_purchase: '2025-09-03'})).join(' ');
    expect(text).toContain('net purchases fell');
    expect(text).toContain('Sep 3, 2025');
    expect(text).toContain('Unidentified distributor purchases may be missing');
    expect(text).not.toMatch(/stopped buying|no purchases|lost customer/i);
  });
  it('describes healthy growth without inventing a recovery problem', () => {
    const text = businessSituation(account({prior_cents: 200000, current_cents: 250000, prior_tests: 500, current_tests: 600})).join(' ');
    expect(text).toContain('rose from $2,000 to $2,500 (up $500, 25%)');
    expect(text).toContain('test quantities changed from 500 to 600');
    expect(text).not.toMatch(/decline|recovery|inactive|reorder/i);
  });
  it('keeps flagged SKU decline visible even when total revenue grows', () => {
    const text = businessSituation(account({prior_cents: 200000, current_cents: 300000, products: [product], signals: [{type: 'product_decline', sku: 'CL-MAIL50'}]})).join(' ');
    expect(text).toContain('Despite the overall purchasing increase');
    expect(text).toContain('net purchases fell from $2,000 to $500');
  });
  it('does not fabricate percentage growth, new-customer status or dates from a zero baseline', () => {
    const text = businessSituation(account({prior_cents: 0, current_cents: 100020, last_purchase: null})).join(' ');
    expect(text).toContain('rose from $0 to $1,000.20 (up $1,000.20)');
    expect(text).toContain('does not establish a new customer');
    expect(text).not.toMatch(/%|last identified|NaN|Infinity/);
  });
  it('treats missing history and missing totals differently from zero purchasing', () => {
    const text = businessSituation(account({prior_cents: 0, current_cents: 0, last_contacted: '2025-11-28'}, ['missing_purchase_history', 'identity_needs_review'])).join(' ');
    expect(text).toContain('No confidently linked purchase history');
    expect(text).toContain('CRM records contact on Nov 28, 2025, but that does not establish a purchase');
    expect(text).not.toContain('$0');
    expect(businessSituation(account({prior_cents: 10}))).toEqual(['The saved purchase totals are incomplete, so a reliable purchasing comparison is unavailable.']);
  });
  it('keeps undated rows and provisional identity visible without making them explanations for a decline', () => {
    const text = businessSituation(account({prior_cents: 100000, current_cents: 20000, crm_notes: 'Asked about grant funding'}, ['undated_history', 'ambiguous_identity'])).join(' ');
    expect(text).toContain('provisionally assigned net purchases fell');
    expect(text).toContain('Customer matching remains uncertain; undated transactions cannot be placed in the comparison periods');
    expect(text).not.toContain('funding caused');
  });
  it('summarizes flagged distributor open lines once, separate from revenue and delivery promises', () => {
    const first = {category: 'aging_open_order', amount_cents: 120000, evidence: {order_id: 'SO-1', age_days: 40}};
    const a = {...account({as_of: '2026-11-01', prior_cents: 500000, current_cents: 300000, prior_tests: 1000, current_tests: 500, commercial_signals: [first, {...first}, {category: 'aging_open_order', amount_cents: 50025, evidence: {order_id: 'SO-2', age_days: 35}}]}), account_key: 'DISTRIBUTOR|buyer|example'};
    const sentences = businessSituation(a), text = sentences.join(' ');
    expect(sentences).toHaveLength(4);
    expect(text).toContain('2 flagged open orders had $1,700.25 in open lines (35–40 days old)');
    expect(text).toContain('open lines are excluded from net purchases');
    expect(text).toContain('age alone does not establish a fulfillment delay');
    expect(text).toContain('distributor bill-to purchases, overlapping attributed end-customer sales');
    expect(text).not.toContain('fell from $5,000 to $4,700.25');
  });
  it('does not invent a recent open order amount, age, or fulfillment result', () => {
    const text = businessSituation(account({as_of: '2026-11-01', commercial_signals: [{category: 'missed_replenishment', evidence: {recent_open_orders: ['SO-7', 'SO-7']}}]}, ['open_orders_require_review'])).join(' ');
    expect(text).toContain('open order SO-7 was recorded separately from net purchases');
    expect(text).toContain('completion is not established');
    expect(text.match(/SO-7/g)).toHaveLength(1);
    expect(text).not.toMatch(/\$|days old|late/);
  });
  it('keeps unknown boundaries and invalid calendar dates unknown', () => {
    const text = businessSituation(account({comparison: {...comparison, prior_end_exclusive: undefined}, prior_cents: 100, current_cents: 200, last_purchase: '2026-02-30', last_contacted: 'unknown'})).join(' ');
    expect(text).toContain('In the saved comparison periods');
    expect(text).not.toMatch(/Jan–Oct|last identified|March|Mar /);
  });
  it('derives other comparison windows instead of assuming January–October', () => {
    const text = businessSituation(account({comparison: {prior_start: '2024-04-01', prior_end_exclusive: '2024-07-01', current_start: '2025-04-01', current_end_exclusive: '2025-07-01'}, prior_cents: 100, current_cents: 100})).join(' ');
    expect(text).toContain('Apr–Jun 2024 vs. Apr–Jun 2025');
    expect(text).toContain('were unchanged at $1');
  });
  it('counts training in sessions, never tests', () => {
    const text = businessSituation(account({prior_cents: 0, current_cents: 35000, products: [{...product, sku: 'CL-TRN', name: 'Officer training', prior_cents: 0, current_cents: 35000, prior_tests: 0, current_tests: 0, prior_packs_or_sessions: 0, current_packs_or_sessions: 1}]})).join(' ');
    expect(text).toContain('sessions purchased changing from 0 to 1');
    expect(text).not.toContain('tests purchased');
  });
  it('retains material context in at most four sentences without mutating saved inputs', () => {
    const a = account({prior_cents: 500000, current_cents: 300000, products: [product], crm_notes: 'Wants training', commercial_signals: [{category: 'aging_open_order', amount_cents: 50025, evidence: {order_id: 'SO-2', age_days: 35}}]}, ['undated_history', 'identity_needs_review']);
    const before = JSON.stringify(a);
    const sentences = businessSituation(a);
    expect(sentences).toHaveLength(4);
    expect(sentences.join(' ')).toMatch(/SO-2.*customer matching remains uncertain.*undated transactions/);
    expect(JSON.stringify(a)).toBe(before);
  });
  it('leaves prospecting outside this renderer', () => {
    expect(businessSituation({...account(), workflow: 'prospecting'})).toEqual([]);
  });
});
