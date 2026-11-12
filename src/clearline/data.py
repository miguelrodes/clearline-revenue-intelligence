"""Deterministic recovery evidence. Source CSVs are read only, never copied into Git."""
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import pandas as pd


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def basic(value):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(value).lower().replace("'", "")).split())


def canonical(name, state):
    """Type-preserving aliases are hypotheses; missing/conflicting states never join."""
    s = basic(name)
    state = str(state).strip().upper()
    match = re.match(r"^([a-z]{2}) (?:doc|state correctional|probation)", s)
    conflict = bool(match and state and match.group(1).upper() != state)
    kind, stem = "unknown", s
    patterns = [
        (r"\b(jail|detention)\b", "county_jail", r"\b(co|county|jail|detention|center)\b"),
        (r"\b(sheriff|sheriffs|so)\b", "sheriff", r"\b(co|county|sheriff|sheriffs|so|office)\b"),
        (r"\b(police|pd)\b", "police_dept", r"\b(city of|police|department|dept|pd)\b"),
        (r"\b(correctional|doc)\b", "state_prison", r"^[a-z]{2} (doc|state correctional facility) |\bcorrectional\b"),
        (r"\bprobation\b", "probation_parole", r"^[a-z]{2} probation parole |\b(co|county|adult|probation|dept)\b"),
        (r"\b(drug|treatment) court\b", "drug_court", r"\b(co|county|drug|treatment|court)\b"),
        (r"\b(logistics|hub|security)\b", "facility_security", r"\b(regional|logistics|hub|security)\b"),
    ]
    for pattern, typ, remove in patterns:
        if re.search(pattern, s):
            kind, stem = typ, " ".join(re.sub(remove, "", s).split())
            break
    key = f"{state}|{kind}|{stem}" if state and s and not conflict else ""
    return key, kind, stem


@dataclass(frozen=True)
class ScanPolicy:
    as_of: str = "2026-11-01"
    inactivity_days: int = 90
    cadence_multiplier: float = 1.5
    decline_fraction: float = 0.25
    minimum_prior_revenue: float = 1000


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1")))


def _read(folder, name, required):
    path = Path(folder) / f"{name}.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"{name}.csv missing columns: {sorted(missing)}")
    df["source_row"] = range(2, len(df) + 2)
    return df, sha256(path.read_bytes()).hexdigest()


def scan(folder, policy=ScanPolicy()):
    as_of = pd.Timestamp(policy.as_of)
    if not 0 < policy.decline_fraction < 1 or policy.inactivity_days < 1 or policy.cadence_multiplier <= 0:
        raise ValueError("Invalid scan thresholds")
    orders, oh = _read(folder, "orders", ["order_id", "order_date", "bill_to_account", "end_customer", "ship_to_city", "ship_to_state", "sales_channel", "sku", "qty", "unit_price", "line_total", "status"])
    products, ph = _read(folder, "products", ["sku", "name", "tests_per_pack", "list_price_until_2025_06_30", "list_price_from_2025_07_01"])
    crm, ch = _read(folder, "crm_accounts", ["crm_id", "account_name", "state", "owner", "notes", "last_contacted"])
    public, ah = _read(folder, "public_agencies", ["agency_name", "state", "city"])
    if products.sku.duplicated().any():
        raise ValueError("Duplicate product SKU; cannot calculate reliable volumes")
    if not orders.status.isin(["invoiced", "open", "credit_memo"]).all():
        raise ValueError("Unrecognized order status")
    if not orders.sales_channel.isin(["direct", "distributor"]).all():
        raise ValueError("Unrecognized sales channel")
    if not orders.sku.isin(products.sku).all():
        raise ValueError("Order contains unknown SKU")
    duplicate_excess = int(orders.drop(columns="source_row").duplicated().sum())
    orders["date"] = pd.to_datetime(orders.order_date, errors="coerce")
    if (orders.order_date.ne("") & orders.date.isna()).any():
        raise ValueError("Invalid nonempty order date")
    orders["value_cents"] = orders.line_total.map(cents)
    orders["qty"] = pd.to_numeric(orders.qty, errors="raise")
    if not orders.qty.map(lambda n: float(n).is_integer()).all():
        raise ValueError("Expected whole packs/sessions")
    orders["qty"] = orders.qty.astype(int)
    orders["net_cents"] = orders.value_cents.where(orders.status.isin(["invoiced", "credit_memo"]), 0)
    if ((orders.status.eq("credit_memo") & ((orders.value_cents > 0) | (orders.qty > 0))) |
        (orders.status.ne("credit_memo") & ((orders.value_cents < 0) | (orders.qty < 0)))).any():
        raise ValueError("Unexpected signed credit/order quantities or values")
    catalogue = products.set_index("sku")
    packs = products.set_index("sku").tests_per_pack.astype(int)
    orders["tests"] = (orders.qty * orders.sku.map(packs)).where(orders.status.ne("open") & orders.sku.ne("CL-TRN"), 0)
    orders["customer"] = orders.bill_to_account.where(orders.sales_channel.eq("direct"), orders.end_customer)
    for frame, name, state in [(orders, "customer", "ship_to_state"), (crm, "account_name", "state"), (public, "agency_name", "state")]:
        frame[["key", "kind", "stem"]] = pd.DataFrame([canonical(n, s) for n, s in zip(frame[name], frame[state])], index=frame.index)
    ambiguous = set(public.loc[public.key.duplicated(False), "key"]) | set(crm.loc[crm.key.duplicated(False), "key"])
    cm = crm.loc[~crm.key.duplicated(False) & crm.key.ne("")].set_index("key")
    pm = public.loc[~public.key.duplicated(False) & public.key.ne("")].set_index("key")
    missing_signatures = set(zip(orders.loc[orders.ship_to_state.eq(""), "kind"], orders.loc[orders.ship_to_state.eq(""), "stem"]))
    # Comparable YTD windows exclude as-of day; same-day purchases still suppress inactivity.
    current_start = as_of.replace(month=1, day=1)
    previous_start = current_start - pd.DateOffset(years=1)
    previous_end = as_of - pd.DateOffset(years=1)
    known = orders[orders.key.ne("") & (orders.date.le(as_of) | orders.date.isna())]
    opportunities = []
    for key, all_rows in known.groupby("key"):
        history = all_rows[all_rows.date.lt(as_of)]
        buys = all_rows[all_rows.status.eq("invoiced") & all_rows.qty.gt(0) & all_rows.sku.ne("CL-TRN") & all_rows.date.notna()]
        direct = buys[buys.sales_channel.eq("direct")]
        if direct.empty:
            continue
        dates = buys.date.drop_duplicates().sort_values()
        direct_dates = direct.date.drop_duplicates().sort_values()
        median_gap = float(dates.diff().dt.days.dropna().median()) if len(dates) > 1 else None
        direct_gap = float(direct_dates.diff().dt.days.dropna().median()) if len(direct_dates) > 1 else None
        age = int((as_of - dates.max()).days)
        direct_age = int((as_of - direct_dates.max()).days)
        prior = history[history.date.ge(previous_start) & history.date.lt(previous_end)]
        current = history[history.date.ge(current_start)]
        prior_cents, current_cents = int(prior.net_cents.sum()), int(current.net_cents.sum())
        prior_tests, current_tests = int(prior.tests.sum()), int(current.tests.sum())
        signals = []
        inactive = len(direct_dates) >= 3 and median_gap and age > policy.inactivity_days and age > policy.cadence_multiplier * median_gap
        direct_inactive = len(direct_dates) >= 3 and direct_gap and direct_age > policy.inactivity_days and direct_age > policy.cadence_multiplier * direct_gap
        if inactive:
            signals.append({"type": "inactivity", "days_since_purchase": age, "median_gap_days": median_gap})
        elif direct_inactive:
            signals.append({"type": "direct_gap_channel_review", "days_since_direct_purchase": direct_age, "days_since_identified_purchase": age})
        if prior_cents >= cents(policy.minimum_prior_revenue) and current_cents < prior_cents * (1 - policy.decline_fraction):
            signals.append({"type": "reduced_purchasing", "prior_cents": prior_cents, "current_cents": current_cents,
                            "prior_tests": prior_tests, "current_tests": current_tests})
        sku_rows = []
        for sku in sorted(set(prior.sku) | set(current.sku)):
            p, c = prior[prior.sku.eq(sku)], current[current.sku.eq(sku)]
            pt, ct = int(p.tests.sum()), int(c.tests.sum())
            pq = int(p.loc[p.status.ne("open"), "qty"].sum())
            cq = int(c.loc[c.status.ne("open"), "qty"].sum())
            base = cents(catalogue.loc[sku, "list_price_until_2025_06_30"])
            row = {"sku": sku, "name": catalogue.loc[sku, "name"], "prior_cents": int(p.net_cents.sum()),
                   "current_cents": int(c.net_cents.sum()), "prior_tests": pt, "current_tests": ct,
                   "prior_packs_or_sessions": pq, "current_packs_or_sessions": cq,
                   "constant_list_value_change_cents": (cq-pq)*base}
            sku_rows.append(row)
            if sku != "CL-TRN" and pt > 0 and ct < pt * (1-policy.decline_fraction) and row["prior_cents"] >= cents(policy.minimum_prior_revenue):
                signals.append({"type": "product_decline", "sku": sku, "prior_tests": pt, "current_tests": ct})
        if not signals:
            continue
        cr = cm.loc[key].to_dict() if key in cm.index else {}
        pr = pm.loc[key].to_dict() if key in pm.index else {}
        cities = sorted(set(all_rows.ship_to_city) - {""})
        holds = []
        if key in ambiguous: holds.append("ambiguous_identity")
        if all_rows.date.isna().any(): holds.append("undated_history")
        if all_rows.status.eq("open").any(): holds.append("open_orders_require_review")
        if all_rows.sales_channel.eq("distributor").any() or "switched to distributor" in cr.get("notes", "").lower(): holds.append("known_distributor_channel")
        if tuple(key.split("|")[1:]) in missing_signatures: holds.append("possible_missing_state_alias")
        if len(cities) > 1: holds.append("multiple_shipping_cities")
        if not pr or not cities or basic(pr.get("city", "")) not in {basic(x) for x in cities}: holds.append("identity_needs_review")
        name = pr.get("agency_name") or direct.customer.iloc[0]
        name_tier = "exact_name_state" if all(n == name for n in set(all_rows.customer)) else "reviewable_alias"
        evidence = {
            "provenance": "fictional_case_data", "as_of": policy.as_of,
            "comparison": {"current_start": str(current_start.date()), "current_end_exclusive": policy.as_of,
                           "prior_start": str(previous_start.date()), "prior_end_exclusive": str(previous_end.date())},
            "account_key": key, "name": name, "state": key.split("|")[0], "match_tier": name_tier,
            "aliases": sorted(set(all_rows.customer)), "source_rows": list(map(int, all_rows.source_row)),
            "crm_id": cr.get("crm_id", ""), "crm_notes": cr.get("notes", ""), "owner": cr.get("owner", ""),
            "last_contacted": cr.get("last_contacted", ""), "last_purchase": str(dates.max().date()),
            "prior_cents": prior_cents, "current_cents": current_cents, "decline_cents": max(0, prior_cents-current_cents),
            "prior_tests": prior_tests, "current_tests": current_tests,
            "signals": signals, "holds": holds, "products": sku_rows,
            "limits": ["Unknown distributor end customers can conceal continued purchasing.",
                       "Historical decline is not a recovery forecast; quantities measure purchases, not usage.",
                       "Constant list value isolates pack changes at old list prices; it is not realized revenue.",
                       "Semantic aliases remain identity hypotheses; CRM notes have no independent timestamp."],
        }
        opportunities.append({"id": digest(key)[:20], "account_key": key, "name": name, "state": evidence["state"],
                              "decline_cents": evidence["decline_cents"], "holds": holds, "evidence": evidence,
                              "evidence_hash": digest(evidence)})
    current = orders[orders.date.ge(current_start) & orders.date.lt(as_of)]
    prior = orders[orders.date.ge(previous_start) & orders.date.lt(previous_end)]
    summary = {"as_of": policy.as_of, "rows": len(orders), "hashes": {"orders": oh, "products": ph, "crm_accounts": ch, "public_agencies": ah},
               "net_cents_whole_export": int(orders.net_cents.sum()), "current_cents": int(current.net_cents.sum()),
               "prior_cents": int(prior.net_cents.sum()), "current_tests": int(current.tests.sum()), "prior_tests": int(prior.tests.sum()),
               "undated_lines": int(orders.date.isna().sum()), "duplicate_excess_retained": duplicate_excess,
               "opportunities": len(opportunities), "reviewable": sum(not x["holds"] for x in opportunities),
               "inactivity_reviewable": sum(not x["holds"] and any(s["type"] == "inactivity" for s in x["evidence"]["signals"]) for x in opportunities)}
    return summary, sorted(opportunities, key=lambda x: (-x["decline_cents"], x["id"]))
